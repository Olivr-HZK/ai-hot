# TikTok Discovery 验证码失败图片留存计划

## Summary
- 在 TikTok Discovery 遭遇验证码后，所有进入“拖动释放后等待人工确认”的尝试，只要未通过并继续停留验证码页、验证码刷新、或最终超时失败，都必须保存验证码图片。
- 图片用于后续滑块参数调优，因此保存粒度从当前单一 `verification_state.json` 扩展为“每次尝试一条失败快照记录”。
- 不改变搜索/过滤主流程，只增强验证码处理阶段的本地留档。

## Key Changes
- 在验证码目录新增结构化尝试档案：
  - `verification/captcha_attempts/<keyword_slug>/attempt_XX/`
  - 每次尝试保存：`before_full.png`、`after_full.png`、可选 `before_captcha.png`、`after_captcha.png`、`snapshot.json`。
  - `before/after_captcha.png` 优先用 `sliderPuzzle.containerSelector` 截取验证码容器；失败时保留 full page 截图。
- 扩展 `verification_state.json`：
  - 新增 `failedAttempts` 数组，记录每次失败尝试的 `autoAttempt`、`keyword`、`reason`、`captchaRefreshed`、`releasedForManualConfirmation`、`score`、`dragPx`、`angleDelta`、截图路径、html 路径、时间戳。
  - 最终 `manual_review_failed` 时追加 `finalFailureSnapshot`，确保超时点也有图片。
- 在 `wait_for_manual_verification()` 中加入快照点：
  - 每次 slider 尝试前保存 before snapshot。
  - 如果 `releasedForManualConfirmation=true` 后页面仍是 `verification_required`，保存 after snapshot，并记录为 `manual_confirmation_not_passed`。
  - 如果 before/after 验证码截图 hash 不一致，标记 `captchaRefreshed=true`。
  - 如果等待 200s 超时，保存最终 snapshot，并标记 `timeout_without_feedback`。
- 保持现有行为：
  - 通过验证码时仍写 `status=resolved`。
  - 未进入人工确认阶段的普通 headless 验证失败仍按现有失败逻辑处理，但也可保存最终截图。
  - 不影响 stage artifact、搜索计划、候选、过滤结果格式。

## Test Plan
- 单元测试：
  - slider 释放后仍停留验证码页时，写入 `failedAttempts[0]`，并生成 after/full 截图路径。
  - before/after 截图内容不同，`captchaRefreshed=true`。
  - `verification_wait_seconds=0` 或超时路径写入 `manual_review_failed` 和 `finalFailureSnapshot`。
  - 容器截图失败时不阻塞，仍保留 full page 截图。
  - 成功通过验证码时不记录失败尝试，只写 `resolved`。
- 回归测试：
  - `python -m py_compile scripts/tiktok_keyword_discovery.py`
  - `python -m unittest tests.test_tiktok_keyword_discovery`
  - `python -m unittest discover tests`

## Assumptions
- “验证码图片”默认保存 full page 截图，同时尽力保存验证码容器截图；容器截图失败不让 Discovery 失败。
- 每次失败都保留独立图片文件，不覆盖旧失败快照。
- 失败图片只写入当前 run 的本地目录，不上传飞书、不修改历史 run。
