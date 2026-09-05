# 论文分类模块规则

- 本目录只负责配置驱动的论文多标签与 `paper`/`survey` 分类，不负责论文筛选决定或摘要正文生成。
- 模型只能通过共享 loopback transport 调用；原始输入、响应、缓存和报告只能写入已忽略的 `build/paper-summaries/`。
- 公开分类真源固定为 `data/paper-annotations.json`，写入前必须完成严格 schema 校验并使用原子替换。
- 标签名称、顺序和判定说明只来自 `config/site.yaml`；代码不得硬编码可选标签。
- 单篇失败必须与其他论文隔离；历史 archive、候选 ledger 和摘要页面不得因分类失败被修改。
- 所有新增测试、fixture 和 mock 仅放在 `build/`，验证后删除且不得提交。
