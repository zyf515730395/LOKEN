"""Canonical full-site build entry point for the local workbench."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from papers.site import generate_site
from writings.importers.models import PROJECT_ROOT

from .models import BuildSummary, WorkbenchError
from .status import load_build_summary


def build_site(*, generated_on: date | None = None) -> BuildSummary:
    project = Path(PROJECT_ROOT)
    try:
        generate_site(
            project / "content" / "papers" / "archive.json",
            project / "docs" / "index.html",
            project / "content" / "papers" / "arxiv-candidates.json",
            project / "config" / "milestone_models.yaml",
            output_root=project / "docs",
            search_index_path=project / "docs" / "search-index.json",
            generated_on=generated_on,
            writings_source_root=project / "content" / "writings",
            writings_report_path=project / "build" / "reports" / "writings.json",
        )
        result = load_build_summary()
        if result.status in {"not-started", "failed"}:
            raise WorkbenchError("invalid_report", "public build report is unavailable or invalid")
        return result
    except WorkbenchError:
        raise
    except (OSError, ValueError) as error:
        raise WorkbenchError(
            "build_failed", "public site build failed safely; inspect the source report"
        ) from error
