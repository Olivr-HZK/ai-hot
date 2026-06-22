# 社媒热点筛选与推送项目说明文档

更新日期：2026-05-18

## 1. 项目概览

本项目用于从 TikTok 和 X 抓取社媒热点素材，经过质量过滤、反馈规则调节、图片/视频权重排序、X 图片安全筛选、多模态视觉去重、AI 简介生成、产品适配判断后，将结果写入飞书多维表格并推送飞书日报。

当前项目主要服务 3 个 AI 产品：

- Deep Think - AI Seek Chatbot：只服务 UA 需求，不输出产品侧需求。
- AI Photo Enhancer - Evoke：服务 UA 和产品需求。
- AI Video Generator - Toki：服务 UA 和产品需求，是产品侧需求的主目标，产品侧素材中 Toki 目标占比应尽量达到 70% 以上。

本项目的两个核心目标：

- UA 侧：及时发现可作为广告素材或广告创意参考的热点。
- 产品侧：发现可沉淀为 AI 产品新功能、模板、玩法或交互方向的热点。

产品素材需求的详细定义见：

- `references/product_material_requirements.md`

## 2. 目录结构

```text
.
├── run_pipeline.py                         # 日常流程总入口
├── requirements.txt                        # Python 依赖
├── .env.example                            # 环境变量模板
├── README.md                               # 本说明文档
├── references/
│   ├── product_material_requirements.md    # 三个产品的素材需求文档
│   └── tiktok_feedback_optimization_rules.json
│                                           # 反馈优化后的筛选/排序规则
├── scripts/
│   ├── phase1_scrape.py                    # TikTok 抓取、过滤、排序入口
│   ├── phase1_scrape_x.py                  # X 抓取、过滤、排序入口
│   ├── feishu_push.py                      # 飞书卡片推送和多维表格写入
│   ├── feedback_rules.py                   # 规则加载、校验、评分和过滤
│   ├── product_targeting.py                # product_v2 产品适配逻辑
│   ├── audience_targeting.py               # UA/产品定向推送逻辑
│   ├── ua_geo_targeting.py                 # UA 国家定向素材逻辑
│   ├── x_safety_review.py                  # X 图片安全筛选
│   ├── visual_dedupe.py                    # 多模态视觉去重
│   ├── comment_enrichment.py               # 评论读取与 topComments 填充
│   └── ai_intro.py                         # AI 热点简介生成
├── feedback_loop/
│   ├── optimizer.py                        # 读取飞书反馈并更新规则
│   ├── feishu_feedback.py                  # 飞书反馈读取
│   └── experiment_report.py                # legacy/product_v2 灰度效果报告
├── trend-scrap/
│   ├── tiktok-scraper/                     # TikTok Node 抓取器
│   └── x-scraper/                          # X Node 抓取器
├── skill_runs/                             # 本地运行产物
└── x_history_eval/                         # 历史评估和回放产物
```

## 3. 日常流程

主入口是 `run_pipeline.py`。默认流程分为 3 个阶段：

1. Stage 0：读取飞书反馈并优化规则。
2. Stage 1：抓取 TikTok/X，进行过滤、排序、去重和简介生成。
3. Stage 2：写入飞书多维表格并推送飞书日报卡片。

完整运行：

```powershell
python run_pipeline.py --platforms tiktok,x
```

只跑 TikTok：

```powershell
python run_pipeline.py --platforms tiktok
```

只跑 X：

```powershell
python run_pipeline.py --platforms x
```

复用已有抓取结果，不重新抓取：

```powershell
python run_pipeline.py --platforms tiktok,x --skip-scrape
```

只生成结果，不写飞书、不推送：

```powershell
python run_pipeline.py --platforms tiktok,x --skip-feishu
```

构造飞书 payload 和写表数据，但不真正发送：

```powershell
python run_pipeline.py --platforms tiktok,x --dry-run-feishu
```

跳过反馈优化：

```powershell
python run_pipeline.py --platforms tiktok,x --skip-feedback
```

## 4. 日期与灰度变体

项目支持新旧筛选逻辑隔离：

