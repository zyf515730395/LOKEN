# 项目代理规则

## 修改前同步远程代码

- 每次开始修改项目文件前，必须先执行 `git pull --ff-only`，确认本地分支已同步远程最新代码。
- 如果工作区存在未提交改动，或 `git pull --ff-only` 执行失败，不得使用强制拉取、重置或覆盖等方式处理；应停止修改并向用户说明情况，等待用户决定。

## 新特性测试文件仅限本地

- 可以为新特性创建和运行本地测试，但所有为测试新特性而新增或修改的测试相关文件都必须仅保留在本地，特性完成后进行删除
- 不得暂存、提交、推送、上传这些文件，也不得将其包含在 Pull Request、补丁或任何其他发送到远程/云端的变更中。
- 测试相关文件包括但不限于：单元测试、集成测试、端到端测试、临时测试脚本、测试配置、fixture、mock、snapshot、golden file、测试数据及覆盖率产物。

## 按特性拆分本地提交

- 功能实现并验证完成后，应按相互独立的特性拆分为多笔本地 Git commit，避免把无关功能混入同一提交。
- 每笔 commit 只暂存该特性对应的源码、配置、文档或生成产物；提交前必须检查暂存区内容和 `git diff --cached --check`。

## README 保持固定

- 任何更改都不再修改 `README.md`。

## Writings 目录约定

- `content/writings/<slug>/index.md` 是公开文章唯一真源；本地图片只放在同 bundle 的 `assets/`。
- `src/writings/` 只包含文章校验、渲染与发布逻辑；跨主题能力留在 `src/shared/`。
- `docs/writings/` 只保存生成产物，受管范围以 `manifest.json` 为准，不手工编辑受管文件。
- `build/` 只保存本地报告和临时产物，必须保持忽略且不得提交。

## Writings 导入器约定

- `src/writings/importers/` 只负责把外部导出物转换为标准 writing bundle；发布器不得反向依赖 importer。
- 导入计划、私有映射、预览、报告和解压内容只放在已忽略的 `build/notion-import/` 或 `build/reports/`，不得进入 `content/` 或 `docs/`。
- importer 只能通过显式 apply 修改 `content/writings/<slug>/`，不得生成、提交或推送站点产物。

## WeChat Reading 导入器约定

- `src/writings/importers/weread/` 只负责本地微信读书 Markdown 归一化、loopback 模型调用、私有缓存、预览与 CLI 编排。
- 可复用的路径安全、状态和事务逻辑保留在 `src/writings/importers/`；Notion 与 WeChat adapter 不得相互依赖。
- 微信读书计划、原始归一化内容、提示词、模型响应、缓存、预览、状态和报告只放在已忽略的 `build/weread-import/` 或 `build/reports/`。
- 只有显式 apply 可以修改 `content/writings/<slug>/`；adapter 不得直接生成 `docs/`。
