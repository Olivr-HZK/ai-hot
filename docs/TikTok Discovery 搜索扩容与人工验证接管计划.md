# TikTok Discovery 搜索扩容与人工验证接管计划

## Summary
- 每个关键词搜索目标提升到最多 50 个唯一 TikTok 视频 URL。
- 搜索滚动改为增长驱动：每轮滚动后随机等待 2-4 秒，并持续抽取 URL/cards。
- 出现人机验证时，程序通知用户手动完成；用户完成后程序自动检测恢复并继续当前关键词。

## Key Changes
- 搜索扩容：
  - 新增配置：`TIKTOK_KEYWORD_DISCOVERY_SCROLL_WAIT_MIN_MS=2000`、`TIKTOK_KEYWORD_DISCOVERY_SCROLL_WAIT_MAX_MS=4000`。
  - 默认提高 `TIKTOK_KEYWORD_DISCOVERY_MAX_SCROLLS=40`。
  - 新增 `TIKTOK_KEYWORD_DISCOVERY_MAX_NO_GROWTH_ROUNDS=6`。
  - 滚动动作轮换使用 `mouse.wheel`、`PageDown`、`lastCard.scrollIntoView()`。
  - 每轮滚动后立即抽取 URL 和 `05_search_cards` 数据，按 `video_id` 去重，达到 50 即停止。
- 本地产物：
  - `05_search_links/*.json` 增加 `scrollRounds`、`growthEvents`、`noGrowthRounds`、`stopReason`、`variantsTried`。
  - `05_search_cards/*.json` 保存每轮新增卡片、rank、sourceKeyword、rawStats、coverCandidates。
  - 新增 `verification_state.json`，记录触发验证的 keyword、URL、时间、已收集数量、截图路径和 HTML snippet 路径。
- 人工验证接管：
  - 将 `assert_page_ok` 改为页面状态检测：`ok`、`login_required`、`verification_required`、`empty_shell`。
  - 检测到验证后，如果是可见 Edge，暂停当前关键词并通知用户手动完成验证。
  - 通知方式优先用控制台输出 + 写本地状态文件；如项目已有飞书通知工具，可复用内部通知发送一条“需要人工验证”的消息。
  - 程序按 `TIKTOK_KEYWORD_DISCOVERY_VERIFICATION_POLL_SECONDS=5` 轮询页面状态。
  - 用户完成验证后，程序继续当前关键词，不丢弃已收集 URL/cards。
  - 超过 `TIKTOK_KEYWORD_DISCOVERY_VERIFICATION_WAIT_SECONDS=600` 后，记录 `verification_required_timeout`，保留产物并跳过当前关键词。
- 同词补量兜底：
  - 如果主搜索页滚动耗尽但未满 50，启用同词轻变体补量：原词、带引号、`<term> template`、`<term> trend`、hashtag 形态。
  - 所有变体归入原关键词 allocation，按 `video_id` 去重，总数最多 50。

## Test Plan
- 随机等待测试：确认每轮等待落在 2000-4000ms 且不固定。
- 增长驱动测试：模拟链接增长、无增长、达到 50，确认 `stopReason` 正确。
- 卡片保留测试：模拟虚拟列表回收，确认已出现 cards 不丢失。
- 验证检测测试：fixture 覆盖 login/captcha/verify/challenge/empty shell。
- 人工恢复测试：模拟状态从 `verification_required` 变为 `ok`，确认继续当前 keyword。
- 超时测试：验证未恢复时写 `verification_required_timeout` 并跳过。
- 回归测试：`details/filter` 继续消费 `05_search_links + 05_search_cards`，主 TikTok 流程和 INS discovery 不变。

## Assumptions
- 不自动绕过人机验证；用户在可见 Edge 中手动完成。
- 初期默认 `TIKTOK_KEYWORD_DISCOVERY_HEADLESS=false`，保证能人工接管。
- 无人值守或 headless 下遇到验证时只记录、跳过、后续重试。
