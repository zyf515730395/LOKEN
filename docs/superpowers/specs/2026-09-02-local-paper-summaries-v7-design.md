# V7 本地论文精读生成器设计

## 目标

V7 补齐 `学习一个` 中已经存在但没有仓库内实现的“论文要点”生产链路：从已人工筛选接受的 arXiv 论文中找出尚未生成要点的条目，优先读取 arXiv HTML，HTML 确实不可用时才下载 PDF，通过 WSL 上的 OpenAI-compatible 端侧服务生成结构化中文要点，并安全写入现有 `docs/notes/*.html`。

这是一条本地、私有、可恢复的批处理流程。浏览器不连接模型，论文原文、抽取文本、prompt、模型响应和运行报告都留在忽略的 `build/` 下。

## 范围

V7 包含：

- 从 `data/arxiv-candidates.json` 选择 `accepted` 且有唯一 `selected_topic` 的论文；
- 读取现有论文要点 manifest，默认只处理缺失或 `pending` 的论文；
- arXiv HTML-first 获取、PDF fallback、私有内容缓存和文本抽取；
- 严格 loopback 的端侧模型调用、分块归纳、结构化校验与缓存；
- 保留历史要点、原子更新主题页和 manifest；
- 单篇失败继续下一篇，并生成不含原文或模型内容的安全报告；
- 一个面向自动化的 CLI。

V7 不包含：

- 浏览器端推理、云端模型、API key 或公网模型服务；
- 自动修改论文筛选决定；
- 覆盖已有 `ready` 要点，除非显式指定单篇 `--refresh`；
- 把 PDF、HTML、抽取文本或模型原始响应提交到 Git；
- 定时任务启用；先交付可验证的本地命令，再单独接入自动化；
- `跑得还快`地图功能。

## 用户入口

```text
python -m papers.summaries run --model MODEL [--limit N]
python -m papers.summaries run --paper ARXIV_ID --model MODEL [--refresh]
python -m papers.summaries status [--json]
```

模型配置也可来自已有环境变量：

- `TOGOS_WSL_LLM_MODEL`；
- `TOGOS_WSL_LLM_BASE_URL`，默认 `http://127.0.0.1:11434/v1`。

显式参数优先。`run` 默认按论文更新时间升序处理最多 10 篇，避免一次占满端侧资源；重复 `--paper` 保持用户给定顺序。`--refresh` 只允许和显式 `--paper` 一起使用，防止批量覆盖历史内容。

退出码：

- `0`：全部目标已生成或无需处理；
- `3`：至少一篇失败，但其他论文已继续并安全提交；
- `2`：输入、私有状态、目标页面或全局事务不安全，未进行不确定写入。

## 候选选择

候选 ledger 是筛选决定的唯一来源。只有同时满足以下条件的论文才可处理：

1. `status == accepted`；
2. `selected_topic` 是站点允许的五个论文主题之一；
3. arXiv ID 通过规范化并与 ledger key 一致；
4. 目标主题 notes manifest 中状态缺失或为 `pending`；
5. 显式 `--paper` 时，该论文也必须已接受，不能绕过人工筛选。

已有 `ready` 条目默认是不可变历史。`--refresh --paper ID` 可重新生成该 ID，但必须保留其他历史文章字节内容和顺序。

## HTML-first 获取协议

每篇论文必须先请求固定地址：

```text
https://arxiv.org/html/<normalized-id>
```

只有以下情况视为“HTML 不可用”并允许 PDF fallback：

- HTTP `404`、`410` 或 `415`；
- HTTP `200` 但不是 HTML；
- HTML 缺少论文主体，或规范化后正文低于最小可用长度。

限流、超时、DNS、TLS、`429` 和 `5xx` 是暂时性获取失败，不得偷偷切换 PDF；当前论文在有限重试后记为失败，然后继续下一篇。这样能保证“HTML 优先”是实际行为，而不是名义上的首个 URL。

PDF fallback 使用固定地址 `https://arxiv.org/pdf/<normalized-id>.pdf`。响应必须是 PDF、大小受限且 ID 与固定目标一致。V7 使用 `pypdf` 做本地文本抽取；加密、页数异常、文本为空或内容超限只阻塞当前论文。

请求禁用代理和跨站重定向，只允许 `https://arxiv.org`。HTML 与 PDF 都设置有限连接/读取超时、固定 User-Agent、响应大小上限和有限指数退避。每篇论文的最终来源记录为 `html` 或 `pdf`，但公网输出不展示本地缓存路径。

## 私有源缓存

```text
build/paper-summaries/
├── sources/<arxiv-id>/
│   ├── source.html | source.pdf
│   └── extracted.json
├── cache/<digest>.json
├── report.json
└── state.json
```

缓存 envelope 包含版本、规范 arXiv ID、来源类型、内容 SHA-256、获取契约版本、校验和和必要的非敏感元数据。原始文件与抽取文本不进入报告。缓存损坏时忽略并重新获取，不使用半写文件。

## 文本抽取与分块

