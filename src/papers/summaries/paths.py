"""Canonical private paths for local paper summaries."""

from __future__ import annotations

from pathlib import Path
import re

from .models import PaperSummaryError


PROJECT_ROOT = Path(__file__).resolve().parents[3]
PRIVATE_ROOT = PROJECT_ROOT / "build" / "paper-summaries"
ARXIV_ID = re.compile(r"\d{4}\.\d{4,5}")


def normalize_arxiv_id(value: str) -> str:
    normalized = str(value).strip().split("v", 1)[0]
    if ARXIV_ID.fullmatch(normalized) is None:
        raise PaperSummaryError("invalid_arxiv_id", "arXiv ID is invalid")
    return normalized


def private_path(*parts: str) -> Path:
    root = PRIVATE_ROOT.resolve()
    target = root.joinpath(*parts).resolve()
    if target != root and not target.is_relative_to(root):
        raise PaperSummaryError(
            "unsafe_private_path", "paper summary path escaped the private root"
        )
    return target


def source_directory(arxiv_id: str) -> Path:
    return private_path("sources", normalize_arxiv_id(arxiv_id))
