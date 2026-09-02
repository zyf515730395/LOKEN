# V7 本地论文精读生成器实施计划

## Task 1：抽取共享 loopback transport

**文件：**

- 新增：`src/shared/loopback_chat.py`
- 修改：`src/writings/importers/weread/client.py`
- 本地测试：`build/v7-tests/test_loopback_transport.py`

先锁定现有 WeRead 的 URL、peer、redirect、size、timeout 和响应校验行为，再把传输层抽到共享模块。WeRead 保留原错误码与公开接口，论文模块使用自己的领域错误映射。完成后删除本地测试并提交 `refactor: share loopback model transport`。

## Task 2：实现 HTML-first 论文获取与抽取

**文件：**

- 新增：`src/papers/summaries/models.py`
- 新增：`src/papers/summaries/paths.py`
- 新增：`src/papers/summaries/acquisition.py`
- 新增：`src/papers/summaries/extraction.py`
- 修改：`pyproject.toml`
- 本地测试：HTML/PDF fixture、HTTP mock 和路径安全测试

先验证 HTML 成功、HTML 明确不可用、HTML 暂时失败三条分支，再实现固定 arXiv URL、有限重试、内容上限、私有原子缓存和统一文档抽取。PDF 用 `pypdf`，只有 HTML 不可用分支可触发。完成后提交 `feat: acquire paper sources with html first`。

## Task 3：实现结构化端侧归纳与缓存

**文件：**

- 新增：`src/papers/summaries/prompts.py`
- 新增：`src/papers/summaries/summarizer.py`
- 新增：`src/papers/summaries/cache.py`
- 本地测试：分块、JSON 严格校验、map-reduce、模型失败和缓存测试

用本地 mock OpenAI-compatible 服务先写失败测试，再实现 bounded map-reduce、三字段 JSON、证据约束、内容寻址缓存和 refresh。完成后提交 `feat: summarize papers with the local model`。

## Task 4：安全发布现有论文要点页

**文件：**

- 新增：`src/papers/summaries/catalog.py`
- 新增：`src/papers/summaries/publisher.py`
- 本地测试：现有 notes 页面副本、历史保护、重复 ID、主题隔离和原子写入

先证明发布失败不会破坏历史文件，再实现候选选择、现有 manifest 解析、article 渲染、主题批量提交与首页契约联动。完成后提交 `feat: publish generated paper summaries safely`。

## Task 5：CLI、状态与端到端回归

**文件：**

- 新增：`src/papers/summaries/__init__.py`
- 新增：`src/papers/summaries/__main__.py`
- 新增：`src/papers/summaries/cli.py`
- 新增：`src/papers/summaries/workflow.py`
- 本地测试：CLI、退出码、失败继续、报告隐私和完整假服务流程

实现 `run` 与 `status`，用两篇假论文验证一篇失败不阻止下一篇、重跑幂等、首页显示“查看要点”且搜索只出现一次。删除所有本地测试和运行产物，提交 `feat: add the local paper summary workflow`。

## Task 6：完整验证、合并与继续

重复运行全站构建，执行 Python/JavaScript/HTML、隐私、确定性和 `git diff --check`；检查 `README.md` 未变化。审查 HTML-first、历史保护、loopback 和失败隔离。通过后快进合并本地 `main`、推送远端、清理工作树，然后自动开始下一版本的定时任务设计；若真实 WSL 模型尚未配置，只阻塞真实模型验收，不阻塞已由 mock 证明的实现。
