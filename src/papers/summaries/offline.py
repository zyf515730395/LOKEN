"""Publish locally reviewed summary caches without changing curation ledgers."""

from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from papers.site import generate_site, parse_entry
from shared.rendering import atomic_write_bytes

from .acquisition import ArxivSourceClient
from .cache import PaperSummaryCache, cache_key
from .catalog import PaperCandidate, TOPIC_SLUGS, notes_path
from .models import PaperSummary, PaperSummaryError
from .paths import PRIVATE_ROOT, normalize_arxiv_id, run_lock
from .publisher import load_ready_keys, publish_summaries, restore_topic_document


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REVIEW = PRIVATE_ROOT / "batch" / "topic-review.json"
DEFAULT_DOCS = PROJECT_ROOT / "docs"
DEFAULT_ARCHIVE = PROJECT_ROOT / "content" / "papers" / "archive.json"
DEFAULT_LEDGER = PROJECT_ROOT / "content" / "papers" / "arxiv-candidates.json"
DEFAULT_MILESTONES = PROJECT_ROOT / "config" / "milestone_models.yaml"
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "site.yaml"
DEFAULT_ANNOTATIONS = PROJECT_ROOT / "content" / "papers" / "paper-annotations.json"
OFFLINE_STATE = PRIVATE_ROOT / "offline-import-state.json"
REVIEW_POLICY = "archive-topic-review-v1"
SUPPORTED_REVIEW_POLICIES = (REVIEW_POLICY, "archive-topic-review-v2")
REMOVAL_REVIEW_ACTION = "remove_rejected_topic_entries"
SUPPORTED_REVIEW_ACTIONS = ("review_only_no_deletion", REMOVAL_REVIEW_ACTION)
CACHE_PATH = re.compile(r"cache/(?P<prefix>[0-9a-f]{2})/(?P<key>[0-9a-f]{64})\.json")
REPORT_FIELDS = {
    "id", "topic", "title", "historical", "accept", "accept_reason",
    "review_origin", "source", "summary_cache", "public_url",
}


@dataclass(frozen=True, slots=True)
class OfflineImportResult:
    selected: int
    skipped: int
    published: int
    removed: int


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _read_json(path: Path, *, limit: int) -> object:
    try:
        raw = path.read_bytes()
        if not raw or len(raw) > limit:
            raise ValueError("invalid file size")
        return json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RecursionError):
        raise PaperSummaryError("invalid_offline_review", "offline review data is invalid") from None


def _transaction_identity(docs: Path, archive: Path, ledger: Path) -> dict[str, str]:
    return {
        "docs_root": str(docs.resolve()),
        "archive_path": str(archive.resolve()),
        "ledger_path": str(ledger.resolve()),
    }


def _write_transaction_state(identity: dict[str, str]) -> None:
    payload = {"version": 1, "status": "publishing", **identity}
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    try:
        atomic_write_bytes(OFFLINE_STATE, data)
    except OSError:
        raise PaperSummaryError(
            "state_write_failed", "offline publication state could not be written"
        ) from None


def _read_transaction_state() -> dict[str, str] | None:
    if not OFFLINE_STATE.exists():
        return None
    payload = _read_json(OFFLINE_STATE, limit=16 * 1024)
    if (
        not isinstance(payload, dict)
        or set(payload) != {"version", "status", "docs_root", "archive_path", "ledger_path"}
        or payload["version"] != 1
        or payload["status"] != "publishing"
        or not all(isinstance(payload[name], str) and payload[name] for name in (
            "docs_root", "archive_path", "ledger_path"
        ))
    ):
        raise PaperSummaryError("invalid_offline_state", "offline publication state is invalid")
    return payload


def _clear_transaction_state() -> None:
    try:
        OFFLINE_STATE.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        raise PaperSummaryError("state_write_failed", "offline publication state could not be cleared") from None


def _prune_rejected_topics(
    archive: dict[str, object], rejected: tuple[tuple[str, str], ...]
) -> tuple[dict[str, object], int]:
    """Return a copy without the rejected topic memberships."""
    updated = copy.deepcopy(archive)
    removed = 0
    for topic, paper_id in rejected:
        entries = updated.get(topic)
        if isinstance(entries, dict) and paper_id in entries:
            del entries[paper_id]
            removed += 1
    return updated, removed


