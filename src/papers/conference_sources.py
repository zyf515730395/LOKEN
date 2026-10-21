"""Bounded, identity-checked official sources for conference library summaries.

Unlike the arXiv queue, conference IDs never masquerade as arXiv identifiers.
All downloads and evidence receipts belong to the caller's private source cache.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import quote, unquote, urljoin, urlsplit

import requests

from .proceedings import normalize_title
from .summaries.acquisition import _atomic_write
from .summaries.extraction import extract_pdf_document, extract_introduction, _validate_document
from .summaries.models import AcquiredPaper, PaperDocument, PaperSection, PaperSummaryError


HOSTS = frozenset({
    'openaccess.thecvf.com', 'proceedings.mlr.press', 'papers.nips.cc',
    'papers.neurips.cc', 'icml.cc', 'iclr.cc', 'neurips.cc', 'eccv.ecva.net',
    'ecva.net', 'www.ecva.net', 'ojs.aaai.org', 'aaai.org',
    'openreview.net', 'arxiv.org', 'dl.acm.org', 'ieeexplore.ieee.org',
    'doi.org', 'api.crossref.org', 'proceedings.iclr.cc',
    's2026.conference-schedule.org', 's2025.conference-schedule.org',
    'sa2025.conference-schedule.org',
})
# Explicit publisher transitions; a redirect to another otherwise supported
# publisher is still rejected unless this pair is declared here.
REDIRECT_PAIRS = frozenset({
    ('papers.nips.cc', 'papers.neurips.cc'), ('papers.neurips.cc', 'papers.nips.cc'),
    ('ecva.net', 'www.ecva.net'), ('www.ecva.net', 'ecva.net'),
    ('doi.org', 'dl.acm.org'), ('doi.org', 'ieeexplore.ieee.org'),
})
MAX_BYTES = 64 * 1024 * 1024
HOST_COOLDOWNS = Path(__file__).resolve().parents[2] / 'build/conferences/intake/host-cooldowns.json'


class SourceInfrastructureError(RuntimeError):
    """A source worker failure must stop the job rather than fail every paper."""
# Verified from ECCV 2026's official per-paper pages. This CDN is deliberately
# absent from HOSTS: only an exact PDF link from the matching edition is usable.
_EVENTHOSTS_PDF = re.compile(r'https://media\.eventhosts\.cc/Conferences/ECCV2026/pdfs/[0-9]+\.pdf')


def _official_cdn_link(url: str, page_url: str) -> bool:
    return bool(_EVENTHOSTS_PDF.fullmatch(url) and re.fullmatch(
        r'https://eccv\.ecva\.net/virtual/2026/(?:poster|oral|spotlight)/[0-9]+', page_url))


def _safe_url(url: str, *, verified_cdn_urls: frozenset[str] = frozenset()) -> str:
    try:
        parsed = urlsplit(url)
        permitted_host = (parsed.hostname in HOSTS or
                          url in verified_cdn_urls and _EVENTHOSTS_PDF.fullmatch(url) is not None)
        valid = (parsed.scheme == 'https' and permitted_host
                 and parsed.username is None and parsed.password is None
                 and parsed.port in (None, 443) and not any(ord(c) < 33 for c in url))
    except ValueError:
        valid = False
    if not valid:
        raise PaperSummaryError('source_url_unsupported', 'source URL is outside supported official HTTPS hosts')
    return url


def _published(value: str) -> str:
    value = value.strip().replace('/', '-')
    if not re.fullmatch(r'\d{4}(?:-\d{2}(?:-\d{2})?)?', value):
        return ''
    try:
        parts = [int(part) for part in value.split('-')]
        date(*(parts + [1] * (3 - len(parts))))
    except ValueError:
        return ''
    return value


def _page_details(raw: bytes, url: str, title: str) -> dict:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(raw, 'html.parser')
    meta = {str(tag.get('name', tag.get('property', ''))).casefold(): str(tag.get('content', ''))
            for tag in soup.select('meta[content]')}
    identities = [meta.get('citation_title', ''), meta.get('dc.title', '')]
    identities.extend(tag.get_text(' ', strip=True) for tag in soup.select('h1, h2, #papertitle'))
    schedule = urlsplit(url).hostname in {'s2026.conference-schedule.org', 's2025.conference-schedule.org', 'sa2025.conference-schedule.org'}
    if schedule:
        current = soup.select_one('.left-col > .presentation-title')
        identities = [current.get_text(' ', strip=True)] if current else []
    expected = normalize_title(title)
    if not expected or not any(normalize_title(value) == expected for value in identities):
        raise PaperSummaryError('paper_identity_mismatch', 'official page title does not match the accepted paper')
    metadata = {}
    published = _published(meta.get('citation_publication_date', meta.get('dc.date.issued', '')))
    if published:
        metadata['published'] = published
    doi = meta.get('citation_doi', '').strip()
    if re.fullmatch(r'10\.\d{4,9}/\S+', doi):
        metadata['doi'] = doi
    abstract = meta.get('citation_abstract', '')
    description = ''
    if schedule:
        node = soup.select_one('.left-col > .abstract-sect .abstract')
        if node:
            description = node.get_text(' ', strip=True)
    if not abstract:
        node = None if schedule else soup.select_one('#abstract, .abstract, .abstract-content, .paper-abstract')
        if node:
            abstract = node.get_text(' ', strip=True)
    links = [meta.get('citation_pdf_url', '')]
    for anchor in soup.select('a[href]'):
        href = str(anchor['href'])
        label = anchor.get_text(' ', strip=True).casefold()
        if ('.pdf' in href.lower() or '/pdf' in href.lower()
                or label in {'pdf', 'paper', 'download pdf', 'openreview', 'arxiv'}
                or re.search(r'/article/(?:view|download)/', href)):
            links.append(href)
    permitted, verified_cdn_urls = [], []
    for link in links:
        if not link:
            continue
        absolute = urljoin(url, link)
        # These are explicit links on the identity-checked official page, not
        # title searches. Fetch the linked submission's full paper directly.
        arxiv = re.fullmatch(r'https://arxiv\.org/abs/(\d{4}\.\d{4,5}(?:v[1-9]\d*)?)', absolute)
        if arxiv:
            permitted.append('https://arxiv.org/html/' + arxiv.group(1))
            absolute = 'https://arxiv.org/pdf/' + arxiv.group(1)
        if absolute.startswith('https://openreview.net/forum?id='):
            absolute = absolute.replace('/forum?', '/pdf?', 1)
        try:
            verified_cdn = _official_cdn_link(absolute, url)
            _safe_url(absolute, verified_cdn_urls=frozenset({absolute}) if verified_cdn else frozenset())
        except PaperSummaryError:
            continue
        if absolute not in permitted:
            permitted.append(absolute)
            if verified_cdn:
                verified_cdn_urls.append(absolute)
    return {'metadata': metadata, 'links': permitted, 'abstract': abstract, 'description': description,
            'verified_cdn_urls': verified_cdn_urls}


def _download(url: str, directory: Path, *, verified_cdn_urls: frozenset[str] = frozenset(),
              refresh: bool = False) -> tuple[bytes, str, str]:
    """Cache bounded raw responses, checking every redirect before requesting it."""
    _safe_url(url, verified_cdn_urls=verified_cdn_urls)
    key = hashlib.sha256(url.encode()).hexdigest()
    path, receipt = directory / (key + '.raw'), directory / (key + '.json')
    try:
        info = json.loads(receipt.read_text(encoding='utf-8'))
        raw = path.read_bytes() if path.stat().st_size <= MAX_BYTES else b''
        final = _safe_url(info['final_url'], verified_cdn_urls=verified_cdn_urls)
        if (info.get('url') == url and raw and info.get('sha256') == hashlib.sha256(raw).hexdigest()
                and (urlsplit(final).hostname == urlsplit(url).hostname
                     or (urlsplit(url).hostname, urlsplit(final).hostname) in REDIRECT_PAIRS)):
            if not refresh:
                return raw, str(info['content_type']), final
    except (OSError, ValueError, KeyError, TypeError):
        pass
    for attempt in range(3):
        try:
            return _bounded_attempt(url, directory, key, path, receipt,
                                     verified_cdn_urls=verified_cdn_urls)
        except PaperSummaryError as error:
            details = getattr(error, 'details', {})
            _atomic_write(directory / (key + '.failure.json'), json.dumps({
                'error': error.code, 'details': details, 'observed_at': datetime.now(timezone.utc).isoformat(),
            }, ensure_ascii=False).encode())
            if not details.get('transient') or attempt == 2:
                raise
            time.sleep(2 ** attempt)
    raise AssertionError('bounded download retry exhausted')


def _bounded_attempt(*args, wall_seconds: float = 120, **kwargs):
    """A supervised Linux worker bounds slow headers and trickling response bodies."""
    import multiprocessing
    import sys
    if sys.platform != 'linux':
        raise PaperSummaryError('source_runtime_invalid', 'conference network recovery requires shared WSL/Linux')
    context = multiprocessing.get_context('fork')
    receive, send = context.Pipe(duplex=False)
    def worker():
        receive.close()
        try:
            send.send(('ok', _download_attempt(*args, **kwargs)))
        except PaperSummaryError as error:
            send.send(('error', error.code, error.message, error.details))
        except BaseException as error:
            send.send(('fatal', type(error).__name__))
        finally:
            send.close()
    process = context.Process(target=worker)
    process.start()
    send.close()
    try:
        if not receive.poll(wall_seconds):
            raise PaperSummaryError('source_unavailable', 'official source exceeded hard download deadline',
                details={'url': args[0], 'exception_type': 'DownloadDeadline', 'transient': True})
        try:
            result = receive.recv()
        except EOFError:
            raise SourceInfrastructureError('official source worker exited before a result; preserve runtime evidence') from None
        if result[0] == 'ok':
            return result[1]
        if result[0] == 'error':
            raise PaperSummaryError(result[1], result[2], details=result[3])
        if result[1] == 'MemoryError':
            raise MemoryError('source worker exhausted memory')
        raise SourceInfrastructureError('source worker failed: ' + result[1])
    finally:
        receive.close()
        process.join(timeout=1)
        if process.is_alive():
            process.terminate()
            process.join(timeout=3)
        if process.is_alive():
            process.kill()
            process.join()
        process.close()


def _load_host_state() -> dict:
    try:
        state = json.loads(HOST_COOLDOWNS.read_text())
        if not isinstance(state, dict):
            raise ValueError('invalid host cooldown map')
        for saved in state.values():
            target = saved.get('until') if isinstance(saved, dict) else saved
            if not isinstance(target, str) or datetime.fromisoformat(target).tzinfo is None:
                raise ValueError('invalid host cooldown deadline')
        return state
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, TypeError):
        raise PaperSummaryError('source_retry_state_invalid', 'preserve invalid official-host cooldown receipts') from None


def _host_gate(url: str) -> None:
    state = _load_host_state()
    if state:
        saved = state.get(urlsplit(url).hostname)
        target = saved.get('until') if isinstance(saved, dict) else saved
        status = saved.get('http_status', 429) if isinstance(saved, dict) else 429
        if target and datetime.fromisoformat(target) > datetime.now(timezone.utc):
            raise PaperSummaryError('source_rate_limited' if status == 429 else 'source_unavailable',
                'official host is cooling down', details={'url': url, 'http_status': status, 'retry_at': target})


def _rate_limit(url: str, value: str, *, status: int = 429) -> str:
    now = datetime.now(timezone.utc)
    try:
        target = now + timedelta(seconds=max(1, int(value)))
    except (ValueError, OverflowError):
        try:
            target = parsedate_to_datetime(value)
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError, OverflowError):
            target = now + timedelta(minutes=10)
    target = max(target, now + timedelta(seconds=1)).astimezone(timezone.utc)
    state = _load_host_state()
    saved = state.get(urlsplit(url).hostname)
    previous = saved.get('until') if isinstance(saved, dict) else saved
    if previous:
        target = max(datetime.fromisoformat(previous), target)
    target = target.astimezone(timezone.utc).isoformat()
    state[urlsplit(url).hostname] = {'until': target, 'http_status': status}
    _atomic_write(HOST_COOLDOWNS, json.dumps(state).encode())
    return target


def _preserve(path: Path, raw: bytes) -> None:
    if path.exists():
        old = path.read_bytes()
        if old != raw:
            archive = path.with_name(path.stem + '.' + hashlib.sha256(old).hexdigest() + path.suffix)
            if not archive.exists():
                _atomic_write(archive, old)
    _atomic_write(path, raw)


def _download_attempt(url, directory, key, path, receipt, *, verified_cdn_urls):
    current = url
    deadline = time.monotonic() + 120
    with requests.Session() as session:
        session.trust_env = False
        session.proxies = requests.utils.get_environ_proxies(url)
        try:
            for _ in range(6):
                if time.monotonic() >= deadline:
                    raise PaperSummaryError('source_unavailable', 'official source request exceeded wall-clock boundary',
                        details={'url': current, 'exception_type': 'DownloadDeadline', 'transient': True})
                _host_gate(current)
                with session.get(current, allow_redirects=False, stream=True, timeout=(10, 60),
                                 headers={'User-Agent': 'LOKEN-conference-intake/1.0'}) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        target = urljoin(current, response.headers.get('Location', ''))
                        try:
                            _safe_url(target, verified_cdn_urls=verified_cdn_urls)
                        except PaperSummaryError:
                            raise PaperSummaryError('source_redirect_rejected', 'official source redirected to an unsupported host',
                                details={'url': current, 'target_url': target, 'http_status': response.status_code}) from None
                        pair = (urlsplit(current).hostname, urlsplit(target).hostname)
                        if pair[0] != pair[1] and pair not in REDIRECT_PAIRS:
                            raise PaperSummaryError('source_redirect_rejected', 'official source redirected outside its permitted publisher',
                                details={'url': current, 'target_url': target, 'http_status': response.status_code})
                        current = target
                        continue
                    if response.status_code != 200:
                        details = {'url': current, 'http_status': response.status_code,
                                   'transient': response.status_code >= 500 or response.status_code in {408, 425}}
                        if response.status_code == 429 or (response.status_code == 503 and response.headers.get('Retry-After')):
                            details['retry_at'] = _rate_limit(current, response.headers.get('Retry-After', '600'),
                                                             status=response.status_code)
                            details['transient'] = False
                        code = {429: 'source_rate_limited', 403: 'source_access_denied', 404: 'source_not_found',
                                410: 'source_not_found'}.get(response.status_code, 'source_unavailable')
                        raise PaperSummaryError(code, 'official publisher source is currently inaccessible', details=details)
                    body = bytearray()
                    for chunk in response.iter_content(64 * 1024):
                        if time.monotonic() >= deadline:
                            raise PaperSummaryError('source_unavailable', 'official source download exceeded wall-clock boundary',
                                details={'url': current, 'exception_type': 'DownloadDeadline', 'transient': True})
                        body.extend(chunk)
                        if len(body) > MAX_BYTES:
                            raise PaperSummaryError('source_too_large', 'official source exceeds the download boundary',
                                                    details={'url': current, 'max_bytes': MAX_BYTES})
                    raw = bytes(body)
                    content_type = response.headers.get('Content-Type', '').split(';')[0].lower()
                    _preserve(path, raw)
                    _preserve(receipt, json.dumps({'url': url, 'final_url': current,
                        'sha256': hashlib.sha256(raw).hexdigest(), 'content_type': content_type,
                        'fetched_at': datetime.now(timezone.utc).isoformat()},
                        ensure_ascii=False).encode())
                    return raw, content_type, current
        except requests.RequestException as error:
            raise PaperSummaryError('source_unavailable', 'official source request failed',
                details={'url': current, 'exception_type': type(error).__name__, 'transient': True}) from None
    raise PaperSummaryError('source_redirect_rejected', 'official source exceeded the redirect boundary')


def _pdf_document(raw: bytes, title: str, abstract: str = '', *, cache_root: Path | None = None) -> PaperDocument:
    try:
        document = extract_pdf_document(raw, title)
    except PaperSummaryError as error:
        if cache_root is None or error.code not in {'paper_identity_mismatch', 'html_unavailable'}:
            raise
        from pypdf import PdfReader
        from io import BytesIO
        if len((PdfReader(BytesIO(raw), strict=True).pages[0].extract_text() or '').strip()) >= 80:
            raise
        from .conference_evidence import ocr_document
        document = ocr_document(raw, title, cache_root)
    # The shared extractor's overlap check is intentionally broad for arXiv.
    # Conference downloads require the exact normalized title in the first page.
    first = document.sections[0].text if document.sections else ''
    probe = re.split(r'\babstract\b', first, maxsplit=1, flags=re.I)[0]
    if normalize_title(title) not in normalize_title(probe[:5000]):
        raise PaperSummaryError('paper_identity_mismatch', 'PDF first page does not contain the accepted paper title')
    document = _without_running_headers(document)
    if not abstract:
        match = re.search(r'\babstract\b\s*[:.\-—]?\s*(.+?)(?:\n\s*(?:1[.\s]+)?introduction\b)',
                          first, re.I | re.S)
        abstract = match.group(1).strip() if match else ''
    abstract = re.sub(r'^abstract\s*[:.\-—]?\s*', '', abstract.strip(), flags=re.I)
    if not 40 <= len(abstract) <= 16000:
        abstract = ''
    document = _validate_document(PaperDocument(document.title, abstract, document.sections), title)
    from .conference_evidence import select_evidence
    select_evidence(document)
    return document


def _html_document(raw: bytes, title: str, abstract: str) -> PaperDocument | None:
    from bs4 import BeautifulSoup
    from .conference_evidence import select_evidence
    soup = BeautifulSoup(raw, 'html.parser')
    article = soup.select_one('article, .ltx_document, [itemprop="articleBody"], .article-body')
    if article is None:
        return None
    for node in article.select('script, style, nav, footer, aside, .ltx_bibliography, .ltx_role_footnote'):
        node.decompose()
    # A long abstract or landing page is not a full-text document.
    headings = [h.get_text(' ', strip=True) for h in article.select('h2, h3, h4')]
    if not any(re.search(r'\b(introduction|overview|motivation|background|method|approach|conclusion)\b', h, re.I) for h in headings):
        return None
    sections, parts, heading = [], [], 'Body'
    for node in article.find_all(['h2', 'h3', 'h4', 'p']):
        if node.name.startswith('h'):
            if parts:
                sections.append(PaperSection(heading, '\n'.join(parts)))
            heading, parts = node.get_text(' ', strip=True), []
        else:
            parts.append(node.get_text(' ', strip=True))
    if parts:
        sections.append(PaperSection(heading, '\n'.join(parts)))
    document = _validate_document(PaperDocument(title, abstract, tuple(sections)), title)
    select_evidence(document)
    return document


def _without_running_headers(document: PaperDocument) -> PaperDocument:
    """Remove evidenced PDF page furniture before strict section extraction.

    LNCS author headers such as ``4 L. Han et al.`` otherwise look like a
    numbered section. Only the first line of its exact numbered PDF page is
    eligible, and author headers must repeat on another page.
    """
    author_headers = []
    for index, section in enumerate(document.sections, 1):
        first = section.text.splitlines()[0] if section.text else ''
        match = re.fullmatch(rf'{index}\s+([A-Z]\.\s+[A-Za-z-]+\s+et al\.)', first)
        author_headers.append(match.group(1) if match and section.heading == f'Page {index}' else '')
    sections = []
    for index, section in enumerate(document.sections, 1):
        lines = section.text.splitlines()
        if lines and section.heading == f'Page {index}':
            author = author_headers[index - 1]
            title_header = re.fullmatch(rf'(.{{15,}})\s+{index}', lines[0])
            if (author and author_headers.count(author) >= 2 or title_header
                    and normalize_title(title_header.group(1)) in normalize_title(document.title)):
                lines = lines[1:]
        sections.append(PaperSection(section.heading, '\n'.join(lines)))
    return PaperDocument(document.title, document.abstract, tuple(sections))


def _crossref(url: str, title: str, directory: Path, *, refresh: bool = False) -> tuple[dict, list[str]]:
    """Resolve only an explicit ACM/IEEE DOI, never a fuzzy bibliographic search."""
    match = re.search(r'(10\.(?:1145|1109)/[^?#]+)', unquote(url))
    if match is None:
        return {}, []
    doi = match.group(1)
    raw, _, _ = _download('https://api.crossref.org/works/' + quote(doi, safe=''), directory, refresh=refresh)
    try:
        item = json.loads(raw)['message']
        if (str(item.get('DOI', '')).casefold() != doi.casefold()
                or not any(normalize_title(t) == normalize_title(title) for t in item.get('title', []))):
            raise PaperSummaryError('paper_identity_mismatch', 'DOI metadata does not match the accepted paper')
        metadata = {'doi': doi}
        for field in ('published-online', 'published-print', 'published'):
            parts = item.get(field, {}).get('date-parts', [[]])[0]
            value = '-'.join(f'{int(part):04d}' if index == 0 else f'{int(part):02d}'
                             for index, part in enumerate(parts))
            if _published(value):
                metadata['published'] = value
                break
        links = [link['URL'] for link in item.get('link', [])
                 if link.get('content-type') == 'application/pdf' and isinstance(link.get('URL'), str)]
        return metadata, links
    except PaperSummaryError:
        raise
    except (ValueError, TypeError, KeyError, IndexError):
        raise PaperSummaryError('source_metadata_invalid', 'official DOI metadata could not be parsed') from None


def acquire_conference_paper(record: dict, cache_root: Path, *, refresh: bool = False) -> tuple[AcquiredPaper, dict]:
    """Acquire full text; failure preserves accepted library membership upstream.

    ``cache_root`` is this record's directory under build/conferences/intake/sources.
    A record's calendar/edition date is never substituted for publication evidence.
    """
    identity, title = str(record.get('id', '')), str(record.get('title', '')).strip()
    if re.fullmatch(r'conf-[a-f0-9]{8,64}', identity) is None or not title:
        raise PaperSummaryError('source_record_invalid', 'conference source requires an internal ID and title')
    directory = Path(cache_root).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    url = str(record.get('url', ''))
    metadata, queue, abstract = {}, [], ''
    failures = []
    for candidate in [url, *(item.get('url', '') for item in [*record.get('conferences', []), *record.get('provenance', [])] if isinstance(item, dict))]:
        if not candidate or candidate in queue:
            continue
        try:
            queue.append(_safe_url(candidate))
        except PaperSummaryError as error:
            failures.append(error)
    arxiv_id = str(record.get('arxiv_id', ''))
    if arxiv_id:
        if re.fullmatch(r'\d{4}\.\d{4,5}(?:v[1-9]\d*)?', arxiv_id) is None:
            raise PaperSummaryError('invalid_arxiv_id', 'conference record contains an invalid arXiv ID')
        metadata['arxiv_id'] = arxiv_id.split('v')[0]
        queue[0:0] = ['https://arxiv.org/html/' + arxiv_id, 'https://arxiv.org/pdf/' + arxiv_id]
    if urlsplit(url).hostname in {'doi.org', 'dl.acm.org', 'ieeexplore.ieee.org'}:
        try:
            verified, links = _crossref(url, title, directory, refresh=refresh)
            metadata.update(verified)
            queue.extend(links)
        except PaperSummaryError as error:
            if error.code == 'paper_identity_mismatch':
                raise
            failures.append(error)
    visited, verified_cdn_urls = set(), set()
    for _ in range(10):
        if not queue:
            break
        target = queue.pop(0)
        if target in visited:
            continue
        visited.add(target)
        try:
            raw, content_type, final_url = _download(target, directory,
                verified_cdn_urls=frozenset(verified_cdn_urls), refresh=refresh)
            if raw.startswith(b'%PDF-'):
                document = _pdf_document(raw, title, abstract, cache_root=directory)
                arxiv = re.fullmatch(r'https://arxiv\.org/pdf/(\d{4}\.\d{4,5})(?:v[1-9]\d*)?(?:\.pdf)?', final_url)
                if arxiv:
                    metadata['arxiv_id'] = arxiv.group(1)
                path = directory / 'source.pdf'
                _preserve(path, raw)
                sha = hashlib.sha256(raw).hexdigest()
                from .conference_evidence import select_evidence, evidence_receipt
                extraction = {'method': 'pdf_text'}
                ocr_path = directory / ('ocr-' + sha + '.json')
                if ocr_path.exists():
                    ocr_info = json.loads(ocr_path.read_text())
                    if ocr_info.get('source_sha256') == sha:
                        extraction = {'method': 'local_ocr', 'page_limit': 12,
                                      'truncated': ocr_info.get('truncated', True)}
                _preserve(directory / 'verified.json', json.dumps({'id': identity, 'title': title,
                    'url': final_url, 'source_sha256': sha, 'metadata': metadata,
                    'extraction': extraction,
                    'summary_evidence': evidence_receipt(select_evidence(document))}, ensure_ascii=False).encode())
                return AcquiredPaper(identity, 'pdf', path, sha, document), metadata
            if content_type not in {'text/html', 'application/xhtml+xml'}:
                raise PaperSummaryError('source_unavailable', 'official response did not provide a paper document')
            details = _page_details(raw, final_url, title)
            verified_cdn_urls.update(details['verified_cdn_urls'])
            metadata.update(details['metadata'])
            abstract = details['abstract'] or abstract
            queue.extend(link for link in details['links'] if link not in visited)
            document = _html_document(raw, title, abstract)
            if document is not None:
                from .conference_evidence import select_evidence, evidence_receipt
                path = directory / 'source.html'
                _preserve(path, raw)
                sha = hashlib.sha256(raw).hexdigest()
                _preserve(directory / 'verified.json', json.dumps({'id': identity, 'title': title,
                    'url': final_url, 'source_sha256': sha, 'metadata': metadata,
                    'extraction': {'method': 'html_text'},
                    'summary_evidence': evidence_receipt(select_evidence(document))}, ensure_ascii=False).encode())
                return AcquiredPaper(identity, 'html', path, sha, document), metadata
        except PaperSummaryError as error:
            failures.append(error)
    from .conference_retry import queue_for
    rank = {'identity': 0, 'network': 1, 'material': 2, 'adapter': 3, 'annotation': 4}
    failure = min(failures, key=lambda e: rank[queue_for(e.code)]) if failures else PaperSummaryError(
        'source_unavailable', 'no accessible official full paper source was found')
    deadlines = [e.details['retry_at'] for e in failures if queue_for(e.code) == 'network' and e.details.get('retry_at')]
    if queue_for(failure.code) == 'network' and deadlines:
        failure.details['retry_at'] = max(deadlines, key=datetime.fromisoformat)
    failure.details['source_attempts'] = [{'error': e.code, **e.details} for e in failures if e is not failure] + [
        {'error': failure.code, **{k:v for k,v in failure.details.items() if k != 'source_attempts'}}]
    raise failure


def acquire_conference_abstract(record: dict, cache_root: Path, *, refresh: bool = False, allow_description: bool = False) -> tuple[AcquiredPaper, dict]:
    """Independent official abstract evidence; never sufficient for body summaries."""
    directory = Path(cache_root).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    urls = [str(record['url']), *(item.get('url', '') for item in [*record.get('conferences', []), *record.get('provenance', [])] if isinstance(item, dict) and item.get('url'))]
    arxiv = str(record.get('arxiv_id', ''))
    if re.fullmatch(r'\d{4}\.\d{4,5}(?:v[1-9]\d*)?', arxiv):
        urls.insert(0, 'https://arxiv.org/abs/' + arxiv)
    error = PaperSummaryError('abstract_unavailable', 'verified official abstract is unavailable')
    for url in list(dict.fromkeys(urls))[:10]:
        try:
            # The publication-date collector already fetched these official
            # pages. Recheck exact identity before reusing its bounded raw bytes.
            existing = HOST_COOLDOWNS.parent.parent / 'dates/responses' / (hashlib.sha256(url.encode()).hexdigest() + '.raw')
            schedule_host = urlsplit(url).hostname in {'s2026.conference-schedule.org', 's2025.conference-schedule.org', 'sa2025.conference-schedule.org'}
            if not refresh and schedule_host and existing.exists() and existing.stat().st_size <= MAX_BYTES:
                _safe_url(url)
                raw, content_type, final = existing.read_bytes(), 'text/html', url
                _page_details(raw, final, record['title'])
            else:
                raw, content_type, final = _download(url, directory, refresh=refresh)
            if content_type not in {'text/html', 'application/xhtml+xml'}:
                continue
            details = _page_details(raw, final, record['title'])
            basis = 'official_abstract' if details['abstract'] else 'official_description'
            abstract = re.sub(r'^abstract\s*[:.\-—]?\s*', '', (details['abstract'] or (details.get('description', '') if allow_description else '')).strip(), flags=re.I)
            if not 40 <= len(abstract) <= 16000:
                continue
            path = directory / 'abstract-source.html'
            _preserve(path, raw)
            sha = hashlib.sha256(raw).hexdigest()
            _preserve(directory / 'abstract-verified.json', json.dumps({
                'id': record['id'], 'title': record['title'], 'url': final,
                'source_sha256': sha, 'basis': basis}, ensure_ascii=False).encode())
            return AcquiredPaper(record['id'], 'html', path, sha,
                PaperDocument(record['title'], abstract, ())), details['metadata']
        except PaperSummaryError as caught:
            error = caught
    raise error
