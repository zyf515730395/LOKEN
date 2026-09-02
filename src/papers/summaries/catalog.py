"""Select reviewed papers without trusting arbitrary ledger URLs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re

from papers.candidate_ledger import load_candidate_ledger, normalize_arxiv_id

from .models import PaperSummaryError


TOPIC_SLUGS = {
    "Image Generation": "image-generation",
    "Video Generation": "video-generation",
    "3D Generation": "3d-generation",
    "Neural Rendering": "neural-rendering",
    "Depth Estimation": "depth-estimation",
}
ARXIV_ID = re.compile(r"^\d{4}\.\d{4,5}$")


@dataclass(frozen=True, slots=True)
class PaperCandidate:
    arxiv_id: str
    title: str
    topic: str
    updated: date


def _candidate(paper_id: str, entry: object) -> PaperCandidate | None:
    if not isinstance(entry, dict) or entry.get("status") != "accepted":
        return None
    normalized = normalize_arxiv_id(paper_id)
    if normalized != paper_id or entry.get("id") != paper_id or not ARXIV_ID.fullmatch(paper_id):
        raise PaperSummaryError("invalid_candidate", f"invalid accepted paper id: {paper_id}")
    title = entry.get("title")
    topic = entry.get("selected_topic")
    if not isinstance(title, str) or not title.strip() or topic not in TOPIC_SLUGS:
        raise PaperSummaryError("invalid_candidate", f"invalid accepted paper metadata: {paper_id}")
    try:
        updated = date.fromisoformat(entry["updated"])
    except (KeyError, TypeError, ValueError):
        raise PaperSummaryError("invalid_candidate", f"invalid accepted paper date: {paper_id}") from None
    return PaperCandidate(paper_id, " ".join(title.split()), topic, updated)


def load_candidates(
    ledger_path: str | Path,
    *,
    ready_ids: set[str] | set[tuple[str, str]] | None = None,
    paper_ids: tuple[str, ...] = (),
    limit: int | None = None,
    refresh: bool = False,
) -> tuple[PaperCandidate, ...]:
    try:
        ledger = load_candidate_ledger(ledger_path)
    except ValueError as error:
        raise PaperSummaryError("invalid_candidate_ledger", str(error)) from None
    candidates = {
        candidate.arxiv_id: candidate
        for key, entry in ledger["papers"].items()
        if (candidate := _candidate(key, entry)) is not None
    }
    ready: set[str] | set[tuple[str, str]] = ready_ids or set()
    if paper_ids:
        normalized_requested = tuple(normalize_arxiv_id(value) for value in paper_ids)
        missing = [value for value in normalized_requested if value not in candidates]
        if missing:
            raise PaperSummaryError(
                "paper_not_accepted", f"paper is not an accepted candidate: {missing[0]}"
            )
        selected = [candidates[value] for value in normalized_requested]
    else:
        selected = sorted(candidates.values(), key=lambda value: (value.updated, value.arxiv_id))
    if not refresh:
        selected = [
            value
            for value in selected
            if value.arxiv_id not in ready and (value.topic, value.arxiv_id) not in ready
        ]
    if limit is not None:
        if limit < 1:
            raise PaperSummaryError("invalid_limit", "limit must be at least one")
        selected = selected[:limit]
    return tuple(selected)


def notes_path(docs_root: str | Path, topic: str) -> Path:
    try:
        slug = TOPIC_SLUGS[topic]
    except KeyError:
        raise PaperSummaryError("invalid_topic", "paper topic is not publishable") from None
    return Path(docs_root) / "notes" / f"{slug}.html"