def _load_reviewed(
    review_path: Path, docs_root: Path, archive_path: Path
) -> tuple[tuple[PaperCandidate, PaperSummary], int, tuple[tuple[str, str], ...], dict[str, object]]:
    private_root = PRIVATE_ROOT.resolve()
    review = review_path.resolve()
    if not review.is_relative_to(private_root):
        raise PaperSummaryError("unsafe_offline_review", "offline review escaped the private root")
    payload = _read_json(review, limit=32 * 1024 * 1024)
    if (
        not isinstance(payload, dict)
        or set(payload) != {
            "version", "policy_version", "action", "accept_candidates",
            "reject_candidates", "needs_review",
        }
        or payload["version"] != 1
        or payload["policy_version"] not in SUPPORTED_REVIEW_POLICIES
        or payload["action"] not in SUPPORTED_REVIEW_ACTIONS
        or not all(isinstance(payload[name], list) for name in (
            "accept_candidates", "reject_candidates", "needs_review"
        ))
    ):
        raise PaperSummaryError("invalid_offline_review", "offline review schema is invalid")
    archive = _read_json(archive_path, limit=64 * 1024 * 1024)
    if not isinstance(archive, dict) or not set(archive).issubset(TOPIC_SLUGS):
        raise PaperSummaryError("invalid_archive", "paper archive is invalid")
    archived = {}
    try:
        for topic, entries in archive.items():
            if not isinstance(entries, dict):
                raise ValueError
            for paper_id, row in entries.items():
                archived[topic, paper_id] = parse_entry(paper_id, row)
    except (TypeError, ValueError):
        raise PaperSummaryError("invalid_archive", "paper archive is invalid") from None

    ready = load_ready_keys(docs_root)
    results = []
    rejected = []
    skipped = 0
    seen = set()
    cache = PaperSummaryCache()
    review_items = [(item, True) for item in payload["accept_candidates"]]
    if payload["action"] == REMOVAL_REVIEW_ACTION:
        review_items.extend((item, False) for item in payload["reject_candidates"])
    for item, expected_accept in review_items:
        if not isinstance(item, dict) or set(item) != REPORT_FIELDS:
            raise PaperSummaryError("invalid_offline_review", "review entry is invalid")
        paper_id = item["id"]
        topic = item["topic"]
        try:
            normalized = normalize_arxiv_id(paper_id)
        except PaperSummaryError:
            raise PaperSummaryError("invalid_offline_review", "reviewed paper id is invalid") from None
        key = (topic, paper_id)
        row = archived.get(key)
        expected_url = f"notes/{TOPIC_SLUGS.get(topic, '')}.html#summary-{paper_id}"
        if (
            normalized != paper_id
            or key in seen
            or (row is None and expected_accept)
            or item["accept"] is not expected_accept
            or type(item["historical"]) is not bool
            or item["review_origin"] not in {"ledger", "local_model"}
            or not isinstance(item["accept_reason"], str)
            or not item["accept_reason"].strip()
            or item["public_url"] != expected_url
        ):
            raise PaperSummaryError("invalid_offline_review", "review entry does not match archive")
        if row is None:
            seen.add(key)
            continue
        if " ".join(str(item["title"]).split()) != " ".join(row["title"].split()):
            raise PaperSummaryError("invalid_offline_review", "review entry does not match archive")
        cache_path = item["summary_cache"]
        match = CACHE_PATH.fullmatch(cache_path) if isinstance(cache_path, str) else None
        if match is None or match.group("prefix") != match.group("key")[:2]:
            raise PaperSummaryError("invalid_offline_review", "summary cache reference is invalid")
        receipt_path = PRIVATE_ROOT / "markdown" / TOPIC_SLUGS[topic] / f"{paper_id}.json"
        receipt = _read_json(receipt_path, limit=16 * 1024)
        markdown_path = receipt_path.with_suffix(".md")
        try:
            markdown_sha256 = hashlib.sha256(markdown_path.read_bytes()).hexdigest()
        except OSError:
            raise PaperSummaryError("invalid_offline_review", "reviewed Markdown receipt is missing") from None
        acquired = ArxivSourceClient()._load_cached(paper_id, row["title"])
        if (
            not isinstance(receipt, dict)
            or receipt.get("version") != 1
            or any(receipt.get(name) != item[name] for name in (
                "id", "topic", "title", "historical", "accept", "accept_reason",
                "review_origin", "source", "summary_cache", "public_url",
            ))
            or receipt.get("updated") != row["date"].isoformat()
            or receipt.get("review_policy") != payload["policy_version"]
            or not isinstance(receipt.get("model"), str)
            or not receipt["model"].strip()
            or acquired is None
            or receipt.get("source_sha256") != acquired.source_sha256
            or receipt.get("source") != acquired.source_path.relative_to(PRIVATE_ROOT).as_posix()
            or receipt.get("summary_cache")
            != cache.path_for(cache_key(acquired.source_sha256, receipt["model"]))
            .relative_to(PRIVATE_ROOT)
            .as_posix()
            or receipt.get("markdown_sha256") != markdown_sha256
        ):
            raise PaperSummaryError("invalid_offline_review", "reviewed summary is not bound to its paper")
        summary = cache.load(match.group("key"))
        if summary is None:
            raise PaperSummaryError("offline_cache_missing", "reviewed summary cache is missing or invalid")
        seen.add(key)
        if not expected_accept:
            rejected.append(key)
            continue
        if key in ready:
            skipped += 1
            continue
        results.append((PaperCandidate(paper_id, " ".join(row["title"].split()), topic, row["date"]), summary))
    return tuple(results), skipped, tuple(rejected), archive


