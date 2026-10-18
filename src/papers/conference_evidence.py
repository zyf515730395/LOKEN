"""Honest, bounded body evidence for identity-verified conference documents."""
from __future__ import annotations

import hashlib
import re

from papers.summaries.extraction import extract_introduction
from papers.summaries.models import PaperDocument, PaperSummaryError

MAX_EVIDENCE = 18_000
STOP = re.compile(r'^(?:\d+[.\s]*)?(?:references|bibliography|acknowledg\w*|appendix)\b', re.I)
ABSTRACT = re.compile(r'^(?:\d+[.\s]*)?abstract\b', re.I)
OVERVIEW = re.compile(r'^(?:\d+(?:\.\d+)*[.\s]*)?(?:overview|motivation|background|problem\s+(?:statement|formulation))\b', re.I)


def _usable(text: str) -> bool:
    return len(text.strip()) >= 400 and len(re.findall(r'\b[a-zA-Z]{2,}\b', text)) >= 50


def select_evidence(document: PaperDocument) -> dict:
    """Never fabricate an abstract or call an arbitrary excerpt Introduction."""
    try:
        text = extract_introduction(document)
        if not _usable(text):
            raise PaperSummaryError('body_evidence_unavailable', 'introduction is too short for summary evidence')
        basis, headings = 'introduction', ['Introduction']
    except PaperSummaryError:
        usable = []
        for section in document.sections:
            if STOP.match(section.heading.strip()):
                break
            if ABSTRACT.match(section.heading.strip()):
                continue
            text = section.text
            # Page-based PDFs may contain the title, abstract and references inline.
            text = re.split(r'(?im)^\s*(?:references|bibliography|acknowledg\w*)\s*$', text)[0]
            if document.abstract:
                text = text.replace(document.abstract, '')
            text = text.replace(document.title, '')
            abstract_start = re.search(r'(?im)^\s*abstract\s*[:.\-—]?\s*', text)
            if abstract_start:
                rest = text[abstract_start.end():]
                boundary = re.search(r'(?im)^\s*(?:\d+[.\s]+)?(?:introduction|overview|motivation|background|methods?|approach)\s*[:.]*\s*$', rest)
                text = rest[boundary.start():] if boundary else text[:abstract_start.start()]
            text = re.sub(r'(?im)^\s*(?:https?://\S+|copyright\b.*|all rights reserved.*|\d+)\s*$', '', text)
            if _usable(text):
                usable.append((section.heading, text.strip()))
        overview = [(h, t) for h, t in usable if OVERVIEW.match(h.strip())]
        selected = overview or usable
        if not selected:
            raise PaperSummaryError('body_evidence_unavailable', 'verified paper has no usable body evidence')
        basis = 'overview' if overview else 'body_excerpt'
        headings = [h for h, _ in selected]
        text = '\n\n'.join(f'{h}\n{t}' for h, t in selected)
    truncated = len(text) > MAX_EVIDENCE
    text = text[:MAX_EVIDENCE]
    return {'basis': basis, 'text': text, 'sections': headings,
            'truncated': truncated, 'sha256': hashlib.sha256(text.encode()).hexdigest()}


def evidence_receipt(evidence: dict) -> dict:
    return {key: value for key, value in evidence.items() if key != 'text'}


def ocr_document(raw: bytes, title: str, directory) -> PaperDocument:
    """Bounded optional local OCR; missing tools never become fabricated text."""
    import json
    import shutil
    import subprocess
    import tempfile
    from io import BytesIO
    from pathlib import Path
    from pypdf import PdfReader
    from .summaries.acquisition import _atomic_write
    from .summaries.extraction import _validate_document, MAX_PDF_PAGES
    from .summaries.models import PaperSection
    reader = PdfReader(BytesIO(raw), strict=True)
    if reader.is_encrypted or not reader.pages or len(reader.pages) > MAX_PDF_PAGES:
        raise PaperSummaryError('pdf_invalid', 'OCR input violates PDF page boundaries')
    if len((reader.pages[0].extract_text() or '').strip()) >= 80:
        raise PaperSummaryError('paper_identity_mismatch', 'text-bearing PDF must pass the original identity check')
    digest = hashlib.sha256(raw).hexdigest()
    cache = Path(directory) / ('ocr-' + digest + '.json')
    try:
        data = json.loads(cache.read_text())
        payload = json.dumps(data['pages'], ensure_ascii=False).encode()
        if data.get('source_sha256') == digest and data.get('text_sha256') == hashlib.sha256(payload).hexdigest():
            sections = tuple(PaperSection(f'Page {i}', text) for i, text in enumerate(data['pages'], 1))
            return _validate_document(PaperDocument(title, '', sections), title)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    render, recognize = shutil.which('pdftoppm'), shutil.which('tesseract')
    if not render or not recognize:
        raise PaperSummaryError('ocr_unavailable', 'scanned paper requires local pdftoppm and tesseract',
                                details={'requires': ['pdftoppm', 'tesseract']})
    try:
        with tempfile.TemporaryDirectory(prefix='.ocr-', dir=directory) as scratch:
            folder = Path(scratch)
            (folder / 'input.pdf').write_bytes(raw)
            pages = min(len(reader.pages), 12)
            subprocess.run([render, '-f', '1', '-l', str(pages), '-scale-to', '1800', '-png',
                            str(folder / 'input.pdf'), str(folder / 'page')], check=True,
                           timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            texts = []
            for image in sorted(folder.glob('page-*.png'), key=lambda p: int(p.stem.rsplit('-', 1)[1])):
                result = subprocess.run([recognize, str(image), 'stdout', '-l', 'eng'],
                    check=True, capture_output=True, text=True, timeout=30)
                texts.append(result.stdout)
            payload = json.dumps(texts, ensure_ascii=False).encode()
            _atomic_write(cache, json.dumps({'source_sha256': digest, 'pages': texts,
                'text_sha256': hashlib.sha256(payload).hexdigest(), 'basis': 'local_ocr',
                'page_limit': 12, 'truncated': len(reader.pages) > pages}, ensure_ascii=False).encode())
        return _validate_document(PaperDocument(title, '', tuple(
            PaperSection(f'Page {i}', text) for i, text in enumerate(texts, 1))), title)
    except (subprocess.SubprocessError, OSError):
        raise PaperSummaryError('ocr_failed', 'bounded local OCR did not complete') from None
