"""Conservative institution extraction from explicit author-affiliation markup."""

from html.parser import HTMLParser
import re

from papers.summaries.models import AcquiredPaper


class _Affiliations(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, bool, bool]] = []
        self.parts: list[str] = []
        self.values: list[str] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "meta" and attributes.get("name", "").lower() == "citation_author_institution":
            self.values.append(attributes.get("content", ""))
        if tag in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            if tag == "br" and self.stack:
                self.parts.append("; ")
            return
        affiliation = "ltx_affiliation" in attributes.get("class", "").split()
        if affiliation and not any(item[1] for item in self.stack):
            self.parts = []
        self.stack.append((tag, affiliation, tag in {"sup", "script", "style"}))

    def handle_endtag(self, tag):
        index = next((i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i][0] == tag), None)
        if index is None:
            return
        closing = self.stack[index:]
        del self.stack[index:]
        if any(item[1] for item in closing) and not any(item[1] for item in self.stack):
            self.values.append("".join(self.parts))
            self.parts = []

    def handle_data(self, data):
        if any(item[1] for item in self.stack) and not any(item[2] for item in self.stack):
            self.parts.append(data)


def extract_institutions(paper: AcquiredPaper) -> tuple[str, ...]:
    """Only explicit HTML affiliations count; ambiguous PDF text remains missing."""
    if paper.kind != "html":
        return ()
    try:
        if paper.source_path.stat().st_size > 16 * 1024 * 1024:
            return ()
        parser = _Affiliations()
        parser.feed(paper.source_path.read_text(encoding="utf-8"))
        parser.close()
    except (OSError, UnicodeError, ValueError):
        return ()
    values = []
    seen = set()
    for raw in parser.values:
        value = " ".join(raw.split()).strip(" ,;0123456789*†‡")
        # Email-only affiliations are not institutions. Strip trailing contact details.
        value = re.split(r"(?:[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|https?://)", value)[0].strip(" ,;({")
        if not 2 <= len(value) <= 400 or any(c in value for c in "<>") or value.casefold() in seen:
            continue
        seen.add(value.casefold())
        values.append(value)
    return tuple(values[:30])