- `legacy`：老逻辑，保持原有筛选路径。
- `product_v2`：基于三产品需求文档的新逻辑。
- `auto`：自动模式，偶数日使用 `legacy`，奇数日使用 `product_v2`。

默认使用 `auto`。运行时会根据 `TARGET_DATE` 或当前日期判断。

指定变体：

```powershell
python run_pipeline.py --platforms tiktok,x --variant legacy
python run_pipeline.py --platforms tiktok,x --variant product_v2
python run_pipeline.py --platforms tiktok,x --variant auto
```

也可以通过环境变量指定：

```powershell
$env:PIPELINE_VARIANT="product_v2"
python run_pipeline.py --platforms tiktok,x
```

指定目标日期：

```powershell
$env:TARGET_DATE="2026-05-18"
python run_pipeline.py --platforms tiktok,x
```

飞书写表时会在“热点简介”末尾追加逻辑标识：

```text
[logic: legacy]
[logic: product_v2]
```

该标识用于后续反馈回溯，不新增飞书字段。

## 5. 平台策略

### 5.1 TikTok

TikTok 主要用于发现视频类热点素材，尤其服务 Toki 的 photo-to-video、AI action figure、AI emote、AI transform、AI dance 等方向。

当前素材类型权重：

- 视频：`1.00`
- 图片：`0.50`
- 图文/混合：`0.75`
- 未知：`1.00`

TikTok 搜索词已压缩为不超过 15 个，优先保留真人、人像、照片/视频变换、情绪怀旧、情侣/家庭、模板复用相关关键词。

### 5.2 X

X 主要用于发现图片、图文、prompt 和工作流相关素材。图片内容不局限于 AI 生成，用户拍摄的真人相关图片也可以进入候选，例如艺术写真、风格化照片、时尚大片、节日照片、创意照片。

当前素材类型权重：

- 图片：`1.20`
- 视频：`1.00`
- 图文/混合：`1.10`
- 未知：`0.90`

X 图片和图文候选必须经过安全筛选，过滤色情、擦边、AI 美女诱导、二次元软色情、成人向视觉内容等风险素材。

## 6. 筛选与排序逻辑

整体处理顺序大致如下：

1. 抓取平台原始数据。
2. 命中基础 include 关键词或 UA 国家定向条件。
3. 排除反馈规则中的硬排除内容。
4. X 额外执行图片相关性判断。
5. 按时间窗口过滤。
6. 选取 UA 国家定向候选。
7. 按基础质量阈值过滤。
8. 按目标日期过滤。
9. 归一化并按热度分排序。
10. X 图片/图文执行安全筛选。
11. 读取候选评论并写入本地 `topComments`。
12. 执行多模态视觉去重。
13. 生成 AI 热点简介。
14. 标记 `pipelineVariant`。
15. `product_v2` 下执行产品适配。
16. 执行 UA/产品定向推送逻辑。
17. 合并 TikTok/X 结果，并限制 UA 国家定向数量。
18. 写入本地 JSON、飞书多维表格和飞书日报卡片。

核心规则文件：

```text
references/tiktok_feedback_optimization_rules.json
```

主要规则块：

- `scrape`：TikTok 搜索词和抓取数量。
- `x_scrape`：X 搜索词和抓取数量。
- `quality_thresholds`：基础质量阈值。
- `media_type_weights`：平台图片/视频权重。
- `filters`：include/exclude 关键词与硬排除组。
- `x_photo_relevance`：X 图片真人相关性判断。
- `ua_geo_targeting`：UA 国家定向逻辑。
- `audience_targeting`：UA/产品定向学习结果。
- `product_targeting`：三产品适配逻辑。
- `analysis_prompt`：AI 简介和分析提示词。
- `learning_summary`：反馈优化总结。

## 7. 质量阈值

当前基础质量规则包括：

- 评论数门槛：`commentCount >= 20`。
- 低评论率降权：按评论数和播放量/浏览量计算评论率。
- 发布时间窗口：默认最近 168 小时内。
- 视频时长限制：默认最长 30 秒。
- 点赞阈值：按发布时间分段判断。

低评论内容不新增飞书字段，只通过现有数据进行过滤或降权。

## 8. 硬排除与降权

硬排除方向：

