# 产品定位收敛为 Evoke / Toki / Kavi / Avatar 计划

## Summary
- 将项目的产品宇宙收敛为 4 个重点产品：`Evoke`、`Toki`、`Kavi`、`Avatar`。
- 删除 `Deep Think`、`Zensi` 在产品文档、推送规则、模型审核提示词、筛选配置、反馈规则中的未来使用。
- 历史飞书记录和本地历史结果不迁移，只确保后续抓取、筛选、审核、推送不再把素材归因到这两个产品。

## Key Changes
- 更新产品文档与推送规则：
  - `references/product_material_requirements.md` 只保留 Evoke / Toki / Kavi / Avatar 的定位、素材需求、优先级和案例标准。
  - `references/push_rules.md` 删除 Deep Think / Zensi 相关描述；`UA` 不再代表 Deep Think 专属，只表示适合广告投放侧。
- 同步筛选与审核逻辑：
  - TikTok / X / INS 的产品匹配产品列表统一为 `evoke`、`toki`、`kavi`、`avatar_jigsaw`。
  - 删除 `deepthink` 的 UA-only 分支；不再因为命中 Deep Think 类关键词而标记 `UA` 或 `ALL`。
  - `uaGeoTargeting` 规则保留：命中欧美定向且匹配 Evoke/Toki/Kavi/Avatar 时标记 `ALL`，并继续计入 UA 国家定向名额。
- 同步模型审核提示词：
  - `ua_material_review`、`x_team_product_review`、`ins_product_review` 的产品枚举只允许四个产品或 `none`。
  - 如果模型返回 `deepthink` / `zensi`，归一化为 `none`，不得通过产品侧或 UA 侧终审。
- 同步反馈调节：
  - `references/tiktok_feedback_optimization_rules.json`、`references/instagram_feedback_rules.json`、Stage0 默认规则与校验逻辑删除 `deepthink` 配置。
  - Stage0 后续优化不得重新生成 Deep Think / Zensi 产品规则或关键词方向。
- 同步 INS 创作者发现：
  - 创作者发现提示词删除 Deep Think / Zensi。
  - `productFit` 候选更新为 Evoke / Toki / Kavi / Avatar，避免旧 schema 继续只识别 `deepthink/evoke/toki`。

## Test Plan
- 静态检查：
  - 确认活跃脚本和规则文档中不再出现 Deep Think / Zensi 产品定位。
  - JSON 规则文件可正常解析。
  - Python 改动文件通过 `python -m py_compile`。
- 行为检查：
  - Deep Think/Zensi 类文本不再产生产品匹配、不再标记 `UA` 或 `ALL`。
  - Evoke / Toki / Kavi / Avatar 样例仍能正常通过产品匹配和审核。
  - TikTok `uaGeoTargeting + 四个重点产品` 仍输出 `ALL`，且仍计入 UA 国家定向素材名额。
  - X / INS 模型若返回 removed product，结果应被归为 `none` 并拒绝通过产品终审。
- 回归检查：
  - 飞书写入字段不变。
  - 推送对象仍只使用 `产品`、`UA`、`ALL`。
  - 每日推送上限、产品视频上限、UA 国家定向上限逻辑不变。

## Assumptions
- “删除另外两个”指删除 Deep Think 和 Zensi 的未来产品定位与筛选归因，不清理历史数据。
- Avatar 在代码中继续使用现有内部 key：`avatar_jigsaw`，对外展示简称为 `Avatar`。
- 未来素材主要服务 Evoke / Toki / Kavi / Avatar；UA 可推送这些产品的广告投放素材参考，但不再单独服务 Deep Think 或 Zensi。
