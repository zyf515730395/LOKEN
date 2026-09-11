"""Bounded official-page and GitHub discovery for later arXiv identity checks.

Repository timestamps are never publication evidence. The caller supplies a
cached HTTP fetcher and independently verifies returned arXiv candidates.
"""
from __future__ import annotations

import base64
from datetime import datetime
import json
import re
import threading
import time
from typing import Callable
from urllib.parse import urlencode, urljoin, urlsplit, quote, parse_qs

from bs4 import BeautifulSoup

from .conference_date_sources import _articles, _date, _doi, _page, _crossref, safe_metadata_url
from .proceedings import normalize_title

_REPO = re.compile(r'https://github\.com/([A-Za-z0-9][A-Za-z0-9_.-]{0,99})/([A-Za-z0-9_.-]{1,100})(?:/[^\s]*)?')
_ARXIV = re.compile(r'https?://arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})(?:v[1-9]\d*)?(?:\.pdf)?(?=$|[\s\)\]<>"\x27?#])')
_MAX_README = 512_000
_GITHUB_GUARD = threading.Lock()
_GITHUB_STOPPED = False
_LAST_SEARCH = 0.0


def _github_fetch(url: str, fetch: Callable[[str], bytes]) -> bytes:
    """Serialize GitHub discovery; stop this process after any 403/429.

    GitHub documents 10 unauthenticated searches/minute and 60 core calls/hour.
    Pending records keep lookup_errors so a later run can resume them.
    """
    global _GITHUB_STOPPED, _LAST_SEARCH
    with _GITHUB_GUARD:
        if _GITHUB_STOPPED:
            raise RuntimeError('github_rate_limited_retry_later')
        if '/search/' in url:
            delay = max(0.0, 6.2 - (time.monotonic() - _LAST_SEARCH))
            if delay:
                time.sleep(delay)
            _LAST_SEARCH = time.monotonic()
        try:
            return fetch(url)
        except OSError as error:
            if getattr(getattr(error, 'response', None), 'status_code', None) in {403, 429}:
                _GITHUB_STOPPED = True
            raise


def _repo(url: str) -> str:
    match = _REPO.fullmatch(url)
    if not match or match[2] in {'.', '..'}:
        return ''
    return match[1] + '/' + match[2].removesuffix('.git')


def _arxiv_ids(text: str) -> list[str]:
    return list(dict.fromkeys(match[1] for match in _ARXIV.finditer(text)))


def _identity(soup: BeautifulSoup, title: str) -> bool:
    expected = normalize_title(title)
    if not expected:
        return False
    declared = [str(n.get('content', '')) for n in soup.select('meta[name="citation_title"], meta[name="dc.title"]')]
    if declared:
        return all(normalize_title(t) == expected for t in declared)
    headings = [n.get_text(' ', strip=True) for n in soup.select('h1, h2, #papertitle')]
    if any(normalize_title(t) == expected for t in headings):
        return True
    articles = []
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            articles.extend(_articles(json.loads(node.get_text())))
        except (ValueError, TypeError):
            pass
    return len(articles) == 1 and normalize_title(str(articles[0].get('headline', articles[0].get('name', '')))) == expected


def _readme(repository: str, fetch: Callable[[str], bytes]) -> str:
    payload = json.loads(_github_fetch('https://api.github.com/repos/' + repository + '/readme', fetch))
    if payload.get('encoding') != 'base64' or not isinstance(payload.get('content'), str):
        return ''
    encoded = payload['content']
    if len(encoded) > _MAX_README * 2:
        return ''
    raw = base64.b64decode(''.join(encoded.split()), validate=True)
    return raw.decode('utf-8', errors='replace') if len(raw) <= _MAX_README else ''


def _readme_identity(text: str, title: str, authors: list[str], official_url: str, linked: bool) -> bool:
    # Bibliography mentions deep in a survey/awesome list do not identify a repo.
    intro = text[:6000]
    normalized = normalize_title(intro)
    method = title.split(':', 1)[0].strip()
    abbreviated = ':' in title and re.fullmatch(r'[\w.-]{4,50}',method) and normalize_title(method) in normalized
    if normalize_title(title) not in normalized and not abbreviated:
        return False
    if linked:
        return True
    if official_url and official_url in intro:
        return True
    author = any(len(normalize_title(a)) >= 6 and normalize_title(a) in normalized for a in authors)
    official = re.search(r'\b(?:official\s+(?:(?:PyTorch|TensorFlow|JAX)\s+)?(?:implementation|repository|code)|implementation\s+of\s+(?:the\s+)?paper)\b', intro, re.I)
    return bool(author and official)


