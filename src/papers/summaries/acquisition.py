"""Fixed-host HTML-first arXiv acquisition with bounded PDF fallback."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import time
from typing import Callable

import requests

from .extraction import (
    EXTRACTION_VERSION,
    _validate_document,
    extract_html_document,
    extract_pdf_document,
)
from .models import AcquiredPaper, PaperDocument, PaperSection, PaperSummaryError
from .paths import normalize_arxiv_id, source_directory


ARXIV_ORIGIN = "https://arxiv.org"
HTML_UNAVAILABLE_STATUSES = {404, 410, 415}
MAX_HTML_BYTES = 32 * 1024 * 1024
MAX_PDF_BYTES = 64 * 1024 * 1024
RETRY_ATTEMPTS = 3
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 90
SOURCE_CACHE_VERSION = 1


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _atomic_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _title_digest(value: str) -> str:
    return _sha256(" ".join(value.split()).encode("utf-8"))


def _document_payload(document: PaperDocument) -> dict:
    return {
        "title": document.title,
        "abstract": document.abstract,
        "sections": [
            {"heading": section.heading, "text": section.text}
            for section in document.sections
        ],
    }


def _parse_document(value: object, expected_title: str) -> PaperDocument:
    if not isinstance(value, dict) or set(value) != {"title", "abstract", "sections"}:
        raise ValueError("invalid cached document")
    if (
        not isinstance(value["title"], str)
        or not isinstance(value["abstract"], str)
        or not isinstance(value["sections"], list)
    ):
        raise ValueError("invalid cached document")
    sections: list[PaperSection] = []
    for item in value["sections"]:
        if (
            not isinstance(item, dict)
            or set(item) != {"heading", "text"}
            or not isinstance(item["heading"], str)
            or not isinstance(item["text"], str)
        ):
            raise ValueError("invalid cached document")
        sections.append(PaperSection(item["heading"], item["text"]))
    return _validate_document(
        PaperDocument(value["title"], value["abstract"], tuple(sections)),
        expected_title,
    )


class ArxivSourceClient:
    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.session = session or requests.Session()
        self.session.trust_env = False
        self.sleeper = sleeper

    def _download(self, url: str, *, limit: int) -> tuple[int, str, bytes]:
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try:
                response = self.session.get(
                    url,
                    headers={
                        "Accept": "text/html,application/pdf;q=.9",
                        "User-Agent": "TOGOS-local-paper-summaries/1.0",
                    },
                    timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                    allow_redirects=False,
                    stream=True,
                )
            except (requests.ConnectionError, requests.Timeout):
                if attempt == RETRY_ATTEMPTS:
                    raise PaperSummaryError(
                        "source_unavailable", "arXiv source request failed after retries"
                    ) from None
                self.sleeper(float(2 ** (attempt - 1)))
                continue
            if response.status_code == 429 or 500 <= response.status_code <= 599:
                response.close()
                if attempt == RETRY_ATTEMPTS:
                    raise PaperSummaryError(
                        "source_unavailable", "arXiv source returned a temporary failure"
                    )
                self.sleeper(float(2 ** (attempt - 1)))
                continue
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().casefold()
            if response.status_code != 200:
                response.close()
                return response.status_code, content_type, b""
            length = response.headers.get("Content-Length")
            if length is not None:
                try:
                    if int(length) > limit:
                        raise PaperSummaryError(
                            "source_too_large", "arXiv source exceeds the download boundary"
                        )
                except ValueError:
                    raise PaperSummaryError(
                        "source_invalid", "arXiv source length is invalid"
                    ) from None
            body = bytearray()
            try:
                for chunk in response.iter_content(64 * 1024):
                    body.extend(chunk)
                    if len(body) > limit:
                        raise PaperSummaryError(
                            "source_too_large", "arXiv source exceeds the download boundary"
                        )
            finally:
                response.close()
            return response.status_code, content_type, bytes(body)
        raise AssertionError("unreachable")

    def _load_cached(self, arxiv_id: str, expected_title: str) -> AcquiredPaper | None:
        directory = source_directory(arxiv_id)
        metadata_path = directory / "extracted.json"
        try:
            metadata_raw = metadata_path.read_bytes()
            if len(metadata_raw) > 2 * 1024 * 1024:
                return None
            envelope = json.loads(metadata_raw.decode("utf-8", errors="strict"))
            if (
                not isinstance(envelope, dict)
                or set(envelope) != {"version", "arxiv_id", "kind", "source_sha256", "expected_title_sha256", "extraction_version", "document", "checksum"}
                or metadata_raw != _canonical(envelope) + b"\n"
            ):
                return None
            body = {key: value for key, value in envelope.items() if key != "checksum"}
            checksum = _sha256(_canonical(body))
            if (
                envelope["version"] != SOURCE_CACHE_VERSION
                or envelope["arxiv_id"] != arxiv_id
                or envelope["kind"] not in {"html", "pdf"}
                or envelope["expected_title_sha256"] != _title_digest(expected_title)
                or envelope["extraction_version"] != EXTRACTION_VERSION
                or not hmac.compare_digest(str(envelope["checksum"]), checksum)
            ):
                return None
            kind = envelope["kind"]
            path = directory / f"source.{kind}"
            raw = path.read_bytes()
            limit = MAX_HTML_BYTES if kind == "html" else MAX_PDF_BYTES
            if len(raw) > limit or _sha256(raw) != envelope["source_sha256"]:
                return None
            document = _parse_document(envelope["document"], expected_title)
            return AcquiredPaper(arxiv_id, kind, path, envelope["source_sha256"], document)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError, RecursionError, PaperSummaryError):
            return None

    def _store_result(
        self,
        arxiv_id: str,
        kind: str,
        raw: bytes,
        document: PaperDocument,
        expected_title: str,
    ) -> AcquiredPaper:
        suffix = "html" if kind == "html" else "pdf"
        directory = source_directory(arxiv_id)
        path = directory / f"source.{suffix}"
        _atomic_write(path, raw)
        source_sha256 = _sha256(raw)
        body = {
            "version": SOURCE_CACHE_VERSION,
            "arxiv_id": arxiv_id,
            "kind": kind,
            "source_sha256": source_sha256,
            "expected_title_sha256": _title_digest(expected_title),
            "extraction_version": EXTRACTION_VERSION,
            "document": _document_payload(document),
        }
        envelope = {**body, "checksum": _sha256(_canonical(body))}
        _atomic_write(directory / "extracted.json", _canonical(envelope) + b"\n")
        return AcquiredPaper(arxiv_id, kind, path, source_sha256, document)

    def acquire(self, arxiv_id: str, expected_title: str) -> AcquiredPaper:
        paper_id = normalize_arxiv_id(arxiv_id)
        cached = self._load_cached(paper_id, expected_title)
        if cached is not None:
            return cached
        html_status, html_type, html_raw = self._download(
            f"{ARXIV_ORIGIN}/html/{paper_id}", limit=MAX_HTML_BYTES
        )
        fallback = html_status in HTML_UNAVAILABLE_STATUSES
        if html_status == 200 and html_type in {"text/html", "application/xhtml+xml"}:
            try:
                document = extract_html_document(html_raw, expected_title)
            except PaperSummaryError as error:
                if error.code != "html_unavailable":
                    raise
                fallback = True
            else:
                return self._store_result(
                    paper_id, "html", html_raw, document, expected_title
                )
        elif html_status == 200:
            fallback = True
        elif not fallback:
            raise PaperSummaryError(
                "source_http_error", "arXiv HTML returned a non-success status"
            )
        if not fallback:
            raise AssertionError("HTML fallback state is inconsistent")

        pdf_status, pdf_type, pdf_raw = self._download(
            f"{ARXIV_ORIGIN}/pdf/{paper_id}.pdf", limit=MAX_PDF_BYTES
        )
        if pdf_status != 200:
            raise PaperSummaryError(
                "pdf_unavailable", "arXiv PDF returned a non-success status"
            )
        if pdf_type not in {"application/pdf", "application/octet-stream"} or not pdf_raw.startswith(b"%PDF-"):
            raise PaperSummaryError("pdf_invalid", "arXiv PDF response is not a PDF")
        document = extract_pdf_document(pdf_raw, expected_title)
        return self._store_result(paper_id, "pdf", pdf_raw, document, expected_title)
