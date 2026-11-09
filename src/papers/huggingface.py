"""Hugging Face discovery adapter for the existing candidate collector."""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import time
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import requests

from .candidate_ledger import atomic_write_json, merge_collected_candidates, normalize_arxiv_id

API = 'https://huggingface.co/api/daily_papers'
ARXIV_ID = re.compile(r'\d{4}\.\d{4,5}(?:v\d+)?')
HF_ID = re.compile(r'hf-[a-f0-9]{24}')


def _words(text: str) -> str:
    return ' '.join(re.findall(r'\w+', text.casefold()))


def _arxiv_identity(paper: dict) -> str | None:
    identities = set()
    raw = paper.get('id', '')
    if isinstance(raw, str) and ARXIV_ID.fullmatch(raw):
        identities.add(normalize_arxiv_id(raw))
    for name in ('arxivId', 'arxiv_id', 'arxivUrl', 'arxiv_url', 'paperUrl', 'pdfUrl'):
        value = paper.get(name)
        if not isinstance(value, str):
            continue
        if ARXIV_ID.fullmatch(value):
            identities.add(normalize_arxiv_id(value))
            continue
        url = urlsplit(value)
        if url.scheme in ('http', 'https') and url.netloc in ('arxiv.org', 'www.arxiv.org'):
            match = re.fullmatch(r'/(?:abs|pdf)/(' + ARXIV_ID.pattern + r')(?:\.pdf)?', url.path)
            if match:
                identities.add(normalize_arxiv_id(match[1]))
    if len(identities) > 1:
        raise ValueError('Conflicting HF arXiv identities')
    return next(iter(identities), None)


def daily_records(items: list, config: dict, day: dt.date) -> list[dict]:
    """Discard unrelated items before persistence; local review remains authoritative."""
    if not isinstance(items, list):
        raise ValueError('HF daily response must be a list')
    records = []
    for item in items:
        paper = item.get('paper') if isinstance(item, dict) else None
        if not isinstance(paper, dict):
            raise ValueError('Malformed HF daily paper')
        title, abstract = paper.get('title'), paper.get('summary')
        if not isinstance(title, str) or not isinstance(abstract, str):
            raise ValueError('HF title/abstract missing')
        matched = []
        from papers.scope import excluded
        if excluded(config, _arxiv_identity(paper) or '', title):
            continue
        for topic, settings in config['keywords'].items():
            fields = settings.get('fields', ['ti', 'abs'])
            haystack = ' ' + _words(' '.join(text for field, text in [('ti', title), ('abs', abstract)] if field in fields)) + ' '
            if any(' ' + _words(term) + ' ' in haystack for term in settings['filters'] if _words(term)):
                matched.append(topic)
        if not matched:
            continue
        # HF's paper publication date and its daily selection date are distinct.
        published = paper.get('publishedAt')
        if not isinstance(published, str) or not re.match(r'^\d{4}-\d{2}-\d{2}(?:T|$)', published):
            raise ValueError('Relevant HF paper has no verified publication date')
        date = dt.date.fromisoformat(published[:10])
        submitted = paper.get('submittedOnDailyAt')
        if submitted and (not isinstance(submitted, str) or submitted[:10] != day.isoformat()):
            raise ValueError('HF selection date differs from requested date')
        source_id = paper.get('id')
        if not isinstance(source_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,199}', source_id):
            raise ValueError('Invalid HF paper identity')
        arxiv_id = _arxiv_identity(paper)
        url = f'https://huggingface.co/papers/{source_id}'
        key = arxiv_id or 'hf-' + hashlib.sha256(url.encode()).hexdigest()[:24]
        display = arxiv_id or f'{date:%y%m.%d}XXX'
        paper_url = f'https://arxiv.org/abs/{arxiv_id}' if arxiv_id else url
        authors = paper.get('authors', [])
        if authors is None:
            authors = []
        if not isinstance(authors, list) or any(not isinstance(author, dict) or not isinstance(author.get('name', ''), str) for author in authors):
            raise ValueError('Malformed HF author list')
        first = authors[0].get('name', '') if authors else ''
        author = f'{first} et.al.' if first else '-'
        # Archive rows are a legacy pipe format: keep data from breaking its delimiters.
        clean_title = ' '.join(title.split()).replace('|', '&#124;')
        clean_author = ' '.join(author.split()).replace('|', '&#124;')
        for topic in matched:
            records.append(dict(id=key, title=' '.join(title.split()), abstract=abstract,
                authors=author, updated=date.isoformat(), paper_url=paper_url,
                pdf_url=f'https://arxiv.org/pdf/{arxiv_id}.pdf' if arxiv_id else '',
                topic=topic, display_id=display, sources=['huggingface'],
                hf_daily={'dates': [day.isoformat()], 'url': url,
                    'evidence_sha256': hashlib.sha256((' '.join(title.split())+'\0'+abstract).encode()).hexdigest()},
                archive_row=f'|**{date.isoformat()}**|**{clean_title}**|{clean_author}|[{display}]({paper_url})|null|\n'))
    return records


