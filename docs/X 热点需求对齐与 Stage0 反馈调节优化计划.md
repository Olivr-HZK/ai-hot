# X 热点需求对齐与 Stage0 反馈调节优化计划

## Summary
- 当前 X 代码方向只“部分达标”：搜索词和产品审核已接近 PDF 样例，但质量门槛过高、真人图片素材入口过窄，导致符合需求的 X 帖容易在筛选阶段被清空。
- 优化目标是让 X 稳定产出两类内容：AI workflow 案例，以及真人图片/写真/视觉玩法素材。
- Stage0 反馈调节需要同步从“泛平台关键词调权”升级为“能调节 X 团队需求标准”。

## Key Changes
- 将 X 入选拆成三条 lane：
  - `workflow`：ChatGPT / GPT Images / Seedance / Suno / prompt / storyboard / workflow / 制作流程类，优先贴合 PDF 样例。
  - `ai_photo`：AI 画像、照片转视频、风格化生成、before-after、模板复用、prompt 分享。
  - `real_photo`：非 AI 真人图片素材，如艺术写真、风格化照片、时尚大片、节日照、情侣/家庭/婚礼/毕业照，但必须有明确广告素材复用价值。
- 给 X 单独设置质量阈值：
  - 不再完全套用 TikTok 热度门槛。
  - `workflow` 可降低播放/点赞/评论门槛，因为 X 上高价值 workflow 往往互动较低。
  - `real_photo` 保持更高视觉质量和安全审核门槛，避免普通摄影、明星街拍、写真客片误入。
- 扩展 X 搜索词：
  - 保留现有 PDF 样例词，如 `ChatGPT Seedance prompt workflow`、`GPT Images Seedance prompt`、`AI photo album vlog workflow`。
  - 增加真人视觉素材词，如 `AI fashion portrait prompt`、`AI editorial portrait prompt`、`photo to video couple prompt`、`cinematic portrait prompt`、`holiday portrait prompt`。
  - 泛化非 AI 摄影词只进入 `real_photo` lane，且必须经过产品手册审核。
- 强化产品手册审核：
  - `xTeamDemandReview` 仍作为硬门槛。
  - 产品侧审核明确接受 PDF 要求中的非 AI 真人图片素材，但要求能转化为 Avatar / Evoke / Kavi / Toki 类广告创意。
  - 继续拒绝动漫、IP/明星依赖、路透、传统摄影业务、新闻资讯、硬件发布、crypto/Web3、成人擦边、低复用纯美图。
- 推送对象保持现有逻辑：
  - X 通过产品侧审核后默认 `pushObject="产品"`。
  - 再用 UA 手册复审，适合投放 UA 的升级为 `ALL`。
  - X 不输出纯 `UA`。

## Stage0 Feedback Changes
- 修改 Stage0 优化器标准，使它能更新 X 团队需求配置，而不是只调全局 TikTok 风格关键词。
- AI optimizer prompt 中新增可调字段：
  - `x_team_demand.workflow_tool_keywords`
  - `x_team_demand.workflow_action_keywords`
  - `x_team_demand.workflow_output_keywords`
  - `x_team_demand.photo_product_keywords`
  - `x_team_demand.real_photo_keywords`
  - `x_team_demand.reject_keywords`
  - `x_quality_thresholds`
  - `x_scrape.search_queries`
- Stage0 对 X 反馈单独归因：
  - 正反馈进入 X 专属 preferred / lane keywords。
  - 负反馈进入 `x_team_demand.reject_keywords` 或 X 降权词。
  - 如果多次出现“相关但热度不足”的正反馈，Stage0 可小幅降低对应 lane 的 X 质量门槛。
  - 如果多次出现“高热但无产品价值”的负反馈，Stage0 应提高该 lane 的产品审核严格度或增加拒绝词。
- 给 Stage0 增加 PDF guardrails：
  - 不允许把 X 优化回普通娱乐热点、明星八卦、纯摄影客片、动漫插画方向。
  - 保留 AI workflow、prompt、制作流程、真人视觉素材复用这几个核心方向。

## Test Plan
- PDF 样例类帖子：ChatGPT + Seedance、GPT Images + Seedance + Suno、iPhone 相册/Vlog workflow 应能进入候选并通过产品侧审核。
- 低互动但高相关 workflow：不应被原 `min_play_count=10000`、`min_comment_count=20` 直接清空。
- 非 AI 真人图片：艺术写真、时尚大片、节日照等可进入 `real_photo`，但必须通过产品手册审核。
- 误入内容：动漫、明星街拍、paparazzi、传统婚礼摄影客片、摄影师作品集、硬件/模型新闻必须被过滤。
- Stage0 回归：X 正负反馈会更新 X 专属规则；TikTok/INS 原有反馈逻辑不受影响。
- 缓存数据回放：用当前本地 X 抓取缓存验证筛选过程至少能留下合理候选池，避免再次在质量过滤阶段变成 0。

## Assumptions
- 不新增飞书字段，内部可在审核原因中提到 Avatar / Evoke / Kavi / Toki。
- X 最终数量允许少于 `top_n`，宁可少推，也不推与产品需求无关的内容。
- 热点评分排序继续沿用原 X 体系，只调整 X 的候选入口、质量阈值和 Stage0 反馈标准。