HTML 抽取只保留论文主体中的标题、摘要、分节标题、段落、列表和表格可读文本，移除导航、引用列表、脚注链接、样式、脚本和纯公式辅助标记。PDF 按页抽取并规范空白。

两种来源都生成统一结构：

```json
{
  "title": "...",
  "abstract": "...",
  "sections": [{"heading": "...", "text": "..."}]
}
```

抽取结果必须与 ledger 标题具有可接受的规范化相似度，避免错误页面。正文按摘要和分节边界切成最多 18,000 字符的 map 块；单篇抽取文本总量和块数都有硬上限。参考文献不进入模型输入。

## 端侧模型与结构化输出

复用并抽取现有 WeChat Reading 的 loopback-only transport：只接受字面量 `127.0.0.1`、`localhost` 或 `::1` 的 `http /v1`，拒绝代理、重定向、userinfo、query、fragment 和非 loopback peer。

map 和 reduce 都要求 `temperature: 0`，输出严格 JSON：

```json
{
  "one_sentence": "一句非空结论",
  "problem": "论文解决的问题",
  "contributions": ["三到六条创新点"]
}
```

未知字段、重复字段、HTML、控制字符、空值、超长文本或数组越界均阻塞当前论文。输出还要经过证据检查：每个阶段只能基于当前提供的论文文本，不允许声称阅读全文之外的来源；最终条目保留论文原文链接。

内容缓存 key 覆盖论文源 SHA-256、抽取契约、prompt 版本、模型名和 transport 版本。模型不可用、响应无效或缓存损坏只影响当前论文。

## 公共页面写入

每篇结果渲染为现有三段格式：

```html
<article id="summary-ARXIV_ID" data-arxiv-id="ARXIV_ID" data-status="ready">
  <h1>[ARXIV_ID] TITLE</h1>
  <p><a href="https://arxiv.org/abs/ARXIV_ID">arXiv 原文</a></p>
  <h2>一句话结论</h2>
  <p>...</p>
  <h2>解决的问题</h2>
  <p>...</p>
  <h2>创新点</h2>
  <ul>...</ul>
</article>
```

发布器把新条目放在对应主题列表顶部，并将 manifest 更新为 `ready` URL。它在内存中解析并验证完整目标页，确保：

- 历史 article ID 唯一且未丢失；
- 非目标历史 article 的规范化字节保持不变；
- manifest 与 article 集合一一对应；
- 新内容经过 HTML escape；
- 主题与固定文件名一致；
- 写入使用同卷临时文件、flush、fsync 和原子替换。

同一批中多个论文先全部独立生成，再按主题一次性原子提交。某篇失败不会阻止同主题其他成功结果；全局页面结构不安全则该主题不写入，其他安全主题仍可提交并报告降级。

## 状态与反馈

`status` 只报告：接受数、ready 数、pending 数、可处理数、失败数、按来源缓存数量、上次模型名和相对报告路径。它不输出标题、摘要、抽取文本、响应、绝对路径或环境变量。

`run` 每篇只输出规范 ID、主题、最终状态、来源类型和安全错误码，最后给出总数与下一步。例如模型未启动时提示启动 loopback 服务后重试失败 ID，而不是打印堆栈。

## 失败隔离

以下是单篇失败并继续：HTML 暂时失败、HTML/PDF 不可用、PDF 解析失败、文本不足、标题不匹配、模型超时、结构化输出错误、缓存损坏后重新生成失败。

以下是主题级失败：目标 notes 页结构或 manifest 不安全、同一 ID 重复、历史正文在重建中丢失、原子替换失败。该主题保持原文件不变，其他主题继续。

以下是全局失败：ledger schema 不安全、私有根越界、lock/WAL 无法恢复、CLI 试图刷新未显式指定的论文。

## 验收标准

1. HTML 成功时绝不请求 PDF；HTML 明确不可用时才请求 PDF；暂时性 HTML 失败不请求 PDF。
2. HTML 与 PDF 都能归一为相同论文文档契约，并拒绝错误标题、空文本和超限输入。
3. loopback transport 的 WeRead 现有行为不回归，论文生成拒绝非本机模型地址。
4. 结构化 map-reduce、缓存命中、缓存失效与 `--refresh` 行为可确定验证。
5. 一篇下载或模型失败时，后续论文继续；报告包含每个目标的安全状态。
6. 新要点安全追加并在首页变为“查看要点”；所有既有历史要点保持。
7. 同一命令重跑不重复文章、不重复模型调用；默认不覆盖 ready 历史。
8. 运行报告、缓存和原文全部位于 `build/`，公共页面与 Git diff 不泄露私有路径、prompt 或原始响应。
9. Python、JavaScript、站点构建、标题搜索和 `git diff --check` 全部通过。
10. 所有新增测试、fixture、mock 服务、下载文件、模型响应、报告、缓存和 Python cache 在提交前删除；`README.md` 不变。

## 版本边界

V7 先交付本地命令和安全写入能力。真实 WSL 模型可用后再运行真实论文验收；定时任务接入作为下一独立版本，避免把网络抓取、模型容量和 Git 发布三个故障域一次性耦合。地图继续延期。
