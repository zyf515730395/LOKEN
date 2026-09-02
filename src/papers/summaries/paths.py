"""Canonical private paths for local paper summaries."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import re
from typing import Iterator

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


@contextmanager
def run_lock() -> Iterator[None]:
    """Hold a non-blocking, process-wide lock for public summary mutation."""
    path = private_path("run.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    locked = False
    try:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except (OSError, BlockingIOError):
            raise PaperSummaryError(
                "workflow_locked", "another paper summary run is active"
            ) from None
        yield
    finally:
        if locked:
            stream.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        stream.close()