def _queries(title: str, full_title: bool = False) -> list[str]:
    method = title.split(':', 1)[0].strip()
    queries = []
    if ':' in title and re.fullmatch(r'[\w.-]{3,50}', method):
        queries.append(method + ' in:name,description,readme')
    if full_title:
        queries.append('"' + title.replace('"', '')[:180] + '" in:readme')
    return queries


def _ieee_date(soup: BeautifulSoup, title: str, url: str) -> dict:
    # IEEE publication metadata can also live in a JSON object in a script.
    # Never use conferenceDate, dateAdded, dateOfInsertion or repository dates.
    for script in soup.select('script'):
        text = script.get_text()
        match = re.search(r'(?:xplGlobal\.document\.metadata|global\.document\.metadata)\s*=\s*', text)
        if not match:
            continue
        try:
            value, _ = json.JSONDecoder().raw_decode(text[match.end():].lstrip())
        except ValueError:
            continue
        if not isinstance(value, dict) or normalize_title(str(value.get('title', value.get('articleTitle', '')))) != normalize_title(title):
            continue
        # dateOfPublication explicitly denotes publication; publicationDate is
        # omitted because IEEE conference records also use it for event dates.
        raw_date = value.get('dateOfPublication', '')
        parsed = _date(raw_date)
        if not parsed and isinstance(raw_date, str):
            for pattern in ('%d %B %Y', '%d %b %Y', '%B %d, %Y'):
                try:
                    parsed = datetime.strptime(raw_date.strip(), pattern).date().isoformat()
                    break
                except ValueError:
                    pass
        if parsed:
            return {'published': parsed, 'date_source': {'url': url, 'basis': 'publisher_publication'}}
    return {}


def _crossref_discovery(record: dict, fetch: Callable[[str], bytes]) -> tuple[dict, list[str]]:
    title = record['title']
    doi = _doi(record.get('doi', '')) or _doi(record.get('url', ''))
    query_url = ('https://api.crossref.org/works/' + quote(doi, safe='') if doi else
                 'https://api.crossref.org/works?' + urlencode({'query.title': title, 'rows': 5}))
    raw = fetch(query_url)
    message = json.loads(raw).get('message', {})
    items = [message] if doi else message.get('items', [])
    matches = {}
    for item in items:
        candidate_doi = _doi(item.get('DOI', ''))
        if (candidate_doi and (not doi or candidate_doi.casefold() == doi.casefold())
                and any(normalize_title(str(t)) == normalize_title(title) for t in item.get('title', []))):
            matches[candidate_doi.casefold()] = item
    if len(matches) != 1:
        return {}, []
    item = next(iter(matches.values()))
    # Reuse the already-read response for the existing publication-date parser.
    result = _crossref(title, doi, lambda _: raw)
    authors = [' '.join(str(a.get(k, '')).strip() for k in ('given', 'family')).strip()
               for a in item.get('author', []) if isinstance(a, dict)]
    if any(authors):
        result['authors'] = list(dict.fromkeys(a for a in authors if a))
        result['author_evidence_url'] = query_url
    result['evidence_urls'] = ['https://doi.org/' + _doi(item['DOI'])]
    urls = [item.get('resource', {}).get('primary', {}).get('URL', '')]
    urls.extend(link.get('URL', '') for link in item.get('link', []) if isinstance(link, dict))
    destinations = []
    for value in urls:
        if not isinstance(value, str):
            continue
        # Registered resource URLs sometimes use HTTP; only fetch HTTPS.
        value = re.sub(r'^http://', 'https://', value)
        if not safe_metadata_url(value) or urlsplit(value).hostname != 'ieeexplore.ieee.org':
            continue
        parsed = urlsplit(value)
        number = parse_qs(parsed.query).get('arnumber', [''])[0]
        if re.fullmatch(r'\d+', number):
            value = 'https://ieeexplore.ieee.org/document/' + number
        if value not in destinations:
            destinations.append(value)
    return result, destinations[:1]


