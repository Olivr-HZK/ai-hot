# TikTok 00:01 Cookie 搜索发现系统：全阶段本地留痕

## Summary
- 00:01 TikTok discovery 只用 `www.tiktok.com_cookies.txt` + Playwright 网页搜索，不调用 Apify、RapidAPI、SocialCrawl 或外部模型 API。
- 搜索词最多 `100` 个：主流程 10 个词置顶 + 近 7 天高质量 TikTok 帖每帖 5 个生成词，并参考本地产品文档筛选。
- 每词 allocation 固定 `50`，所有阶段产物都保存到本地 run 目录，支持按阶段重试、复盘和调试。
- 07:00 主流程只合并当天 `approved.json`，不等待未完成 discovery。

## Key Changes
- 新增 discovery run 目录：
  - 根目录：`skill_runs/tiktok_keyword_discovery/`
  - 单次运行：`runs/<runId>/`
  - 最新指针：`latest.json`
  - lock：`skill_runs/locks/tiktok_keyword_discovery.lock`
- 每个阶段都写本地文件：
  - `00_config.json`：运行参数、环境开关、cookie 文件路径、搜索上限、allocation、headless 设置，不包含 cookie 值。
  - `01_feedback_seeds.json`：近 7 天高质量 TikTok 反馈帖、热度、反馈原因、原始 URL。
  - `02_product_doc_snapshot.md/json`：本次读取的产品文档快照和提取出的正向/排除信号。
  - `03_keyword_candidates.json`：每个 seed 生成的 5 个词、产品命中依据、被过滤原因。
  - `04_search_plan.json`：最终最多 100 个搜索词、每词 allocation=50、主流程 10 词标记。
  - `05_search_links/<keyword_slug>.json`：每个词搜索页收集到的视频链接、滚动次数、页面状态、失败原因。
  - `06_detail_raw/<video_id>.json`：详情页抽取结果、DOM/JSON 来源、统计字段、页面状态；必要时保存截断 HTML 到 `06_detail_html/`。
  - `07_candidates.json`：标准化后的 TikTok 候选项，作为后续筛选输入。
  - `08_filtered.json`：通过现有 TikTok 筛选链后的候选。
  - `09_rejected.json`：每阶段 rejected 项和原因。
  - `10_approved.json`：最终 approved 项。
  - `report.json`：阶段耗时、数量漏斗、错误摘要、是否可合并。
- 支持阶段性重试：
  - `--run-id <id>` 复用指定 run 目录。
  - `--resume` 跳过已有成功阶段，从缺失或失败阶段继续。
  - `--stage keywords|search|details|filter|report` 只跑指定阶段及其必要后续。
  - 每个阶段读取前一阶段产物，不重新消耗已成功的搜索词或详情页。
- 主流程接入：
  - `run_pipeline.py` 新增 TikTok discovery 合并逻辑，仿照 INS discovery。
  - 仅当 `latest.json.status=success`、`generatedAt` 为当天、`approvedCount>0` 时读取 `10_approved.json`。
  - 合并项标记 `hotspotPlatform=TikTok`、`sourcePlatform=tiktok`、`captureSource=tiktok_keyword_discovery`、`pushObject=ALL`。

## Config
- `TIKTOK_KEYWORD_DISCOVERY_DAILY_ENABLED=false`
- `TIKTOK_KEYWORD_DISCOVERY_MERGE_ENABLED=false`
- `TIKTOK_KEYWORD_DISCOVERY_COOKIE_FILE=www.tiktok.com_cookies.txt`
- `TIKTOK_KEYWORD_DISCOVERY_PRODUCT_DOC_PATH=references/product_material_requirements.md`
- `TIKTOK_KEYWORD_DISCOVERY_ROOT=skill_runs/tiktok_keyword_discovery`
- `TIKTOK_KEYWORD_DISCOVERY_MAX_TERMS=100`
- `TIKTOK_KEYWORD_DISCOVERY_TERMS_PER_SEED=5`
- `TIKTOK_KEYWORD_DISCOVERY_ALLOCATION=50`
- `TIKTOK_KEYWORD_DISCOVERY_LOOKBACK_DAYS=7`
- `TIKTOK_KEYWORD_DISCOVERY_HEADLESS=true`
- `TIKTOK_KEYWORD_DISCOVERY_FAILS_PIPELINE=false`

## Test Plan
- 产物测试：模拟一次 run，确认每个阶段文件都生成，`latest.json` 指向最新 `report.json`。
- 重试测试：删除 `06_detail_raw` 中部分文件后 `--resume`，确认只补抓缺失详情，不重跑关键词和已完成搜索。
- 搜索词测试：主流程 10 词置顶保留，总词数最多 100，每帖生成 5 个候选词，产品文档排除词生效。
- 无 API 测试：确认 discovery 不启动 Node TikTok scraper，不读取 Apify/RapidAPI/SocialCrawl 配置，不请求相关域名。
- 合并测试：构造当天 approved，确认 07:00 合并、去重、受总上限控制；过期或失败 report 被跳过。

## Assumptions
- “所有阶段产物”包含可复盘的 JSON/报告/必要截断 HTML，但不保存或打印 cookie 内容。
- 产品文档来源为本地 `references/product_material_requirements.md`。
- 00:01 任务若未完成，07:00 主流程跳过该 run，只记录状态，不阻塞 TikTok/X/INS 常规流程。
