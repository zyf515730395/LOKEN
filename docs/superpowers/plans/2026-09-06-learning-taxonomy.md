# Learning taxonomy implementation plan

**Goal:** Six ordered research topics, high-recall collection, reviewed-only publication of new daily candidates, controlled detail tags and author institutions.

**Approved design:** Conversation approval on 2026-09-06. Names: Image Gen&Edit, Video Gen&Edit, 3D Gen&Recon, World Model, Relighting, Depth Estimation. Missing institution: `-`. Remove the complete-summary link. Keep README unchanged.

**Architecture:** Preserve archive IDs and legacy summary URLs. Resolve topic aliases at consumption boundaries. Collection writes candidates; newly collected papers require explicit acceptance before publication. Preserve historical archive visibility, per user correction. Annotation v2 separates navigation topics from controlled detail tags and evidence-backed institutions.

**Constraints:** Config owns all taxonomies. Models remain loopback-only. Private work and tests remain under ignored build/ and tests are removed after validation. Split local commits by feature. No push.

## Execution

- [x] Collection: extend `src/papers/collector.py` with UTC windows, overlap, pagination and per-topic successful collection cursors in the ledger. Candidate merge does not expose pending entries. Test window coverage, query batching, retries and preserving review decisions locally.
- [x] Configuration: update `config/site.yaml` with six topics, aliases, broad keyword families, method/task/representation dictionaries and survey references. Test exact order and config validation.
- [x] Annotations: extend `src/papers/annotations/` schema, prompt, cache and source evidence. Legacy classification retains topics but has no invented detail tags. Test unknown tags, missing institutions, cache round trips and migration.
- [x] Publication: update `src/papers/site.py` so new-candidate review filtering precedes grouping/search/counts; show institutions and detail chips. Keep old summary URLs usable, remove complete-summary UI and dead JavaScript/CSS. Test accepted/pending/rejected/missing-review and cross-topic summaries.
- [x] Integration: check local operational consumers for topic renames; rebuild generated HTML/search, validate Python and JavaScript, inspect the browser at desktop/mobile widths. Review diff and commit only relevant tracked source/config/data/generated output, after `git diff --cached --check`.

**Ruling:** Work in the user's existing checkout on a new local feature branch to retain its private operational caches. Do not create a second worktree or copy private assets.

## Verification outcome

Local behavioral tests cover pagination, cursor failure isolation, candidate promotion, schema/cache validation, institution evidence, prospective filtering, topic aliases and new summary transactions. Python compilation, JavaScript and local Bash syntax checks passed. Browser checks passed at desktop and 390px widths, including single-paper summaries, old Video deep links and horizontally scrolled mobile panels. Historical archive, ledger and note-page hashes were unchanged during generation. Temporary tests are removed before commits. No full arXiv collection, historical inference, runtime execution or push was performed.