- 色情、擦边、软色情。
- AI 美女诱导图。
- 二次元软色情。
- 成人向视觉内容。
- 低质量换脸。
- 纯 AI 新闻、融资、公司动态、模型发布、硬件资讯。
- 股票、加密货币、Web3 项目宣传。
- 政治、战争、监管新闻。
- 无法泛化的明星路透。

降权方向：

- 卡通人物、粘土人、水果人、拟人动物。
- 宠物跳舞，除非能迁移为 Toki 宠物视频模板且评论质量高。
- 纯教程但结果弱。
- 近期重复模板。
- 评论率低但评论数达到最低门槛的内容。

## 9. 多模态视觉去重

视觉去重在质量过滤和初步排序后、AI 简介生成前执行。

目标：

- 识别同类视觉玩法重复。
- 减少复古海报、雨夜情侣、变装换装、美妆发型、生日成长对比、贴纸/迷你人偶、BGM 舞蹈/IP 加成等重复素材。
- 与当日候选和近 15 天历史热点比对。

本地 JSON 会写入：

- `visualDedupe.materialType`
- `visualDedupe.subjectType`
- `visualDedupe.signature`
- `visualDedupe.duplicateGroupKey`
- `visualDedupe.isDuplicate`
- `visualDedupe.duplicateReason`
- `visualDedupe.representativeScore`

不新增飞书字段。

默认使用 OpenRouter 多模态模型，并排除 OpenAI/Claude/Gemini/Google 系模型。

## 10. 评论读取

项目支持读取候选内容的评论正文，并写入本地 JSON：

```json
{
  "topComments": ["comment 1", "comment 2"]
}
```

用途：

- 帮助判断素材是否有真实用户需求。
- 后续可用于“有效评论”判断。
- 飞书日报折叠卡片可展示前 3 条有效评论摘要。

注意：

- 不新增飞书多维表字段。
- 评论接口失败、无权限或限流时不阻断主流程，只记录 warning 并返回空数组。

## 11. 国家定向素材

项目仍会在本地记录面向美国、加拿大、澳大利亚、新西兰、欧洲等国家或地区的定向信号。

当前规则：

- 国家定向信号只作为审核与分析参考，不再单独占用推送名额。
- 飞书“推送对象”字段固定为 `ALL`。
- 必须通过基础筛选逻辑，不能选入已被规则否决的垃圾信息。

相关本地字段：

- `uaGeoTargeting`
- `pushObject: "ALL"`

规则位置：

```text
references/tiktok_feedback_optimization_rules.json -> ua_geo_targeting
```

## 12. 产品适配逻辑

`product_v2` 变体会启用 `scripts/product_targeting.py`。

### 12.1 Deep Think

只允许进入 UA，不允许进入产品侧推送。

适合方向：

- 多模型对比。
- 数学解题。
- 写作、邮件、简历、脚本。
- AI 占卜、星座、塔罗。
- AI 图片生成/编辑的广告演示。

### 12.2 Evoke

可进入 UA、产品或 ALL。

适合方向：

- 老照片修复。
- 模糊照片变清晰。
- 黑白照片上色。
- 划痕、皱纹、破损照片修复。
- AI portrait。
- 旧照转视频。

### 12.3 Toki

可进入 UA、产品或 ALL。产品侧优先级最高。

适合方向：

- photo-to-video。
- AI action figure / AI figurine。
- Labubu / 公仔化 / 手办化。
- AI emote / face animation。
- AI transform / AI magic。
- AI dance。
- AI hug / couple / pet animation。

在 `product_v2` 中，产品侧候选会尽量保证 Toki 占比达到 70% 以上。若 Toki 候选不足，不强塞低质量素材，只记录 warning。

## 13. 飞书写入约束

当前写入字段包括：

- 推送日期
- 热点简介
- 热点平台
- 热点链接
- 播放量
- 点赞数
- 评论数
- 发布天数
- 热度评分
- 推送对象
- 自动prompt获取

只读反馈字段包括：

- 采纳意愿
- 原因

旧反馈字段不删除，但程序不再读取：

- UA采纳意愿
- UA原因
- 产品采纳意愿
- 产品原因
- 浩鹏意愿
- 浩鹏原因

