# X 推送逻辑按《飞书热点需求（团队）》优化计划

## Summary
- 新增 X「团队图片/工作流需求」通道，覆盖 PDF 中两类内容：AI 制作流程案例、真人写真/图片玩法素材。
- 新通道绕过 X 当前 `include_keywords=["ai"]` 限制，但仍必须经过时间、质量、安全、去重、历史反馈等后续审核。
- 飞书字段不新增；按你选择的“产品优先”策略，符合 Avatar/Evoke/Kavi 图片玩法或制作流程的信息优先写 `推送对象=产品`，同时具备 UA 投放价值时写 `ALL`。

## Key Changes
- 扩展 X 搜索词与规则，加入 PDF 对应方向：
  - AI 工作流：`ChatGPT Seedance workflow`、`GPT Images Seedance`、`Suno Seedance video`、`AI video workflow prompt`、`iPhone vlog AI`、`photo album to video AI`、`AI couple video prompt`。
  - 真人图片：`art portrait photography`、`stylized portrait`、`fashion editorial photography`、`festival portrait`、`creative portrait photography`、`iPhone shot portrait`。
- 在 `scripts/phase1_scrape_x.py` 增加 X 团队需求候选池：
  - `workflow` lane：识别 AI 工具 + workflow/prompt/tutorial/production process/iPhone vlog/photo album/couple video 等内容，可接受图文、混合媒体或视频。
  - `photo` lane：识别真人相关写真/照片内容，如艺术写真、风格化照片、时尚大片、节日照片、婚礼/毕业、情侣/家庭、创意照等；不要求 AI 关键词，但要求图片或混合媒体。
- 新增内部标记字段 `xTeamDemand`：
  - 记录 `lane`、命中原因、候选池排名、匹配关键词、是否来自 PDF 需求通道。
  - 仅内部使用，不写入飞书新字段。
- 合并逻辑：
  - 标准 X 通道保持原逻辑。
  - X 团队需求通道与标准通道合并去重后，继续走安全审核、评论补充、视觉去重、AI 简介、产品/受众定向、历史反馈过滤。
  - 每日最多保留 `2` 条 X 团队需求内容，其中至少尝试保底 `1` 条图片/写真类内容；如果没有通过审核，不伪造结果，只打印 warning。
- 推送对象逻辑：
  - `workflow` lane 默认产品优先：命中制作流程、玩法教程、产品参考价值时写 `产品`。
  - `photo` lane 默认产品优先：能作为 Avatar/Evoke/Kavi 图片玩法参考时写 `产品`。
  - 若同一条也满足 UA 高热可投放素材逻辑，则写 `ALL`。
  - 已有 UA geo / UA material 的强制 `UA` 规则不被覆盖，除非该条同时被新团队需求通道确认为产品参考，才升级为 `ALL`。

## Test Plan
- X 工作流案例：包含 `ChatGPT + Seedance` 或 `GPT Images + Seedance + Suno` 的帖子进入候选，最终通过后 `pushObject=产品` 或 `ALL`。
- X 非 AI 写真：不含 `ai`，但是真人艺术写真/时尚大片/节日照片，能绕过 include keyword 限制进入后续审核。
- 负例拦截：政治、新闻资讯、硬件发布、crypto/Web3、成人擦边、纯 meme、低质量内容即使高热也不能进入最终推送。
- 回归：原 X 标准产品通道、X UA 高热素材通道、TikTok/INS 流程不受影响。
- 飞书兼容：不新增飞书字段，现有 `推送对象`、热点简介、平台标签等字段继续按当前结构写入。

## Assumptions
- PDF 中的 Avatar/Evoke/Kavi 需求在当前系统里先体现为“产品侧内容参考”，不新增产品名字段。
- 新增 X 搜索词会增加 X 抓取覆盖面，但不改 TikTok/INS 抓取策略。
- 图片/写真类内容可以是用户实拍，也可以是 AI 生成；最终是否推送取决于安全、质量、复用价值和历史反馈过滤。
