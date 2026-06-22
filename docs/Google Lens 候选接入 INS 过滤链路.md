# Google Lens 候选接入 INS 过滤链路

## Summary
- 将 `google-lens-eagle-import` 的 Google Lens 原始候选池从 `80` 提高到 `100`。
- 先从 100 条原始候选里提取 Instagram 帖子链接，再走本项目现有 INS 过滤链路。
- 最终只在本地输出并展示通过过滤的帖子，不写入飞书、不推送。

## Key Changes
- 更新 `google-lens-eagle-import/SKILL.md` 中 Lens 参数：
  - `visualMatchesCandidateLimit: 100`
  - 保持 Lens 原始候选保存完整，后续筛选不影响原始结果归档。
- 新增 Google Lens INS 后处理脚本：
  - 读取 Lens run 目录里的 `all_visual_matches.json` / `lens_results_attr.json`。
  - 从候选中提取并规范化 `instagram.com/p/`、`/reel/`、`/tv/` 链接。
  - 按 shortcode 去重；profile 页面暂不作为“INS帖”进入过滤。
  - 对每条 permalink 使用项目已有 cookie/yt-dlp 元数据能力补全作者、caption、图片/视频缩略图、发布时间、互动数等字段。
- 接入现有 INS 过滤系统：
  - 将补全后的候选转换为 `normalize_ins_post` 兼容 raw post。
  - 依次走媒体可用性、质量/互动门槛、产品审核、安全审核、视觉去重和历史反馈排除。
  - 缺少 permalink、媒体、发布时间或基础文本的候选记录到 blocked report，不进入审核。
- 新增本地输出：
  - `instagram_candidates.json`：从 Lens 候选中识别出的 INS 帖。
  - `instagram_enriched.json`：补全元数据后的候选。
  - `instagram_blocked.json`：未进入审核或被过滤的原因。
  - `instagram_approved.json`：通过现有 INS 过滤链路的帖子。
  - `instagram_approved.md`：给你检查用的可读结果清单。

## Test Plan
- 用 fixture Lens 结果测试链接提取：混合普通网页、INS profile、INS post/reel/tv，确认只保留帖子链接并正确去重。
- Mock yt-dlp 元数据返回，确认生成的 raw post 能通过 `normalize_ins_post` 得到 `hotspotUrl`、`mediaUrls`、`authorMeta`、`text`、`mediaType`。
- 测试元数据缺失、私密/失效链接、重复 shortcode 时流程不失败，并写入 blocked report。
- 用上一轮 `DYra52myUbK` Lens run 做回归：重新抽取 100 条候选，生成 INS 筛选结果，本地展示通过审核的帖子。

## Assumptions
- “ins帖”仅指 `/p/`、`/reel/`、`/tv/` permalink；公开 profile 链接不进入本轮过滤。
- 元数据补全优先使用项目现有 cookie/yt-dlp 路径，不新增外部 API。
- 本轮结果只保存在本地 run 目录并展示给你，不写飞书、不推送、不导入 Eagle。
- 通过过滤的帖子不设展示数量上限，按现有 INS 评分和 Lens 原始排序综合排列。
