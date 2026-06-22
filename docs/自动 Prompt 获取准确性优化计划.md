# 自动 Prompt 获取准确性优化计划

## Summary
- 当前问题根因：`自动prompt获取` 会把 `hotspotIntro/summary` 当作候选上下文交给模型，模型可能“整理/补写”成短版 prompt，而不是原帖真实 prompt。
- 优化目标：只写入创作者真实分享的 prompt；有明确 `Prompt:` 时优先原样保留，模型只做确认和翻译，不允许扩写、概括或从简介补内容。
- 如果本地缓存只抓到短链或截断片段，不再用简介拼 prompt；宁可写空，并在内部记录 `prompt_truncated_or_link_only`。

## Key Changes
- 调整文本来源分层：
  - `title/text/desc/caption/comments/transcript/ocrText` 可作为 prompt 候选来源。
  - `hotspotIntro/summary/aiIntro/video_summary` 只作为判断上下文，不再参与候选 prompt 内容生成。
  - 评论中只有 `prompt please`、`share prompt?`、`求提示词` 继续判空。

- 调整提取策略：
  - 明确命中 `Prompt:` / `提示词：` / `Prompt Buat...` 时，截取其后的原文段落作为候选。
  - 如果候选是英文且内容完整，最终写入原始候选文本，仅做空白、URL、重复标签清理。
  - 如果候选非英文，模型只翻译该候选，不得增删内容。
  - 如果候选过短、只有短链、明显被截断，则写空，并记录原因；不从 `hotspotIntro` 或图片描述补写。

- 调整模型审核提示词与返回结构：
  - 模型输入包含 `candidatePrompts` 和 `contextBlocks`，但明确要求：只能确认候选，不能根据 context 改写候选。
  - 模型返回改为：`hasPrompt`、`selectedCandidateIndex`、`action=accept_exact|translate|reject`、`translatedPromptEnglish`、`reason`。
  - 英文候选通过时，代码使用原始候选写表，不使用模型生成文本；只有翻译场景才使用模型输出。

- 补充回填与修正：
  - manual 回填脚本继续只更新 `自动prompt获取` 字段，不接入日常流程。
  - 对已经被模型改写过的最近记录，可重新跑一次回填；这条 `Shinning1010` 若本地仍只有短链/截断文本，则应写空，除非先补入你提供的完整原 prompt。
  - 后续如果要支持 `t.co` 链接展开，需要单独加显式联网解析开关，默认关闭，避免误耗 API 和不稳定抓取。

## Test Plan
- 明确英文 prompt：`Prompt: Use my uploaded portrait...` 应原样写入完整英文 prompt。
- 中文/印尼语 prompt：只翻译候选本身，不添加 `hotspotIntro` 中的信息。
- 候选短链或截断：`Prompt: https://t.co/...` 或极短片段应写空，并记录截断原因。
- 求 prompt 评论：`prompt please`、`share prompt?`、`求提示词` 应写空。
- 回归：`prompt反推结果`、`素材类型` 仍不读取、不写入；飞书推送卡片不展示 prompt。

## Assumptions
- `自动prompt获取` 字段应追求真实性高于覆盖率。
- `hotspotIntro` 是内部分析文本，不应被视作创作者 prompt 来源。
- 默认不展开短链；需要展开时后续作为独立功能加开关和权限控制。