def fetch_day(day: dt.date, *, session=None, sleeper=time.sleep) -> list:
    session = session or requests.Session()
    url = f'{API}?date={day.isoformat()}'
    items, visited = [], set()
    for _ in range(20):
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        if (parsed.scheme != 'https' or parsed.netloc != 'huggingface.co'
                or parsed.path != '/api/daily_papers' or parsed.fragment
                or query.get('date') != [day.isoformat()] or set(query) - {'date', 'p'}
                or url in visited):
            raise ValueError('Unsafe or cyclic HF pagination')
        visited.add(url)
        for attempt in range(3):
            try:
                response = session.get(url, timeout=(10, 30), allow_redirects=False)
                if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                    delay = response.headers.get('Retry-After', '')
                    delay = int(delay) if delay.isdigit() else 2 ** (attempt + 1)
                    if delay > 30:
                        response.raise_for_status()
                    sleeper(delay)
                    continue
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError('HF redirected or returned an unexpected status')
                payload = response.json()
                if not isinstance(payload, list):
                    raise ValueError('HF daily response must be a list')
                break
            except (requests.ConnectionError, requests.Timeout):
                if attempt == 2:
                    raise
                sleeper(2 ** (attempt + 1))
        items.extend(payload)
        next_link = response.links.get('next', {}).get('url')
        if not next_link:
            return items
        url = next_link
    raise ValueError('HF pagination exceeded 20 pages')


def collect_daily(config: dict, archive: dict, ledger: dict, ledger_path, now: dt.datetime) -> tuple[dict, dict]:
    """Checkpoint complete dates independently; refresh overlap on every cloud slot."""
    settings = config.get('collection', {}).get('huggingface', {})
    result = {'collected': 0, 'new_candidates': 0, 'failed_dates': []}
    if not settings.get('enabled', False):
        return ledger, result
    today = now.astimezone(ZoneInfo('Asia/Shanghai')).date()
    start = dt.date.fromisoformat(str(settings.get('start_date', today)))
    receipt = ledger.get('huggingface_collection', {})
    cursor = dt.date.fromisoformat(receipt.get('completed_through', start.isoformat()))
    overlap = max(1, int(settings.get('overlap_days', 3)))
    day = max(start, min(cursor, today) - dt.timedelta(days=overlap - 1))
    end = min(today, day + dt.timedelta(days=6))
    failed = False
    while day <= end:
        try:
            records = daily_records(fetch_day(day), config, day)
            _, updated, added = merge_collected_candidates(archive, ledger, records, list(config['keywords']))
            state = dict(updated.get('huggingface_collection', {}))
            if not failed:
                state['completed_through'] = day.isoformat()
            state.update(checked_at=now.isoformat(), status='incomplete' if failed else 'complete', failed_dates=list(result['failed_dates']))
            updated['huggingface_collection'] = state
            atomic_write_json(ledger_path, updated)
            ledger = updated
            result['collected'] += len({row['id'] for row in records})
            result['new_candidates'] += added
        except (requests.RequestException, ValueError) as error:
            failed = True
            result['failed_dates'].append(day.isoformat())
            ledger['huggingface_collection'] = {**ledger.get('huggingface_collection', {}),
                'checked_at': now.isoformat(), 'status': 'incomplete',
                'failed_dates': list(result['failed_dates']), 'error': str(error)[:500]}
            atomic_write_json(ledger_path, ledger)
        day += dt.timedelta(days=1)
    if end < today:
        result['failed_dates'].append('catchup_pending')
        ledger['huggingface_collection'] = {**ledger.get('huggingface_collection', {}),
            'status': 'incomplete', 'failed_dates': list(result['failed_dates'])}
        atomic_write_json(ledger_path, ledger)
    return ledger, result


def external_rows(ledger: dict) -> list[dict]:
    """Non-arXiv publications never enter the arXiv acquisition queue."""
    from .conference_library import display_id
    rows = []
    for key, entry in ledger.get('papers', {}).items():
        if not HF_ID.fullmatch(key) or entry.get('status') != 'accepted' or not entry.get('selected_topic'):
            continue
        published = dt.date.fromisoformat(entry['updated'])
        rows.append(dict(id=key, title=entry['title'], date=published, authors=entry['authors'],
            paper_url=entry['paper_url'], display_id=display_id({'published': published.isoformat()}),
            topics=(entry['selected_topic'],), tags=(), institutions=(), paper_type='paper',
            annotation_status='pending', hf_daily=entry['hf_daily']))
    return rows
