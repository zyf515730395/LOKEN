"""Versioned, private failure queues for conference source and inference recovery."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json

RECOVERY_VERSION = 'conference-recovery-v1'
MATERIAL = frozenset({'introduction_unavailable', 'abstract_unavailable', 'html_unavailable',
    'pdf_invalid', 'source_too_large', 'paper_too_large', 'ocr_unavailable', 'ocr_failed',
    'body_evidence_unavailable', 'pdf_dependency_missing', 'source_access_denied', 'source_not_found'})
ADAPTER = frozenset({'source_redirect_rejected', 'source_url_unsupported', 'source_metadata_invalid', 'source_retry_state_invalid'})


def source_signature(record: dict) -> str:
    value = {key: record.get(key) for key in ('id', 'title', 'url', 'doi', 'arxiv_id', 'source_version')}
    value['official_sources'] = [{key: item.get(key) for key in ('edition', 'url', 'source_version')}
        for item in [*record.get('conferences', []), *record.get('provenance', [])] if isinstance(item, dict)]
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def current_attempt(record: dict, receipt: dict) -> bool:
    released = receipt.get('reviewed_release', {}).get('reviewed_at')
    if released and released > receipt.get('attempted_at', ''):
        return False
    if receipt.get('retry_policy') is None and receipt.get('status') != 'failed':
        return not record.get('source_refresh')
    return (receipt.get('retry_policy') == RECOVERY_VERSION
            and receipt.get('source_signature') == source_signature(record))


def retry_allowed(record: dict, receipt: dict, *, now: datetime | None = None) -> bool:
    if receipt.get('status') != 'failed' or not current_attempt(record, receipt):
        return True
    deadline = receipt.get('next_retry_at')
    if deadline is None:
        return False
    try:
        target = datetime.fromisoformat(deadline)
        return target.tzinfo is not None and target <= (now or datetime.now(timezone.utc))
    except (ValueError, TypeError):
        return False


def queue_for(code: str) -> str:
    if code == 'paper_identity_mismatch':
        return 'identity'
    if code in MATERIAL:
        return 'material'
    if code in ADAPTER:
        return 'adapter'
    if code.startswith(('source_', 'http_')) or code in {'Timeout', 'TimeoutError', 'ConnectionError'}:
        return 'network'
    return 'annotation'


def failed_receipt(record: dict, receipt: dict, previous: dict, details: dict,
                   *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    code = receipt['error']
    codes = [code, *receipt.get('errors', {}).values()]
    # Identity/source quarantine must survive a simultaneous annotation failure.
    rank = {'identity': 0, 'adapter': 1, 'material': 2, 'network': 3, 'annotation': 4}
    queue = min((queue_for(c) for c in codes), key=rank.get)
    same = (current_attempt(record, previous) and previous.get('error') == code
            and previous.get('status') == 'failed')
    streak = previous.get('failure_streak', 0) + 1 if same else 1
    days = 7 if queue in {'material', 'adapter'} else (1, 3, 7)[min(streak - 1, 2)]
    target = now + timedelta(days=days)
    if queue == 'network' and details.get('retry_at'):
        try:
            retry_at = datetime.fromisoformat(details['retry_at'])
            if retry_at.tzinfo is not None and retry_at > now:
                target = max(target, retry_at)
        except (ValueError, TypeError):
            pass
    return {**receipt, 'retry_policy': RECOVERY_VERSION, 'retry_queue': queue,
            'source_signature': source_signature(record), 'failure_streak': streak,
            'next_retry_at': None if queue == 'identity' else target.isoformat(),
            'failure_details': details}
