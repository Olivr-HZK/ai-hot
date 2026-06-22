# X US T1 英文识别与正式抓取调整计划

## 当前英文识别逻辑
- TikTok：读取 `textLanguage` 或 `language`，转小写后判断。
- X：读取 `raw_source.lang`，如果没有再读 `item.lang` 或 `item.language`。
- 只有以下值会被视为英文：
  ```text
  en / eng / english
  ```
- US T1 的目标命中要求是：
  ```text
  英文通过 + 美国信号命中 + 未命中排除词
  ```
- 今天 X cache 模式 0 通过的主因不是排除词，而是：
  - `1498` 条里只有 `43` 条识别为英文；
  - `0` 条命中美国信号；
  - 只有 `7` 条命中排除词。

## 调整方向
将 X US T1 的正式运行改为优先使用 `scrape` 模式，而不是依赖普通 X 缓存。

- 当运行：
  ```powershell
  python scripts/us_t1/us_content_push.py --platforms x
  ```
  且没有显式传 `--source` 时，X 默认使用 `scrape`。
- X scrape 会自动读取最新版 `x_scrape.search_queries`，并为每个关键词追加：
  ```text
  lang:en ("United States" OR USA OR America OR American)
  ```
- 如果显式传：
  ```powershell
  --source cache
  ```
  则仍使用缓存调试，不请求 X API。

## Key Changes
- 在 `scripts/us_t1/us_content_push.py` 中增加平台级 source 决策：
  - `--source` 显式传入时优先级最高。
  - 未传 `--source` 时：
    - `x` 默认 `scrape`
    - `tiktok` 仍默认使用现有 `US_T1_DEFAULT_SOURCE`，默认 `cache`
- 新增可选配置：
  ```env
  US_T1_X_DEFAULT_SOURCE=scrape
  ```
- X scrape 模式下，`usT1Targeting.geoHits` 明确记录：
  ```text
  search_query_us_constraint
  ```
  表示美国限定来自搜索条件。
- X scrape 模式下，如果 API 未返回语言字段，但查询已包含 `lang:en`，则 `detectedLanguage` 可标记为 `en`。
- cache 模式保持严格：没有美国文本/作者/地点信号时不放行，避免把普通 X 缓存误当作美国定向素材。

## Test Plan
- 运行帮助检查：
  ```powershell
  python scripts/us_t1/us_content_push.py --help
  ```
- 缓存调试：
  ```powershell
  python scripts/us_t1/us_content_push.py --platforms x --source cache --dry-run
  ```
  预期不请求 X API，可能仍为 0。
- 正式 X US T1：
  ```powershell
  python scripts/us_t1/us_content_push.py --platforms x --dry-run
  ```
  预期使用 scrape，查询包含 `lang:en` 和美国限定词。
- 验证报告：
  - `source` 或平台 source 记录为 `scrape`
  - `geoHits` 包含 `search_query_us_constraint`
  - 预筛后最多前 20 条进入审核
  - 最终通过项最多 5 条
  - 不写入飞书多维表格

## Assumptions
- “按照 1 的调整方向”理解为：X US T1 正式运行时使用美国/英文限定的实时搜索，而不是用普通 X 缓存判断美国定向。
- cache 模式继续作为调试工具，不作为正式美国定向结果来源。
- 该规则仍独立于主流程，不占用任何产品/UA/UA geo 推送名额。
