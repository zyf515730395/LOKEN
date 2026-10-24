"""Read-only, fail-closed admission for historical work between routine jobs."""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re

from papers import paths
from papers.scheduler import JOBS, ZONE, periods

CHECKPOINT_HOURS = (8, 10, 12, 16, 18, 21, 22)
PUBLICATION_RESERVE_SECONDS = 600


def _read(path):
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError(f'Invalid object: {path.name}')
    return value


def _aware(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError('Receipt time requires a timezone')
    return result.astimezone(ZONE)


def check(at=None, *, root=None, reserve_seconds=PUBLICATION_RESERVE_SECONDS):
    """Never interpret an empty due list or a retry delay as completed scope.

    Collection evidence is an independently audited cloud receipt, not the
    ledger modification time or a successful workflow exit alone. This reader
    deliberately cannot create completion receipts or launch network requests.
    """
    at = at or datetime.now(ZONE)
    if at.tzinfo is None or reserve_seconds < 0:
        raise ValueError('Aware time and nonnegative publication reserve required')
    at = at.astimezone(ZONE)
    root = Path(root) if root is not None else paths.ROOT
    checkpoints = [at.replace(hour=h, minute=0, second=0, microsecond=0)
                   + timedelta(days=d) for d in (0, 1) for h in CHECKPOINT_HOURS]
    boundary = min(value for value in checkpoints if value > at)
    reasons = []
    if (boundary - at).total_seconds() <= reserve_seconds:
        reasons.append('next_checkpoint_publication_reserve')
    try:
        state = _read(root/'build/reports/task-coordinator.json')
        if state.get('version') != 1 or not isinstance(state.get('jobs'), dict):
            raise ValueError('Invalid coordinator state')
        if state.get('resume_after') and _aware(state['resume_after']) > at:
            reasons.append('coordinator_paused')
        targets = periods(at)
        for job in JOBS:
            receipt = state['jobs'].get(job, {})
            saved = receipt.get('period', '')
            if job == 'models' and len(saved) == 7:
                saved += '-01'
            if saved != targets[job] or receipt.get('status') not in ('completed', 'partial'):
                reasons.append(f'routine_pending:{job}:{targets[job]}')
        control = root/'build/reports/digests/backfill-control.json'
        if control.exists() and _aware(_read(control)['resume_after']) > at:
            reasons.append('historical_paused')
        collection_slots = [at.replace(hour=h, minute=0, second=0, microsecond=0)
                            - timedelta(days=d) for d in (0, 1) for h in (8, 12, 16)]
        collection_period = max(value for value in collection_slots if value <= at)
        receipt = _read(root/'build/reports/collection-receipt.json')
        evidence = (root/receipt['evidence_path']).resolve()
        evidence.relative_to((root/'build/reports').resolve())
        verified = _aware(receipt['verified_at'])
        if (receipt.get('schema_version') != 1
                or receipt.get('period') != collection_period.strftime('%Y-%m-%dT%H:%M')
                or receipt.get('status') not in ('completed', 'partial')
                or receipt.get('full_attempt') is not True or receipt.get('published') is not True
                or not collection_period <= verified <= at
                or not re.fullmatch(r'https://github\.com/zyf515730395/LOKEN/actions/runs/\d+', receipt.get('run_url', ''))
                or hashlib.sha256(evidence.read_bytes()).hexdigest() != receipt.get('evidence_sha256')):
            reasons.append('collection_not_verified')
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        missing = Path(error.filename).name if getattr(error, 'filename', None) else ''
        reasons.append(f'routine_evidence_unavailable:{type(error).__name__}:{missing}')
    for relative in ('build/paper-summaries/pending-runtime-push.json',
                     'build/paper-summaries/recheck/local-only.json',
                     'build/reports/stocks/pending-publication.json',
                     'build/reports/stocks/actuals/pending-publication.json'):
        if (root/relative).exists():
            reasons.append(f'publication_or_review_pending:{relative}')
    for pending in (root/'build/reports/model-maintenance').glob('pending-publication*.json'):
        try:
            if _read(pending).get('status') != 'completed':
                reasons.append(f'publication_pending:{pending.name}')
        except (OSError, ValueError):
            reasons.append(f'publication_evidence_invalid:{pending.name}')
    return {'admitted': not reasons, 'reasons': reasons,
            'next_checkpoint': boundary.isoformat(),
            'admit_until': (boundary-timedelta(seconds=reserve_seconds)).isoformat()}


def main():
    import sys
    if sys.platform != 'linux':
        raise SystemExit('Run routine admission inside the shared WSL/Linux environment')
    result = check()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['admitted'] else 4


if __name__ == '__main__':
    raise SystemExit(main())
