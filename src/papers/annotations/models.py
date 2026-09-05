"""Validated contracts for paper labels and paper type."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


class PaperAnnotationError(ValueError):
    """Stable error that does not retain source or model response bodies."""

    def __init__(self, code: str, message: str) -> None:
        self.code = str(code)
        self.message = " ".join(str(message).split()) or "paper annotation failed"
        super().__init__(f"{self.code}: {self.message}")


@dataclass(frozen=True, slots=True)
class LabelDefinition:
    name: str
    description: str
    slug: str


@dataclass(frozen=True, slots=True)
class PaperAnnotation:
    tags: tuple[str, ...]
    paper_type: Literal["paper", "survey"]
