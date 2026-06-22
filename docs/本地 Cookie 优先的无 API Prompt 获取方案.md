# 本地 Cookie 优先的无 API Prompt 获取方案

## Summary
- `自动prompt获取` 的源链接重访首选本地 Cookie 模式：从 `.env` 指定的项目本地 cookie 文件读取登录态，再访问 X/TikTok/Instagram 原帖网页。
- 不调用 Apify、RapidAPI、SocialCrawl 或其他外部 API。
- 如果 cookie 访问失败，再回退到本地缓存和公开 HTML；仍拿不到真实原文则写空。

## Key Changes
- 新增配置：
  - `AUTO_PROMPT_SOURCE_REHYDRATE_MODE=no_api`
  - `AUTO_PROMPT_USE_LOCAL_COOKIES=true`
  - `AUTO_PROMPT_COOKIE_FILE=skill_runs/cookies/source_rehydrate_cookies.json`
  - `AUTO_PROMPT_COOKIE_DOMAINS=x.com,tiktok.com,instagram.com`
  - `AUTO_PROMPT_COOKIE_TIMEOUT_SECONDS=30`
- Cookie 文件格式：
  - 使用 JSON 文件，保存在项目本地目录，不提交仓库。
  - 支持两种结构：
    - `{ "x.com": "name=value; name2=value2", "tiktok.com": "...", "instagram.com": "..." }`
    - 或 Playwright/浏览器导出的 cookie 数组：`[{ "name": "...", "value": "...", "domain": ".x.com" }]`
  - `.gitignore` 增加 `skill_runs/cookies/`，避免 cookie 泄露。

- 访问顺序：
  - 先查 `skill_runs/source_rehydrate/` 缓存。
  - 再查本地历史抓取缓存，按 URL/post id/tweet id/video id 匹配正文和评论。
  - 再使用 `.env` 指定 cookie 访问源链接和短链展开页。
  - 最后尝试无 cookie 公开 HTML。
  - 全程禁用 platform detail endpoint、RapidAPI replies、Apify dataset comments。

- Prompt 提取规则：
  - 只从本地原始正文、cookie 网页正文、公开 HTML、caption、评论中提取。
  - `hotspotIntro/summary/aiIntro` 仍只作为上下文，不作为 prompt 内容来源。
  - 完整英文 prompt 原样写入；非英文 prompt 只翻译候选本身；短链/截断候选写空。

- 手动回填：
  - `scripts/manual/backfill_auto_prompt_recent.py` 继续复用同一逻辑。
  - 审计报告记录 `cookieUsed`、`cookieDomain`、`htmlStatus`、`cacheHit`、拒绝原因。
  - 支持先 dry-run 最近 N 条确认，再正式覆盖飞书字段。

## Test Plan
- Cookie 文件存在且有效：X 原帖网页能返回正文，`Prompt:` 被原样提取。
- Cookie 文件缺失：记录 `cookie_file_missing`，回退公开 HTML，不报错。
- Cookie 过期：记录 `cookie_html_unusable`，继续回退，不写假 prompt。
- TikTok/Instagram cookie 可用：caption/页面正文有 prompt 时提取。
- 无 API 保证：运行时不访问 RapidAPI/Apify/SocialCrawl endpoint。
- 安全：确认 `skill_runs/cookies/` 被 `.gitignore` 忽略。

## Assumptions
- 用户会手动把可用 cookie 导出到 `.env` 指定的本地 JSON 文件。
- Cookie 仅用于访问公开网页，不用于调用任何平台 API。
- Cookie 文件属于敏感信息，永不在日志中打印具体 cookie 值。
