"""Normalize arXiv HTML and PDF into one bounded paper document."""

from __future__ import annotations

from html.parser import HTMLParser
from io import BytesIO
import re
import unicodedata

from .models import PaperDocument, PaperSection, PaperSummaryError


EXTRACTION_VERSION = "paper-extraction-v1"
MIN_DOCUMENT_CHARS = 1_000
MAX_DOCUMENT_CHARS = 400_000
MAX_PDF_PAGES = 200
_SPACE = re.compile(r"\s+")
_WORD = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_REFERENCE_HEADING = re.compile(r"(?im)^\s*(?:references|bibliography)\s*$")


def _clean(value: str) -> str:
    return _SPACE.sub(" ", unicodedata.normalize("NFKC", value)).strip()


def _title_similarity(left: str, right: str) -> float:
    left_words = set(_WORD.findall(_clean(left).casefold()))
    right_words = set(_WORD.findall(_clean(right).casefold()))
    if not left_words or not right_words:
        return 0.0
    return len(left_words & right_words) / min(len(left_words), len(right_words))


def _validate_document(document: PaperDocument, expected_title: str) -> PaperDocument:
    if _title_similarity(document.title, expected_title) < .45:
        raise PaperSummaryError(
            "paper_identity_mismatch", "downloaded paper title does not match the candidate"
        )
    total = len(document.text)
    if total < MIN_DOCUMENT_CHARS:
        raise PaperSummaryError("html_unavailable", "paper body is not available as usable text")
    if total > MAX_DOCUMENT_CHARS:
        raise PaperSummaryError("paper_too_large", "paper text exceeds the processing boundary")
    return document


class _ArxivHTMLParser(HTMLParser):
    _SKIP_TAGS = {"script", "style", "nav", "footer", "noscript", "svg"}
    _BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th"}
    _VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.capture_depth = 0
        self.skip_depth = 0
        self.current_tag: str | None = None
        self.current_classes = ""
        self.current: list[str] = []
        self.blocks: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or "" for key, value in attrs}
        classes = attributes.get("class", "")
        if tag == "article" or "ltx_document" in classes.split():
            self.capture_depth += 1
        elif self.capture_depth and tag not in self._VOID_TAGS:
            self.capture_depth += 1
        if self.capture_depth and (
            tag in self._SKIP_TAGS
            or "ltx_bibliography" in classes
            or "ltx_role_footnote" in classes
        ):
            self.skip_depth += 1
        elif self.skip_depth and tag not in self._VOID_TAGS:
            self.skip_depth += 1
        if self.capture_depth and not self.skip_depth and tag in self._BLOCK_TAGS:
            self.current_tag = tag
            self.current_classes = classes
            self.current = []

    def handle_data(self, data: str) -> None:
        if self.capture_depth and not self.skip_depth and self.current_tag:
            self.current.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in self._VOID_TAGS:
            return
        if self.capture_depth and not self.skip_depth and tag == self.current_tag:
            value = _clean("".join(self.current))
            if value:
                self.blocks.append((tag, self.current_classes, value))
            self.current_tag = None
            self.current_classes = ""
            self.current = []
        if self.skip_depth:
            self.skip_depth -= 1
        if self.capture_depth:
            self.capture_depth -= 1

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self._VOID_TAGS:
            self.handle_endtag(tag)


def extract_html_document(raw: bytes, expected_title: str) -> PaperDocument:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise PaperSummaryError("html_unavailable", "arXiv HTML is not valid UTF-8") from None
    parser = _ArxivHTMLParser()
    try:
        parser.feed(text)
        parser.close()
    except (ValueError, RecursionError):
        raise PaperSummaryError("html_unavailable", "arXiv HTML structure is invalid") from None
    title = ""
    abstract_parts: list[str] = []
    sections: list[PaperSection] = []
    heading = "正文"
    paragraphs: list[str] = []
    in_abstract = False
    for tag, classes, value in parser.blocks:
        class_set = set(classes.split())
        if tag == "h1" and not title:
            title = value
            continue
        if "ltx_abstract" in class_set or "ltx_title_abstract" in class_set:
            in_abstract = True
        if tag.startswith("h"):
            if paragraphs:
                sections.append(PaperSection(heading, "\n".join(paragraphs)))
                paragraphs = []
            heading = value
            in_abstract = "abstract" in value.casefold()
            continue
        if in_abstract:
            abstract_parts.append(value)
        else:
            paragraphs.append(value)
    if paragraphs:
        sections.append(PaperSection(heading, "\n".join(paragraphs)))
    document = PaperDocument(
        title=_clean(title),
        abstract=_clean(" ".join(abstract_parts)),
        sections=tuple(sections),
    )
    return _validate_document(document, expected_title)


def extract_pdf_document(raw: bytes, expected_title: str) -> PaperDocument:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise PaperSummaryError(
            "pdf_dependency_missing", "pypdf is required for PDF fallback"
        ) from None
    try:
        reader = PdfReader(BytesIO(raw), strict=True)
    except Exception:
        raise PaperSummaryError("pdf_invalid", "arXiv PDF cannot be parsed") from None
    if reader.is_encrypted or not reader.pages or len(reader.pages) > MAX_PDF_PAGES:
        raise PaperSummaryError("pdf_invalid", "arXiv PDF violates the page boundary")
    pages: list[str] = []
    try:
        for page in reader.pages:
            raw_page = unicodedata.normalize("NFKC", page.extract_text() or "")
            reference_start = _REFERENCE_HEADING.search(raw_page)
            if reference_start is not None:
                prefix = _clean(raw_page[: reference_start.start()])
                if prefix:
                    pages.append(prefix)
                break
            pages.append(_clean(raw_page))
    except Exception:
        raise PaperSummaryError("pdf_invalid", "arXiv PDF text extraction failed") from None
    joined = "\n".join(value for value in pages if value)
    probe = joined[: max(4_000, len(expected_title) * 8)]
    if _title_similarity(probe, expected_title) < .08:
        raise PaperSummaryError(
            "paper_identity_mismatch", "downloaded PDF does not match the candidate"
        )
    document = PaperDocument(
        title=_clean(expected_title),
        abstract="",
        sections=tuple(
            PaperSection(f"Page {index}", value)
            for index, value in enumerate(pages, start=1)
            if value
        ),
    )
    return _validate_document(document, expected_title)
