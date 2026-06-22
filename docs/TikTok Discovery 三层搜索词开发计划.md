# TikTok Discovery 三层搜索词开发计划

## Summary
- 将 TikTok Discovery 搜索词升级为三层：`5 常青产品词 + 10 即时热点词 + 5 预热事件词`。
- 默认每日活跃搜索词 20 个，默认目标抓取量 `1150`：常青 `5*45`、即时 `10*70`、预热 `5*45`。
- 只扩大 TikTok Discovery 产量，不扩大主项目 TikTok 外部 API 抓取；除 OpenRouter 可选参与选词/复审外，不引入新增付费外部 API。
- 即时热点词不要求 AI 相关，只要高热、可复用、适合广告投放或产品素材参考，就可进入。

## Key Changes
- 新增 Discovery 专用分层关键词配置，独立于主项目 `scrape.search_queries` 的 10 词限制：
  - 层级数量：`evergreen=5`、`hot=10`、`preheat=5`。
  - 层级配额：`evergreen=45`、`hot=70`、`preheat=45`。
  - 默认国家池：`US`、`Europe(UK/DE/FR/ES/IT)`、`Mexico`、`Brazil`、`Australia`、`India`。
- 常青产品词每周优化：
  - 来源：产品文档、产品定位、历史 Discovery 结果、飞书反馈。
  - 默认兜底词：`photo to video ai`、`ai face animation`、`before after photo`、`ai avatar puzzle`、`ai action figure`。
  - 用 30 日反馈和 Discovery 产出表现排序，选 5 个；低样本时保证 Toki/Kavi/Evoke/Avatar 基本覆盖。
- 即时热点词每日优化：
  - 来源：当前事件种子、TikTok/Creative Center 网页趋势、最近 24-72 小时 Discovery 结果中的高频 hashtag/题材、OpenRouter 可选归纳。
  - 不设 AI 硬门槛；通过条件改为 `产品适配` 或 `广告素材适配` 二选一。
  - 广告素材适配包括：高热人物动作、情绪表达、庆祝姿势、运动员/真人海报风格、球衣/服装/身份转变、家庭/节日场景、热门转场结构、可复刻拍摄构图、强 CTA/评论需求。
  - 当前兜底热点词：`world cup poster`、`world cup jersey edit`、`football celebration edit`、`match entrance edit`、`world cup ai photo`、`football card edit`、`sports poster edit`、`jersey portrait edit`、`cinematic sports edit`、`training transformation`。
  - 过滤纯新闻、比分讨论、八卦、政治、战争、IP 搬运、擦边、低质粉丝剪辑、无广告复用价值内容。
- 预热事件词按本地事件日历生成：
  - 覆盖大型节日、国家纪念日、全球体育赛事、篮球赛事、电竞赛事。
  - 生命周期：`T-30` 进入候选，`T-14` 加权，`T-7 到 T+2` 可进入最终 20 词，过期后若仍高热则转即时热点层。
  - 当前兜底预热词：`father's day photo template`、`dad photo slideshow`、`family memory photo`、`4th of july photo template`、`fireworks portrait edit`。

## Interface / Data Flow
- 新增 Discovery 分层配置文件，建议为 `references/tiktok_discovery_keyword_layers.json`：
  - 包含层级数量、配额、国家池、事件日历、默认兜底词、风险过滤词、热点源开关、广告素材适配关键词。
- `scripts/tiktok_keyword_discovery.py` 增加分层选词入口：
  - 新增 CLI/env：`TIKTOK_KEYWORD_DISCOVERY_LAYERED_ENABLED=true`、`TIKTOK_KEYWORD_DISCOVERY_LAYER_CONFIG=<path>`。
  - 分层启用时，`04_search_plan.json` 由分层生成器产生；未启用时沿用现有主词 + feedback seed 行为。
- `04_search_plan.json` 每个词新增元数据：
  - `layer`：`evergreen | hot | preheat`
  - `allocation`
  - `score`
  - `scoreDetails`
  - `source`
  - `fitType`：`product | ad_material | both`
  - `eventContext`，仅预热/事件热点需要
- Discovery 过滤链路增加即时热点旁路：
  - 常青/预热仍优先走产品适配。
  - 即时热点允许走广告素材审核，即使正文不含 AI 关键词。
  - 最终推送仍需通过安全、去重、质量、反馈硬过滤。
- 主项目 TikTok API 抓取保持原状：
  - 不修改现有 `scrape.search_queries=10` 校验。
  - 不改变主项目外部 API 抓取量。
  - Discovery merge 继续沿用现有 `TIKTOK_KEYWORD_DISCOVERY_MERGE_ENABLED`。

## Test Plan
- 单元测试分层生成：
  - 启用分层后生成 20 个词，层级数量为 `5/10/5`。
  - 默认 allocation 总和为 `1150`。
  - 去重后不足时按同层候选补足，仍不足时用兜底词补足。
- 即时热点测试：
  - 非 AI 高热词如 `world cup jersey edit`、`football celebration edit` 可进入 `hot`。
  - 非 AI 但有广告复用价值的候选可标记 `fitType=ad_material`。
  - 纯比分、新闻、八卦、IP、政治、擦边词被过滤。
  - TikTok 趋势源失败时不阻塞，使用事件种子和历史 Discovery fallback。
- 常青/预热测试：
  - 常青词按反馈排序，无反馈时使用默认词。
  - 2026-06-12 下 Father’s Day、July 4 / America250 可进入预热候选。
  - 事件过期后自动衰减；仍高热时可转入 hot 层。
- 集成回归：
  - `--stage keywords` 写出带层级 metadata 的 `04_search_plan.json`。
  - `--stage search/details/filter/report --resume` 兼容旧 artifact。
  - `load_tiktok_keyword_discovery_items()` merge 行为不变。
  - `python -m py_compile scripts/tiktok_keyword_discovery.py feedback_loop/optimizer.py scripts/feedback_rules.py` 和相关 unittest 通过。

## Assumptions
- 第一版总量默认 `1150`，后续通过配置调到 1000-1400。
- 分层机制只服务 TikTok Discovery，不改变主项目 TikTok API 搜索词和 350 条主抓取逻辑。
- “相关”定义为：可服务 Evoke/Toki/Kavi/Avatar 产品素材，或可作为 UA 广告创意/素材结构/投放钩子参考。
- 事件日历第一版使用本地可维护配置，不依赖外部节假日 API。
- OpenRouter 只用于关键词归纳/复审，不对每条原始候选逐条调用。
