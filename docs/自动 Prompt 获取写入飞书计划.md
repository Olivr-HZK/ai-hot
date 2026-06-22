# 自动 Prompt 获取写入飞书计划

## Summary
- 对最终已通过审核、确认进入飞书写表/推送的素材，新增一次 prompt 提取。
- 只检查素材已有文本信息：标题/正文、热点简介、评论区内容、摘要和标签。
- 如果发现真实可复用 prompt，则写入飞书多维表格字段 `自动prompt获取`；非英文 prompt 必须翻译成英文后写入。
- 如果没有发现 prompt，`自动prompt获取` 写为空字符串。
- 保持 `prompt反推结果`、`素材类型` 仍为忽略字段，不读取、不写入、不参与分析。

## Key Changes
- 新增 `scripts/auto_prompt_extraction.py`：
  - 输入最终热点 item，输出内部字段 `autoPromptExtraction` 和外部字段值 `autoPromptText`。
  - 先用规则识别 prompt 候选：`prompt:`、`prompts:`、`提示词`、`Prompt Buat...`、引号/分段后的长描述、评论中的明确 prompt 分享等。
  - 排除“求 prompt”但没有实际 prompt 的内容，例如 `prompt please`、`what prompt`、`求提示词`。
  - 对候选文本调用 OpenRouter 模型做二次确认、清洗和翻译；默认模型读取 `AUTO_PROMPT_MODEL`，否则使用 `OPENROUTER_MODEL`，当前即 `qwen/qwen3.7-max`。
  - 模型返回 JSON：`hasPrompt`、`promptEnglish`、`source`、`reason`；只有 `hasPrompt=true` 且 `promptEnglish` 非空时写入飞书。
  - 如果发现非英文 prompt 但翻译失败，飞书字段写空，并在内部 `autoPromptExtraction.error` 记录原因，避免写入非英文。

- 修改飞书写入逻辑：
  - 在 `scripts/feishu_push.py` 的 `write_to_bitable()` 中，对 `hotspots` 先执行 `apply_auto_prompt_extraction()`，再构造写表字段。
  - `WRITE_FIELD_NAMES` 新增：
    - `auto_prompt = "自动prompt获取"`
  - `build_bitable_fields()` 永远写入 `自动prompt获取`：
    - 有 prompt：写英文 prompt
    - 无 prompt：写 `""`
  - 写入前可读取表字段列表；若飞书表暂时没有 `自动prompt获取` 字段，则跳过该字段并打印 warning，不阻断日常流程。

- 配置新增到 `.env.example`：
  - `AUTO_PROMPT_EXTRACTION_ENABLED=true`
  - `AUTO_PROMPT_MODEL=qwen/qwen3.7-max`
  - `AUTO_PROMPT_REQUIRE_MODEL=true`
  - `AUTO_PROMPT_MAX_COMMENTS=10`
  - `AUTO_PROMPT_MAX_TEXT_CHARS=6000`

- 保持主流程语义：
  - 只处理最终通过筛选和审核的素材。
  - 不改变 TikTok / X / INS 的筛选、排序、推送对象和配额逻辑。
  - 不把提取到的 prompt 展示到飞书卡片，只写多维表格字段。
  - 不读取或写入 `prompt反推结果`。

## Test Plan
- 明确英文 prompt：
  - 标题/正文含 `Prompt: create a cinematic portrait...`，应写入英文 prompt。
- 中文 prompt：
  - 正文或评论含 `提示词：赛博朋克风格人像...`，应翻译为英文后写入。
- 印尼语/其他语言 prompt：
  - 类似 `Prompt Buat foto serupa...`，应翻译为英文后写入。
- 求 prompt 但无实际 prompt：
  - 评论只有 `prompt please`、`share prompt?`，应写空。
- 无 prompt 素材：
  - `自动prompt获取` 字段写空字符串。
- 飞书字段保护：
  - 确认写入字段包含 `自动prompt获取`，不包含 `prompt反推结果`、`素材类型`。
- 回归：
  - `python -m py_compile scripts/auto_prompt_extraction.py scripts/feishu_push.py`
  - 用 `--dry-run` 检查写表 payload。
  - 正常日常流程仍能写表和推送。

## Assumptions
- `自动prompt获取` 是飞书多维表格中的文本字段。
- “通过审核确认推送”指进入 `write_to_bitable()` 的最终热点列表。
- prompt 提取只基于文本、简介和评论，不做图片反推 prompt；图片反推仍不属于本功能。