必须使用已有选项，不要新建选项。

“热点平台”允许值：

- `TikTok`
- `X`

“推送对象”固定写入：

- `ALL`

历史上曾错误创建过 `AII`、小写 `x`、小写 `tiktok` 等选项。代码已做规范化映射，后续不要再写入这些错误选项。

## 14. 反馈学习规则

反馈优化脚本：

```powershell
python feedback_loop/optimizer.py
```

核心反馈处理：

- `采纳意愿=1星` 计为否决素材。
- `采纳意愿=2星` 计为可用素材。
- `采纳意愿=3星` 计为高质量素材。
- `原因` 是唯一反馈原因字段。

反馈优化会更新规则文件，但不改变飞书表结构。

## 15. 灰度效果评估

灰度报告脚本：

```powershell
python feedback_loop/experiment_report.py --days 14
```

干运行查看：

```powershell
python feedback_loop/experiment_report.py --days 14 --dry-run
```

输出目录：

```text
skill_runs/experiments/
```

统计指标：

- UA 高采纳率。
- UA 低/否率。
- 产品高采纳率。
- 产品低/否/无率。
- 高质量素材数。
- 高质量素材率。
- 低质素材数。
- 低质素材率。
- 有效反馈数。

当某个变体反馈量不足时，报告会标记为 `insufficient_data`，不直接判断胜负。

## 16. 本地运行产物

常见输出文件：

```text
skill_runs/hotspots.json              # TikTok/X 合并后的最终热点
skill_runs/hotspots_tiktok.json       # TikTok 阶段输出
skill_runs/hotspots_x.json            # X 阶段输出
skill_runs/experiments/               # 灰度报告输出
```

平台抓取器产物：

```text
trend-scrap/tiktok-scraper/data/filtered-result.json
trend-scrap/x-scraper/data/filtered-result.json
```

注意：`filtered-result.json` 会被阶段脚本覆盖为过滤后的最终结果。需要保留原始抓取数据时，应确认抓取器是否另有 raw 文件或先复制备份。

## 17. 环境变量

请从 `.env.example` 复制为 `.env` 并填写真实值。

飞书：

- `FEISHU_WEBHOOK`
- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `FEISHU_CHAT_ID`
- `FEISHU_BITABLE_URL`
- `BITABLE_APP_TOKEN`
- `BITABLE_TABLE_ID`

TikTok 抓取：

- `APIFY_TOKEN`
- `APIFY_TOKEN_POOL`
- `APIFY_TIKTOK_ACTOR_ID`
- `RAPIDAPI_TIKTOK_KEY`
- `RAPIDAPI_TIKTOK_HOST`
- `RAPIDAPI_TIKTOK_SEARCH_PATH`
- `SCRAPER_FORCE_RAPIDAPI`

X 抓取：

- `X_RAPIDAPI_KEY`
- `X_RAPIDAPI_HOST`
- `X_SEARCH_COUNT`
- `X_PAGES_PER_TERM`
- `X_MIN_FILTERED_PER_TERM`
- `X_MAX_FILTERED_PER_TERM`
- `X_MAX_HOURS_AGO`
- `X_MAX_VIDEO_DURATION_SECONDS`
- `X_REPLIES_ENDPOINT`
- `X_REPLIES_ID_PARAM`
- `X_REPLIES_COUNT_PARAM`

AI 和模型：

- `OPENAI_API_KEY`
- `OPENAI_FEEDBACK_MODEL`
- `OPENROUTER_API_KEY`
- `OPENROUTER_MODEL`
- `VISUAL_DEDUPE_MODEL`
- `VISUAL_DEDUPE_HISTORY_DAYS`
- `VISUAL_DEDUPE_DISABLE`
- `X_SAFETY_REVIEW_MODEL`
- `X_SAFETY_REVIEW_DISABLE`
- `INTRO_ANALYSIS_MODEL`
- `INTRO_ANALYSIS_TIMEOUT_SECONDS`
- `FEEDBACK_DISABLE_AI`

运行控制：

- `PIPELINE_PLATFORMS`
- `PIPELINE_VARIANT`
- `TARGET_DATE`
- `FEISHU_DRY_RUN`
- `TOP_COMMENTS_LIMIT`

