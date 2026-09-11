"""Identity-checked publication metadata; no full-text or arXiv API requests."""
from __future__ import annotations

from datetime import date
import json
import re
from typing import Callable
from urllib.parse import quote, unquote, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from .conference_sources import HOSTS
from .proceedings import normalize_title


def safe_metadata_url(url: str) -> bool:
    """Limit metadata requests, including the configured SIGGRAPH hosts."""
    try:
        parts = urlsplit(url)
        return bool(parts.scheme == 'https' and parts.username is None
                    and parts.password is None and parts.port in (None, 443)
                    and not any(ord(c) < 33 for c in url)
                    and (parts.hostname in HOSTS or parts.hostname in {'ras.papercept.net', 's2024.conference-program.org'} or re.fullmatch(
                        r'(?:s|sa)20\d{2}\.conference-schedule\.org', parts.hostname or '')))
    except ValueError:
        return False


def _date(value: object) -> str:
    if not isinstance(value, str):
        return ''
    match = re.fullmatch(r'(\d{4})(?:[-/](\d{1,2})(?:[-/](\d{1,2}))?)?(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?', value.strip())
    if not match:
        return ''
    parts = [int(part) for part in match.groups() if part is not None]
    try:
        date(*(parts + [1] * (3 - len(parts))))
    except ValueError:
        return ''
    return '-'.join([f'{parts[0]:04d}'] + [f'{part:02d}' for part in parts[1:]])


def _doi(value: object) -> str:
    if not isinstance(value, str):
        return ''
    value = unquote(value.strip())
    value = re.sub(r'^https://(?:dx\.)?doi\.org/', '', value, flags=re.I)
    return value if re.fullmatch(r'10\.\d{4,9}/[^\s?#]+', value) else ''


def _articles(value: object):
    if isinstance(value, list):
        for node in value:
            yield from _articles(node)
    elif isinstance(value, dict):
        types = value.get('@type', [])
        if isinstance(types, str):
            types = [types]
        if 'ScholarlyArticle' in types:
            yield value
        yield from _articles(value.get('@graph', []))


def _page(raw: bytes, url: str, title: str) -> tuple[dict, str]:
    soup = BeautifulSoup(raw, 'html.parser')
    metadata: dict[str, list[str]] = {}
    for tag in soup.select('meta[content]'):
        key = str(tag.get('name', tag.get('property', ''))).casefold()
        metadata.setdefault(key, []).append(str(tag['content']))
    articles = []
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            articles.extend(_articles(json.loads(node.get_text())))
        except (ValueError, TypeError):
            continue
    expected = normalize_title(title)
    identities = metadata.get('citation_title', []) or metadata.get('dc.title', [])
    if not identities:
        identities = [tag.get_text(' ', strip=True) for tag in soup.select('h1, h2, #papertitle')]
    matching_articles = [a for a in articles if normalize_title(str(a.get('headline', a.get('name', '')))) == expected]
    declared_titles = metadata.get('citation_title', []) or metadata.get('dc.title', [])
    if declared_titles and any(normalize_title(t) != expected for t in declared_titles):
        return {}, ''
    if len(matching_articles) > 1:
        return {}, ''
    if not expected or not (any(normalize_title(t) == expected for t in identities) or matching_articles):
        return {}, ''
    # A proceedings listing with multiple citation records is not a paper page.
    if len({normalize_title(t) for t in metadata.get('citation_title', [])}) > 1:
        return {}, ''
    result = {}
    dates = []
    for key in ('citation_publication_date', 'dc.date.issued', 'dc.date'):
        dates.extend(filter(None, (_date(v) for v in metadata.get(key, []))))
    dates.extend(filter(None, (_date(a.get('datePublished')) for a in matching_articles)))
    if dates:
        # Conflicting date metadata cannot establish a publication date.
        selected = max(dates, key=len)
        if all(selected.startswith(d) for d in dates):
            result.update(published=selected, date_source={'url': url, 'basis': 'publisher_publication'})
    authors = metadata.get('citation_author', [])
    if authors:
        result['authors'] = list(dict.fromkeys(a.strip() for a in authors if a.strip()))
    ids = []
    links = [str(a['href']) for a in soup.select('a[href]')]
    links.extend(metadata.get('citation_pdf_url', []))
    for link in links:
        match = re.fullmatch(r'https?://arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})(?:v[1-9]\d*)?(?:\.pdf)?', urljoin(url, link))
        if match and match.group(1) not in ids:
            ids.append(match.group(1))
    if ids:
        result['arxiv_ids'] = ids
    dois = {_doi(v) for v in metadata.get('citation_doi', [])} - {''}
    return result, next(iter(dois)) if len(dois) == 1 else ''


def _crossref(title: str, doi: str, fetch: Callable[[str], bytes]) -> dict:
    url = ('https://api.crossref.org/works/' + quote(doi, safe='') if doi else
           'https://api.crossref.org/works?' + urlencode({'query.title': title, 'rows': 5}))
    message = json.loads(fetch(url)).get('message', {})
    items = [message] if doi else message.get('items', [])
    matches = {}
    for item in items:
        titles = item.get('title', [])
        candidate_doi = _doi(item.get('DOI'))
        if (candidate_doi and any(normalize_title(str(t)) == normalize_title(title) for t in titles)
                and (not doi or candidate_doi.casefold() == doi.casefold())):
            matches[candidate_doi.casefold()] = item
    if len(matches) != 1:
        return {}
    item = next(iter(matches.values()))
    dates = []
    for field in ('published-online', 'published-print', 'published'):
        parts = item.get(field, {}).get('date-parts', [])
        if len(parts) == 1 and isinstance(parts[0], list) and 1 <= len(parts[0]) <= 3:
            values = parts[0]
            if all(type(p) is int for p in values):
                parsed = _date('-'.join(str(p) for p in values))
                if parsed:
                    dates.append(parsed)
    if not dates:
        return {}
    # Earliest actual publication wins, retaining its original precision.
    precise = [value for value in dates if not any(other.startswith(value) and len(other) > len(value) for other in dates)]
    published = min(precise)
    return {'published': published, 'date_source': {
        'url': 'https://doi.org/' + _doi(item['DOI']), 'basis': 'publisher_publication'}}


def web_metadata(record: dict, fetch: Callable[[str], bytes]) -> dict:
    """Resolve exact-title official dates; the caller owns caching and redirects.

    Fetchers must validate each redirect with ``safe_metadata_url`` and bound
    response sizes. An unavailable page does not prevent independent DOI lookup.
    """
    title = str(record.get('title', ''))
    if not normalize_title(title):
        return {}
    result = {}
    url = str(record.get('url', ''))
    errors = []
    doi = _doi(record.get('doi', ''))
    safe_url = safe_metadata_url(url)
    if not doi and safe_url and urlsplit(url).hostname == 'doi.org':
        doi = _doi(url)
    if safe_url and urlsplit(url).hostname not in {'arxiv.org', 'api.crossref.org', 'doi.org'}:
        try:
            result, page_doi = _page(fetch(url), url, title)
            doi = doi or page_doi
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
            errors.append({'source': url, 'error': type(error).__name__})
    if len(result.get('published', '')) < 10:
        try:
            fallback = _crossref(title, doi, fetch)
            existing = result.get('published', '')
            candidate = fallback.get('published', '')
            if candidate and (not existing or candidate.startswith(existing) and len(candidate) > len(existing)):
                result.update(fallback)
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
            errors.append({'source': 'https://api.crossref.org', 'error': type(error).__name__})
    if errors:
        result['lookup_errors'] = errors
    return result
