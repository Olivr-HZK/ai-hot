# 每日流程平台隔离与 JSON 监控输出计划

## Summary
- 将 `run_pipeline.py` 改为平台并行隔离执行：TikTok、X、INS 互不阻塞。
- 单个平台失败或超时，只影响该平台；其它平台继续运行，最终合并并推送可用结果。
- 每次运行都输出稳定 JSON 结果文件，供外部监控程序读取。

## Key Changes
- 新增监控输出目录：`skill_runs/pipeline_monitor/`。
- 每次运行写入两类 JSON：
  - `skill_runs/pipeline_monitor/latest.json`：最新一次运行结果，监控程序优先读这个。
  - `skill_runs/pipeline_monitor/runs/<runId>.json`：历史归档，`runId` 使用 `yyyyMMdd_HHmmss`。
- JSON 使用原子写入：先写 `.tmp`，再替换正式文件，避免监控程序读到半截内容。
- 新增 `.env.example` 配置：
  - `PIPELINE_PARALLEL_PLATFORMS=true`
  - `PIPELINE_MAX_WORKERS=3`
  - `PIPELINE_PLATFORM_TIMEOUT_SECONDS=5400`
  - `PIPELINE_TIKTOK_TIMEOUT_SECONDS=7200`
  - `PIPELINE_X_TIMEOUT_SECONDS=3600`
  - `PIPELINE_INS_TIMEOUT_SECONDS=3600`
  - `PIPELINE_CONTINUE_ON_PLATFORM_FAILURE=true`
  - `PIPELINE_MONITOR_DIR=skill_runs/pipeline_monitor`

## JSON Output Schema
- 顶层字段固定为：
```json
{
  "schemaVersion": 1,
  "runId": "20260522_070000",
  "startedAt": "2026-05-22T07:00:00+08:00",
  "finishedAt": "2026-05-22T07:43:12+08:00",
  "status": "success | partial_success | failed",
  "variant": "legacy | product_v2",
  "platformsRequested": ["tiktok", "x", "ins"],
  "platformsSucceeded": ["x", "ins"],
  "platformsFailed": ["tiktok"],
  "hotspotsPath": "skill_runs/hotspots.json",
  "hotspotCount": 4,
  "skipFeishu": true,
  "feishuStatus": "skipped | success | failed",
  "error": "",
  "platformResults": []
}
```
- `platformResults` 每个平台一条：
```json
{
  "platform": "tiktok",
  "status": "success | failed | timeout | output_error",
  "exitCode": 0,
  "durationSeconds": 123.4,
  "timeoutSeconds": 7200,
  "outputPath": "skill_runs/hotspots_tiktok.json",
  "itemCount": 3,
  "logPath": "skill_runs/logs/platform_tiktok_20260522_070000.log",
  "error": ""
}
```

## Implementation Changes
- `run_pipeline.py`：
  - 用 `ThreadPoolExecutor` 并行运行各平台子进程。
  - 每个平台独立日志、独立超时、独立结果解析。
  - 超时后在 Windows 下用 `taskkill /PID <pid> /T /F` 清理整棵进程树。
  - 合并阶段只读取成功平台输出；失败平台写入 JSON 报告但不阻塞。
  - 用 `try/finally` 确保即使整体异常，也尽量写出 `latest.json` 和归档 JSON。
- 合并与推送：
  - 至少有 1 条热点：写入 `skill_runs/hotspots.json`，按原逻辑进入飞书阶段。
  - 没有任何可用热点：写 JSON 报告，跳过飞书，返回非 0。
  - `--skip-feishu`、`--dry-run-feishu`、`--skip-scrape` 保持原语义。
- 定时脚本：
  - `scripts/scheduled_daily_no_feishu.ps1` 和 `scripts/scheduled_feishu_stage.ps1` 不改调用方式。
  - 日常流程关闭状态不变；本计划只优化代码行为，不自动恢复 Windows 定时任务。

## Test Plan
- 模拟 TikTok 超时：X/INS 正常完成，`latest.json` 显示 `partial_success`，TikTok 为 `timeout`。
- 模拟 X 返回非 0：TikTok/INS 继续，最终合并可用结果。
- 模拟某平台 JSON 输出损坏：该平台为 `output_error`，其它平台继续合并。
- 模拟全平台失败：`status=failed`，`hotspotCount=0`，不推送飞书。
- 正常三平台运行：`status=success`，三平台 itemCount 正确，`hotspots.json` 正常生成。
- 验证 JSON 原子写入：运行过程中不出现半成品 `latest.json`。
- 验证 `--skip-feishu`：报告中 `skipFeishu=true`、`feishuStatus=skipped`。

## Assumptions
- 监控程序读取 `skill_runs/pipeline_monitor/latest.json` 即可获得最新运行状态。
- 历史运行结果保留在 `skill_runs/pipeline_monitor/runs/`，暂不自动清理。
- 默认策略为：失败平台不阻塞，推送其它平台可用结果。
- 不改变各平台内部筛选、审核、打分和飞书字段结构。