def publish_offline_summaries(
    *,
    dry_run: bool = False,
    review_path: str | Path = DEFAULT_REVIEW,
    docs_root: str | Path = DEFAULT_DOCS,
    archive_path: str | Path = DEFAULT_ARCHIVE,
    ledger_path: str | Path = DEFAULT_LEDGER,
) -> OfflineImportResult:
    """Publish summaries listed by the fixed private review manifest."""
    docs = Path(docs_root)
    archive = Path(archive_path)
    ledger = Path(ledger_path)
    if dry_run:
        results, skipped, rejected, current_archive = _load_reviewed(Path(review_path), docs, archive)
        _, removed = _prune_rejected_topics(current_archive, rejected)
        return OfflineImportResult(len(results), skipped, 0, removed)
    with run_lock():
        def regenerate() -> None:
            site_project_root = docs.resolve().parent
            generate_site(
                archive,
                docs / "index.html",
                ledger,
                DEFAULT_MILESTONES,
                output_root=docs,
                search_index_path=docs / "search-index.json",
                config_path=DEFAULT_CONFIG,
                annotation_path=DEFAULT_ANNOTATIONS,
                writings_source_root=site_project_root / "content" / "writings",
                writings_report_path=site_project_root / "build" / "reports" / "writings.json",
                refresh_related=False,
            )

        identity = _transaction_identity(docs, archive, ledger)
        interrupted = _read_transaction_state()
        if interrupted is not None:
            if any(interrupted[name] != value for name, value in identity.items()):
                raise PaperSummaryError(
                    "recovery_target_mismatch", "interrupted offline publication targets differ"
                )
            try:
                regenerate()
                _clear_transaction_state()
            except PaperSummaryError:
                raise
            except Exception:
                raise PaperSummaryError(
                    "recovery_failed", "interrupted offline publication could not be recovered"
                ) from None

        results, skipped, rejected, current_archive = _load_reviewed(Path(review_path), docs, archive)
        next_archive, removed = _prune_rejected_topics(current_archive, rejected)
        if not results and not removed:
            return OfflineImportResult(0, skipped, 0, 0)
        topics = tuple(dict.fromkeys(candidate.topic for candidate, _ in results))
        try:
            original_archive = archive.read_bytes()
            originals = {}
            for topic in topics:
                try:
                    originals[topic] = notes_path(docs, topic).read_bytes()
                except FileNotFoundError:
                    originals[topic] = None
        except OSError:
            raise PaperSummaryError("summary_page_missing", "summary page is unavailable for safe publication") from None

        _write_transaction_state(identity)
        try:
            if removed:
                atomic_write_bytes(
                    archive,
                    (json.dumps(next_archive, ensure_ascii=False) + "\n").encode("utf-8"),
                )
            if results:
                publish_summaries(docs, results)
            regenerate()
        except Exception as error:
            try:
                atomic_write_bytes(archive, original_archive)
                for topic, content in originals.items():
                    restore_topic_document(docs, topic, content)
                regenerate()
                _clear_transaction_state()
            except Exception:
                raise PaperSummaryError(
                    "rollback_failed", "offline publication and automatic rollback both failed"
                ) from None
            if isinstance(error, PaperSummaryError):
                raise
            raise PaperSummaryError(
                "offline_publish_failed", "offline summaries could not be published safely"
            ) from None
        _clear_transaction_state()
    return OfflineImportResult(len(results), skipped, len(results), removed)
