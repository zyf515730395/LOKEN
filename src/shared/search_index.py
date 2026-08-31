"""Validated, deterministic public-title search index publishing."""

from __future__ import annotations

from dataclasses import dataclass
import datetime
import json
from pathlib import Path, PurePosixPath
import re
from typing import Iterable, Literal, Mapping, Any
from urllib.parse import urlsplit

from .rendering import atomic_write_text
from .site_shell import SECTIONS


SectionKey = Literal["learning", "milestones", "writings", "journeys"]
SearchKind = Literal["paper", "model", "article"]
SECTION_ORDER = {section.key: index for index, section in enumerate(SECTIONS)}
SUPPORTED_KINDS = {"paper", "model", "article"}
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True, slots=True)
class SearchDocument:
    id: str
    title: str
    url: str
    section: SectionKey
    kind: SearchKind
    published_at: str | None = None


def _validate_document(document: SearchDocument) -> None:
    if not isinstance(document.id, str) or not document.id.strip():
        raise ValueError("Search document id must be a non-empty string")
    if not isinstance(document.title, str) or not document.title.strip():
        raise ValueError(f"Search document title is required: {document.id}")
    if document.section not in SECTION_ORDER:
        raise ValueError(f"Unsupported search section: {document.section}")
    if document.kind not in SUPPORTED_KINDS:
        raise ValueError(f"Unsupported search kind: {document.kind}")

    if not isinstance(document.url, str) or not document.url:
        raise ValueError(f"Search document URL is required: {document.id}")
    parsed = urlsplit(document.url)
    path = PurePosixPath(parsed.path)
    if (
        document.url.startswith("/")
        or "\\" in document.url
        or parsed.scheme
        or parsed.netloc
        or not parsed.path
        or ".." in path.parts
    ):
        raise ValueError(f"Search document URL must stay inside the public site: {document.url}")
    if document.published_at is not None:
        try:
            datetime.date.fromisoformat(document.published_at)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"Invalid search publication date for {document.id}: {document.published_at}"
            ) from error


def _serialize_document(document: SearchDocument) -> dict[str, str]:
    payload = {
        "id": document.id,
        "title": document.title,
        "url": document.url,
        "section": document.section,
        "kind": document.kind,
    }
    if document.published_at is not None:
        payload["published_at"] = document.published_at
    return payload


def build_search_payload(
    documents: Iterable[SearchDocument], *, generated_on: datetime.date
) -> dict[str, object]:
    validated = []
    seen_ids = set()
    for document in documents:
        _validate_document(document)
        if document.id in seen_ids:
            raise ValueError(f"Duplicate search document id: {document.id}")
        seen_ids.add(document.id)
        validated.append(document)
    validated.sort(
        key=lambda document: (
            SECTION_ORDER[document.section],
            document.kind,
            document.id,
        )
    )
    return {
        "version": 1,
        "generated_at": generated_on.isoformat(),
        "documents": [_serialize_document(document) for document in validated],
    }


def write_search_index(
    path: str | Path,
    documents: Iterable[SearchDocument],
    *,
    generated_on: datetime.date,
) -> None:
    atomic_write_text(
        path,
        serialize_search_index(documents, generated_on=generated_on),
    )


def serialize_search_index(
    documents: Iterable[SearchDocument], *, generated_on: datetime.date
) -> str:
    """Serialize the validated public search index without writing it."""
    payload = build_search_payload(documents, generated_on=generated_on)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"


def public_article_search_documents(
    records: Iterable[Mapping[str, Any]],
) -> list[SearchDocument]:
    """Normalize explicitly public future writing records without reading private metadata."""
    documents = []
    for record in records:
        if record.get("public") is not True:
            continue
        title = record.get("title")
        slug = record.get("slug")
        published_at = record.get("published_at")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("Public article title must be a non-empty string")
        if not isinstance(slug, str) or not SLUG_PATTERN.fullmatch(slug):
            raise ValueError(f"Invalid public article slug: {slug}")
        documents.append(
            SearchDocument(
                id=f"article:{slug}",
                title=title.strip(),
                url=f"writings/{slug}.html",
                section="writings",
                kind="article",
                published_at=published_at,
            )
        )
    return documents