## 18. 数据源优先级与费用注意

TikTok 日常流程优先使用 Apify。当 Apify 所有账号额度耗尽后，再使用 RapidAPI。

X 当前主要使用 RapidAPI。

注意：

- 全量真实抓取会产生外部 API 请求和费用。
- 需要测试筛选逻辑时，优先使用 `--skip-scrape` 复用本地已抓取数据。
- 需要验证飞书 payload 时，优先使用 `--dry-run-feishu`。

## 19. 常用维护命令

单独处理 TikTok 已有数据：

```powershell
python scripts/phase1_scrape.py --skip-scrape --output skill_runs/hotspots_tiktok.json
```

单独处理 X 已有数据：

```powershell
python scripts/phase1_scrape_x.py --skip-scrape --output skill_runs/hotspots_x.json
```

只写入或推送已有热点文件：

```powershell
python scripts/feishu_push.py --hotspots skill_runs/hotspots.json
```

飞书推送干运行：

```powershell
python scripts/feishu_push.py --hotspots skill_runs/hotspots.json --dry-run
```

验证 Python 关键模块可导入：

```powershell
$env:PYTHONDONTWRITEBYTECODE="1"
python -B -c "import sys; sys.path.insert(0, 'scripts'); import feedback_rules, product_targeting, ua_geo_targeting, visual_dedupe, x_safety_review"
```

验证 Node 抓取器语法：

```powershell
node --check trend-scrap\tiktok-scraper\src\scraper.js
node --check trend-scrap\x-scraper\src\scraper.js
```

## 20. 常见问题

### 20.1 TikTok 抓取失败

可能原因：

- Apify token 额度耗尽。
- RapidAPI key 额度耗尽或接口限流。
- Node 未安装或不在 PATH。
- 抓取器入口文件不存在。

处理方式：

- 检查 `.env` 中 Apify 和 RapidAPI 配置。
- 检查 `SCRAPER_FORCE_RAPIDAPI` 是否被强制开启。
- 先用 `--skip-scrape` 验证后续筛选和飞书流程是否正常。

### 20.2 X 结果质量差

优先检查：

- `x_scrape.search_queries` 是否偏离真人图片/写真/风格化照片方向。
- `x_photo_relevance` 是否命中过多无关内容。
- `x_safety_review` 是否被关闭。
- 是否有低评论内容绕过了质量阈值。

### 20.3 飞书出现新选项

飞书字段只能使用既有选项：

- 热点平台：`TikTok`、`X`、`Instagram`
- 推送对象：固定写入 `ALL`

如果出现 `AII`、`x`、`tiktok`、`ins` 等新选项，应检查 `scripts/feishu_push.py` 中的平台标准化映射，并在飞书中删除错误选项。

### 20.4 流程卡住

常见卡点：

- Apify 或 RapidAPI 网络请求长时间无响应。
- 评论接口读取超时。
- OpenRouter 多模态模型响应慢。
- 飞书接口限流或网络不可达。

排查建议：

- 查看终端当前阶段日志。
- 临时关闭昂贵阶段，例如设置 `VISUAL_DEDUPE_DISABLE=true` 或 `X_SAFETY_REVIEW_DISABLE=true`。
- 使用 `--skip-scrape` 定位是否为抓取阶段问题。
- 使用 `--dry-run-feishu` 定位是否为飞书写入问题。

## 21. 维护原则

- 飞书反馈后续只读取 `采纳意愿`、`原因`。
- 不创建新的飞书单选选项，推送对象固定使用 `ALL`。
- 新逻辑优先写入本地 JSON 字段，等灰度验证有效后再考虑稳定化。
- 筛选规则应围绕 Evoke / Toki / Kavi / Avatar 维护，不再为已移除产品做适配。
- TikTok 以视频素材为主，X 以图片/图文素材为主。
- X 图片必须额外进行安全筛选。
- 国家定向信号不再单独占用推送名额，但必须通过筛选逻辑。
- 反馈中 1 星视为否决，2 星视为可用，3 星视为高质量。
- 对重复素材先保留本地诊断信息，不写入新的飞书字段。
