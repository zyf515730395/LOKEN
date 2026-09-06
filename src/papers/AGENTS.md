# Paper pipeline rules

- `docs/togos-papers.json` is the canonical public archive input. Candidate decisions remain in `data/arxiv-candidates.json`; paper labels and `paper`/`survey` types remain in `data/paper-annotations.json`.
- The ordered label taxonomy and model-facing descriptions come only from `config/site.yaml`. New labels must not be hard-coded in Python or JavaScript.
- `src/papers/site.py` owns the paper archive view. `docs/index.html` and `docs/search-index.json` are generated outputs and must not be edited by hand.
- Ordinary papers are grouped into year and month by their publication date. The Monday-to-Sunday week label may cross month or year boundaries without changing that ownership.
- Surveys appear only in the yearly `Surveys` period; ordinary papers appear only in monthly periods. A multi-label paper may appear in each matching label view, while search remains deduplicated by arXiv ID.
- Missing annotations use the legacy archive topic as a temporary `paper` fallback and remain pending until the local annotation workflow replaces them.
- Keep model calls loopback-only and private inputs, responses, caches, reports, and test artifacts below ignored `build/`. Follow the narrower rules in `annotations/` and `summaries/` when editing those modules.
- When publishing a paper-pipeline change, commit the relevant source/config/data together with every affected generated page or index; never stage local test or cache artifacts.
