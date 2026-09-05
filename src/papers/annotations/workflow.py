"""Failure-isolated annotation workflow for the complete public archive."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json
from pathlib import Path

from papers.site import generate_site
from papers.candidate_ledger import atomic_write_json, normalize_arxiv_id
from papers.summaries.acquisition import ArxivSourceClient
from papers.summaries.paths import PROJECT_ROOT, private_path, run_lock
from shared.loopback_chat import LoopbackChatError, validate_loopback_base_url

from .catalog import (
    annotation_coverage,
    archive_titles,
    load_annotation_catalog,
    load_label_definitions,
    write_annotation_catalog,
)
from .classifier import classify_paper
from .models import PaperAnnotation, PaperAnnotationError


DEFAULT_CONFIG = PROJECT_ROOT / "config" / "site.yaml"
DEFAULT_ARCHIVE = PROJECT_ROOT / "docs" / "togos-papers.json"
DEFAULT_CATALOG = PROJECT_ROOT / "data" / "paper-annotations.json"
DEFAULT_LEDGER = PROJECT_ROOT / "data" / "arxiv-candidates.json"
DEFAULT_MILESTONES = PROJECT_ROOT / "config" / "milestone_models.yaml"
DEFAULT_DOCS = PROJECT_ROOT / "docs"


@dataclass(frozen=True, slots=True)
class AnnotationRunRecord:
    arxiv_id: str
    status: str
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class AnnotationRunResult:
    selected: int
    succeeded: int
    failed: int
    records: tuple[AnnotationRunRecord, ...]

    @property
    def partial(self) -> bool:
        return self.failed > 0


def _read_archive(path: Path) -> dict[str, dict[str, object]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
        raise PaperAnnotationError("invalid_archive", "paper archive cannot be read") from None
    if not isinstance(payload, dict) or any(not isinstance(value, dict) for value in payload.values()):
        raise PaperAnnotationError("invalid_archive", "paper archive schema is invalid")
    return payload


def status_snapshot(
    *,
    config_path: str | Path = DEFAULT_CONFIG,
    archive_path: str | Path = DEFAULT_ARCHIVE,
    catalog_path: str | Path = DEFAULT_CATALOG,
) -> dict[str, int]:
    labels = load_label_definitions(config_path)
    archive = _read_archive(Path(archive_path))
    annotations = load_annotation_catalog(catalog_path, labels)
    return annotation_coverage(archive, annotations)


def run_annotations(
    *,
    model: str,
    base_url: str,
    timeout: float,
    workers: int = 2,
    paper_ids: tuple[str, ...] = (),
    limit: int | None = None,
    refresh: bool = False,
    config_path: str | Path = DEFAULT_CONFIG,
    archive_path: str | Path = DEFAULT_ARCHIVE,
    catalog_path: str | Path = DEFAULT_CATALOG,
    docs_root: str | Path = DEFAULT_DOCS,
) -> AnnotationRunResult:
    if not isinstance(model, str) or not model.strip():
        raise PaperAnnotationError("model_required", "local model name is required")
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise PaperAnnotationError("invalid_timeout", "model timeout must be positive")
    if type(workers) is not int or not 1 <= workers <= 8:
        raise PaperAnnotationError("invalid_workers", "workers must be an integer from 1 to 8")
    if refresh and len(paper_ids) != 1:
        raise PaperAnnotationError("refresh_requires_one_paper", "refresh requires exactly one paper")
    try:
        validate_loopback_base_url(base_url)
    except LoopbackChatError as error:
        raise PaperAnnotationError(error.code, error.message) from None
    with run_lock():
        labels = load_label_definitions(config_path)
        archive = _read_archive(Path(archive_path))
        candidates = archive_titles(archive)
        annotations = load_annotation_catalog(catalog_path, labels)
        requested = tuple(dict.fromkeys(normalize_arxiv_id(paper_id) for paper_id in paper_ids))
        if requested:
            missing = [paper_id for paper_id in requested if paper_id not in candidates]
            if missing:
                raise PaperAnnotationError("paper_not_archived", f"paper is not archived: {missing[0]}")
            selected = list(requested)
        else:
            selected = [paper_id for paper_id in sorted(candidates) if paper_id not in annotations]
        if limit is not None:
            if limit < 1:
                raise PaperAnnotationError("invalid_limit", "limit must be at least one")
            selected = selected[:limit]
        records: dict[str, AnnotationRunRecord] = {}
        completed: dict[str, PaperAnnotation] = {}

        def process(paper_id: str) -> PaperAnnotation:
            title, _ = candidates[paper_id]
            source = ArxivSourceClient().acquire(paper_id, title)
            return classify_paper(
                source,
                labels,
                model=model.strip(),
                base_url=base_url,
                timeout=timeout,
                refresh=refresh,
            )

        with ThreadPoolExecutor(max_workers=min(workers, len(selected)) or 1) as executor:
            futures = {executor.submit(process, paper_id): paper_id for paper_id in selected}
            for future in as_completed(futures):
                paper_id = futures[future]
                try:
                    completed[paper_id] = future.result()
                except PaperAnnotationError as error:
                    records[paper_id] = AnnotationRunRecord(paper_id, "failed", error.code, error.message)
                except Exception:
                    records[paper_id] = AnnotationRunRecord(paper_id, "failed", "unexpected_failure", "paper failed without changing public output")
                else:
                    records[paper_id] = AnnotationRunRecord(paper_id, "succeeded")
        if completed:
            write_annotation_catalog(catalog_path, {**annotations, **completed})
            publication_root = Path(docs_root).resolve().parent
            generate_site(
                archive_path,
                Path(docs_root) / "index.html",
                DEFAULT_LEDGER,
                DEFAULT_MILESTONES,
                output_root=docs_root,
                search_index_path=Path(docs_root) / "search-index.json",
                config_path=config_path,
                annotation_path=catalog_path,
                writings_source_root=publication_root / "content" / "writings",
                writings_report_path=publication_root / "build" / "reports" / "writings.json",
            )
        ordered_records = tuple(records[paper_id] for paper_id in selected)
        result = AnnotationRunResult(
            len(selected),
            sum(record.status == "succeeded" for record in ordered_records),
            sum(record.status == "failed" for record in ordered_records),
            ordered_records,
        )
        atomic_write_json(
            private_path("annotation-report.json"),
            {
                "version": 1,
                "selected": result.selected,
                "succeeded": result.succeeded,
                "failed": result.failed,
                "records": [
                    {
                        "id": record.arxiv_id,
                        "status": record.status,
                        "error_code": record.error_code,
                        "error_message": record.error_message,
                    }
                    for record in result.records
                ],
            },
        )
        return result
