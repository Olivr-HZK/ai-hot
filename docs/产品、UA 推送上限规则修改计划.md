# 产品 / UA 推送上限规则修改计划

## Summary
- 在最终合并写入 `skill_runs/hotspots.json`、飞书写表、飞书推送之前，新增统一推送名额裁剪。
- `ALL` 同时占用产品侧和 UA 侧名额。
- `ALL` 若命中欧美国家定向信号，也计入 UA 国家定向素材每日上限。
- 不改变各平台抓取、筛选、评分、审核逻辑，只在最终输出阶段做跨平台推送配额控制。

## 之前已设定的推送规则
- 推送对象取值继续为：`产品`、`UA`、`ALL`。
- `ALL` 表示同一条内容同时适合产品侧和 UA 侧。
- Deep Think 只面向 UA，不作为产品侧推送。
- Evoke 和 Toki 同时支持产品侧与 UA 侧。
- Toki 在产品侧保持优先级，产品侧候选中 Toki 目标占比继续按现有 `toki_product_min_share=0.7` 执行。
- TikTok / X / INS 仍保留各自现有筛选链路。
- 反馈规则继续沿用：
  - `UA=低` 视为 UA 否决信号。
  - `产品=无` 视为产品否决信号。
  - `UA=高 + 产品=低/无` 学习为 UA 倾向。
  - `产品=高 + UA=低/否` 学习为产品倾向。
  - 无关、擦边、动漫、明星依赖、传统摄影业务等负反馈继续进入拒绝或降权。

## Key Changes
- 新增最终推送配额配置：
  - `push_caps.enabled = true`
  - `push_caps.product_side_daily_max = 10`
  - `push_caps.ua_side_daily_max = 10`
  - `push_caps.product_video_daily_max = 3`
  - `push_caps.ua_geo_daily_max = 3`
- 修改最终合并逻辑：
  - `产品` 计入产品侧。
  - `UA` 计入 UA 侧。
  - `ALL` 同时计入产品侧和 UA 侧。
  - 若加入某条内容会导致 `ALL+产品 > 10` 或 `ALL+UA > 10`，则跳过该条。
- 产品视频素材上限：
  - `产品` 或 `ALL` 中的视频 / 图生视频 / 视频模板 / mixed-video 素材，每天最多保留 3 条。
- UA 国家定向素材上限：
  - `UA` 中命中欧美国家定向的内容计入 `ua_geo_daily_max`。
  - `ALL` 中命中欧美国家定向的内容也计入 `ua_geo_daily_max`。
  - 只要内容命中现有 UA geo 国家信号，包括美国、加拿大、澳大利亚、新西兰、欧洲、英国、法国、德国等，就按 UA 国家定向素材统计。
  - 每天最多保留 3 条 UA 国家定向素材，跨平台合计，不是每个平台 3 条。
- 飞书字段不新增、不改名：
  - 表格和推送仍只使用现有字段。
  - 配额裁剪只影响最终进入飞书的结果数量。

## Implementation Notes
- 在 `run_pipeline.py` 的平台结果合并后、最终排序写出前新增 `apply_push_caps()`。
- 新增统一判断：
  - `has_product_side(item)`：`pushObject in ["产品", "ALL"]`
  - `has_ua_side(item)`：`pushObject in ["UA", "ALL"]`
  - `is_product_video(item)`：产品侧内容且媒体类型为视频或 mixed-video。
  - `is_ua_geo_counted(item)`：UA 侧内容，且已有 `uaGeoTargeting` 标记，或命中现有欧美国家定向关键词 / 地区信号。
- `ALL` 不再只按产品素材处理；它同时参与 UA 总量和 UA 国家定向数量统计。
- 被裁剪的内容只写日志或监控摘要，不自动改写为其他推送对象。

## Test Plan
- 构造 12 条 `产品` 内容，验证最终最多保留 10 条。
- 构造 12 条 `UA` 内容，验证最终最多保留 10 条。
- 构造 `ALL + 产品 + UA` 混合内容，验证：
  - `ALL+产品 <= 10`
  - `ALL+UA <= 10`
- 构造 5 条产品侧视频素材，验证最终最多保留 3 条。
- 构造 5 条 `UA` 欧美国家定向素材，验证最终最多保留 3 条。
- 构造 5 条 `ALL` 且命中欧美国家定向的素材，验证同样最多计入 3 条 UA 国家定向上限。
- 验证 `ALL` 视频且命中欧美国家时，同时占用：
  - 产品侧名额
  - UA 侧名额
  - 产品视频名额
  - UA 国家定向名额
- 回归验证飞书字段结构不变，TikTok、X、INS 各自筛选逻辑不变。

## Assumptions
- “属于欧美国家”按现有 UA geo 定向信号判断，而不是新增独立国家识别体系。
- 产品-only 内容即使提到欧美国家，也不计入 UA 国家定向素材，除非它的 `pushObject` 是 `ALL` 或 `UA`。
- 配额裁剪按最终热度评分从高到低保留，超额项跳过，不自动改写推送对象。
