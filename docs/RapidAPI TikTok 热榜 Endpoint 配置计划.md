# RapidAPI TikTok 热榜 Endpoint 配置计划

## Summary
- 搜索结果确认：当前使用的 `tiktok-api23.p.rapidapi.com` 属于 Tikfly / Lundehund 的 TikTok API；RapidAPI Playground 中存在 `Ads (Trending)` 分类，并列出 `Get Trending Video`、`Get Trending Hashtag`、`Get Trending Song`、`Get Trending Keyword` 等 endpoint。参考：RapidAPI Playground 搜索结果显示 `Get Trending Video` 列表，Tikfly 官网示例也使用 `https://tiktok-api23.p.rapidapi.com/api/user/info` + `x-rapidapi-key` 调用方式。
- 重要限制：RapidAPI / Tikfly 定价页显示 `Ads & Trending Endpoint` 为 `Request Custom`，所以热榜 endpoint 很可能需要当前 RapidAPI 账号开通权限，否则会返回 403 / plan limit / forbidden。
- 本项目代码已预留配置键：`RAPIDAPI_TIKTOK_HOT_FEED_PATH`。只要填入 RapidAPI Playground 中 `Get Trending Video` 的 path，日常 TikTok 抓取会先尝试热榜，失败则 warning 后继续关键词搜索，不阻塞流程。

## Key Configuration
- 在 RapidAPI 页面进入：
  - `Tiktok API / tiktok-api23`
  - `Playground`
  - `Ads (Trending) ⭐️`
  - `GET Get Trending Video`
  - 复制 Request URL 中 host 后面的 path 和 query。
- `.env` 配置为：
  ```env
  RAPIDAPI_TIKTOK_HOST=tiktok-api23.p.rapidapi.com
  RAPIDAPI_TIKTOK_SEARCH_PATH=/api/search/video
  RAPIDAPI_TIKTOK_HOT_FEED_PATH=<从 Playground 复制的 Get Trending Video path，可包含 query>
  ```
- `references/tiktok_feedback_optimization_rules.json` 保持：
  ```json
  "hot_feed": {
    "enabled": true,
    "max_items": 100,
    "max_pages": 1,
    "path": "",
    "method": "GET"
  }
  ```
- 推荐优先用 `.env` 的 `RAPIDAPI_TIKTOK_HOT_FEED_PATH`，不把具体 endpoint path 写死到规则文件，便于后续 RapidAPI endpoint 调整。

## Validation Plan
- 先在 RapidAPI Playground 直接运行 `Get Trending Video`，确认账号已开通 `Ads & Trending Endpoint` 权限。
- 再用本地终端做最小请求测试，不进入完整爬取：
  ```powershell
  curl.exe --get "https://tiktok-api23.p.rapidapi.com<你的HOT_FEED_PATH>" `
    --header "x-rapidapi-key: <你的RapidAPI Key>" `
    --header "x-rapidapi-host: tiktok-api23.p.rapidapi.com"
  ```
- 期望返回中至少包含一种视频列表字段：`item_list`、`itemList`、`items`、`videos`、`aweme_list`、`results`，或在 `data` 下包含这些字段。
- 如果返回 403 / subscription / forbidden / plan limit：不是代码问题，说明该账号未开通 Ads & Trending，需要在 RapidAPI / Tikfly 侧申请 custom access。
- 配好后运行一次非推送测试：
  ```powershell
  node trend-scrap/tiktok-scraper/src/scraper.js
  ```
  检查 `skill_runs/scrape_checkpoints/tiktok/latest_status.json` 中 `hotFeed.enabled=true`，且 `hotFeed.itemCount > 0` 或记录了明确错误。

## Rollback / Fallback
- 若热榜 endpoint 不稳定或未开通，把 `.env` 中 `RAPIDAPI_TIKTOK_HOT_FEED_PATH=` 置空即可。
- 置空后程序会跳过热榜源，继续使用现有 Apify + RapidAPI 关键词搜索，不影响日常流程。
- 暂不建议切换到其他 provider，除非 API23 的 Ads & Trending 权限无法开通；备选可评估 KeyAPI `/v1/tiktok/trending/videos` 或 TikHub `/video/trending/list`，但它们需要新增鉴权方式和字段适配。

## Sources
- RapidAPI `tiktok-api23` Playground 搜索结果显示 `Ads (Trending)` 分类和 `Get Trending Video` endpoint。
- Tikfly 官网说明该服务使用 `tiktok-api23.p.rapidapi.com` 与 `x-rapidapi-key` 调用，并标注 `Ads & Trending Endpoint` 需要 custom access。
- KeyAPI 与 TikHub 文档可作为备选趋势接口参考，但不作为本项目默认配置。
