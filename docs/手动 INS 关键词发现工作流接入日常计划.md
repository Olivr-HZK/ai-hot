# 手动 INS 关键词发现工作流接入日常计划（历史方案，默认已关闭）

> 当前默认策略：关闭 00:01 INS 关键词发现自动流程，只保留 07:00 日常博主抓取。以下内容保留为历史设计记录；如需恢复，必须显式设置 `INS_KEYWORD_DISCOVERY_DAILY_ENABLED=true` 和 `INS_KEYWORD_DISCOVERY_MERGE_ENABLED=true`。

## Summary
- 将现有 INS 关键词发现/搜索/审核工作流升级为日常流程的一部分。
- 每天 `00:01` 自动运行 INS 关键词发现：读取高质量 INS 历史反馈、更新搜索词池、搜索全部 active 词、审核候选，并保存完整本地结果。
- 每天 `07:00` 主流程合并 TikTok / X / 常规 INS / INS 关键词发现通过项，统一 `pushObject=ALL`，受每日总上限 15 条限制，然后写入飞书并推送。
- 从明天 `2026-06-05` 开始默认启用。

## Key Changes
- 新增日常 INS 关键词发现入口：
  - 新增 cron/scheduler 包装脚本，例如 `scripts/cron_ins_keyword_discovery.sh` 和 Windows 对应 PowerShell。
  - 默认命令等价于运行现有 INS 工作流，但使用日常模式：
    - 回看历史高质量 INS 反馈生成/更新搜索词池。
    - 搜索全部 active pool：`max_pool_terms=0`。
    - 默认不启用 RapidAPI，只使用本地 Instagram cookie。
    - 输出继续落到 `skill_runs/instagram_keyword_discovery/`，包括 seeds、keywords、raw candidates、engagement_passed、approved、rejected、report。
- 合并进主流程：
  - `run_pipeline.py` 在合并平台结果时额外读取当天 `skill_runs/instagram_keyword_discovery/latest.json`。
  - 若 `latest.json.generatedAt` 是当天且 `approvedCount > 0`，读取其 `paths.approved` 并合并进最终热点池。
  - 对 URL 去重；重复时保留热度更高或已有主流程项。
  - 所有加入项统一标记 `hotspotPlatform=Instagram`、`sourcePlatform=ins`、`pushObject=ALL`。
  - 若 INS 关键词发现结果缺失、过期、JSON 损坏或仍在运行，只记录 warning，不阻塞 TikTok/X/常规 INS。
- 定时任务：
  - macOS cron 增加一条默认任务：`1 0 * * * /bin/bash scripts/cron_ins_keyword_discovery.sh`。
  - 保留现有 `0 7 * * 1-5 /bin/bash scripts/cron_daily_full.sh`。
  - Windows 注册脚本同步增加每日 `00:01` INS 关键词发现任务，保留工作日 `07:00` 主流程任务。
  - INS 关键词发现脚本使用 lock file，避免上一轮未结束时重复启动。
- 配置默认启用：
  - 新增配置：
    - `INS_KEYWORD_DISCOVERY_DAILY_ENABLED=true`
    - `INS_KEYWORD_DISCOVERY_DAILY_CRON=1 0 * * *`
    - `INS_KEYWORD_DISCOVERY_MERGE_ENABLED=true`
    - `INS_KEYWORD_DISCOVERY_REQUIRE_TODAY=true`
    - `INS_KEYWORD_DISCOVERY_FAILS_PIPELINE=false`
  - 继续沿用现有 INS 手动工作流配置：
    - `INS_MANUAL_KEYWORD_POOL_PATH`
    - `INS_MANUAL_ACCOUNT_COOKIES`
    - `INS_MANUAL_MAX_POOL_TERMS=0`
    - `INS_MANUAL_ALLOW_RAPIDAPI=false`

## Behavior
- `00:01` 阶段只负责 INS 关键词池搜索和审核，不写飞书、不推送。
- `07:00` 阶段负责统一合并、排序、总上限裁剪、写入飞书和推送。
- INS 关键词发现通过项和其他平台素材一起竞争每日总上限 15 条。
- 若 `00:01` 阶段失败，`07:00` 主流程继续运行，但监控 JSON 中记录 `insKeywordDiscovery.status=failed/stale/missing`。
- 若 `00:01` 阶段产出 0 条通过项，主流程正常继续。

## Test Plan
- 日常 INS 关键词发现：
  - 模拟运行日常入口，确认输出 `skill_runs/instagram_keyword_discovery/latest.json` 和 `runs/<runId>/approved.json`。
  - 确认 `writesFeishu=false`、`pushesFeishu=false`。
  - 确认 `max_pool_terms=0` 时搜索全部 active 词池。
- 主流程合并：
  - 构造当天 `latest.json + approved.json`，运行 `run_pipeline.py --skip-scrape --dry-run-feishu`，确认 approved 项进入最终 `skill_runs/hotspots.json`。
  - 构造过期 `latest.json`，确认主流程跳过并记录 warning。
  - 构造重复 URL，确认最终去重。
  - 构造 20 条总候选，确认最终最多 15 条且全部 `pushObject=ALL`。
- 定时任务：
  - 检查 macOS crontab 安装后同时存在 `00:01` INS 关键词发现和 `07:00` 主流程。
  - 检查 Windows 注册脚本存在两个任务，且 00:01 任务不写飞书。
- 回归：
  - 常规 INS `phase1_scrape_ins.py` 不被替换，仍正常运行。
  - TikTok / X 流程不受影响。
  - 飞书字段结构不新增，写表仍不写 `采纳意愿` / `原因`。

## Assumptions
- “每日 0:01”按每天自然日执行，不限工作日。
- “加入日常”表示通过项进入 07:00 主流程最终写表和推送。
- INS 关键词发现使用本地 cookie，不消耗 RapidAPI，除非后续显式开启 `--allow-rapidapi`。
- 如果 00:01 搜索全量 active 池运行超过 07:00，主流程跳过本轮未完成结果，不等待阻塞。
