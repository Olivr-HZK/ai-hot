# TikTok Discovery 搜索 JSON 解析器设计

## Summary
- 新增“搜索响应 JSON 解析器”，在 Edge 搜索页滚动期间捕获 TikTok 同域返回的搜索 JSON 响应，从响应里的 `item_list/itemStruct/stats/statsV2` 直接生成主流程兼容候选。
- 不再把单个视频详情页作为主要结构化数据来源；详情页只保留为低优先级补充。
- 旧搜索链接无法补出完整结构化数据，必须重新跑 search 才能捕获搜索 JSON 响应。

## Key Changes
- 在 `scripts/tiktok_keyword_discovery.py` 的 search 阶段增加 `TikTokSearchResponseRecorder`：
  - 在 `page.goto()` 前注册 `page.on("response")`。
  - 只处理 `www.tiktok.com` / `m.tiktok.com` 同域响应。
  - 捕获 URL 包含 `/api/search/`、`/api/recommend/`、`/api/post/item_list/` 或响应 JSON 中包含 `item_list/itemList/itemStruct` 的数据。
  - 保存原始响应摘要到 `05_search_responses/<keyword>.jsonl`，包含 `url`、`queryVariant`、`scrollRound`、`status`、`itemCount`、`capturedAt`、`bodyHash`、`items`。

- 新增搜索 JSON 到候选字段的规范化层：
  - 从常见路径提取视频对象：`item_list[*]`、`itemList[*]`、`data[*]`、`itemStruct`、`aweme_info`、`awemeInfo`。
  - 标准化字段为现有候选 schema：`id`、`text`、`hashtags`、`authorMeta`、`playCount`、`diggCount`、`commentCount`、`shareCount`、`createTime`、`createTimeISO`、`videoMeta.webVideoUrl`、`videoMeta.coverUrl`、`sourceQuery`、`captureSource=tiktok_keyword_discovery`。
  - `statsV2` 优先于 `stats`，字段别名覆盖 `playCount/play_count/viewCount`、`diggCount/likeCount`、`commentCount/comment_count`、`shareCount/share_count`。
  - 若响应里有完整互动字段，则 `parseProvenance.sources` 记录 `search_network_json`。

- 调整 details 阶段的数据入口：
  - `load_search_metadata()` 同时读取 `05_search_links`、`05_search_cards`、`05_search_responses`。
  - `candidate_from_search_meta()` 优先使用 `search_network_json`，其次用 `search_embedded_json`，再用 `search_card_dom`。
  - 只有缺少非互动补充字段时才尝试详情页；缺少互动字段时不再依赖详情页补齐。
  - 每个 video_id 继续写 `06_detail_raw/<video_id>.json`，但内容改为“URL 解析报告”，记录网络 JSON、DOM、详情页各来源是否命中。

- 搜索阶段报告增强：
  - `05_search_links/*.json` 增加 `networkResponseCount`、`networkItemCount`、`networkCandidateCount`。
  - `05_search_cards/*.json` 保持兼容。
  - `report.json` 增加 `searchNetworkJsonCount`、`networkStructuredCandidateCount`、`detailFallbackCount`。

## Test Plan
- Fixture 单测：构造 TikTok 搜索 JSON，覆盖 `item_list.itemStruct.statsV2`、`stats`、`awemeInfo` 三种结构，确认生成候选字段完整。
- 回归单测：只有 DOM 卡片、没有搜索 JSON 时，仍能生成 partial candidate，但缺互动字段必须 rejected。
- 阶段测试：`--stage search` 后必须生成 `05_search_responses/*.jsonl`，并且 `links/cards/responses` 数量可在报告中看到。
- 阶段测试：`--stage details --resume` 能只读取已有 `05_search_responses` 生成 `07_candidates.json`，不打开详情页。
- 端到端测试：用今天 10 个 TikTok 搜索词重新跑 search + details + filter，确认候选中 `playCount/diggCount/commentCount/createTime` 来自 `search_network_json`。
- 隔离测试：不调用 Node TikTok scraper，不访问 RapidAPI / Apify / SocialCrawl，不写主流程 TikTok 默认 data 文件。

## Assumptions
- “允许获取 TikTok 返回的搜索 JSON 响应”指允许在 Playwright Edge 会话内监听 TikTok 网页自身加载的同域 JSON 响应；仍禁止外部 API。
- 初版以被动捕获搜索页响应为主，不主动构造签名请求；若被动捕获不足，再单独设计同页 `fetch` + TikTok web 签名 fallback。
- 需要重新跑搜索阶段，因为旧 run 只有 links/cards，没有保存搜索 JSON 响应。
- 参考来源：TikTok-Api 的 `video.info()` 解析 `SIGI_STATE/__UNIVERSAL_DATA_FOR_REHYDRATION__`，search 使用 TikTok web search endpoint；见 [video.py](https://raw.githubusercontent.com/davidteather/TikTok-Api/master/TikTokApi/api/video.py)、[search.py](https://raw.githubusercontent.com/davidteather/TikTok-Api/master/TikTokApi/api/search.py)、[TikTok-Api docs](https://davidteather.github.io/TikTok-Api/TikTokApi.html)。
