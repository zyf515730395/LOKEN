# V6 网站视觉重构实施计划

## 目标

在不改变内容数据契约的前提下，把公共站点重构为“极简知识罗盘”，统一桌面端、移动端、浅色和深色体验。

## 约束

- 不修改 `README.md`。
- 不开发“跑得还快”的地图能力。
- 不引入远程字体、前端框架或地图依赖。
- 新增或修改的测试文件只保留在本地，验证后删除，不提交。
- 每个独立特性单独提交，提交前检查暂存区和 `git diff --cached --check`。

## Task 1：固定视觉壳层契约

**文件：**

- 修改：`src/shared/site_shell.py`
- 修改：`docs/assets/js/site-shell.js`
- 本地临时验证：HTML 结构断言与 Node DOM 行为测试

**步骤：**

1. 先写会失败的本地断言，锁定一级导航轨道标记、统一工具栏、二级栏纯目录和可访问标签。
2. 调整共享壳层标记，保持现有 URL、存储键与事件入口稳定。
3. 调整侧栏折叠和抽屉控制文案/图标状态。
4. 运行局部断言、Python 编译与 JavaScript 语法检查。
5. 删除临时测试文件并提交 `refactor: reshape the knowledge navigation shell`。

## Task 2：建立全站视觉令牌与响应式骨架

**文件：**

- 修改：`docs/assets/css/site.css`

**步骤：**

1. 先用本地断言锁定核心令牌、桌面侧栏宽度、移动断点、焦点态和 reduced-motion。
2. 重写色彩、字体、间距、一级方位轨道、二级目录、顶部工具区与搜索浮层。
3. 校准 1440×1000、900px 附近和 390×844 三种宽度。
4. 用真实首页做浅色/深色截图检查，并修正溢出与对比度。
5. 删除临时测试文件并提交 `feat: establish the knowledge compass visual system`。

## Task 3：校准论文、里程碑和文章页面

**文件：**

- 修改：`docs/assets/css/site.css`
- 必要时修改：`src/papers/site.py`
- 必要时修改：`src/milestones/publisher.py`
- 必要时修改：`src/writings/rendering.py`

**步骤：**

1. 先写本地结构断言，确认所有页面正文顶部都有主题名和说明，二级栏没有重复信息。
2. 调整首页标题区、统计、主题分区、论文表格和移动卡片层级。
3. 调整里程碑时间线、比较表格、文章列表、文章正文和空状态。
4. 构建全站并在真实页面中检查至少首页、模型页、文章索引、占位页。
5. 删除临时测试文件并按页面族拆分提交：
   - `style: refine paper and milestone reading views`
   - `style: refine writing and empty section views`

## Task 4：全站回归与交付

**文件：**

- 重新生成：`docs/index.html`
- 重新生成：`docs/milestone-models/*.html`
- 重新生成：`docs/writings/**/*.html`
- 重新生成：`docs/journeys/index.html`

**步骤：**

1. 运行完整站点构建两次，确认生成结果确定性。
2. 运行 Python 语法、JavaScript 语法、现有单元测试和 `git diff --check`。
3. 检查 `README.md` 未变化、无临时测试/缓存/预览产物进入暂存区。
4. 浏览器验证搜索、主题切换、二级栏折叠、移动抽屉与关键深链。
5. 请求代码审查并修正高置信问题。
6. 快进合并回本地 `main`，推送 `origin/main`，清理功能工作树。
