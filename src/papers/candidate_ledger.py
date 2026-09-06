"""Persist the public candidate ledger used by cloud collection."""

from __future__ import annotations

import copy
import datetime as dt
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
        topic = record["topic"]
        if topic not in item["matched_topics"]:
            item["matched_topics"].append(topic)
        item["archive_rows"][topic] = record["archive_row"]

    for paper_id, record in merged.items():
        entry = papers.get(paper_id)
        if entry is None and paper_id in existing_ids:
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
            added += 1

        entry["title"] = record["title"]
        entry["abstract"] = record["abstract"]
        entry["authors"] = record["authors"]
        entry["updated"] = record["updated"]
        entry["paper_url"] = record["paper_url"]
        entry["pdf_url"] = record["pdf_url"]
        entry["matched_topics"] = sorted(
            set(entry.get("matched_topics", [])) | set(record["matched_topics"])
        )
        entry["archive_rows"] = {
            **entry.get("archive_rows", {}),
            **record["archive_rows"],
        }

    next_ledger["updated_at"] = collected_at
    return next_archive, next_ledger, added
