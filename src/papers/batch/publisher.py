"""Publish validated private batch annotations into the public annotation catalog."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
import json
from pathlib import Path

from papers.annotations.catalog import (
    annotation_labels_for_topics,
    annotation_from_value,
    filter_annotation_for_topics,
    load_annotation_catalog,
    load_annotation_definitions,
    load_topic_tag_allowlists,
    write_annotation_catalog,
)
from papers.annotations.models import PaperAnnotation, PaperAnnotationError
from papers.candidate_ledger import load_candidate_ledger, normalize_arxiv_id
from papers.paths import ANNOTATIONS, ARCHIVE, CONFIG, DOCS, LEDGER
from papers.site import parse_entry
from papers.summaries.models import PaperSummaryError
from papers.summaries.paths import run_lock
from papers.summaries.publisher import load_ready_keys

from . import workflow
from .catalog import ArchiveCandidate, archive_review_state


ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class AnnotationPublishResult:
    scanned: int
    eligible: int
    existing: int
    invalid: int
    published: int


def sanitize_annotation_catalog(
    annotations: dict[str, PaperAnnotation],
    labels,
    allowlists,
    topics_by_id: dict[str, set[str]],
) -> tuple[dict[str, PaperAnnotation], set[str]]:
    """Preserve catalog records while removing tags outside current archive topics."""
    result = dict(annotations)
    changed: set[str] = set()
    for paper_id, annotation in annotations.items():
        topics = topics_by_id.get(paper_id)
        if not topics:
            continue
        filtered = filter_annotation_for_topics(annotation, labels, allowlists, topics)
        if filtered != annotation:
            result[paper_id] = filtered
            changed.add(paper_id)
    return result, changed


def _load_archive_items(archive_path: Path, ledger_path: Path):
    """Load every archive topic entry, including entries with public summaries."""
    try:
        archive = json.loads(Path(archive_path).read_text(encoding="utf-8"))
        ledger = load_candidate_ledger(ledger_path)["papers"]
        if not isinstance(archive, dict) or not set(archive).issubset(workflow.TOPIC_SLUGS):
            raise ValueError("invalid archive topics")
        result = {}
        for topic, entries in archive.items():
            if not isinstance(entries, dict):
                raise ValueError("invalid archive category")
            for raw_id, row in entries.items():
                paper_id = normalize_arxiv_id(raw_id)
                parsed = parse_entry(paper_id, row)
                ledger_entry = ledger.get(paper_id, {})
                historical = not bool(ledger_entry)
                review_state = archive_review_state(ledger_entry, topic)
                title = ledger_entry.get("title") or parsed["title"]
                abstract = ledger_entry.get("abstract") or ""
                if not isinstance(title, str) or not isinstance(abstract, str):
                    raise ValueError("invalid paper metadata")
                item = ArchiveCandidate(
                    paper_id,
                    " ".join(title.split()),
                    topic,
                    parsed["date"],
                    historical,
                    review_state,
                    abstract,
                )
                previous = result.get((topic, paper_id))
                if previous is None or item.updated > previous.updated:
                    result[topic, paper_id] = item
        return result
    except PaperAnnotationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError, KeyError, AttributeError, PaperSummaryError):
        raise PaperAnnotationError(
            "invalid_archive", "archive or candidate ledger cannot be read safely"
        ) from None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _load_receipt(path: Path):
    try:
        raw = path.read_bytes()
        if not raw or len(raw) > 16 * 1024:
            return None
        value = json.loads(
            raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique_object
        )
        return value if isinstance(value, dict) else None
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RecursionError):
        return None


def _receipt_annotation(item, labels):
    if workflow.note_status(item) != "ready":
        return None, True
    _, receipt_path = workflow.note_paths(item)
    receipt = _load_receipt(receipt_path)
    if receipt is None:
        return None, True
    if receipt.get("accept") is not True:
        return None, False
    if (
        receipt.get("review_origin") not in {"ledger", "local_model"}
        or not isinstance(receipt.get("accept_reason"), str)
        or not receipt["accept_reason"].strip()
    ):
        return None, True
    value = {
        "topics": receipt.get("topics"),
        "tags": receipt.get("tags"),
        "paper_type": receipt.get("paper_type"),
        "institutions": receipt.get("institutions"),
    }
    try:
        return annotation_from_value(item.arxiv_id, value, labels), False
    except PaperAnnotationError:
        return None, True


def publish_annotations(
    *,
    dry_run: bool = False,
    config_path: str | Path = CONFIG,
    archive_path: str | Path = ARCHIVE,
    ledger_path: str | Path = LEDGER,
    catalog_path: str | Path = ANNOTATIONS,
    docs_root: str | Path = DOCS,
) -> AnnotationPublishResult:
    """Add missing annotations backed by current accepted receipts and public summaries."""
    context = nullcontext() if dry_run else run_lock()
    with context:
        labels = load_annotation_definitions(config_path)
        allowlists = load_topic_tag_allowlists(config_path, labels)
        annotations = load_annotation_catalog(catalog_path, labels)
        rechecked_ids = {paper_id for paper_id, entry in load_candidate_ledger(ledger_path)['papers'].items()
                         if entry.get('recheck_decisions')}
        archive_items = _load_archive_items(Path(archive_path), Path(ledger_path))
        topics_by_id: dict[str, set[str]] = {}
        for topic, paper_id in archive_items:
            topics_by_id.setdefault(paper_id, set()).add(topic)
        annotations, sanitized_ids = sanitize_annotation_catalog(
            annotations, labels, allowlists, topics_by_id,
        )
        ready = load_ready_keys(docs_root)
        note_keys = workflow.existing_note_keys()
        candidate_keys = sorted(ready & note_keys)

        additions: dict[str, PaperAnnotation] = {}
        eligible_ids = set()
        existing_ids = set()
        conflicted_ids = set()
        invalid = 0
        for key in candidate_keys:
            item = archive_items.get(key)
            if item is None:
                invalid += 1
                continue
            paper_id = item.arxiv_id
            if paper_id in rechecked_ids and paper_id in annotations:
                existing_ids.add(paper_id)
                continue
            allowed_labels = annotation_labels_for_topics(
                labels,
                allowlists,
                topics_by_id[paper_id],
            )
            annotation, receipt_invalid = _receipt_annotation(item, allowed_labels)
            if receipt_invalid:
                invalid += 1
                continue
            if annotation is None:
                continue
            eligible_ids.add(paper_id)
            if paper_id in annotations:
                existing_ids.add(paper_id)
            if paper_id in conflicted_ids:
                continue
            previous = additions.get(paper_id)
            if previous is not None and previous != annotation:
                additions.pop(paper_id)
                conflicted_ids.add(paper_id)
                invalid += 1
                continue
            additions[paper_id] = annotation

        changed_ids = sanitized_ids | {
            paper_id for paper_id, annotation in additions.items()
            if annotations.get(paper_id) != annotation
        }
        if changed_ids and not dry_run:
            write_annotation_catalog(catalog_path, {**annotations, **additions})
        return AnnotationPublishResult(
            scanned=len(candidate_keys),
            eligible=len(eligible_ids),
            existing=len(existing_ids),
            invalid=invalid,
            published=0 if dry_run else len(changed_ids),
        )
