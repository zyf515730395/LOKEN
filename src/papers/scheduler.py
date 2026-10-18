"""Due-period receipts for the single Codex local-task coordinator.

This module does not launch agents or models. The coordinator executes the
returned jobs serially and records a result only after checking publication.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta
import json
import sys
from zoneinfo import ZoneInfo

from papers import paths
from papers.candidate_ledger import atomic_write_json

ZONE = ZoneInfo('Asia/Shanghai')
STATE = paths.ROOT / 'build/reports/task-coordinator.json'
JOBS = ('daily', 'models', 'conferences')
STATUSES = ('completed', 'partial', 'failed', 'deferred')


def periods(now):
    if now.tzinfo is None:
        raise ValueError('scheduler time requires a timezone')
    now = now.astimezone(ZONE)
    daily = now.replace(hour=18, minute=0, second=0, microsecond=0)
    if now < daily:
        daily -= timedelta(days=1)
    monthly = model_period_start(now)
    weekly = (now - timedelta(days=now.weekday())).replace(
        hour=10, minute=0, second=0, microsecond=0)
    if now < weekly:
        weekly -= timedelta(days=7)
    return {'daily': daily.strftime('%Y-%m-%d'),
            'models': monthly.strftime('%Y-%m-%d'),
            'conferences': weekly.strftime('%Y-%m-%d')}


def model_period_start(now):
    """Latest due half-month boundary, shared with per-family verification."""
    now = now.astimezone(ZONE)
    first = now.replace(day=1, hour=12, minute=0, second=0, microsecond=0)
    middle = first.replace(day=15)
    if now >= middle:
        return middle
    if now >= first:
        return first
    return (first - timedelta(days=1)).replace(day=15)


def due_jobs(state, now):
    if state.get('resume_after') and now < datetime.fromisoformat(state['resume_after']):
        return []
    due = []
    for job, period in periods(now).items():
        receipt = state.get('jobs', {}).get(job, {})
        # A saved Saturday run belongs to the transition week; do not schedule
        # an older Monday period before the first new Monday becomes due.
        if job == 'conferences' and receipt.get('period', '') > period:
            continue
        saved_period = receipt.get('period', '')
        if job == 'models' and len(saved_period) == 7:
            saved_period += '-01'
        if saved_period >= period and receipt.get('status') in ('completed', 'partial'):
            continue
        retry_at = receipt.get('retry_at')
        if retry_at and datetime.fromisoformat(retry_at) > now:
            continue
        due.append({'job': job, 'period': period})
    return due


def record(state, job, period, status, summary, now):
    if job not in JOBS or status not in STATUSES or not summary.strip():
        raise ValueError('valid job, status and evidence summary are required')
    fmt = '%Y-%m-%d'
    parsed = datetime.strptime(period, fmt)
    # Let the already saved Saturday receipt finish during the Monday transition.
    legacy_conference = (job == 'conferences' and parsed.weekday() == 5
                         and state.get('jobs', {}).get(job, {}).get('period') == period
                         and period <= now.astimezone(ZONE).strftime('%Y-%m-%d'))
    if parsed.strftime(fmt) != period or (period > periods(now)[job] and not legacy_conference):
        raise ValueError('receipt must name an already due period from status')
    if job == 'conferences' and parsed.weekday() != 0 and not legacy_conference:
        raise ValueError('conference period must be a Monday')
    if job == 'models' and parsed.day not in (1, 15):
        raise ValueError('model period must be day 1 or 15')
    result = deepcopy(state)
    result['version'] = 1
    jobs = result.setdefault('jobs', {})
    if jobs.get(job, {}).get('period', '') > period:
        raise ValueError('cannot overwrite a newer period receipt')
    jobs[job] = {'period': period, 'status': status, 'summary': summary,
                 'recorded_at': now.isoformat(),
                 'retry_at': (now + timedelta(hours=1)).isoformat()
                 if status in ('failed', 'deferred') else None}
    return result


def load_state():
    if not STATE.exists():
        return {'version': 1, 'jobs': {}}
    value = json.loads(STATE.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or value.get('version') != 1 or not isinstance(value.get('jobs'), dict):
        raise ValueError('invalid coordinator receipt; preserve it for inspection')
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status')
    add = sub.add_parser('record')
    add.add_argument('job', choices=JOBS)
    add.add_argument('--period', required=True)
    add.add_argument('--status', required=True, choices=STATUSES)
    add.add_argument('--summary', required=True)
    args = parser.parse_args(argv)
    if sys.platform != 'linux':
        parser.error('run coordinator commands inside the shared WSL/Linux environment')
    # Only protects receipt read/modify/write; serial execution is owned by the
    # single enabled heartbeat, while inference uses the existing runtime locks.
    from papers.runtime import lock
    with lock('coordinator-state.lock'):
        now = datetime.now(ZONE)
        state = load_state()
        if args.command == 'record':
            state = record(state, args.job, args.period, args.status, args.summary, now)
            atomic_write_json(STATE, state)
        print(json.dumps({'now': now.isoformat(), 'due': due_jobs(state, now),
                          'receipts': state['jobs']}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
