# X 高质量博主优先抓取与关键词动态降额计划

## Summary
- X 抓取顺序改为：先读取飞书 `yYzT06` 高质量博主表，抓取这些博主在当前 X 时间窗口内的发帖，再执行关键词搜索。
- 高质量博主发帖如果产生有效命中，则减少后续关键词搜索数量。
- 关键词降频时优先排除过去表现不佳的关键词，而不是简单裁掉末尾关键词。
- 下游筛选、团队需求匹配、产品审核、UA 升级、反馈硬过滤、飞书字段结构不变。

## Key Changes
- 新增 X 高质量博主配置，放入 `x_scrape`：
  - `quality_creators_enabled = true`
  - `quality_creators_sheet_url = "https://scnmrtumk0zm.feishu.cn/wiki/HLs9wvAACiq5HzkM7cDcmYkAnwf?sheet=yYzT06"`
  - `quality_creators_max_accounts = 20`
  - `quality_creators_posts_per_account = 20`
  - `quality_creators_pages_per_account = 1`
  - `quality_creators_reduce_queries_per_hit = 2`
  - `quality_creators_min_search_queries = 8`
- X scraper 新增两类请求：
  - 读取飞书 sheet，抽取 `x.com/<username>` 或 `@username`。
  - 对每个 username 调用 Twitter241：
    - `GET /user?username=<username>` 获取 `rest_id`
    - `GET /user-tweets?user=<rest_id>&count=<count>&cursor=<cursor>` 获取发帖。
- 时间窗口沿用当前 X 逻辑：
  - 默认 `X_MAX_HOURS_AGO=72`
  - 若设置 `TARGET_DATE`，则按该自然日过滤。
- “高质量博主命中”的定义：
  - 通过 scraper 层基础过滤：有正文、有视觉媒体、在时间窗口内、视频时长不超限。
  - 不绕过 Python 阶段团队需求、质量、安全、产品手册审核。
- 关键词动态降额：
  - 原始上限仍为 `x_scrape.max_search_queries = 20`。
  - 若高质量博主命中 `N` 条有效帖子，则关键词执行数为：
    - `max(quality_creators_min_search_queries, 20 - N * quality_creators_reduce_queries_per_hit)`
  - 例：命中 1 条执行 18 个关键词；命中 3 条执行 14 个关键词；最低保留 8 个关键词。
- 关键词裁剪优先级：
  - 保留 PDF workflow 核心词优先级最高，尤其是：
    - `ChatGPT Seedance iPhone vlog workflow`
    - `ChatGPT Seedance photo album workflow`
    - `GPT Images Seedance Suno couple video`
    - `GPT Images Seedance prompt workflow`
    - `Seedance iPhone couple video prompt`
    - `photo to video storyboard prompt`
  - 对其余关键词，根据过去飞书反馈表现排序。
  - 表现不佳关键词优先被裁剪：
    - 直接命中该关键词来源的历史推送，如果 `UA=低/否决` 且 `产品=低/无/否决`，记为负反馈。
    - 若历史 `hotspotIntro` 或本地 `matched_search_terms/sourceQuery` 能关联到关键词，也计入该关键词表现。
    - 近期负反馈更多、无高质量反馈的关键词优先降频。
  - 没有历史反馈证据的关键词按原配置顺序保留，避免误杀新方向。
- 数据合并：
  - 博主发帖和关键词搜索结果进入同一个 `filtered-result.json`。
  - 按 tweet id 去重。
  - 每条保留来源标记：
    - `capture_source = "quality_creator" | "search"`
    - `matched_quality_creator = username`
    - `matched_search_terms = [...]`

## Implementation Notes
- 在 `trend-scrap/x-scraper/src/scraper.js` 内实现高质量博主抓取、关键词降额和合并。
- 新增一个轻量的本地关键词表现读取逻辑：
  - 优先读取 `skill_runs/feedback/*_recent_feedback.json` 中已有 Stage0 反馈缓存。
  - 若缓存不存在，不实时额外读取飞书，直接按默认顺序保留关键词。
  - 这样避免 X scraper 每次额外消耗飞书 API 或因为飞书失败阻塞抓取。
- Stage0 继续负责长期反馈调节：
  - `feedback_loop/optimizer.py` 保持现有 X 20 个搜索词与 6/7/7 配比约束。
  - 可补充输出关键词表现摘要，供 X scraper 降频时读取。
- 若飞书高质量博主表读取失败、账号为空、profile API 失败：
  - 记录 warning。
  - 回退到当前纯关键词搜索逻辑。
  - 不阻断 X 流程。
- checkpoint 增加可选监控字段：
  - `qualityCreatorCount`
  - `qualityCreatorHitCount`
  - `searchQueryCountBeforeReduction`
  - `searchQueryCountAfterReduction`
  - `droppedSearchQueries`
  - `dropReasons`

## Test Plan
- 飞书表可读：读取 `yYzT06`，解析出当前 2 个 X 账号。
- 飞书表不可读：X scraper 输出 warning，继续执行完整关键词搜索。
- 高质量博主 0 命中：关键词数量不减少。
- 高质量博主 1 命中：关键词数量减少 2 个。
- 高质量博主多命中：按规则降额，但不低于 8 个关键词。
- 有历史负反馈关键词：降额时优先被移除。
- PDF workflow 核心词：即使降额也优先保留，除非关键词总保留数低于核心词数量。
- 没有反馈缓存：按原配置顺序保留关键词。
- 博主发帖和关键词搜索命中同一 tweet：最终去重并合并来源字段。
- 回归：
  - X 团队需求筛选不变。
  - X 产品手册审核不变。
  - X 安全审核、评论补充、视觉去重、AI 简介不变。
  - 飞书写表字段不变。
  - `node --check trend-scrap/x-scraper/src/scraper.js` 通过。
  - Python 相关文件内存编译通过。

## Assumptions
- “过去表现不佳”优先使用已有 Stage0 反馈缓存，不在 scraper 中强制实时读取飞书反馈表。
- “推送对应时间范围”沿用 X 当前时间窗口：默认 72 小时，或 `TARGET_DATE` 对应自然日。
- 高质量博主来源只提升抓取优先级，不给予审核豁免。
- 关键词最低保留 8 个，避免搜索覆盖面被压得过窄。
