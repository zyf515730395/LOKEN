# LOKEN Logo 与 V9 吞吐优化实施计划

**Spec:** `docs/superpowers/specs/2026-09-03-logo-and-v9-throughput-design.md`

## Global Constraints

- `README.md` 不得修改。
- 本次新增或修改的测试、fixture、mock 仅限本地，完成后删除且不得提交。
- Logo 必须来自用户提供的 PNG，只裁透明边，不生成替代图形。
- 筛选阶段只使用 title、abstract、matched_topics 和主题定义，不读取 Introduction。
- 摘要模型只接收 title 与 Introduction；论文获取维持 HTML-first 与既有 PDF fallback 语义。
- 并发只覆盖逐篇获取与推理；私有状态、公开页面、报告和站点构建顺序写入。
- 单篇失败继续，结果顺序稳定，公共事务不安全时整批停止。

### Task 1: Replace the Placeholder Brand with the Real Logo

- 创建本地失败测试，断言共享导航只渲染 `brand-logo` 图片，不再渲染 `brand-mark`、`brand-wordmark` 或可见品牌文本。
- 裁剪用户 PNG 的透明空边，写入 `docs/assets/images/loken-logo.png`。
- 修改 `src/shared/site_shell.py` 和 `docs/assets/css/site.css`，更新资源版本并重建受管页面。
- 执行生成器、Python/JS 语法、图片尺寸与桌面/移动视觉检查；删除测试。
- 独立提交：`style: install the official LOKEN logo`。

### Task 2: Restrict Summary Inputs to Introduction

- 创建本地失败测试，覆盖 HTML section、PDF 编号文本、无 Introduction、长 Introduction 分块以及 prompt 不泄漏 abstract/其他章节。
- 在 `src/papers/summaries/` 实现有界 Introduction 提取并调整 prompt/cache 版本。
- 保持 HTML-first 获取和现有结构化输出契约。
- 删除测试并独立提交：`feat: summarize papers from introductions only`。

### Task 3: Add Bounded Paper Concurrency

- 创建本地失败测试，覆盖 workers 范围、并发重叠、单篇失败继续、稳定结果顺序以及顺序发布。
- 为 workflow 与 CLI 增加 workers 配置；worker 内独立创建获取客户端，主线程汇总并发布。
- 报告记录有效 worker 数，不记录环境或服务细节。
- 删除测试并独立提交：`feat: process paper summaries concurrently`。

### Task 4: Connect the Weekday Automation

- 更新 V9 设计文档与本机忽略的 WSL 运行脚本：全部 pending 按 `updated`、`id` 升序稳定分批，每批同时限制为最多 20 篇和 24,000 序列化材料字符，且只提供 `id`、`title`、`abstract`、`matched_topics` 与五类主题定义。
- 筛选不得获取或读取 HTML、PDF、Introduction；失败或无法可靠判断的论文保留 pending。全部批次结束并校验决定后只 apply 一次，随后仅对 accepted 论文启动摘要。
- WSL runtime 默认 `TOGOS_WSL_LLM_WORKERS=2`、仅接受整数 1–8，在模型启动前校验并把有效值传给 `papers.summaries run --workers`；vLLM unit 使用 `--max-num-seqs 2`。
- 更新既有 `arxiv` 自动任务而不创建重复任务，保留工作日计划、Git 安全门和部分失败语义。
- 静态验证脚本和任务 prompt；独立提交公共文档：`docs: define the V9 throughput workflow`。

### Task 5: Verify, Review, and Integrate

- 运行完整 Python 编译、JS 语法、站点连续两次构建、隐私扫描、README 哈希和 diff 检查。
- 独立审查完整分支，修复阻断问题。
- 普通合并到 `main`，推送 `origin/main`，并展示本地站点效果。
