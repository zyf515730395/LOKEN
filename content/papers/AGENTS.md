# Public paper data

- `archive.json` is the canonical historical/public paper archive. Preserve every existing historical entry.
- `arxiv-candidates.json` owns collection cursors and pending/accepted/rejected decisions; only pending candidates are reviewed.
- `paper-annotations.json` owns validated public topic/tag/type/affiliation metadata.
- Models, source documents, responses, caches, receipts, reports and queue checkpoints never belong here; they remain under ignored `build/paper-summaries/`.
- `docs/togos-papers.json` is a generated compatibility export, not an editable input.
