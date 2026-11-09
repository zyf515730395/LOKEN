"""Persist the public candidate ledger used by cloud collection."""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any


LEDGER_VERSION = 1
ARXIV_VERSION = re.compile(r"v\d+$")
VALID_STATUSES = {"pending", "accepted", "rejected"}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def normalize_arxiv_id(paper_id: str) -> str:
    return ARXIV_VERSION.sub("", paper_id.strip())


def empty_ledger() -> dict[str, Any]:
    return {
        "version": LEDGER_VERSION,
        "updated_at": None,
        "papers": {},
        "collection_cursors": {},
    }


def load_candidate_ledger(path: str | Path) -> dict[str, Any]:
    ledger_path = Path(path)
    if not ledger_path.exists():
        return empty_ledger()
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid candidate ledger: {ledger_path}") from error
    if ledger.get("version") != LEDGER_VERSION or not isinstance(
        ledger.get("papers"), dict
    ):
        raise ValueError(f"Unsupported candidate ledger schema: {ledger_path}")
    for paper_id, entry in ledger["papers"].items():
        if not isinstance(entry, dict) or entry.get("status") not in VALID_STATUSES:
            raise ValueError(f"Invalid candidate ledger entry: {paper_id}")
    if not isinstance(ledger.get("collection_cursors", {}), dict):
        raise ValueError(f"Invalid collection cursors: {ledger_path}")
    return ledger


def atomic_write_json(
    path: str | Path, payload: dict[str, Any], *, pretty: bool = True
) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp-{os.getpid()}")
    content = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2 if pretty else None,
        sort_keys=pretty,
    )
    temporary.write_text(content + ("\n" if pretty else ""), encoding="utf-8")
    os.replace(temporary, destination)


def archive_ids(archive: dict[str, dict[str, object]]) -> set[str]:
    return {
        normalize_arxiv_id(paper_id)
        for entries in archive.values()
        for paper_id in entries
    }


def merge_sources(target: dict, record: dict) -> None:
    """Discovery provenance is a union, never a replacement of paper identity."""
    target['sources'] = sorted(set(target.get('sources', ['arxiv'])) | set(record.get('sources', ['arxiv'])))
    if record.get('hf_daily'):
        old = target.get('hf_daily', {})
        target['hf_daily'] = {**record['hf_daily'], **old,
            'dates': sorted(set(old.get('dates', [])) | set(record['hf_daily'].get('dates', [])))}


def reopen_depth_candidate(entry: dict, record: dict) -> dict:
    """Pure, one-time replay of the 2026-11-09 source exclusion becoming stale.

    Incoming HF discovery is evidence for review eligibility, never acceptance.
    Ordinary rejections and subsequent review decisions remain authoritative.
    """
    migration = entry.get('topic_migration', {})
    evidence = record.get('hf_daily', {})
    if (entry.get('status') != 'rejected' or entry.get('selected_topic') is not None
            or migration.get('date') != '2026-11-09'
            or migration.get('reason') != 'User removed depth-only papers without HF or tracked-conference provenance'
            or migration.get('previous_status') not in (None, 'pending', 'accepted')
            or 'hf_reopened' in migration
            or entry.get('decision_reason') != 'User scope change: depth-only, neither HF nor tracked conference'
            or 'huggingface' not in record.get('sources', [])
            or entry.get('id') != record.get('id')):
        return entry
    # Bind the official source URL and evidence to this exact incoming record.
    url = evidence.get('url', '')
    match = re.fullmatch(r'https://huggingface\.co/papers/(\d{4}\.\d{4,5}(?:v\d+)?)', url)
    title, abstract = record.get('title'), record.get('abstract')
    days = evidence.get('dates')
    if (not match or normalize_arxiv_id(match[1]) != entry['id']
            or not isinstance(title, str) or not title.strip()
            or not isinstance(abstract, str) or not abstract.strip()
            or not isinstance(days, list) or not days
            or evidence.get('evidence_sha256') != hashlib.sha256((' '.join(title.split())+'\0'+abstract).encode()).hexdigest()):
        return entry
    try:
        if any(not isinstance(day, str) or dt.date.fromisoformat(day).isoformat() != day for day in days):
            return entry
    except ValueError:
        return entry
    canonical = entry.get('recheck_decisions', {}).get('3D Gen&Recon')
    migration_rejection = (isinstance(canonical, dict) and canonical.get('accept') is False
                           and canonical.get('reason') == 'User excluded depth-only paper without HF or tracked conference')
    if isinstance(canonical, dict) and canonical.get('accept') is False and not migration_rejection:
        return entry
    result = copy.deepcopy(entry)
    audit = {'source': copy.deepcopy(evidence), 'previous_status': entry['status'],
             'previous_selected_topic': entry.get('selected_topic'),
             'previous_decision_reason': entry['decision_reason']}
    if migration_rejection:
        audit['previous_canonical_decision'] = result['recheck_decisions'].pop('3D Gen&Recon')
    result['topic_migration']['hf_reopened'] = audit
    result.update(status='pending', selected_topic=None,
                  decision_reason='HF source verified after depth scope migration; pending review')
    result['subtopics'] = list(dict.fromkeys([*result.get('subtopics', []), 'Depth Estimation']))
    for field in ('title', 'abstract', 'authors', 'updated', 'paper_url', 'pdf_url'):
        if not result.get(field) and field in record:
            result[field] = record[field]
    return result


