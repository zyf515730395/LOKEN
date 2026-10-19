# 论文期刊分析

- `daily-YYYY-MM-DD.json`、`weekly-YYYY-MM-DD.json` 为公开分析真源；周报日期为周一，只用本期公开论文及已发布摘要。
- 每主题保存完整 paper_ids、逐篇 contributions（一句话和证据摘要校验和）、trends（结论、依据、局限、引用论文 ID）。不按标题猜贡献，不把本期样本扩大为全领域结论。
- 覆盖或证据变化时旧分析不作为当前结论展示。缺摘要明确标注。
- 原始输入、模型响应和失败回执仅存 build/reports/digests；推理仅在主工作区共享 WSL 锁与时间预算下执行，渲染器不启动推理。
