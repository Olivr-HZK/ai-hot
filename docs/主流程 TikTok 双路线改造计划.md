# 主流程 TikTok 双路线改造计划

## Summary
- 保持 `x`、`ins` 主流程不变。
- 主流程 `tiktok` 不再调用旧 Apify 抓取逻辑，改为运行两条 TikTok Discovery 路线：`tiktok-UA` 和 `tiktok-Product`。
- 两条路线各自产出后统一去重；同 URL 同时命中 UA 和 Product 时合并为一条，`pushObject=ALL`。
- TikTok 输出绕过全局推送上限；`x/ins` 继续沿用原有上限和逻辑。

## Key Changes

### 主流程编排
- 将 `run_pipeline.py` 中原 `tiktok -> scripts/phase1_scrape.py` 平台入口替换为 TikTok Discovery 双路线编排。
- 保留 `skill_runs/hotspots_tiktok.json` 作为主流程 TikTok 合并输出，新增或内部生成：
  - `hotspots_tiktok_ua.json`
  - `hotspots_tiktok_product.json`
  - 双路线合并后的 `hotspots_tiktok.json`
- 停止主流程中“额外合并 latest TikTok Discovery artifact”的旧行为，避免双路线已经产出的 Discovery 结果被重复合并。
- 旧 Apify TikTok 代码可保留为未调用的 legacy 文件，但主流程不再触达；`x/ins` 相关 Apify 或现有 provider 不改。

### tiktok-UA 路线
- 使用当前 TikTok Discovery 默认分层配置：20 个搜索词，保留外部热点源和 Stage1 反馈调节。
- 时间窗口固定为过去 7 天。
- Stage4 调整为 UA profile：
  - 取消播放、点赞、评论、热度门槛。
  - 时长门槛改为 `<=60s`。
  - 保留安全过滤、反馈排除、URL 去重、历史去重、视觉去重、审核机制。
  - 输出帖子数量无上限，不再被 `top_n` 或全局 `push_caps.total_daily_max` 截断。
- UA 路线最终默认 `pushObject=UA`。
- 若 UA 输出中存在达到产品推送热度标准的素材，按主流程 TikTok 热度评分取最高 1 条，提交给 `tiktok-Product` 的产品审核流程；该额外项不占 Product 每日上限。

### tiktok-Product 路线
- 使用当前 Discovery 逻辑和 dance trend 15 词配置。
- 搜索词不轮换，不启用 Stage1 反馈调节，不启用外部热点源。
- 时间窗口固定为过去 90 天。
- Stage4 调整为 Product profile：
  - 取消播放、点赞、评论、热度门槛。
  - 时长门槛改为 `<=15s`。
  - 去除模型审核/产品审核/UA 审核机制。
  - 只保留基础 URL 合法性、时间窗口、时长过滤、历史去重、URL 去重、视觉去重。
- Product 候选按 3 个窗口分级：
  - 过去 7 天
  - 过去 30 天
  - 过去 90 天
- 每个窗口先取候选并集：
  - 播放量 Top 20
  - 点赞 Top 10
  - 评论 Top 5
- 去重优先级为 `7天 > 30天 > 90天`：同一 URL 命中多个窗口时只归入最高优先级窗口。
- 每个窗口经过去重后按 TikTok 热度评分排序，取 Top `n`。
- `n` 从 env 读取，命名为 `TIKTOK_PRODUCT_PER_WINDOW_LIMIT`，默认 `1`。
- Product 路线每日上限为 `3*n`，不包含 UA 提交来的额外产品审核项。
- Product 路线自身产出的素材最终 `pushObject=ALL`，不再产出 legacy `产品`。

### 双路线合并与推送对象
- TikTok 两条路线完成后按 URL 合并：
  - 仅 UA 命中：保留一条，`pushObject=UA`。
  - 仅 Product 命中：保留一条，`pushObject=ALL`。
  - UA 和 Product 重复：合并元数据，`pushObject=ALL`。
- 保留 route metadata，例如 `tiktokRoute=ua|product|both`、`productWindow=7d|30d|90d`、`submittedFrom=tiktok-UA`。
- TikTok 合并结果整体绕过全局推送 cap；`x/ins` 继续按原逻辑执行 cap 后再进入最终推送。

## Public Interfaces / Config
- 新增 env：
  - `TIKTOK_PRODUCT_PER_WINDOW_LIMIT=1`
- 新增 Discovery route profile 配置或等价代码配置：
  - `tiktok-UA`: default layered config, feedback tuning enabled, 7d window, 60s duration, no metric thresholds, unlimited output.
  - `tiktok-Product`: dance config, feedback tuning disabled, 90d window, 15s duration, metric top pools, cap `3*n`.
- `scripts/phase1_scrape.py` 中被 Discovery 复用的 Stage4 处理函数增加 route/profile 参数，避免通过修改全局阈值实现路线差异。

## Test Plan
- 单元测试：
  - 主流程 `tiktok` 不再调用旧 Apify TikTok script。
  - `x/ins` 平台脚本、输出路径、cap 行为保持不变。
  - UA profile 下播放/点赞/评论/热度低的合格素材仍可进入，`>60s` 被过滤。
  - UA 输出不受数量上限限制，默认 `pushObject=UA`。
  - UA 中产品热度最高的 1 条被提交给 Product 审核，且不占 `3*n`。
  - Product profile 下按 7/30/90 三窗口分别选出播放 Top20、点赞 Top10、评论 Top5 的并集。
  - Product 窗口去重优先级为 7天、30天、90天。
  - `TIKTOK_PRODUCT_PER_WINDOW_LIMIT=1` 时 Product 主输出最多 3 条。
  - Product-only 输出为 `ALL`，UA-only 输出为 `UA`，重复 URL 合并为 `ALL`。
  - TikTok 结果绕过全局 cap，`x/ins` 仍被 cap。
- 回归测试：
  - `python -m py_compile run_pipeline.py scripts/tiktok_keyword_discovery.py scripts/phase1_scrape.py`
  - 运行 TikTok Discovery、push caps、TikTok push object、pipeline merge 相关 unittest。
  - mock 双路线运行，验证最终 `skill_runs/hotspots_tiktok.json` 格式兼容现有飞书推送。

## Assumptions
- `ALL` 继续表示“UA + 产品”，TikTok 不再产出单独 `产品` 推送对象。
- Product 路线按用户要求去除审核机制，但仍保留基础 URL、时间、时长和去重处理。
- 旧 Apify TikTok 文件不强制物理删除，只从主流程入口移除；如需彻底删除 legacy 文件，可另开一次清理。
- Product 额外接收的 UA 提交项最多 1 条，只有通过产品审核后才进入 Product 输出。
