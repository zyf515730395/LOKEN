"""Safe Markdown rendering and atomic text output helpers."""

from __future__ import annotations

import os
from pathlib import Path
import re

import bleach
import markdown


ALLOWED_HTML_TAGS = {
    "a",
    "article",
    "blockquote",
    "br",
    "code",
    "em",
    "h1",
    "h2",
    "h3",
    "hr",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "ul",
}
ALLOWED_HTML_ATTRIBUTES = {
    "a": ["href", "title", "target", "rel"],
    "article": ["id", "class"],
}


def atomic_write_bytes(path: str | Path, content: bytes) -> None:
    """Durably replace a file without exposing a partial write."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def atomic_write_text(path: str | Path, content: str) -> None:
    """Durably replace a UTF-8 text file without exposing a partial write."""
    newline = os.linesep
    encoded = content.replace("\r\n", "\n").replace("\r", "\n")
    if newline != "\n":
        encoded = encoded.replace("\n", newline)
    atomic_write_bytes(path, encoded.encode("utf-8"))


def render_note_content(markdown_content: str) -> str:
    """Render Markdown to a sanitized HTML fragment."""
    display_content = re.sub(
        r"\A---\s*\n.*?\n---\s*\n",
        "",
        markdown_content,
        count=1,
        flags=re.DOTALL,
    )
    rendered = markdown.markdown(display_content, extensions=["extra", "sane_lists"])
    cleaned = bleach.clean(
        rendered,
        tags=ALLOWED_HTML_TAGS,
        attributes=ALLOWED_HTML_ATTRIBUTES,
        protocols={"http", "https", "mailto"},
        strip=True,
    )
    return bleach.linkify(cleaned)
