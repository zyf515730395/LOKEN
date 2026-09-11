"""Resolve conference publication dates through arXiv, then official web metadata.

python -m papers.conference_dates --apply
Requests/checkpoints are private; verified dates and provenance are public.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlencode, urlsplit, urljoin
import xml.etree.ElementTree as ET

import requests

from papers.paths import ROOT
from papers.conference_library import LIBRARY, load_library
from papers.candidate_ledger import atomic_write_json, utc_now
from papers.proceedings import normalize_title
from papers.summaries.paths import run_lock

PRIVATE = ROOT / 'build/conferences/dates'
ATOM = {'a': 'http://www.w3.org/2005/Atom'}
ARXIV_API = 'https://export.arxiv.org/api/query'


class Fetcher:
    def __init__(self, refresh=False):
        self.refresh = refresh
        self.guard = threading.Lock()
        self.last_arxiv = 0.0
        self.arxiv_retry_after = 0.0

    def __call__(self, url):
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None,443):
            raise ValueError('Unsafe metadata URL')
        key = hashlib.sha256(url.encode()).hexdigest()
        path = PRIVATE / 'responses' / (key + '.raw')
        if not self.refresh and path.exists() and time.time() - path.stat().st_mtime < 30 * 86400:
            return path.read_bytes()
        arxiv = parsed.hostname in {'export.arxiv.org','arxiv.org'}
        if arxiv:
            with self.guard:
                if time.monotonic() < self.arxiv_retry_after:
                    response = requests.Response()
                    response.status_code = 429
                    raise requests.HTTPError('arXiv backoff active',response=response)
                delay = max(0, 3.1 - (time.monotonic() - self.last_arxiv))
                if delay: time.sleep(delay)
                self.last_arxiv = time.monotonic()
        request_url = url
        for hop in range(4):
            response = requests.get(request_url, timeout=(10,45), headers={'User-Agent':'LOKEN-publication-metadata/1.0'}, allow_redirects=False)
            if response.status_code not in (301,302,303,307,308):
                break
            from papers.conference_date_sources import safe_metadata_url
            target = urljoin(request_url,response.headers.get('Location',''))
            if not safe_metadata_url(target):
                raise ValueError('Unsafe metadata redirect')
            request_url = target
        if arxiv and response.status_code == 429:
            retry = response.headers.get('Retry-After', '')
            self.arxiv_retry_after = time.monotonic() + max(600,int(retry) if retry.isdigit() else 600)
        response.raise_for_status()
        if response.status_code != 200 or len(response.content) > 20_000_000:
            raise ValueError('Metadata response unavailable or too large')
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(response.content)
        return response.content


def parse_arxiv(raw: bytes) -> list[dict]:
    root = ET.fromstring(raw)
    results = []
    for entry in root.findall('a:entry', ATOM):
        link = entry.findtext('a:id', '', ATOM)
        match = re.fullmatch(r'https?://arxiv.org/abs/(\d{4}\.\d{4,5})(?:v\d+)?',link)
        if not match:
            raise ValueError('Invalid arXiv response entry')
        published = entry.findtext('a:published','',ATOM)[:10]
        date.fromisoformat(published)
        key = match[1]
        results.append({'arxiv_id':key, 'published':published,
                        'title':' '.join(entry.findtext('a:title','',ATOM).split()),
                        'authors':[n.text for n in entry.findall('a:author/a:name',ATOM)],
                        'date_source':{'url':'https://arxiv.org/abs/'+key, 'basis':'arxiv_first_submission'}})
    return results


def match_arxiv(record: dict, results: list[dict]) -> dict:
    candidates = {item['arxiv_id']:item for item in results
                  if normalize_title(item['title']) == normalize_title(record['title'])
                  and (not record.get('arxiv_id') or record['arxiv_id'] == item['arxiv_id'])}
    if len(candidates) != 1: return {}
    result = next(iter(candidates.values()))
    return {k:v for k,v in result.items() if k != 'title'}


def match_linked_arxiv(record: dict, metadata: dict, results: list[dict]) -> dict:
    linked = [item for item in results if item['arxiv_id'] in metadata.get('arxiv_ids', [])]
    exact = match_arxiv(record, linked)
    if exact:
        return exact
    # An official paper page may link an earlier title, but references alone
    # are not identity evidence: require one link and a corroborating author.
    if len(set(metadata.get('arxiv_ids', []))) != 1 or len(linked) != 1:
        return {}
    item = linked[0]
    if record.get('arxiv_id') and record['arxiv_id'] != item['arxiv_id']:
        return {}
    authors = {normalize_title(name) for name in metadata.get('authors', []) if name.strip()}
    if not authors.intersection(normalize_title(name) for name in item.get('authors', [])):
        return {}
    return {key: value for key, value in item.items() if key != 'title'}


def merge_metadata(record: dict, metadata: dict) -> bool:
    """Never regress precision or overwrite the first-submission date with a venue date."""
    published = metadata.get('published')
    if not published or not re.fullmatch(r'\d{4}(?:-\d{2}){0,2}',published): return False
    parts = [int(x) for x in published.split('-')]
    date(*(parts + [1] * (3-len(parts))))
    source = metadata.get('date_source',{})
    arxiv = source.get('basis') == 'arxiv_first_submission'
    if not arxiv and (record.get('date_source',{}).get('basis') == 'arxiv_first_submission'
                      or len(published) <= len(record['published'])): return False
    if arxiv and not re.fullmatch(r'\d{4}\.\d{4,5}', metadata.get('arxiv_id','')): return False
    before = json.dumps(record,sort_keys=True)
    record.update(published=published, date_source=source)
    if metadata.get('arxiv_id'): record['arxiv_id'] = metadata['arxiv_id']
    if metadata.get('doi'): record['doi'] = metadata['doi']
    if metadata.get('authors'): record['authors'] = metadata['authors']
    return before != json.dumps(record,sort_keys=True)


def title_query(title: str) -> str:
    tokens = re.findall(r'[a-zA-Z0-9]+',title)
    # Distinctive words improve recall for punctuation and subtitle changes.
    tokens = sorted(set(t.casefold() for t in tokens if len(t) > 2 and t.casefold() not in
                        {'the','and','for','with','from','via','towards','based','using'}),key=lambda x:(-len(x),x))[:6]
    return '(' + ' AND '.join('ti:'+term for term in tokens) + ')'


def _save(updates: dict, expected: dict, apply: bool):
    if not apply or not updates: return
    with run_lock():
        library = load_library()
        for key, metadata in updates.items():
            current = library['papers'].get(key)
            if not current or current['title'] != expected[key]['title']:
                raise ValueError('Conference library identity changed during metadata lookup')
            merge_metadata(current, metadata)
        atomic_write_json(LIBRARY, library)


def query_arxiv(records: list[dict], fetch) -> list[dict]:
    query = ' OR '.join(title_query(p['title']) for p in records)
    url = ARXIV_API + '?' + urlencode({'search_query':query,'max_results':1000})
    try:
        raw = fetch(url)
        results = parse_arxiv(raw)
        total = int(ET.fromstring(raw).findtext('{http://a9.com/-/spec/opensearch/1.1/}totalResults','0'))
        if total > 1000:
            raise ValueError('arxiv_query_truncated')
        return results
    except (ValueError, requests.RequestException, ET.ParseError) as error:
        if isinstance(error,requests.HTTPError) and error.response is not None and error.response.status_code == 429:
            raise
        if len(records) <= 1:
            raise
        middle = len(records) // 2
        return query_arxiv(records[:middle],fetch) + query_arxiv(records[middle:],fetch)


def resolve(*, apply=False, limit=0, refresh=False, arxiv_only=False, resume=False) -> dict:
    library = load_library()
    records = sorted((p for p in library['papers'].values() if len(p['published']) < 10
                      or not p.get('arxiv_id')),key=lambda p:(p.get('order_date',p['published']),p['title']),reverse=True)
    if limit: records = records[:limit]
    PRIVATE.mkdir(parents=True,exist_ok=True)
    checkpoint = PRIVATE / 'state.json'
    state = json.loads(checkpoint.read_text(encoding='utf-8')) if checkpoint.exists() else {}
    counts = Counter()
    fetch = Fetcher(refresh)
    updates = {}
    expected = {p['id']:p for p in records}
    # Use cached arXiv matches across previous query groupings and reruns.
    index_path = PRIVATE / 'arxiv-index.json'
    index = json.loads(index_path.read_text(encoding='utf-8')) if index_path.exists() else {}
    by_title = defaultdict(list)
    for item in index.values(): by_title[normalize_title(item['title'])].append(item)
    pending = []
    for record in records:
        found = match_arxiv(record,by_title[normalize_title(record['title'])])
        if found:
            updates[record['id']] = found; counts['arxiv'] += 1
        else:
            checked = state.get(record['id'], {})
            try:
                fresh = (datetime.now(timezone.utc) - datetime.fromisoformat(checked.get('arxiv_checked_at', ''))).total_seconds() < 30 * 86400
            except (ValueError, TypeError):
                fresh = False
            if not refresh and fresh and checked.get('arxiv_status') == 'no_unique_match':
                counts['arxiv_cached_no_match'] += 1
            else:
                pending.append(record)
    _save(updates,expected,apply)
    for offset in range(0,len(pending),20):
        group = pending[offset:offset+20]
        batch_updates = {}
        try:
            results = query_arxiv(group,fetch)
            for item in results: index[item['arxiv_id']] = item
            for record in group:
                found = match_arxiv(record,results)
                state[record['id']] = {'arxiv_checked_at':utc_now(), 'arxiv_status':'matched' if found else 'no_unique_match'}
                if found:
                    batch_updates[record['id']] = found; counts['arxiv'] += 1
            atomic_write_json(index_path,index)
            _save(batch_updates,expected,apply)
            updates.update(batch_updates)
        except (ValueError,requests.RequestException,ET.ParseError) as error:
            counts['arxiv_batch_failed'] += 1
            for record in group: state[record['id']] = {'arxiv_error':type(error).__name__,'arxiv_checked_at':utc_now()}
        atomic_write_json(checkpoint,state)
        print(json.dumps({'stage':'arxiv','checked':min(offset+20,len(pending)), 'total':len(pending),**counts}),flush=True)
    if not arxiv_only:
        from papers.conference_date_sources import web_metadata
        remaining = [p for p in records if p['id'] not in updates
                     and not (resume and not refresh and state.get(p['id'], {}).get('web_applied'))]
        def lookup(record):
            try: return record,web_metadata(record,fetch)
            except (ValueError,requests.RequestException) as error: return record,{'error':type(error).__name__}
        for offset in range(0,len(remaining),32):
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lookup,remaining[offset:offset+32]))
            batch_updates = {}
            explicit = [(record,meta) for record,meta in results if meta.get('arxiv_ids')]
            arxiv_results = []
            if explicit:
                ids = sorted({key for _,meta in explicit for key in meta['arxiv_ids'] if re.fullmatch(r'\d{4}\.\d{4,5}',key)})
                try:
                    arxiv_results = parse_arxiv(fetch(ARXIV_API+'?'+urlencode({'id_list':','.join(ids),'max_results':1000}))) if ids else []
                    for item in arxiv_results:index[item['arxiv_id']]=item
                    atomic_write_json(index_path,index)
                except (ValueError,requests.RequestException,ET.ParseError): counts['explicit_arxiv_failed'] += 1
            for record,metadata in results:
                lookup_errors = metadata.get('lookup_errors', [])
                counts['web_source_failed'] += len(lookup_errors)
                linked = match_linked_arxiv(record,metadata,arxiv_results)
                if linked: metadata=linked
                if merge_metadata(dict(record),metadata):
                    batch_updates[record['id']]=metadata
                    counts['arxiv_link' if linked else 'web_date'] += 1
                else: counts['unresolved'] += 1
                state.setdefault(record['id'],{}).update(web_checked_at=utc_now(),web_applied=apply,
                                                       lookup_errors=lookup_errors,
                                                       web_status='resolved' if record['id'] in batch_updates else 'unresolved')
            _save(batch_updates,expected,apply)
            updates.update(batch_updates)
            atomic_write_json(checkpoint,state)
            print(json.dumps({'stage':'web','checked':min(offset+32,len(remaining)),'total':len(remaining),**counts}),flush=True)
    result={'checked_at':utc_now(),'applied':apply,'selected':len(records),'counts':dict(counts),'updated':len(updates)}
    atomic_write_json(PRIVATE/'report.json',result)
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true');parser.add_argument('--refresh',action='store_true')
    parser.add_argument('--limit',type=int,default=0);parser.add_argument('--arxiv-only',action='store_true')
    parser.add_argument('--resume',action='store_true',help='Skip previously attempted web lookups; --refresh retries them')
    args=parser.parse_args(argv)
    if args.limit < 0: parser.error('limit must be nonnegative')
    print(json.dumps(resolve(apply=args.apply,limit=args.limit,refresh=args.refresh,arxiv_only=args.arxiv_only,resume=args.resume)))


if __name__=='__main__':main()
