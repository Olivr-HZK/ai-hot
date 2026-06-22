# INS 高质量素材驱动的手动搜索 / 抓取 / 审核工作流

## Summary

- 该流程只作为手动工具使用，不接入 `run_pipeline.py`、cron 或日常推送。
- 工作流：读取飞书历史高质量 Instagram 素材 -> 提取英文搜索词 -> 更新本地搜索词池 -> 使用本地 Instagram cookie 长时间搜索 -> 抓取候选 -> 进入本项目 INS 审核链路。
- 默认只写本地报告，不写飞书多维表格，不发送飞书推送，不覆盖 `hotspots_ins.json` / `hotspots.json`。

## 搜索词池

- 持久搜索词池路径默认是 `skill_runs/instagram_keyword_discovery/keyword_pool.json`。
- 每次从高质量素材中新学到的搜索词会写入词池；已存在的词只更新学习次数和运行记录。
- 默认会搜索整个 active 词池，适合无 API 成本的长时间手动搜索。
- 可用 `--max-pool-terms` 限制本次搜索的池内词数量；`0` 表示搜索全部 active 词。
- 可用 `--pool-only` 只使用已有词池，不重新读取飞书、不重新提词。
- 可用 `--shuffle-pool` 在限制数量时随机抽取靠前词，适合多轮轮换搜索。

## 常用命令

```powershell
python scripts\manual\ins_keyword_discovery.py --lookback-days 60 --max-seeds 20 --max-search-terms 30
python scripts\manual\ins_keyword_discovery.py --pool-only
python scripts\manual\ins_keyword_discovery.py --pool-only --max-pool-terms 50
python scripts\manual\ins_keyword_discovery.py --pool-only --shuffle-pool --max-pool-terms 50
```

## 配置

```env
INS_MANUAL_ACCOUNT_COOKIES=www.instagram.com_cookies.txt
INS_MANUAL_SEARCH_HEADLESS=true
INS_MANUAL_MAX_LINKS_PER_QUERY=40
INS_MANUAL_MAX_SCROLLS=12
INS_MANUAL_SEARCH_DELAY_SECONDS=1
INS_MANUAL_ALLOW_RAPIDAPI=false
INS_MANUAL_REVIEW_MODEL=qwen/qwen3.7-max
INS_MANUAL_KEYWORD_POOL_PATH=skill_runs/instagram_keyword_discovery/keyword_pool.json
INS_MANUAL_MAX_POOL_TERMS=0
INS_MANUAL_SHUFFLE_POOL=false
```

## 高质量种子定义

- 平台字段必须是 `Instagram`。
- 只读取新反馈字段：`采纳意愿`、`原因`。
- `采纳意愿=3星` 或等价文本 `高` 的素材进入种子池。
- `采纳意愿=1星/2星` 或未标记素材不作为种子。
- 旧字段 `UA采纳意愿`、`产品采纳意愿`、`浩鹏意愿`、`UA原因`、`产品原因`、`浩鹏原因` 不再读取。

## 审核链路

- 抓取后先规范化、去重，并做互动门槛筛选；默认 `likes >= 500` 且 `comments >= 10`。
- 通过互动门槛的候选进入本项目 INS 审核：安全审核、产品适配、产品手册模型审核、UA 材料审核、视觉去重、历史反馈硬过滤。
- 所有通过项在本地报告中统一标记 `pushObject=ALL`。
- 通过项与拒绝项都会写入本地报告，便于人工复盘。

## 输出

- `skill_runs/instagram_keyword_discovery/latest.json`
- `skill_runs/instagram_keyword_discovery/keyword_pool.json`
- `skill_runs/instagram_keyword_discovery/runs/<runId>/seeds.json`
- `skill_runs/instagram_keyword_discovery/runs/<runId>/keywords.json`
- `skill_runs/instagram_keyword_discovery/runs/<runId>/raw_candidates.json`
- `skill_runs/instagram_keyword_discovery/runs/<runId>/engagement_passed.json`
- `skill_runs/instagram_keyword_discovery/runs/<runId>/approved.json`
- `skill_runs/instagram_keyword_discovery/runs/<runId>/rejected.json`
- `skill_runs/instagram_keyword_discovery/runs/<runId>/report.json`

## Daily integration

- From 2026-06-05 this workflow is also used by the daily scheduler.
- The former 00:01 scheduled keyword-discovery stage is disabled by default. `scripts/cron_ins_keyword_discovery.sh` and `scripts/scheduled_ins_keyword_discovery.ps1` only run when `INS_KEYWORD_DISCOVERY_DAILY_ENABLED=true`.
- Keyword discovery writes only local files under `skill_runs/instagram_keyword_discovery/`; it does not write Feishu records, send Feishu pushes, or overwrite canonical hotspot files.
- The 07:00 main pipeline does not merge keyword-discovery results by default. Set both `INS_KEYWORD_DISCOVERY_DAILY_ENABLED=true` and `INS_KEYWORD_DISCOVERY_MERGE_ENABLED=true` to opt back into merging today's approved report.
- Missing, stale, damaged, or still-running discovery reports are treated as warnings. TikTok, X, and the regular Instagram pipeline continue.
- Approved discovery items are normalized to `pushObject=ALL` and compete with all other final items under the daily total cap.
