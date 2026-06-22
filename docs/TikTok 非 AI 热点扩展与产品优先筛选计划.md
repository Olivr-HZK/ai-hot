# TikTok 非 AI 热点扩展与产品优先筛选计划（加入体育/影视真人素材）

## Summary
- TikTok 从当前 `8 AI + 2 非 AI` 调整为 `5 AI + 5 非 AI`，总关键词数仍固定 10。
- 新增 TikTok 热榜候选源：每天先抓 TikTok 热榜/趋势视频，再与关键词搜索结果合并去重。
- 非 AI 候选池扩展到三类：产品模板类、体育真人/特效类、热门电影/电视剧真人/特效类。
- 非 AI 候选仍必须服务 Evoke / Toki / Kavi / Avatar：先产品硬门槛；未硬命中但热度极高的，提交模型按产品手册复审。

## Key Changes
- TikTok 抓取配置调整：
  - `scrape.ai_search_count = 5`
  - `scrape.non_ai_search_count = 5`
  - `scrape.max_search_queries = 10`
  - `scrape.keyword_allocation_total = 350` 保持不变
  - 每个关键词 allocation 仍保持 `[15, 50]`
  - Stage0 关键词调优、周轮换、校验逻辑同步改为固定 `5/5` 配比。

- 非 AI 候选池扩展：
  - 产品模板类：`photo transition template`、`before after photo template`、`profile photo trend`、`portrait transition template`、`photo slideshow template`、`avatar puzzle challenge`。
  - 体育真人/特效类：运动员高光、球星庆祝动作、比赛入场、训练转场、球衣/海报风格、体育卡片、动作定格、赛场电影感镜头、运动员 before/after 变身。
  - 热门电影/电视剧真人/特效类：真人角色变身、影视感海报、角色卡片、剧照风格、片头/预告片风格、红毯/采访真人素材、电影感转场、角色身份升级。
  - 禁止词继续保留并加强：明星街拍/路透、纯 IP 复刻、擦边、纯 meme、政治新闻、crypto/Web3、硬件、普通摄影业务、低质 cosplay、无产品转化价值的追星内容。

- 热榜候选源：
  - 新增 `scrape.hot_feed.enabled = true`。
  - 使用 TikTok RapidAPI 热榜/趋势接口作为优先实现；接口不可用时 warning 后回退关键词搜索。
  - 默认热榜抓取量：`hot_feed.max_items = 100`，`max_pages = 1`。
  - 热榜结果写入 checkpoint，标记来源为 `hot_feed`，与关键词结果按 video id 去重。

- 非 AI 筛选逻辑：
  - 非 AI / 热榜候选不再被 `include_keywords=["ai"]` 直接挡掉。
  - 产品硬门槛直接通过：
    - Evoke：真人肖像、体育/影视海报感、before/after、增强修复、风格化头像/角色卡片。
    - Toki：运动动作、庆祝动作、电影感场景、角色变身、photo-to-video 可转化素材。
    - Kavi：真人短视频模板、体育高光、影视感身份升级、creator persona、特效转场。
    - Avatar：头像拼图、球迷头像、角色头像、社交挑战/分享机制。
  - 未过产品硬门槛但热度显著高的非 AI / 热榜素材进入模型复审。
  - 模型复审重点判断：是否能转为广告创意、模板库素材、prompt/workflow 参考，或 Evoke/Toki/Kavi/Avatar 的产品玩法参考。

- 推送对象规则：
  - 非 AI / 热榜素材若只适合产品侧，标记 `产品`。
  - 若同时适合 UA 投放参考，或命中 `uaGeoTargeting + Evoke/Toki/Kavi/Avatar`，标记 `ALL`。
  - 不新增飞书字段，只新增内部来源与审核记录字段。

## Implementation Changes
- Stage0：
  - TikTok 搜索词校验改为 `5 AI + 5 非 AI`。
  - 非 AI candidate pool 增加体育/影视方向，但 Stage0 不允许生成泛娱乐、追星、路透、擦边或纯 IP 依赖词。
  - 周轮换替换最差 3 个词后必须保持 `5/5` 配比。
  - allocation 总和仍为 `350`。

- TikTok scraper：
  - 新增可选热榜抓取函数。
  - 热榜抓取失败不阻塞关键词搜索。
  - 热榜与搜索结果统一 checkpoint、统一去重、统一输出到 `filtered-result.json`。

- TikTok phase1：
  - 增加 `non_ai_product_lane` 和 `hot_feed_lane`。
  - 对非 AI / 热榜候选先做产品硬门槛，再做高热模型复审。
  - 体育/影视素材必须具备真人主体、动作/身份/场景转换、模板复用、广告钩子或产品玩法价值；否则过滤。
  - 后续安全、评论、视觉去重、简介、反馈硬过滤、推送配额沿用现有逻辑。

## Test Plan
- 配置校验：
  - TikTok 10 个搜索词，5 AI + 5 非 AI。
  - allocation 总和 350，每词 15-50。
  - 周轮换后仍保持 5/5。

- 体育素材：
  - 运动员高光、庆祝动作、球衣海报、训练转场等高热素材，若可转化为 Toki/Kavi/Evoke 模板或广告创意，应进入审核。
  - 普通比赛新闻、比分讨论、球星八卦、低质搬运不通过。

- 影视素材：
  - 真人角色变身、电影感海报、预告片风格转场、剧照风格身份升级可进入审核。
  - 纯明星路透、纯 IP 截图、无转化价值追星内容、版权依赖过强内容不通过或降权。

- 热榜源：
  - 热榜接口成功时产生 `hot_feed` 来源候选。
  - 热榜接口失败时 TikTok 流程继续关键词搜索。
  - 热榜候选必须通过产品硬门槛或高热模型复审。

- 回归：
  - AI 素材原链路不变。
  - 飞书字段不变。
  - checkpoint / partial continue / RapidAPI fallback 不变。
  - `python -m py_compile` 与 `node --check` 通过。

## Assumptions
- 体育/影视内容只作为真人素材、动作素材、特效模板、广告创意参考，不为泛娱乐热度单独推送。
- 热门电影/电视剧素材需要避免纯 IP 复刻和版权依赖；可接受的是“风格/结构/玩法参考”，不是直接搬运角色或片段。
- 热榜抓取默认额外最多 100 条，不计入关键词 allocation 的 350 条。