def discover(record: dict, fetch: Callable[[str], bytes]) -> dict:
    """Return candidate arXiv IDs, authors, evidence URLs and optional IEEE date.

    Requests only target supported official pages and api.github.com repository
    search/readme endpoints. Fetch must enforce bounds and safe redirects. A
    candidate here is not authorization to change any public paper record.
    """
    title = str(record.get('title', '')).strip()
    if not normalize_title(title):
        return {}
    url = str(record.get('url', ''))
    supplied_authors = record.get('authors', [])
    authors = [str(a) for a in supplied_authors if isinstance(a, str)] if isinstance(supplied_authors, list) else []
    result: dict = {}
    repositories: dict[str, bool] = {}
    evidence = []
    ids = []
    errors = []
    ieee_urls = []
    try:
        crossref, ieee_urls = _crossref_discovery(record, fetch)
        authors = crossref.pop('authors', None) or authors
        evidence.extend(crossref.pop('evidence_urls', []))
        result.update(crossref)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
        errors.append({'source': 'https://api.crossref.org/works', 'error': type(error).__name__})
    if safe_metadata_url(url) and urlsplit(url).hostname not in {'arxiv.org', 'api.crossref.org', 'doi.org'}:
        try:
            raw = fetch(url)
            soup = BeautifulSoup(raw, 'html.parser')
            if _identity(soup, title):
                metadata, _ = _page(raw, url, title)
                authors = metadata.get('authors') or authors
                if metadata.get('authors'): result['author_evidence_url'] = url
                ids.extend(metadata.get('arxiv_ids', []))
                evidence.append(url)
                if urlsplit(url).hostname == 'ieeexplore.ieee.org':
                    publication = metadata if metadata.get('published') else _ieee_date(soup, title, url)
                    if publication.get('published') and len(publication['published']) > len(result.get('published', '')):
                        result.update({k: publication[k] for k in ('published', 'date_source')})
                for anchor in soup.select('a[href]'):
                    repository = _repo(urljoin(url, str(anchor['href'])))
                    if repository:
                        repositories[repository] = True
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
            errors.append({'source': url, 'error': type(error).__name__})
    for ieee_url in ieee_urls:
        if ieee_url == url:
            continue
        try:
            raw = fetch(ieee_url)
            soup = BeautifulSoup(raw, 'html.parser')
            if not _identity(soup, title):
                continue
            metadata, _ = _page(raw, ieee_url, title)
            authors = metadata.get('authors') or authors
            if metadata.get('authors'): result['author_evidence_url'] = ieee_url
            ids.extend(metadata.get('arxiv_ids', []))
            evidence.append(ieee_url)
            publication = metadata if metadata.get('published') else _ieee_date(soup, title, ieee_url)
            if publication.get('published') and len(publication['published']) > len(result.get('published', '')):
                result.update({key: publication[key] for key in ('published', 'date_source')})
            for anchor in soup.select('a[href]'):
                repository = _repo(urljoin(ieee_url, str(anchor['href'])))
                if repository:
                    repositories[repository] = True
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
            errors.append({'source': ieee_url, 'error': type(error).__name__})
    # An explicit repository in the input is still required to pass README
    # identity and author/official-link corroboration; it is not pre-trusted.
    for field in ('github_url', 'code_url', 'project_url'):
        repository = _repo(str(record.get(field, '')))
        if repository:
            repositories.setdefault(repository, False)
    checked_repos = set()
    def inspect_repositories():
        for repository, linked in list(repositories.items())[:8]:
            if repository in checked_repos:
                continue
            checked_repos.add(repository)
            readme_url = 'https://api.github.com/repos/' + repository + '/readme'
            try:
                readme = _readme(repository, fetch)
                if _readme_identity(readme, title, authors, url if safe_metadata_url(url) else '', linked):
                    candidates = _arxiv_ids(readme[:6000])
                    if candidates:
                        ids.extend(candidates)
                        evidence.append('https://github.com/' + repository)
            except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
                errors.append({'source': readme_url, 'error': str(error) if isinstance(error, RuntimeError) else type(error).__name__})
    inspect_repositories()
    if not ids:
        for query in _queries(title, bool(record.get('github_title_search'))):
            search_url = 'https://api.github.com/search/repositories?' + urlencode({'q': query, 'per_page': 3})
            try:
                payload = json.loads(_github_fetch(search_url, fetch))
                for item in payload.get('items', [])[:3]:
                    repository = _repo('https://github.com/' + str(item.get('full_name', '')))
                    if repository:
                        repositories.setdefault(repository, False)
            except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
                errors.append({'source': search_url, 'error': type(error).__name__})
        inspect_repositories()
    if ids:
        result['arxiv_ids'] = list(dict.fromkeys(ids))
    if authors:
        result['authors'] = list(dict.fromkeys(authors))
    if evidence:
        result['evidence_urls'] = list(dict.fromkeys(evidence))
    if errors:
        result['lookup_errors'] = errors
    return result
