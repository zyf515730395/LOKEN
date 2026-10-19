# 美股公开内容约定

- `actuals.json` 保存已到发布时间事件的官方公布值覆盖及 revisions 历史；按 event_id 与 period 精确匹配，仅允许 actual/previous，不改 consensus 或历史 outlook。校验来源机构和核验时间，缺数不写零。通过 `python -m stocks.actuals status/apply --input <本地证据JSON>` 检查/应用，验证和构建后独立提交发布。周更期次不因实际值覆盖而重新生成推演。

- `events.json` 是事件与连续收益率观察的公开真源；`outlooks/YYYY-MM-DD.json` 是北京时间周日一期的下一周推演，日期区间为接下来周一至周日。
- JSON 使用 `schema_version: 1`，所有 `updated_at`、`verified_at` 和事件 `scheduled_at` 必须含时区；事件另固定 `timezone: America/New_York`。
- `sources` 为 `{title, url, verified_at}` 列表；官方发布时间和日期只能引用指标对应的 BLS、BEA、Federal Reserve、Treasury 官方域名。
- `actual`、`previous`、`consensus`、`expectation` 的已知值使用 `{value, unit, sources}`；未知为 null。无可靠一致预期来源时保持 null。
- 推演每个指标用 `scenarios.upside/base/downside`，每个情境含 `condition` 和 `implication`，均为条件假设。来源支持事实，不能把推演当作来源已经证明的结果。
- CPI/core CPI、PCE/core PCE、非农/失业率、FOMC 可有官方日程；2Y/10Y 收益率只用 `kind: monitor`、`scheduled_at: null`，观察值另附来源。
- 不存抓取缓存、原始私有材料、失败页面、测试数据或回执；修订保留历史推演。用 `python -m stocks validate` 校验后再构建。
