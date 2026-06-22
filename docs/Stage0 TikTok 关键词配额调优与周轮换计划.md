# Stage0 TikTok 关键词配额调优与周轮换计划

## Summary
- 在 Stage0 反馈调节中新增 TikTok 关键词级表现统计，默认读取过去 7 日飞书反馈。
- TikTok 仍固定 10 个搜索词，8 个 AI + 2 个非 AI。
- 总抓取量保持当前不变：`10 * results_per_keyword(35) = 350`。
- 每个关键词每日抓取数量下限 `15`，上限 `50`。

## Key Changes
- 新增 TikTok 关键词表现统计：
  - 从飞书近 7 日反馈行中筛选 `platform=TikTok`。
  - 用本地 TikTok checkpoint/raw 归档按 URL 反查 `sourceQuery/searchQuery`，建立 `url -> keyword` 映射。
  - 无法匹配 URL 的反馈不强行归因到关键词。
- 关键词评分规则：
  - `UA=高` 或 `产品=高` 计为高质量产出。
  - `UA=中` 计为可用产出，轻微正向。
  - `UA=低/否决`、`产品=低/无/否决` 计为负向/无用产出。
  - 关键词综合分 = 高质量权重 - 无用权重 + 可用素材轻权重，并记录样本量。
- 新增 `scrape.keyword_allocations`：
  - 结构为 `{ keyword: count }`。
  - 每日 Stage0 根据近 7 日表现分配每词抓取数量。
  - 每个关键词分配必须在 `[15, 50]` 之间。
  - 所有关键词分配总和必须恒等于 `350`。
  - 高表现关键词获得更多抓取量，低表现关键词减少抓取量。
- 修改 TikTok scraper：
  - 读取 `scrape.keyword_allocations`。
  - Apify 每个关键词使用该关键词自己的 `resultsPerPage`。
  - RapidAPI fallback 每个关键词使用对应 count，但仍受 RapidAPI 单次 count 上限保护。
  - checkpoint 中记录本轮 `keywordAllocations`。
- 每周关键词轮换：
  - 新增 `scrape.keyword_candidates`，分为 `ai` 和 `non_ai` 候选池。
  - 新增 `scrape.keyword_rotation`，记录 `last_rotation_week`、`replaced_keywords`、`added_keywords`、`reason`。
  - 每周一或检测到 ISO week 变化时执行一次轮换。
  - 替换上周综合表现最差的 3 个关键词，同时保持 8 AI + 2 非 AI 配比。
  - 使用 AI 从候选池中挑选同类型补位关键词；AI 不可用时用确定性 fallback。

## Implementation Notes
- 主要改动位置：
  - `feedback_loop/optimizer.py`：新增近 7 日关键词统计、配额分配、周轮换、AI 选词。
  - `scripts/feedback_rules.py`：扩展默认值和校验，确保 10 个词、8/2 配比、allocation 总和 350、单词分配 15-50。
  - `trend-scrap/tiktok-scraper/src/scraper.js`：按关键词读取独立抓取数量。
- Stage0 当前 `--days` 参数保留；TikTok 关键词统计使用 `scrape.keyword_tuning_window_days=7`。
- AI 选词提示词只允许从候选池返回关键词，不允许自由生成不在候选池中的词。
- 替换掉的关键词只从 `scrape.search_queries` 移出，历史记录保留在 rotation 记录中。

## Test Plan
- 规则校验：
  - `scrape.search_queries` 仍为 10 个。
  - AI 关键词 8 个，非 AI 关键词 2 个。
  - 每个当前搜索词都有 `keyword_allocations`。
  - 每个 allocation 在 `15-50`。
  - `sum(keyword_allocations.values()) == 350`。
- 关键词表现统计：
  - 近 7 日本地 TikTok checkpoint 能正确把飞书 URL 反查到 `sourceQuery`。
  - 高反馈关键词 allocation 上升，低/无用反馈关键词 allocation 下降。
  - 样本不足关键词保留至少 15。
- 周轮换：
  - 模拟 week 变化，最差 3 个关键词被替换。
  - 替换后仍满足 8 AI + 2 非 AI。
  - AI 不可用时 fallback 能从候选池补足 3 个。
- Scraper 回归：
  - Apify 对不同关键词使用不同 `resultsPerPage`。
  - checkpoint 写出 `keywordAllocations`。
  - 总计划抓取量仍为 350。
- 静态检查：
  - `python -m py_compile feedback_loop/optimizer.py scripts/feedback_rules.py`
  - `node --check trend-scrap/tiktok-scraper/src/scraper.js`
  - JSON 规则文件可解析。

## Assumptions
- “总搜索次数与现在保持不变”按当前 TikTok 总抓取条数理解，即 `350`。
- 未收到任何反馈的素材不参与关键词好坏统计。
- 每周轮换默认在周一首次 Stage0 运行时执行。
