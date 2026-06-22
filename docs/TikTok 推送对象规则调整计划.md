# TikTok 推送对象规则调整计划

## Summary
- TikTok Discovery 和 TikTok 主流程默认推送对象改为 `UA`。
- 所有通过现有安全、质量、去重、反馈硬过滤的素材都可推送 UA。
- 只有通过“产品推送热度筛选”的素材才设定为 `ALL`，表示同时推送 UA 和产品。
- 不修改飞书多维表格已有数据、表结构，也不回写或迁移本地历史数据。

## Key Changes
- TikTok 主流程调整：
  - 默认 `pushObject=UA`。
  - 复用现有安全、质量、反馈、去重过滤决定素材是否可进入推送池。
  - 在 UA 推送池内增加产品热度筛选；通过后升级为 `ALL`。
  - TikTok 流程不再产出单独 `产品` 推送对象。
  - `write_hotspots()` 不再强制把 TikTok 输出全部覆盖为 `ALL`。

- TikTok Discovery 调整：
  - Discovery 素材进入主流程时默认 `pushObject=UA`。
  - 即时热点、非 AI 高热广告素材可以进入 UA。
  - Discovery 素材只有满足产品热度筛选时才升级为 `ALL`。
  - 保留现有 Discovery 分层 metadata，不要求修改历史 Discovery artifact。

- 热度筛选规则：
  - 第一版复用现有 TikTok 热度/质量阈值配置。
  - 主要参考播放、点赞、评论、时效等已有字段。
  - hot-layer ad material 可继续使用现有较宽松热点素材逻辑。
  - 普通非 AI 素材仍使用更严格热度门槛。

- 最终推送与归一化：
  - 主流程归一化保留 `UA` / `ALL`，不再全量改为 `ALL`。
  - `apply_push_caps()` 保留素材已有推送对象。
  - 飞书推送代码只调整未来新推送记录的 `pushObject` 归一化逻辑，不修改飞书多维表格历史记录。
  - 空值、未知值、历史 `产品` 在未来运行中默认归一为 `UA`，避免绕过热度筛选。

## Data Safety
- 不执行任何飞书多维表格数据迁移、批量更新、历史记录修正或表结构变更。
- 不改写本地历史输出、历史 Discovery 结果、历史反馈文件或已生成报告。
- 测试使用临时 fixture 或内存数据，不连接真实飞书表，不回写真实历史目录。
- 本次只修改代码、配置读取逻辑和测试；新规则只影响后续新跑出的结果。

## Test Plan
- 单元测试：
  - 普通合格 TikTok 素材默认输出 `UA`。
  - 高热且产品可用素材输出 `ALL`。
  - 低热但可作为 UA 广告参考的素材保持 `UA`。
  - Discovery 非 AI 热点广告素材可进入 `UA`，未过热度筛选时不升级为 `ALL`。
  - `apply_push_caps()` 保留 `UA` / `ALL`。
  - `write_hotspots()` 不再强制 TikTok 输出 `ALL`。
  - 未来运行中遇到空值、未知值、历史 `产品` 时归一为 `UA`。

- 回归测试：
  - 运行 Python 编译检查覆盖 TikTok Discovery、主流程、Feishu push、pipeline 相关文件。
  - 运行 TikTok Discovery、push caps、phase1 scrape、Feishu push 相关 unittest。
  - 运行完整 `python -m unittest discover tests`。

## Assumptions
- `UA` 是所有最终可推送素材的默认对象。
- `ALL` 只表示“UA + 产品”。
- 第一版产品热度筛选复用现有 TikTok 热度/质量阈值，不新增外部 API。
- 本次不改变 TikTok 外部 API 抓取量，也不改变已完成的三层 Discovery 关键词策略。
