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


@dataclass(frozen=True, slots=True)
class PaperSummary:
    one_sentence: str
    problem: str
    contributions: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.one_sentence, str) or not self.one_sentence.strip():
            raise ValueError("one_sentence must be non-empty")
        if not isinstance(self.problem, str) or not self.problem.strip():
            raise ValueError("problem must be non-empty")
        if not isinstance(self.contributions, tuple) or not 3 <= len(self.contributions) <= 6:
            raise ValueError("contributions must contain three to six items")
        limits = (600, 1_600, *(1_000 for _ in self.contributions))
        values = (self.one_sentence, self.problem, *self.contributions)
        if any(
            not isinstance(value, str)
            or not value.strip()
            or len(value) > limit
            or any(ord(character) < 32 and character not in "\t\n\r" for character in value)
            or "<" in value
            or ">" in value
            for value, limit in zip(values, limits, strict=True)
        ):
            raise ValueError("paper summary text is invalid")
