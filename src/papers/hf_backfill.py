"""Explicit, resumable newest-first HF history intake and isolated review.

plan is read-only; cache writes only private evidence; apply imports a bounded
cached interval as candidates, without reviewing, publishing or scheduling it.
review keeps historical responses private; apply-reviewed adds only accepted
new identities. Neither stage publishes or starts another scheduler.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import requests
import yaml

from papers import paths, routine_priority
from papers.candidate_ledger import atomic_write_json, merge_collected_candidates, merge_sources, reopen_depth_candidate
from papers.huggingface import API, daily_records, fetch_day
from papers.hf_history_review import Deferred

REPORT = paths.ROOT / 'build/reports/hf-2024-2025'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def dates(start, end):
    while end >= start:
        yield end
        end -= dt.timedelta(days=1)


def metadata_priority():
    config = yaml.safe_load(paths.CONFIG.read_text(encoding='utf-8'))
    return config.get('collection', {}).get('huggingface', {}).get('historical_metadata_priority') is True


def admit(*, metadata=False):
    result = routine_priority.check()
    overridable = all(reason.startswith('routine_pending:') or reason == 'collection_not_verified' for reason in result['reasons'])
    if not result['admitted'] and not (metadata and metadata_priority() and overridable):
        raise Deferred('; '.join(result['reasons']))
    return result


class AdmittedSession(requests.Session):
    def get(self, *args, **kwargs):
        # Includes every retry and pagination request in fetch_day.
        admit(metadata=True)
        from papers.runtime import daily_waiting
        if daily_waiting() and not metadata_priority():
            raise Deferred('daily_requested_runtime')
        return super().get(*args, **kwargs)


def validate_cache(value, day):
    if (value.get('schema_version') != 1 or value.get('day') != str(day)
            or value.get('source') != f'{API}?date={day}'
            or not isinstance(value.get('items'), list)
            or value.get('response_sha256') != digest(value['items'])):
        raise ValueError(f'Invalid cached HF evidence: {day}')
    return value['items']


def read_cache(day):
    value = json.loads((REPORT / 'days' / f'{day}.json').read_text(encoding='utf-8'))
    return validate_cache(value, day)


def plan(start, end):
    cached, pending, invalid = [], [], []
    for day in dates(start, end):
        try:
            read_cache(day)
            cached.append(str(day))
        except FileNotFoundError:
            pending.append(str(day))
        except (ValueError, TypeError, KeyError):
            invalid.append(str(day))
    return dict(start=str(start), end=str(end), total_days=(end-start).days+1,
                cached_days=len(cached), pending_days=len(pending),
                next_date=max(invalid + pending, default=None), invalid_dates=invalid,
                admission=routine_priority.check(), status='planned')


def cache(start, end, limit, config):
    result = plan(start, end)
    result.update(status='running', fetched_dates=[])
    try:
        admit(metadata=True)
        with AdmittedSession() as session:
            for day in dates(start, end):
                if len(result['fetched_dates']) >= limit:
                    break
                admit(metadata=True)
                try:
                    read_cache(day)
                    continue
                except FileNotFoundError:
                    pass
                # fetch_day supplies bounded retries; failures stop this slice.
                result['current_date'] = str(day)
                items = fetch_day(day, session=session)
                daily_records(items, config, day)
                atomic_write_json(REPORT / 'days' / f'{day}.json', {
                    'schema_version': 1, 'day': str(day), 'items': items,
                    'source': f'{API}?date={day}', 'response_sha256': digest(items),
                    'fetched_at': dt.datetime.now(dt.timezone.utc).isoformat()})
                result['fetched_dates'].append(str(day))
                result.update(plan(start, end), status='running')
                atomic_write_json(REPORT / 'state.json', result)
        result.update(plan(start, end))
        result['status'] = 'cached' if not result['pending_days'] else 'checkpoint'
    except Deferred as error:
        result.update(status='deferred', reason=str(error), admission=routine_priority.check())
    except (requests.RequestException, ValueError, OSError) as error:
        result.update(status='failed', reason=str(error)[:1000])
        stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        atomic_write_json(REPORT / 'failures' / f'{stamp}.json', result)
    atomic_write_json(REPORT / 'state.json', result)
    return result


def apply(start, end, config):
    """Require the entire explicit slice cached and preserve all review decisions."""
    from papers.summaries.paths import run_lock
    admit()
    records = []
    evidence = []
    for day in dates(start, end):
        items = read_cache(day)
        records.extend(daily_records(items, config, day))
        evidence.append({'day': str(day), 'response_sha256': digest(items)})
    with run_lock():
        if subprocess.check_output(['git', 'status', '--porcelain'], cwd=paths.ROOT).strip():
            raise Deferred('dirty_workspace: commit or preserve current work before apply')
        before = paths.LEDGER.read_bytes()
        archive_before = paths.ARCHIVE.read_bytes()
        ledger, archive = json.loads(before), json.loads(archive_before)
        next_archive, updated, added = merge_collected_candidates(archive, ledger, records, list(config['keywords']))
        if archive != next_archive:
            raise ValueError('HF intake must not alter archive')
        allowed = {'sources', 'hf_daily', 'matched_topics', 'archive_rows', 'display_id'}
        incoming = {}
        for record in records:
            first = incoming.setdefault(record['id'], dict(record))
            merge_sources(first, record)
        reopened_ids = []
        for key, old in ledger['papers'].items():
            new = updated['papers'][key]
            expected = reopen_depth_candidate(old, incoming.get(key, {}))
            if expected is not old:
                reopened_ids.append(key)
            if ({k: v for k, v in expected.items() if k not in allowed}
                    != {k: v for k, v in new.items() if k not in allowed}
                    or any(new['archive_rows'].get(k) != v for k, v in old.get('archive_rows', {}).items())):
                raise ValueError(f'Existing candidate metadata changed: {key}')
        report = dict(start=str(start), end=str(end), days=len(evidence),
                      unique_matches=len({r['id'] for r in records}), new_candidates=added,
                      reopened_ids=sorted(reopened_ids),
                      config_sha256=digest(config['keywords']), daily_evidence=evidence,
                      before_sha256=hashlib.sha256(before).hexdigest(), status='prepared')
        # Durable intent before mutation; replay is idempotent via the existing merge.
        atomic_write_json(REPORT / f'apply-{start}-{end}.json', report)
        admit()
        if paths.LEDGER.read_bytes() != before or paths.ARCHIVE.read_bytes() != archive_before:
            raise Deferred('public_inputs_changed')
        atomic_write_json(paths.LEDGER, updated)
        report.update(status='collected_pending_review', after_sha256=hashlib.sha256(paths.LEDGER.read_bytes()).hexdigest())
        atomic_write_json(REPORT / f'apply-{start}-{end}.json', report)
        return report


def mark_existing(start, end, config):
    """Enrich only papers already present in the published search index."""
    from papers.summaries.paths import run_lock
    admit(metadata=True)
    records = [record for day in dates(start, end) for record in daily_records(read_cache(day), config, day)]
    with run_lock():
        before = paths.LEDGER.read_bytes()
        archive_bytes = paths.ARCHIVE.read_bytes()
        archive, ledger = json.loads(archive_bytes), json.loads(before)
        library_path = paths.CONTENT/'conference-library.json'
        library_before = library_path.read_bytes()
        library = json.loads(library_before)
        visible = {item['id'].removeprefix('paper:') for item in json.loads((paths.DOCS/'search-index.json').read_text())['documents'] if item['kind'] == 'paper'}
        conference_matches = {}
        for key,record in library['papers'].items():
            if key in visible and record.get('arxiv_id'):
                conference_matches.setdefault(record['arxiv_id'], []).append(key)
        conference_changed = set()
        for record in records:
            for key in conference_matches.get(record['id'], []):
                target = library['papers'][key]
                prior = json.dumps(target, sort_keys=True)
                merge_sources(target, record)
                if json.dumps(target, sort_keys=True) != prior:
                    conference_changed.add(key)
        eligible = [record for record in records if record['id'] in visible]
        missing = [record for record in eligible if record['id'] not in ledger['papers']]
        _, updated, _ = merge_collected_candidates(archive, ledger, missing, list(config['keywords']))
        for record in eligible:
            merge_sources(updated['papers'][record['id']], record)
        for key, old in ledger['papers'].items():
            new = updated['papers'][key]
            if {k:v for k,v in old.items() if k not in ('sources','hf_daily')} != {k:v for k,v in new.items() if k not in ('sources','hf_daily')}:
                raise ValueError('Review metadata changed: '+key)
        assert set(updated['papers']) - set(ledger['papers']) <= visible
        changed = sorted(key for key,value in updated['papers'].items() if value != ledger['papers'].get(key))
        new_candidates = {record['id'] for record in records} - visible - conference_matches.keys()
        report = dict(start=str(start), end=str(end), status='prepared', matched_existing=len({r['id'] for r in eligible}), changed_ids=changed, conference_changed_ids=sorted(conference_changed), awaiting_review=len(new_candidates), new_candidates_added=0)
        atomic_write_json(REPORT/f'mark-existing-{start}-{end}.json', report)
        if paths.LEDGER.read_bytes() != before or paths.ARCHIVE.read_bytes() != archive_bytes or library_path.read_bytes() != library_before:
            raise Deferred('public_inputs_changed')
        if changed:
            atomic_write_json(paths.LEDGER, updated)
        if conference_changed:
            atomic_write_json(library_path, library)
        report['status'] = 'marked_existing'
        atomic_write_json(REPORT/f'mark-existing-{start}-{end}.json', report)
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('plan', 'cache', 'apply', 'mark-existing', 'review', 'apply-reviewed'))
    parser.add_argument('--start', type=dt.date.fromisoformat, default=dt.date(2024, 1, 1))
    parser.add_argument('--end', type=dt.date.fromisoformat, default=dt.date(2025, 12, 31))
    parser.add_argument('--limit', type=int, default=31, help='maximum new cache days or review papers per slice (1–31)')
    parser.add_argument('--repair-manifest', type=Path, help='explicit private held-review repair scope; normal routine admission required')
    args = parser.parse_args(argv)
    if args.repair_manifest is not None and args.command not in ('review', 'apply-reviewed'):
        parser.error('--repair-manifest is only valid for review/apply-reviewed')
    if not dt.date(2024, 1, 1) <= args.start <= args.end <= dt.date(2025, 12, 31):
        parser.error('date range must be within 2024–2025')
    if not 1 <= args.limit <= 31:
        parser.error('limit must be 1–31')
    if sys.platform != 'linux':
        parser.error('Run inside the shared WSL/Linux environment')
    if args.command == 'plan':
        result = plan(args.start, args.end)
    else:
        from papers.runtime import lock
        config = yaml.safe_load(paths.CONFIG.read_text(encoding='utf-8'))
        with lock('hf-history.lock', blocking=False) as owner:
            if not owner:
                result = {'status': 'deferred', 'reason': 'hf_history_owned'}
            else:
                with lock('runtime.lock', blocking=False) as available:
                    if not available:
                        result = {'status': 'deferred', 'reason': 'runtime_owned'}
                    else:
                        try:
                            if args.command in ('review', 'apply-reviewed'):
                                from papers.hf_history_review import review, apply_reviewed
                                result = (review(args.start, args.end, args.limit, config, repair_manifest=args.repair_manifest) if args.command == 'review'
                                          else apply_reviewed(args.start, args.end, config, repair_manifest=args.repair_manifest))
                            else:
                                result = (cache(args.start, args.end, args.limit, config)
                                          if args.command == 'cache' else mark_existing(args.start, args.end, config)
                                          if args.command == 'mark-existing' else apply(args.start, args.end, config))
                        except Deferred as error:
                            result = {'status': 'deferred', 'reason': str(error)}
                    if result['status'] == 'deferred':
                        atomic_write_json(REPORT / 'last-deferred.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 4 if result['status'] == 'deferred' else 1 if result['status'] == 'failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
