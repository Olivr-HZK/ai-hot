# X 源链接重访升级为 Playwright 浏览器渲染 Cookie 模式

## Summary
- 在现有 `no_api` prompt 重访链路中，为 X 增加 Playwright 浏览器渲染能力。
- 使用 `.env` 指定的本地 cookie JSON 注入浏览器上下文，打开 X 原帖页面，等待 tweet 正文 DOM 出现，再抽取可见帖子文本。
- 不调用 Apify、RapidAPI、SocialCrawl 或 X API；只访问网页。
- 目标是解决当前 `requests` 只能拿到 `generic_shell:x.com`，导致第 7、8 条明文 prompt 被误判为截断的问题。

## Key Changes
- 在 `scripts/source_rehydrate.py` 增加浏览器重访步骤，仅对 X 默认启用：
  - 访问顺序调整为：同版本缓存 -> 本地历史缓存 -> Playwright cookie 渲染 -> cookie HTML -> public HTML -> 已有评论。
  - X 浏览器渲染即使本地缓存命中也执行一次，用于补齐本地缓存中的截断 prompt。
  - 抽取 `article[data-testid="tweet"]` 内的 `div[data-testid="tweetText"]` 文本；若存在 “Show more/显示更多”，先点击展开再抽取。
  - 输出文本块来源标记为 `sourceRehydrate.browserRender.xTweetText`。
- 新增配置：
  - `AUTO_PROMPT_BROWSER_REHYDRATE_ENABLED=true`
  - `AUTO_PROMPT_BROWSER_REHYDRATE_PLATFORMS=x`
  - `AUTO_PROMPT_BROWSER_HEADLESS=true`
  - `AUTO_PROMPT_BROWSER_TIMEOUT_SECONDS=45`
  - `AUTO_PROMPT_BROWSER_WAIT_AFTER_LOAD_MS=1500`
  - `AUTO_PROMPT_BROWSER_CACHE_VERSION=browser_v1`
- Cookie 处理：
  - 复用当前 `AUTO_PROMPT_COOKIE_FILE=skill_runs/cookies/source_rehydrate_cookies.json`。
  - 将 domain->cookie header 转换为 Playwright cookies，注入 `x.com` 上下文。
  - 不打印 cookie 值；审计只记录 `browserCookieUsed=true`、`browserCookieDomain=x.com`。
- 缓存处理：
  - 浏览器模式使用新的 cache version 参与缓存 key，避免复用之前 `generic_shell:x.com` 的旧失败缓存。
  - `sourceRehydrate` 审计新增：`browserUsed`、`browserStatus`、`browserTextBlockCount`、`browserError`、`browserCacheVersion`。
- 依赖：
  - `requirements.txt` 增加 `playwright>=1.58.0`。
  - 若 Playwright 包或 Chromium 二进制缺失，记录 `browser_unavailable`，不中断流程，继续现有 fallback。

## Test Plan
- 本地单条验证：
  - 对 `https://x.com/Shinning1010/status/2059597024128114890` 执行 source rehydrate dry-run。
  - 预期 `browser_render` 成功，文本块中包含完整 `Use my uploaded portrait...` prompt，而不是 `http` 截断。
- 最近 10 条回填：
  - 重跑 `scripts/manual/backfill_auto_prompt_recent.py --limit 10`。
  - 预期第 7、8 条不再因 `generic_shell:x.com` 或截断本地缓存而失败；若正文确有完整 prompt，应写入 `自动prompt获取`。
- 回归：
  - TikTok / Instagram 仍走现有 no-api cookie/public HTML + 本地缓存逻辑，不新增浏览器渲染。
  - `platform_detail` 仍显示 `no_api_mode`，不调用任何外部平台 API。
  - AST / py_compile 检查：`source_rehydrate.py`、`auto_prompt_extraction.py`、`backfill_auto_prompt_recent.py`。
- 失败场景：
  - Cookie 失效：记录 `browser_login_or_shell`，不写假 prompt。
  - DOM 超时：记录 `browser_timeout`，继续 fallback。
  - Playwright 缺失：记录 `browser_unavailable`，不影响日常流程。

## Assumptions
- v1 只为 X 启用浏览器渲染；TikTok / Instagram 暂不启用，避免扩大调试面。
- 浏览器渲染仍属于 no-api 方案，因为它只加载网页，不调用平台数据 API。
- 当前机器已安装 Playwright 1.58 和 Chromium；服务器部署时若缺失，需要运行 `python -m playwright install chromium`。
- 为保证真实性，浏览器抽取到的正文仍只作为 prompt 候选；最终写入仍需通过现有规则和 OpenRouter 模型确认。
