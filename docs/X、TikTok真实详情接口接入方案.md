# X / TikTok 真实详情接口接入方案

## Summary
- 目标是让 `自动prompt获取` 在写表前真正重访源帖详情，获取完整正文、长文、caption、评论，再提取真实 prompt。
- 默认复用当前项目已有 provider：X 用 `twitter241.p.rapidapi.com`，TikTok 用 `tiktok-api23.p.rapidapi.com`；不新增第三方付费源。
- 详情接口路径不写死，统一由 `.env` 配置，方便从 RapidAPI Playground 复制真实 endpoint 后直接启用。

## Key Changes
- 增加详情接口配置：
  - `AUTO_PROMPT_X_DETAIL_ENDPOINT=`
  - `AUTO_PROMPT_X_DETAIL_ID_PARAM=pid`
  - `AUTO_PROMPT_X_REPLIES_ENDPOINT=/tweet/replies`
  - `AUTO_PROMPT_TIKTOK_DETAIL_ENDPOINT=`
  - `AUTO_PROMPT_TIKTOK_DETAIL_ID_PARAM=video_id`
  - `AUTO_PROMPT_TIKTOK_COMMENTS_ENDPOINT=`
  - `AUTO_PROMPT_TIKTOK_COMMENTS_ID_PARAM=video_id`
- 更新 `source_rehydrate`：
  - X：优先调用 X 单帖详情接口，提取 `full_text`、`note_tweet`、`richtext`、thread/quoted/reply 中的长文；再调用 replies 接口取评论。
  - TikTok：优先调用 TikTok video/post detail 接口，提取 `desc`、`caption`、`title`、hashtags；再调用 comments 接口取评论。
  - 详情接口成功后写入 `skill_runs/source_rehydrate/` 缓存；缓存命中不重复请求 API。
- 更新 prompt 提取：
  - 只从详情接口/源页面/评论/本地原始正文中提取 prompt。
  - `hotspotIntro` 仍只做上下文，不作为 prompt 来源。
  - 如果详情接口仍只返回短链、错误页或截断文本，则 `自动prompt获取` 留空，并记录失败原因。
- 配置方式：
  - X endpoint 从 twitter241 RapidAPI Playground 的单帖详情接口复制。
  - TikTok endpoint 从 tiktok-api23 RapidAPI Playground 的 `Post (Video)` / `Get Post Detail` 类接口复制。
  - 如果 tiktok-api23 没有可用详情权限，再评估备选 provider，例如 KeyAPI `/v1/tiktok/video/detail` 或 TikLiveAPI `post-detail/`，但不作为默认方案。

## Test Plan
- 配置前回归：详情 endpoint 为空时，脚本仍能运行，记录 `missing_x_detail_endpoint` / `missing_tiktok_detail_endpoint`，不写假 prompt。
- X 单帖详情测试：对 `https://x.com/Shinning1010/status/2059597024128114890` dry-run，若接口返回完整 `Prompt:`，应原样写入完整英文 prompt。
- TikTok caption 测试：对有 caption prompt 的 TikTok 链接 dry-run，应从 detail/caption 或 comments 中提取。
- 评论 prompt 测试：如果正文无 prompt、评论有明确 `Prompt:`，应写入评论中的真实 prompt。
- 负例：源页面错误页、短链截断、`prompt please`、推广文案、只有简介转述，均写空。
- 回填验证：运行 `scripts/manual/backfill_auto_prompt_recent.py --limit 15 --dry-run`，确认审计报告包含 endpoint、状态、缓存路径和 prompt 结果。

## Assumptions
- 当前优先不新增 API provider，先复用已有 RapidAPI 账号。
- 真实 endpoint path 需要从 RapidAPI Playground 复制到 `.env`，代码只负责兼容可配置路径和字段解析。
- TikTok 官方 `/v2/video/query/` 只适合授权用户自己的视频，不作为本项目公共素材详情源。参考：TikTok Developers 文档说明该接口需要用户授权且查询授权用户视频。
- 备选资料显示 TikTok 第三方详情接口常见形态包括 KeyAPI `/v1/tiktok/video/detail` 和 TikLiveAPI `post-detail/`，仅在现有 provider 不可用时再切换。
