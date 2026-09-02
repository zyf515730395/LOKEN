# LOKEN V9 摘要自动化实施计划

## Task 1：固化运行协议

- 记录 V9 设计与私有/公共边界。
- 审核 V7 CLI、退出码、HTML-first 和事务回滚契约，不重复实现摘要器。
- 提交：`docs: define the V9 summary automation`。

## Task 2：迁移本机 WSL 运行脚本

- 在忽略的 `ops/summary_runtime.sh` 中保留锁、clean pull、依赖同步、vLLM start/stop trap 和受限 Git 暂存。
- 用 `python -m papers.summaries run` 替换旧摘要入口；把退出码 `3` 视为可发布的 partial，其他非零码阻止提交。
- 从 loopback `/models` 取得模型 ID；不把服务配置写入公共代码。
- 验证 `bash -n`、静态控制流、状态命令、隐私扫描和无变化路径。

## Task 3：更新并验证工作日自动任务

- 保留现有工作日计划、模型和筛选规则。
- 摘要步骤改为调用 V9 私有脚本，明确暂时性 HTML 失败不得 PDF fallback，逐篇失败继续。
- 最终报告读取 `build/paper-summaries/report.json` 并列出 attempted/succeeded/failed、失败 ID/错误码、提交 SHA、推送和 vLLM 状态。
- 查看更新后的 automation，确认未创建重复任务。

## Task 4：端到端验收与集成

- 在不启动真实推理的条件下验证脚本语法、分支控制和仓库洁净门槛。
- 验证 Python/JS 语法、README 不变、Git 差异与自动任务状态。
- 独立审查后普通合并 main 并推送；真实模型运行留给下一次工作日任务或显式手动运行。
