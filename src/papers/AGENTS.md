# Paper pipeline rules

- `docs/togos-papers.json` is the canonical public archive input. Candidate decisions remain in `data/arxiv-candidates.json`; paper labels and `paper`/`survey` types remain in `data/paper-annotations.json`.
- The ordered label taxonomy and model-facing descriptions come only from `config/site.yaml`. New labels must not be hard-coded in Python or JavaScript.
- `src/papers/site.py` owns the paper archive view. `docs/index.html` and `docs/search-index.json` are generated outputs and must not be edited by hand.
- Ordinary papers are grouped into year and month by their publication date. The Monday-to-Sunday week label may cross month or year boundaries without changing that ownership.
- Surveys appear only in the yearly `Surveys` period; ordinary papers appear only in monthly periods. A multi-label paper may appear in each matching label view, while search remains deduplicated by arXiv ID.
- Preserve existing historical archive visibility and review decisions. New daily candidates collected since collection.review_required_since must be explicitly accepted before appearing in public lists, counts or search; pending candidates stay in the ledger.
- Topic navigation comes from `paper_labels`; detail tags come from `paper_tag_groups` in the same config. Topics and tags are independent. Topic aliases preserve historical archive and summary URLs; removed topics have no navigation entry.
- Institutions are evidence-backed author affiliations; missing or unreliable evidence renders as `-`. Annotation inference must not guess affiliations from author names.
- Learning pipeline design and implementation notes live in `docs/superpowers/`; local validation scripts and reports live under ignored `build/` and are deleted after verification.
- Keep model calls loopback-only and private inputs, responses, caches, reports, and test artifacts below ignored `build/`. Follow the narrower rules in `annotations/` and `summaries/` when editing those modules.
- When publishing a paper-pipeline change, commit the relevant source/config/data together with every affected generated page or index; never stage local test or cache artifacts.
