# TikTok Discovery URL 解析层设计

## Summary
- 在 TikTok 00:01 discovery 内新增独立 URL 解析层：Edge 搜索页拿 URL 和搜索卡片数据，discovery 转成主路径兼容候选 JSON，再交给 `phase1_scrape.process_scraper_output(input_data=07_candidates.json)`。
- 不调用主路径 Node TikTok scraper，不调用 Apify / RapidAPI / SocialCrawl。
- 解析优先级：搜索页内嵌 JSON/卡片 DOM > 视频详情页网页 fallback > video_id 时间戳 fallback；互动数据缺失则 rejected，不伪造。

## Key Changes
- 重构 discovery 阶段边界：
  - `--stage search` 只打开 Edge 搜索页，输出 `05_search_links/*.json` 和新增 `05_search_cards/*.json`。
  - `--stage details` 读取搜索阶段产物，执行 URL 解析层，输出 `06_detail_raw/*.json` 和 `07_candidates.json`。
  - `--stage all/filter/report` 串起 search、details、filter，保持与主流程隔离。
- 新增 URL 解析层：
  - 规范化 URL 为 `https://www.tiktok.com/@<author>/video/<video_id>`，用 `video_id` 做去重主键。
  - 从搜索页卡片或搜索页内嵌 JSON 提取 `text`、`hashtags`、`authorMeta`、`playCount`、`diggCount`、`commentCount`、`shareCount`、`coverUrl`、`duration`。
  - 当页面数据没有发布时间时，用 `int(video_id) >> 32` 推导 `createTime/createTimeISO`，并记录 provenance 为 `video_id_timestamp`。
  - 若关键互动字段缺失，写入 `09_rejected.json`，原因如 `missing_engagement_stats`，不补 0 伪装成功。
- 候选 JSON 目标 schema：
  - 每条候选必须包含 `id`、`text`、`hashtags`、`diggCount`、`commentCount`、`playCount`、`videoMeta.webVideoUrl`、`videoMeta.coverUrl`、`webVideoUrl`、`authorMeta`、`createTime`、`createTimeISO`、`sourceQuery`、`searchQuery`、`sourcePath=tiktok_cookie_discovery`、`captureSource=tiktok_keyword_discovery`。
  - 额外保留 `tiktokKeywordDiscovery.parseProvenance`，记录字段来自 `search_embedded_json`、`search_card_dom`、`detail_html` 或 `video_id_timestamp`。
- 详情页 fallback：
  - 仅当搜索页卡片无法凑齐候选字段时打开视频详情页。
  - 继续使用 Edge + cookie + route guard。
  - 如果详情页出现登录、验证码、验证壳或统计缺失，只记录 rejected，不阻塞整个 run。
- 本地产物：
  - 保留现有 `05_search_links/*.json`，其中继续放 canonical URL 列表。
  - 新增 `05_search_cards/*.json`，保存每个搜索词的卡片解析快照、rank、sourceKeyword、rawText、rawStats、cover candidates。
  - `06_detail_raw/*.json` 改为每个 video_id 的 URL 解析报告，包含最终 candidate、缺失字段、解析来源、fallback 状态和错误。
  - `07_candidates.json` 只保存可进入主路径过滤链的结构化候选。

## Test Plan
- 单元测试 URL 规范化：不同 TikTok URL、query/hash、重复作者路径都归一到同一 canonical URL 和 video_id。
- 单元测试发布时间推导：`video_id >> 32` 生成可被 `parse_video_datetime` 识别的 `createTime/createTimeISO`。
- 单元测试搜索卡片解析：fixture HTML/JSON 中的 `1.2M`、`45K`、caption、hashtags、cover 能转成主路径候选字段。
- 单元测试缺失字段：缺少播放/点赞/评论任一关键统计时进入 rejected，不写入 `07_candidates.json`。
- 阶段测试：`--stage search` 只生成 `05_*`；`--stage details --resume` 只读取已有搜索产物并生成 `06_detail_raw`、`07_candidates`。
- 回归测试：`process_scraper_output(input_data=07_candidates.json)` 能消费 discovery 候选；常规 TikTok 主流程和 INS discovery 不受影响。

## Assumptions
- Edge 搜索页卡片和页面内嵌 JSON 是 URL 解析层的首选数据源，因为当前详情页容易进入验证壳。
- `video_id` 时间戳只用于发布时间兜底；互动数据不使用兜底值。
- “复用主路径”仅指复用 TikTok 过滤链，不复用 Node TikTok scraper。
