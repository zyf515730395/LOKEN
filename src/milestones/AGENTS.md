# Milestone models

- `config/milestone_models.yaml` is the public catalog; releases are chronological, source-backed official milestones, with variants grouped under generations. Model-family navigation sorts names case-insensitively across topics.
- `catalog.py` validates metadata; `publisher.py` renders family and reading pages; `reader.py` owns loopback-only deep reading. Reuse local Markdown notes and preserve existing notes and generated readings when adding families.
- Date-based note IDs may collide across model releases. Resolve explicit `milestone_family` and `milestone_release` before legacy ID-only notes; never treat a note explicitly assigned to another release as a fallback.
- GPT, Claude and DeepSeek track general-purpose language/reasoning releases; QwenVL tracks the named Qwen-VL lineage. Do not silently add unrelated product or specialized model families. Undisclosed technical information stays `/`; missing reading stays visibly pending.
- Monthly maintenance verifies official release announcements and dates before appending milestones, rebuilds affected pages and search, and records private evidence under ignored `build/reports/`. Tests and temporary scripts are local only and deleted after verification. Do not edit README.
