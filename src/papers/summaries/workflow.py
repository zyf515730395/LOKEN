"""Failure-isolated local paper summary workflow."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from papers.site import generate_site
from shared.loopback_chat import LoopbackChatError, validate_loopback_base_url

from .acquisition import ArxivSourceClient
from .catalog import PaperCandidate, load_candidates
from .models import PaperSummary, PaperSummaryError
from .paths import PROJECT_ROOT, private_path
from .publisher import load_ready_ids, publish_summaries
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


def _atomic_report(payload: dict) -> Path:
    path = private_path("report.json")
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
    return _atomic_report(
        {
            "version": REPORT_VERSION,
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "model": model,
            "selected": result.selected,
            "succeeded": result.succeeded,
            "failed": result.failed,
            "published": result.published,
            "records": [asdict(record) for record in result.records],
        }
    )


def status_snapshot(
    *,
    ledger_path: str | Path = DEFAULT_LEDGER,
    docs_root: str | Path = DEFAULT_DOCS,
) -> dict[str, object]:
    ready = load_ready_ids(docs_root)
    pending = load_candidates(ledger_path, ready_ids=ready)
    all_accepted = load_candidates(ledger_path, refresh=True)
    return {
        "accepted": len(all_accepted),
        "ready": len({item.arxiv_id for item in all_accepted} & ready),
        "pending": len(pending),
        "report": str(private_path("report.json")),
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
    docs = Path(docs_root)
    ledger = Path(ledger_path)
    archive = Path(archive_path)
    ready = load_ready_ids(docs)
    candidates = load_candidates(
        ledger,
        ready_ids=ready,
        paper_ids=paper_ids,
        limit=limit,
        refresh=refresh,
    )
    client = ArxivSourceClient()
    completed: list[tuple[PaperCandidate, PaperSummary]] = []
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
            completed.append((candidate, summary))
            records.append(
                PaperRunRecord(candidate.arxiv_id, candidate.topic, "succeeded", source.kind)
            )
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
    if completed:
        publish_summaries(docs, tuple(completed), refresh=refresh)
        _regenerate_site(docs_root=docs, ledger_path=ledger, archive_path=archive)
    result = RunResult(
        selected=len(candidates),
        succeeded=len(completed),
        failed=sum(record.status == "failed" for record in records),
        published=len(completed),
        records=tuple(records),
    )
    _write_report(result, model=model)
    return result
