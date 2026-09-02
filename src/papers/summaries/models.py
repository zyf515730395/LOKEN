"""Immutable contracts for local paper acquisition and summarization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


class PaperSummaryError(ValueError):
    """Stable error that never retains source or model response bodies."""

    def __init__(self, code: str, message: str) -> None:
        self.code = str(code)
        self.message = " ".join(str(message).split()) or "paper summary failed"
        super().__init__(f"{self.code}: {self.message}")


@dataclass(frozen=True, slots=True)
class PaperSection:
    heading: str
    text: str


@dataclass(frozen=True, slots=True)
class PaperDocument:
    title: str
    abstract: str
    sections: tuple[PaperSection, ...]

    @property
    def text(self) -> str:
        parts = [self.title, self.abstract]
        parts.extend(f"{section.heading}\n{section.text}" for section in self.sections)
        return "\n\n".join(part for part in parts if part)


@dataclass(frozen=True, slots=True)
class AcquiredPaper:
    arxiv_id: str
    kind: Literal["html", "pdf"]
    source_path: Path
    source_sha256: str
    document: PaperDocument
