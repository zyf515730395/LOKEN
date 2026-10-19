# 美股发布模块

- 美股由唯一automation-3协调器串行调度，不保留独立美股自动化。周更仅周日08:00到期，实际值每天08:00/22:00到期；先核对scheduler与stocks阶段回执，补最近一期，均遵守主工作区占用让行。
- 实际值独立写 actuals.json，官方发布后才允许 apply；回执存 build/reports/stocks/actuals，包含核验事件、未发布/失败原因、输入和输出校验和、提交及远端验证。失败下个检查点有界重试；不把未取得实际值记作完成，不改写历史推演。

- 本目录保存美股数据校验、页面生成和每周回执 CLI；不调用论文推理、采集器或论文协调器。
- 配置只放 `config/stocks.yaml`，公开真源只放 `content/stocks/`，阶段回执和临时核验只放忽略的 `build/reports/stocks/`。
- 发布前一次性校验全部公开输入并渲染全部页面；输入无效时保留现有页面。输出只包含经过 HTML 转义的公开字段。
- 事件时间必须为带偏移的 America/New_York 时间，并用 zoneinfo 转换 Asia/Shanghai；2Y/10Y 收益率为连续观察项，禁止制造固定发布日期。
- 日期和已知数值必须携带具体来源与带时区核验时间。官方事件须使用该指标的官方机构域名；未知值为 null，不猜测市场一致预期。
- 预期推演逐指标写明确的条件假设和上行/基准/下行情境；不承诺市场反应。
- 普通子页复用公共 section-header、topic-header 标题层级与内容边距；期刊复用 shared.periodicals。时间线来源区域贴齐卡片底端，不随指标数量改变位置。
- 周期为北京时间周日08:00最近到期一期；只有验证、构建、普通 push 且远端核验成功后才能记 completed。锁/维护占用由自动化预检，未完成记 deferred，保留已完成阶段。
- 每期回执要求 `events.updated_at` 本期刷新，维护时仍未发生或日期未知的事件及全部收益率 monitor 的官方来源本期重新核验；收益率已知实际观测的证据来源也须本期重新核查。已发生的历史事件无需重复核验，真实观测日期允许早于本期（如休市），核验时间不能代替观测日期。

## 每周维护命令与证据

从项目根目录运行，设置 `PYTHONPATH=src`；沿用项目已有 Python 环境，无需启动模型服务。

1. `python -m stocks status` 返回最近到期周日、due 与已有回执。`due: false` 静默结束；不逐周重放。
2. 自动化先核验 Git 状态、当前维护进程以及实际持有的维护/模型锁，其他任务占用即 `python -m stocks record --phase deferred --reason "..."`，保留旧公开内容。锁文件存在不等于被持有，不删除锁文件。
3. 从 `config/stocks.yaml` 的官方日历刷新未来事件（至少覆盖下一周）与连续收益率。使用新近观测的真实日期，不把 H.15 发布日当成市场观测日。逐项记录具体来源和本次核验时间；可靠来源没有一致预期就填 null。
4. 写入当前周日文件 `content/stocks/outlooks/YYYY-MM-DD.json`，仅覆盖下一周北京时间周一至周日有已确认release/meeting事件的指标；无发布事件则sections可为空。不包含monitor、未知日期和窗口外指标。可合并同期核心CPI/PCE或就业项，但不能夹带无事件指标。每节来源本期重新核查，情境只写条件假设；旧内容保留，渲染时按各期周界过滤。
5. `python -m stocks validate`；`python -m stocks record --phase validated`；`python -m stocks build`。集成站点构建与验收后 `python -m stocks record --phase built` 固定当前输入/三个页面指纹。
6. 仅提交本次相关源文件和生成文件，执行 `git diff --cached --check`、普通 push；确认远端后 `python -m stocks record --phase completed`。该命令重新校验公开证据、当前 built 指纹、股票工作树干净和 `origin/main == HEAD`，成功后才写 completed。
7. 基础设施或来源获取失败执行有界重试，仍失败记 deferred 并保留旧有效内容/历史推演/已完成阶段。`record` 不执行抓取、Git 写操作或推理，也不会启动论文协调器。

`build` 先完整校验并渲染三个页面，再逐文件原子替换；无效 JSON、来源、时间或模板失败时不触碰已有公开页面。跨文件更新应在构建、验收完成后统一提交发布。