def merge_collected_candidates(
    archive: dict[str, dict[str, object]],
    ledger: dict[str, Any],
    paper_records: list[dict[str, Any]],
    topics: list[str],
) -> tuple[dict[str, dict[str, object]], dict[str, Any], int]:
    """Merge public arXiv records while preserving prior review decisions."""
    next_archive = copy.deepcopy(archive)
    for topic in topics:
        next_archive.setdefault(topic, {})
    next_ledger = copy.deepcopy(ledger)
    papers = next_ledger["papers"]
    existing_ids = archive_ids(archive)
    collected_at = utc_now()
    added = 0

    merged: dict[str, dict[str, Any]] = {}
    for record in paper_records:
        paper_id = normalize_arxiv_id(record["id"])
        item = merged.setdefault(
            paper_id,
            {
                **record,
                "id": paper_id,
                "matched_topics": [],
                "archive_rows": {},
            },
        )
        is_arxiv = 'arxiv' in record.get('sources', ['arxiv'])
        if is_arxiv:
            for field in ('title', 'abstract', 'authors', 'updated', 'paper_url', 'pdf_url'):
                item[field] = record[field]
        merge_sources(item, record)
        topic = record["topic"]
        if topic not in item["matched_topics"]:
            item["matched_topics"].append(topic)
        if is_arxiv or topic not in item['archive_rows']:
            item["archive_rows"][topic] = record["archive_row"]

    for paper_id, record in merged.items():
        entry = papers.get(paper_id)
        legacy = entry is None and paper_id in existing_ids
        if legacy and not record.get('hf_daily'):
            continue
        if entry is None:
            entry = {
                "id": paper_id,
                "title": record["title"],
                "abstract": record["abstract"],
                "authors": record["authors"],
                "updated": record["updated"],
                "paper_url": record["paper_url"],
                "pdf_url": record["pdf_url"],
                "matched_topics": [],
                "archive_rows": {},
                "status": "pending",
                "selected_topic": None,
                "decision_reason": None,
                "collected_at": collected_at,
                "reviewed_at": None,
            }
            papers[paper_id] = entry
            entry['sources'] = list(record.get('sources', ['arxiv']))
            if legacy:
                from papers.site import parse_entry
                old_rows = {topic: entries[paper_id] for topic, entries in archive.items() if paper_id in entries}
                old = parse_entry(paper_id, next(iter(old_rows.values())))
                entry.update(title=old['title'], authors=old['authors'], updated=old['date'].isoformat(),
                    paper_url=old['paper_url'], archive_rows=old_rows, matched_topics=list(old_rows),
                    status='accepted', selected_topic=next(iter(old_rows)),
                    decision_reason='Preserved existing published archive membership',
                    collected_at=None, sources=['arxiv'])
            else:
                added += 1

        entry = reopen_depth_candidate(entry, record)
        papers[paper_id] = entry
        hf_only = record.get('sources') == ['huggingface']
        if not hf_only:
            for field in ('title', 'abstract', 'authors', 'updated', 'paper_url', 'pdf_url'):
                entry[field] = record[field]
        merge_sources(entry, record)
        if record.get('display_id'):
            entry.setdefault('display_id', record['display_id'])
        entry["matched_topics"] = sorted(
            set(entry.get("matched_topics", [])) | set(record["matched_topics"])
        )
        entry["archive_rows"] = {
            **entry.get("archive_rows", {}),
            **({k: v for k, v in record['archive_rows'].items() if k not in entry.get('archive_rows', {})}
               if hf_only else record['archive_rows']),
        }

    next_ledger["updated_at"] = collected_at
    return next_archive, next_ledger, added
