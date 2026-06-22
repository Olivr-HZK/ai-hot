# US T1 英文识别放宽方案

## Summary
将 US T1 的英文识别从“必须依赖平台语言字段 `en/eng/english`”调整为“平台语言字段通过，或文本中英文字符占比超过 75%”。这样 X 缓存里缺少 `lang` 字段但明显是英文的帖子，可以进入后续美国信号与排除词判断。

## Key Changes
- 修改 `scripts/us_t1/us_content_push.py` 的英文判断：
  - 保留原逻辑：`lang in {"en", "eng", "english"}` 直接通过。
  - 新增文本占比判断：
    ```text
    englishRatio = 英文字母数量 / 有效字符总数
    ```
  - 当 `englishRatio >= 0.75` 时，也视为英文。
- 有效字符总数建议只统计字母、数字和 CJK 字符，忽略空格、标点、链接符号、emoji，避免 URL 和标点影响比例。
- 在 `usT1Targeting` 中记录：
  - `detectedLanguage`
  - `englishRatio`
  - `languageMethod`: `platform_lang | text_ratio | failed`
- X scrape 模式仍保留 `lang:en` 查询限定；cache 模式也可通过文本占比识别英文。
- 美国信号仍保持独立门槛：英文通过不等于美国通过。

## Test Plan
- X cache 中 `raw_source.lang` 缺失，但正文英文占比 >= 75%：应识别为英文。
- `raw_source.lang=en`：即使文本较短，也应识别为英文。
- 中英混杂且英文占比 < 75%：不视为英文。
- 纯 URL、emoji、标点内容：有效字符不足时不视为英文。
- US T1 报告中能看到 `englishRatio` 与 `languageMethod`。
- 回归：TikTok / X US T1 仍不写飞书多维表格，最多推送 5 条。
