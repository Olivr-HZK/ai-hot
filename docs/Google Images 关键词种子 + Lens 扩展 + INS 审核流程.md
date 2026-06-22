# Google Images 关键词种子 + Lens 扩展 + INS 审核流程

## Summary
- 在 `google-lens-eagle-import` 中新增一条独立本地流程：关键词先跑 Google Images，图片种子通过产品/安全/视觉去重审核后，再进入 Google Lens 扩展。
- Lens 原始结果不限来源保存；随后只提取 Instagram `/p/`、`/reel/`、`/tv/` 内容，并复用现有 INS 审核链路。
- 默认做小批验证：最多 5 个关键词、每词取 30 张图片、每词最多 3 张种子进 Lens、每张 Lens 抽 100 条候选。所有阶段产物都保存本地，不写飞书、不推送。

## Key Changes
- 新增主入口：`google-lens-eagle-import/scripts/google_images_keyword_lens_pipeline.py`
  - 支持 `--keywords` / `--keywords-file`、`--max-keywords 5`、`--images-per-keyword 30`、`--seeds-per-keyword 3`、`--lens-candidates 100`、`--visible-browser`。
  - 使用本地 Chrome 持久 profile 访问 Google Images 和 Google Lens；遇到 Google 验证页时等待人工处理一次，超时或重复验证则保存 `degraded` 状态并停止后续未完成阶段。
- Google Images 阶段：
  - 每个关键词保存搜索页截图/HTML、原始图片候选、图片文件/缩略图、来源 URL、标题、域名、rank。
  - 输出：`keywords.json`、`google_images_raw_candidates.json`、`google_images_downloaded.json`、`google_images_fetch_report.json`。
- 种子图审核阶段：
  - 将 Google Images 图片候选适配为项目通用审核 item：`title/text/mediaUrls/hotspotUrl/sourcePlatform=google_images`。
  - 先做产品相关性审核，再做图片安全审核，再用 `apply_visual_dedupe(platform="google_images")` 去重。
  - 输出：`seed_product_passed.json`、`seed_product_blocked.json`、`seed_safety_passed.json`、`seed_safety_blocked.json`、`seed_visual_approved.json`、`seed_visual_deduped.json`。
- Lens + INS 阶段：
  - 对 `seed_visual_approved.json` 中的每张种子图跑 Google Lens，保存每张种子的 Lens 原始结果、截图、HTML 和候选 100 条。
  - 聚合 Lens 结果到 `lens_matches_all.json`，保留 `seedId`、`seedKeyword`、`seedRank`。
  - 扩展现有 `filter_instagram_matches.py`，保留 seed 来源字段，并继续执行 INS permalink 抽取、cookie/yt-dlp 元数据补全、页面图片兜底、INS 产品/安全/互动/视觉去重审核。
  - 输出：`instagram_candidates.json`、`instagram_enriched.json`、`instagram_blocked.json`、`instagram_approved.json`、`instagram_approved.md`、`instagram_filter_report.json`。
- 总输出目录：
  - 默认写入 `skill_runs/google_lens_eagle_import/keyword_lens_runs/<run_id>/`。
  - 顶层保存 `run_manifest.json`、`stage_report.json`、`final_approved.json`、`final_approved.md`，记录每阶段输入、通过、拦截、失败和 degraded 原因。

## Test Plan
- 单元测试：
  - Google Images HTML/DOM fixture 解析，确认提取图片 URL、来源 URL、标题、域名和 rank。
  - 图片候选审核适配器测试，确认能进入产品/安全/视觉去重函数所需字段。
  - Lens 聚合结果去重测试，确认保留 seed 来源。
  - INS 提取测试，确认只保留 `/p/`、`/reel/`、`/tv/` permalink。
- 集成测试：
  - 使用 fixture Google Images 结果和 fixture Lens 结果跑完整 pipeline，无网络也能生成所有阶段 JSON。
  - Mock `yt-dlp`/Playwright，验证 INS 元数据补全失败时写入 blocked，不中断 run。
  - 回归现有 `tests.test_google_lens_instagram_filter` 和全量 `unittest discover`。
- 手动验收：
  - 用 3-5 个关键词试跑，确认每词最多 30 张图、每词最多 3 张种子进 Lens。
  - 人工完成一次 Google 验证后，确认后续 Lens 可继续跑。
  - 确认最终只本地保存，不写飞书、不推送、不导入 Eagle。

## Assumptions
- Google Images 和 Google Lens 只通过本地浏览器访问，不使用外部搜索 API，不绕过验证码。
- 默认小批验证参数为：`maxKeywords=5`、`imagesPerKeyword=30`、`seedsPerKeyword=3`、`lensCandidates=100`。
- Google Images 阶段不限来源；Lens 后只将 Instagram permalink 进入 INS 审核。
- 所有历史 `skill_runs` 保留，新流程只新增独立 run 目录。
