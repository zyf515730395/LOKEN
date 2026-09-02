"""Failure-isolated local paper summary workflow."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from papers.site import generate_site
from shared.loopback_chat import LoopbackChatError, validate_loopback_base_url
from shared.rendering import atomic_write_text

from .acquisition import ArxivSourceClient
from .catalog import PaperCandidate, load_candidates, notes_path
from .models import PaperSummary, PaperSummaryError
from .paths import PROJECT_ROOT, private_path, run_lock
from .publisher import load_ready_keys, publish_summaries
from .summarizer import summarize_paper


DEFAULT_LEDGER = PROJECT_ROOT / "data" / "arxiv-candidates.json"
DEFAULT_DOCS = PROJECT_ROOT / "docs"
DEFAULT_ARCHIVE = DEFAULT_DOCS / "togos-papers.json"
DEFAULT_MILESTONES = PROJECT_ROOT / "config" / "milestone_models.yaml"
REPORT_VERSION = 1


@dataclass(frozen=True, slots=True)
class PaperRunRecord:
    arxiv_id: str
    topic: str
    status: str
    source: str | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class RunResult:
    selected: int
    succeeded: int
    failed: int
    published: int
    records: tuple[PaperRunRecord, ...]

    @property
    def partial(self) -> bool:
        return self.failed > 0


def _atomic_private_json(name: str, payload: dict) -> Path:
    path = private_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return path


def _write_report(result: RunResult, *, model: str) -> Path:
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    report = {
        "version": REPORT_VERSION,
        "generated_at": generated_at,
        "model": model,
        "selected": result.selected,
        "succeeded": result.succeeded,
        "failed": result.failed,
        "published": result.published,
        "records": [asdict(record) for record in result.records],
    }
    path = _atomic_private_json("report.json", report)
    _atomic_private_json(
        "state.json",
        {
            "version": REPORT_VERSION,
            "last_run": generated_at,
            "model": model,
            "selected": result.selected,
            "succeeded": result.succeeded,
            "failed": result.failed,
        },
    )
    return path


def status_snapshot(
    *,
    ledger_path: str | Path = DEFAULT_LEDGER,
    docs_root: str | Path = DEFAULT_DOCS,
) -> dict[str, object]:
    ready = load_ready_keys(docs_root)
    pending = load_candidates(ledger_path, ready_ids=ready)
    all_accepted = load_candidates(ledger_path, refresh=True)
    report_path = private_path("report.json")
    last_failed = 0
    last_model = None
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if isinstance(report, dict) and report.get("version") == REPORT_VERSION:
            if isinstance(report.get("failed"), int) and report["failed"] >= 0:
                last_failed = report["failed"]
            if isinstance(report.get("model"), str):
                last_model = report["model"]
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, RecursionError):
        pass
    source_root = private_path("sources")
    cache_root = private_path("cache")
    return {
        "accepted": len(all_accepted),
        "ready": sum((item.topic, item.arxiv_id) in ready for item in all_accepted),
        "pending": len(pending),
        "processable": len(pending),
        "last_failed": last_failed,
        "source_cache": {
            "html": sum(1 for _ in source_root.glob("*/source.html")),
            "pdf": sum(1 for _ in source_root.glob("*/source.pdf")),
            "summaries": sum(1 for _ in cache_root.glob("*/*.json")),
        },
        "last_model": last_model,
        "report": "build/paper-summaries/report.json",
    }


def _regenerate_site(
    *,
    docs_root: Path,
    ledger_path: Path,
    archive_path: Path,
) -> None:
    generate_site(
        archive_path,
        docs_root / "index.html",
        ledger_path,
        DEFAULT_MILESTONES,
        output_root=docs_root,
        search_index_path=docs_root / "search-index.json",
        writings_source_root=PROJECT_ROOT / "content" / "writings",
        writings_report_path=PROJECT_ROOT / "build" / "reports" / "writings.json",
    )


def run_summaries(
    *,
    model: str,
    base_url: str,
    timeout: float,
    paper_ids: tuple[str, ...] = (),
    limit: int | None = None,
    refresh: bool = False,
    ledger_path: str | Path = DEFAULT_LEDGER,
    docs_root: str | Path = DEFAULT_DOCS,
    archive_path: str | Path = DEFAULT_ARCHIVE,
) -> RunResult:
    if not isinstance(model, str) or not model.strip():
        raise PaperSummaryError("model_required", "local model name is required")
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise PaperSummaryError("invalid_timeout", "model timeout must be positive")
    if refresh and len(paper_ids) != 1:
        raise PaperSummaryError(
            "refresh_requires_one_paper", "refresh requires exactly one paper"
        )
    try:
        validate_loopback_base_url(base_url)
    except LoopbackChatError as error:
        raise PaperSummaryError(error.code, error.message) from None
    with run_lock():
        return _run_summaries_locked(
            model=model,
            base_url=base_url,
            timeout=timeout,
            paper_ids=paper_ids,
            limit=limit,
            refresh=refresh,
            ledger_path=Path(ledger_path),
            docs_root=Path(docs_root),
            archive_path=Path(archive_path),
        )


def _run_summaries_locked(
    *,
    model: str,
    base_url: str,
    timeout: float,
    paper_ids: tuple[str, ...],
    limit: int | None,
    refresh: bool,
    ledger_path: Path,
    docs_root: Path,
    archive_path: Path,
) -> RunResult:
    docs = docs_root
    ledger = ledger_path
    archive = archive_path
    ready = load_ready_keys(docs, strict=False)
    candidates = load_candidates(
        ledger,
        ready_ids=ready,
        paper_ids=paper_ids,
        limit=limit,
        refresh=refresh,
    )
    client = ArxivSourceClient()
    completed: list[tuple[PaperCandidate, PaperSummary, str]] = []
    records: list[PaperRunRecord] = []
    for candidate in candidates:
        try:
            source = client.acquire(candidate.arxiv_id, candidate.title)
            summary = summarize_paper(
                source,
                model=model,
                base_url=base_url,
                timeout=timeout,
                refresh=refresh,
            )
            completed.append((candidate, summary, source.kind))
        except PaperSummaryError as error:
            records.append(
                PaperRunRecord(
                    candidate.arxiv_id,
                    candidate.topic,
                    "failed",
                    error_code=error.code,
                    error_message=error.message,
                )
            )
        except Exception:
            records.append(
                PaperRunRecord(
                    candidate.arxiv_id,
                    candidate.topic,
                    "failed",
                    error_code="unexpected_failure",
                    error_message="paper failed without changing public output",
                )
            )
    published = 0
    grouped: dict[str, list[tuple[PaperCandidate, PaperSummary, str]]] = {}
    for item in completed:
        grouped.setdefault(item[0].topic, []).append(item)
    originals: dict[str, str] = {}
    published_topics: list[str] = []
    for topic, topic_results in grouped.items():
        target = notes_path(docs, topic)
        try:
            originals[topic] = target.read_text(encoding="utf-8")
        except OSError:
            records.extend(
                PaperRunRecord(
                    candidate.arxiv_id,
                    candidate.topic,
                    "failed",
                    source=source_kind,
                    error_code="summary_page_missing",
                    error_message="summary page is unavailable for safe publication",
                )
                for candidate, _, source_kind in topic_results
            )
            continue
        try:
            publish_summaries(
                docs,
                tuple((candidate, summary) for candidate, summary, _ in topic_results),
                refresh=refresh,
            )
        except (PaperSummaryError, OSError) as error:
            code = error.code if isinstance(error, PaperSummaryError) else "publish_failed"
            message = error.message if isinstance(error, PaperSummaryError) else "topic could not be published safely"
            records.extend(
                PaperRunRecord(
                    candidate.arxiv_id,
                    candidate.topic,
                    "failed",
                    source=source_kind,
                    error_code=code,
                    error_message=message,
                )
                for candidate, _, source_kind in topic_results
            )
            continue
        published += len(topic_results)
        published_topics.append(topic)
        records.extend(
            PaperRunRecord(
                candidate.arxiv_id, candidate.topic, "succeeded", source_kind
            )
            for candidate, _, source_kind in topic_results
        )
    if published:
        try:
            _regenerate_site(docs_root=docs, ledger_path=ledger, archive_path=archive)
        except Exception:
            try:
                for topic in published_topics:
                    atomic_write_text(notes_path(docs, topic), originals[topic])
                _regenerate_site(
                    docs_root=docs, ledger_path=ledger, archive_path=archive
                )
            except Exception:
                raise PaperSummaryError(
                    "rollback_failed",
                    "site build and automatic public rollback both failed",
                ) from None
            raise PaperSummaryError(
                "site_build_failed",
                "site build failed; published note pages were restored",
            ) from None
    order = {candidate.arxiv_id: index for index, candidate in enumerate(candidates)}
    records.sort(key=lambda record: order[record.arxiv_id])
    result = RunResult(
        selected=len(candidates),
        succeeded=sum(record.status == "succeeded" for record in records),
        failed=sum(record.status == "failed" for record in records),
        published=published,
        records=tuple(records),
    )
    _write_report(result, model=model)
    return result
