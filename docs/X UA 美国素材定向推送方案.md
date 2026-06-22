# X UA 美国素材定向推送方案

## Summary
基于现有独立 `US T1` 流程，把 X 做成与 TikTok 类似的“美国英语 UA 素材定向推送”通道。该通道独立于日常主流程，默认只发飞书 webhook，不写入多维表格；支持缓存调试和显式抓取，避免误耗 API。

## Key Changes
- 固化 X 独立入口能力：
  - 继续复用 `scripts/us_t1/us_content_push.py`，支持 `--platforms x` 单独跑 X。
  - 输出仍写入 `skill_runs/us_t1/latest.json` 和 `runs/<runId>.json`。
  - 飞书标题区分平台，例如“美国内容候选推送 - X”。

- X 搜索与地区限定：
  - 自动读取最新版 `x_scrape.search_queries`。
  - 抓取模式下每个 X query 自动追加：
    - `lang:en`
    - 美国语义限定：`United States OR USA OR America OR American`
  - 缓存模式下只读取 `skill_runs/scrape_checkpoints/x/latest_raw.json`，不触发 API。

- X 预筛规则：
  - 必须英文。
  - 必须有美国信号：文本、作者地点、place/country、或搜索条件注入的美国限定。
  - 必须不命中现有排除词。
  - 热度使用 UA geo 放宽版，只记录 `heatPass`；默认不硬过滤。
  - 美国/英语/排除词预筛后，只取热度评分前 `20` 条进入两道审核。

- 审核链路：
  - 第一道：产品手册审核，产品只允许 `Evoke / Toki / Kavi / Avatar`。
  - 第二道：OpenRouter 美国投放审核，判断是否适合美国英语 UA 投放、广告素材参考、模板库复用。
  - 通过项统一标记 `pushObject="ALL"`。
  - 不设置素材数量上限；通过多少推送多少。

- 推送与隔离：
  - 只飞书 webhook 推送，不调用 bitable 写入。
  - 不覆盖主流程 `hotspots.json`、`hotspots_x.json`。
  - 不接入每日主流程和定时任务，除非后续明确要求。

## Test Plan
- 缓存模式：
  - 运行 `python scripts/us_t1/us_content_push.py --platforms x --source cache --dry-run`
  - 确认不触发 X API、不写表、不覆盖主流程文件。
- 抓取模式：
  - 运行 `--platforms x --source scrape --per-query 10 --dry-run`
  - 确认 X query 自动包含 `lang:en` 和美国限定词。
- 预筛验证：
  - 非英语内容被过滤。
  - 无美国信号内容被过滤。
  - 命中排除词内容被过滤。
  - 预筛后最多前 `20` 条进入审核。
- 审核验证：
  - 产品手册拒绝则不推送。
  - 美国投放审核拒绝则不推送。
  - 通过项 `pushObject=ALL`，只发送飞书 webhook。
- 回归：
  - TikTok US T1 流程不受影响。
  - X 日常主流程不受影响。
  - 飞书多维表格字段不变。

## Assumptions
- “类似 Tik 的 UA 美国素材定向推送”理解为复用现有独立 US T1 机制，而不是并入日常主流程。
- X 美国限定优先使用 `lang:en` 和文本/作者/地点美国信号；如果 API 无可靠地理字段，不猜测放行。
- 该流程默认用于人工调试和补充推送，后续再决定是否接入定时任务。
