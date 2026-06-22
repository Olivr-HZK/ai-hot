# X 团队需求筛选二次优化方案

## Summary
- 当前 2 条保留结果偏离 PDF 样例的根因：它们只是传统明星/摄影内容，`productFit=false`、UA 手册复审也拒绝，但流程仍按“产品保底”保留了它们。
- 优化方向改为“PDF 样例优先”：优先选择有明确 AI 工具链、prompt、workflow、可复用制作方法的 X 内容；普通实拍写真只能作为补充，且必须通过产品侧手册审核。
- X 最终不再无条件保留 `产品`，而是通过产品手册审核才进入飞书。

## Key Changes
- 收紧 X 入选门槛：
  - `workflow` lane 必须同时具备：AI 工具链、制作动作、明确产出方向、可复用 prompt/workflow 信息。
  - `photo` lane 不再只靠 `fashion/photoshoot/couple` 等泛词入选；必须命中“AI 图片玩法、照片转视频、风格化生成、模板复用、before-after、prompt 分享”等产品相关信号。
  - 普通明星街拍、传统摄影客片、纯摄影作品、无 AI/工具/模板证据的照片直接过滤。
- 增加 X 产品手册终审：
  - 新增 `xTeamDemandReview`，使用产品手册从产品侧判断是否值得推送。
  - 产品手册终审作为硬门槛：不通过就删除，不再保留为 `产品`。
  - UA 手册复审只负责把已通过产品侧的结果从 `产品` 升级为 `ALL`。
- 调整搜索词策略：
  - 降低或移除泛化词：`fashion photoshoot`、`couple photoshoot`、`family portrait`、`wedding photo` 这类会抓到传统摄影内容的词。
  - 强化 PDF 样例词：`ChatGPT Seedance prompt workflow`、`GPT Images Seedance prompt`、`AI photo album vlog workflow`、`AI couple video prompt`、`iPhone style AI video workflow`、`photo to video storyboard prompt`。
- 强化负面过滤：
  - 拦截动漫/插画/角色类：`anime`、`manga`、`OVA`、`cel shading`、`elf`、`character design`、`fanart`。
  - 拦截普通明星/IP/路透：`paparazzi`、`celebrity`、`Lindsay Lohan` 类明星依赖内容。
  - 拦截传统摄影业务：`booked their photoshoot`、`photographer`、`engagement shoot`、`wedding photographer` 等无 AI 产品证据内容。
- 修复流程细节：
  - X 处理脚本不要把最终结果覆盖回 scraper 的 `filtered-result.json`，避免 `--skip-scrape` 后只能看到上次最终结果。
  - 保留原始 X scraper 输出作为信源，另写标准化/最终输出到 `skill_runs`。

## Test Plan
- PDF 类样例：`ChatGPT + Seedance`、`GPT Images + Seedance + Suno`、iPhone 相册/Vlog/情侣视频 workflow 能通过产品侧审核。
- 当前误入 2 条：Lindsay Lohan 街拍、传统情侣订婚摄影必须被过滤。
- 动漫误入：Seedance anime / cel shading / OVA / elf 类内容必须被过滤。
- 普通写真：没有 AI 工具、prompt、模板、产品玩法证据时不进入最终结果。
- UA 升级：产品侧通过且 UA 手册认为可投放时标记 `ALL`，否则保留 `产品`。
- 回归：X 仍沿用原热点评分、质量阈值、时间窗口和 TikTok feedback rules；TikTok/INS 不受影响。

## Assumptions
- “与 PDF 样例更接近”优先理解为：有 AI 创作工具链、prompt/workflow、可复用制作路径，而不是泛化高热照片。
- 非 AI 实拍内容仍允许，但只能在产品手册明确认为可作为 Avatar/Evoke/Kavi/Toki 产品素材参考时通过。
- X 最终结果允许少于原 top_n；宁可少推，也不推产品无关内容。
