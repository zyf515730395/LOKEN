# 本地论文精读模块规则

- 所有原始 HTML、PDF、抽取文本、模型输入输出、状态和报告只能写入 `build/paper-summaries/`。
- 公共写入目标只能是既有 `docs/notes/*.html`；不得从本模块修改论文筛选数据或历史论文元数据。
- 获取顺序必须是 arXiv HTML 优先。只有明确的 HTML 不可用状态或不可用正文才允许 PDF fallback；暂时性网络失败不得降级为 PDF。
- 只允许固定 `https://arxiv.org/html/<id>` 和 `https://arxiv.org/pdf/<id>.pdf`，不得跟随跨站重定向或读取 ledger 中的任意下载 URL。
- 每篇论文失败后记录安全错误并继续；私有根、历史页面、manifest 或事务证据不安全时停止对应提交范围。
- 端侧模型只能通过共享 loopback transport 访问，浏览器与公共构建不得发起模型请求。
- 所有测试、fixture、mock 服务、下载与缓存仅限本地，提交前删除。
