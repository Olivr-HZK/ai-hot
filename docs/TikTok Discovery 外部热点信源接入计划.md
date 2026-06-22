# TikTok Discovery 外部热点信源接入计划

## Summary
- 即时热点词使用 3 个信源：TikTok Creative Center / Trend Discovery、Google Trends Trending Now、最近 72h Discovery 反哺。
- 预热事件词使用 3 个信源：Nager.Date Holiday API、TheSportsDB、Liquipedia / 电竞赛事日历。
- 外部信源只服务 TikTok Discovery 分层选词，不改变主项目 TikTok 外部 API 抓取量。
- 所有外部源失败时不阻塞 Discovery，继续使用现有配置种子和 fallback 词。

## Key Changes
- 在 `references/tiktok_discovery_keyword_layers.json` 增加 `external_sources` 配置：
  - `hot.sources`: `tiktok_creative_center`, `google_trends`, `recent_discovery_history`
  - `preheat.sources`: `nager_date`, `thesportsdb`, `liquipedia`
  - 支持每个 source 独立 `enabled`、国家/地区、lookback/lookahead、timeout、top_n、category/sport/game 过滤。
  - 默认国家池沿用现有 US、Europe、Mexico、Brazil、Australia、India。

- 在 `scripts/tiktok_keyword_discovery.py` 增加热点/事件聚合层：
  - `hot_layer_candidates()` 合并 TikTok Creative Center、Google Trends、最近 72h Discovery 历史、配置种子和 fallback。
  - `preheat_layer_candidates()` 合并 Nager.Date、TheSportsDB、Liquipedia、本地事件日历和 fallback。
  - 生成新的 run artifact，例如 `02_external_hot_trends.json`、`02_external_preheat_events.json`，只记录本次运行结果，不回写历史文件。

- 即时热点源：
  - TikTok Creative Center 抓取热门 hashtags、songs、videos、creators。
  - Google Trends 抓取 Trending Now 近 4h/24h/48h/7d 热点。
  - 最近 72h Discovery 反哺读取当前已有 run artifact：`10_approved.json`、`08_filtered.json`、`07_candidates.json`，提取高频 hashtags、sourceQuery、searchQuery、标题和正文中的广告素材信号。
  - 原始 trend 会转成 TikTok 可搜素材词，例如 `{trend} edit`、`{trend} poster`、`{trend} photo template`、`{trend} transition`、`{trend} jersey edit`。

- 预热事件源：
  - Nager.Date 拉取国家池对应年份的节假日，生成 holiday/photo/slideshow/template 类关键词。
  - TheSportsDB 拉取未来赛事，优先 football/soccer、basketball，生成 match、final、poster、jersey、celebration 类关键词。
  - Liquipedia / 电竞赛事日历拉取或读取配置化赛事日历，优先 LoL、Valorant、CS2、Dota2 等全球赛事，生成 esports poster、team edit、championship edit 类关键词。
  - 本地事件日历继续作为兜底，覆盖 Father’s Day、July 4 / America250 等确定节点。

## Scoring & Filtering
- 即时热点评分：
  - TikTok Creative Center 权重最高。
  - Google Trends 负责发现全网爆发事件。
  - 最近 72h Discovery 反哺负责保留已经被 TikTok Discovery 验证过的高频素材方向。
  - 多来源命中同一关键词时合并来源并加权。
  - 过滤纯新闻、比分讨论、政治、战争、八卦、IP 搬运、擦边、低广告复用价值内容。

- 预热事件评分：
  - 沿用当前生命周期：T-30 入池、T-14 加权、T-7 到 T+2 可进入最终 20 词。
  - 节日、体育、电竞事件统一转换成 `eventContext`，包含 source、eventName、eventDate、daysToEvent、countries、sport/game、sourceUrl。
  - 每个事件最多 3 个词，避免单一事件占满预热层。

- 最终候选 metadata：
  - `source`: `tiktok_creative_center | google_trends | recent_discovery_history | nager_date | thesportsdb | liquipedia | event_calendar`
  - `externalSource`
  - `sourceUrl`
  - `rawTrend` 或 `eventContext`
  - `scoreDetails`
  - `fitType`: `product | ad_material | both`

## Test Plan
- 单元测试：
  - mock TikTok Creative Center/Google Trends 响应，验证 hot 层生成可搜索素材词。
  - mock 最近 72h Discovery artifact，验证 hashtags/sourceQuery/searchQuery/标题正文可反哺 hot 层。
  - mock Nager.Date/TheSportsDB/Liquipedia 响应，验证 preheat 层生成事件词和 `eventContext`。
  - 外部源失败、超时、空响应时不阻塞，fallback 仍补足 5/10/5。
  - 风险词和纯新闻词被过滤。
  - 同一关键词跨来源去重，并保留多来源 metadata。
  - allocation 总和仍为默认 1150。

- 集成回归：
  - `--stage keywords` 写出外部源 artifact 和带来源 metadata 的 `04_search_plan.json`。
  - `--stage search/details/filter/report --resume` 兼容旧 artifact。
  - 不修改飞书表、本地历史 Discovery artifact、历史反馈文件。
  - 运行 `python -m py_compile scripts/tiktok_keyword_discovery.py` 和完整 unittest。

## Assumptions
- 第一版外部源默认只影响 Discovery 关键词生成，不直接抓取素材详情。
- 最近 72h Discovery 反哺保持本地读取，不调用外部 API。
- 不引入新的付费默认依赖；TheSportsDB/Liquipedia 如需 key 或访问限制，用 env 配置并默认可关闭。
- TikTok Creative Center 页面结构可能变化，因此适配器失败时只降级，不让每日 Discovery 失败。
