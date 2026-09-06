"""Canonical public paper inputs; private runtime paths remain in summaries.paths."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTENT = ROOT / 'content' / 'papers'
ARCHIVE = CONTENT / 'archive.json'
LEDGER = CONTENT / 'arxiv-candidates.json'
ANNOTATIONS = CONTENT / 'paper-annotations.json'
CONFIG = ROOT / 'config' / 'site.yaml'
DOCS = ROOT / 'docs'
