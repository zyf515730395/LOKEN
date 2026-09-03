# LOKEN Logo 与 V9 吞吐优化设计

## 目标

先把用户提供的正式 LOKEN Logo 接入左上角品牌入口，再优化工作日论文流水线：筛选阶段批量处理摘要，摘要阶段只读取 Introduction 并以有界并发处理多篇论文。

## 正式 Logo

- 使用用户提供的 PNG 原图，仅裁去透明空边并保存为公开静态资源；不重绘、不补字。
- 左上角品牌入口只显示 Logo 图片，不再显示 `LK` 占位符或 `LOKEN` 文字。
- 深色导航中以 CSS 反相显示原始黑色图形，保留透明背景；图片保持原始宽高比，不拉伸。
- 品牌入口仍保留 `aria-label="LOKEN 首页"`，并继续链接论文首页。

## 筛选批处理

- 现有 Codex 工作日自动任务继续承担筛选判断，不在公共仓库新增另一个分类模型或隐式网络依赖。
- 全部 pending 候选先按 `updated`、`id` 升序稳定排序，再依序分批；每批最多 20 篇，且序列化后的论文材料严格不超过 24,000 字符。
- 每批只向判断上下文提供论文 `id`、`title`、`abstract`、`matched_topics` 以及五类主题边界；不下载、不读取、不输入 HTML、PDF 或 Introduction。单篇材料已超过字符上限时不进入判断上下文，本轮记为失败并保留 pending。
- 每篇输出一条兼容 `--apply-curation` 的决定。批内论文互不影响；无法可靠判断的论文记录为本轮失败并留在 pending，不用猜测结果。
- 所有批次完成后一次性应用已验证的决定文件；只有 accepted 论文进入摘要阶段。

## Introduction-only 摘要

- 继续使用 arXiv HTML-first，只有既有明确不可用语义才回退 PDF。
- 从标准化文档中提取 Introduction：HTML 优先按 section heading，PDF 按编号标题边界；模型输入不再包含 abstract 或全文其他章节。
- 找不到可用 Introduction 时只失败当前论文，错误码稳定为 `introduction_unavailable`。
- 长 Introduction 仍受现有请求字符边界约束并允许 map-reduce，但每个 chunk 都只能来自 Introduction。

## 有界并发

- `papers.summaries run` 新增 `--workers`，默认 2，可由既有内部命名空间下的 `TOGOS_WSL_LLM_WORKERS` 配置，允许范围 1–8；网站品牌更名不扩散到运行时兼容接口。
- 并发单位是论文；每个 worker 独立完成获取、Introduction 提取和模型总结。
- 共享状态、报告、公开摘要页和站点重建仍只在主线程顺序写入，保持现有回滚与幂等语义。
- 单篇异常转成该论文的失败记录，其他 future 继续；最终结果按候选原始顺序稳定输出。

## 自动任务接入

- 定时任务先批量筛选 pending，再应用决定并提交筛选结果；筛选完成后才启动摘要运行。
- 本机 WSL 脚本通过 `TOGOS_WSL_LLM_WORKERS` 接收 worker 数，默认 2、只允许整数 1–8，并在模型启动前拒绝非法值；它把有效值作为 `--workers` 传给公共 CLI，运行报告记录实际值。
- 本机 vLLM unit 的 `--max-num-seqs 2` 与默认 worker 数一致；模型地址、service 名和本地路径继续只存在于忽略的 `ops/`。
- 退出码 `0` 与部分失败 `3` 继续进入安全发布检查，其他退出码停止。

## 验收

- 生成页左上角只含正式 Logo 图片，没有占位符和品牌文字。
- 筛选指令明确证明只使用摘要和候选主题，按 `updated`、`id` 稳定分批，并同时满足 20 篇和 24,000 序列化字符上限。
- 本地回归测试证明模型摘要消息不含 abstract/其他章节，只含 Introduction。
- 本地回归测试证明 worker 上限校验、至少两篇可并发、结果顺序稳定、单篇失败继续。
- Python 编译、JS 语法、站点构建、重复构建、隐私扫描与 Git diff 检查通过；测试文件按项目规则删除且 README 不变。
