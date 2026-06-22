# TikTok Discovery Stage1 反馈调节接入计划

## Summary
- 将 TikTok Discovery 阶段命名调整为：`stage0 -> stage1 -> stage2 -> stage3 -> stage4 -> stage5`。
- 原 5 个阶段映射为：
  - `stage0`: 搜索词生成
  - `stage2`: TikTok 搜索
  - `stage3`: 详情补全
  - `stage4`: 过滤审核
  - `stage5`: 报告输出
- 新增 `stage1`: 反馈调节，在 `stage0` 生成初始搜索词后，读取过去反馈并调整最终搜索计划。
- Stage1 只影响本次 Discovery run 的搜索计划，不回写飞书表、不修改本地历史 artifact、不改主项目 TikTok 抓取配置。

## Key Changes
- CLI stage 支持：
  - 新增 canonical stages：`stage0`、`stage1`、`stage2`、`stage3`、`stage4`、`stage5`、`all`。
  - 保留兼容别名：`keywords=stage0`、`search=stage2`、`details=stage3`、`filter=stage4`、`report=stage5`。
  - `all` 默认执行完整链路：`stage0 -> stage1 -> stage2 -> stage3 -> stage4 -> stage5`。

- Stage0 搜索词生成：
  - 保持现有分层逻辑：常青、即时热点、预热事件。
  - 写初始搜索计划：`04_search_plan_stage0.json`。
  - 同时保留外部热点 artifact：`02_external_hot_trends.json`、`02_external_preheat_events.json`。

- Stage1 反馈调节：
  - 读取最近 7 天反馈，默认沿用主流程 TikTok 关键词调节窗口。
  - 将反馈 URL 映射回历史 Discovery 素材的 `sourceQuery`、`searchQuery`、`planEntries`、`layer`、`keyword`。
  - 统计每个搜索词表现：反馈数、高质量数、可用数、低质/否决数、score。
  - 对 `stage0` 初始搜索计划做两类调整：
    - 重新排序/替换：每层保留数量不变，默认最多替换 `evergreen=1`、`hot=2`、`preheat=1` 个弱词。
    - 重新分配 allocation：保持层级总量不变，默认仍为 `evergreen=225`、`hot=700`、`preheat=225`，只在同层内部按反馈表现加权。
  - 写调节报告：`04_feedback_tuning.json`。
  - 写最终搜索计划：`04_search_plan.json`，供 `stage2` 使用。

- Stage2 到 Stage5：
  - `stage2` 只读取最终 `04_search_plan.json`。
  - `stage3`、`stage4`、`stage5` 逻辑保持不变。
  - report/latest 增加 stage1 摘要，包括是否启用、反馈窗口、匹配反馈数、替换词、allocation 调整。

## Feedback Tuning Rules
- 反馈评分沿用主流程 TikTok 关键词思想：
  - 高质量：`+2.0`
  - 中等可用：`+0.5`
  - 低质/否决：`-1.5`
  - 无反馈：中性权重 `1.0`
- 映射优先级：
  - URL 精确匹配历史 Discovery `07_candidates.json`、`08_filtered.json`、`10_approved.json`。
  - 匹配不到时，用反馈文本与关键词 token 做轻量兜底匹配。
- 替换规则：
  - 只在同层内替换，避免 hot 词挤占 evergreen/preheat 名额。
  - 不引入被风险词过滤、fitType 为 `none`、或已重复的关键词。
  - 低样本时只调整 allocation，不强制替换关键词。
- 配置新增：
  - `feedback_tuning.enabled`
  - `feedback_tuning.lookback_days`
  - `feedback_tuning.replace_counts`
  - `feedback_tuning.allocation_min_multiplier`
  - `feedback_tuning.allocation_max_multiplier`

## Test Plan
- 单元测试：
  - `stage0` 写出 `04_search_plan_stage0.json`。
  - `stage1` 读取 stage0 plan，写出 `04_feedback_tuning.json` 和最终 `04_search_plan.json`。
  - 高反馈关键词 allocation 上升，低质/否决关键词 allocation 下降。
  - 弱词只在同层内被替换，最终仍保持 `5/10/5`。
  - allocation 总和仍为 `1150`。
  - 反馈不足时不替换，只保留 stage0 plan 或轻量重排。
  - legacy stage alias 仍可用。

- 回归测试：
  - `--stage stage2 --resume` 兼容已有 `04_search_plan.json`。
  - 老 artifact 没有 `04_search_plan_stage0.json` 时，resume 仍能读取 `04_search_plan.json`。
  - `python -m py_compile scripts/tiktok_keyword_discovery.py feedback_loop/optimizer.py` 通过。
  - 完整 `python -m unittest discover tests` 通过。

## Assumptions
- Stage1 不调用 OpenRouter/OpenAI；第一版使用确定性反馈调节。
- Stage1 不修改 `references/tiktok_discovery_keyword_layers.json`，只修改当前 run 的最终搜索计划。
- Stage1 不回写飞书，也不改写历史 Discovery run。
- 主流程 TikTok 的 Stage 0 optimizer 保持原状；这里只给 Discovery 增加同类反馈调节阶段。
