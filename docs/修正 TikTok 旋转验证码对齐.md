# 调整人工确认模式释放行为

**Summary**
- 保留“双方向候选”识别策略，用 `angle` 与 `360-angle` 比较视觉残差来减少过转。
- 修改人工确认模式：自动程序拖到最佳位置后必须释放鼠标，让人工在释放后接手确认。
- 不再使用 `heldForManualConfirmation=true` 作为成功状态。

**Key Changes**
- 在 `scripts/slider_puzzle_solver.py` 的无 `success_selector` 路径中：
  - 自动按下滑块，依次评估候选方向。
  - 选择视觉残差最小的目标位置。
  - 移动到最佳位置后执行 `page.mouse.up()`。
  - 释放后等待短时间，让 TikTok 页面进入可人工确认状态。
- 结果字段调整：
  - `heldForManualConfirmation` 改为始终 `false` 或移除使用。
  - 新增/透传 `releasedForManualConfirmation=true`，表示程序已拖到位并释放，等待人工确认。
  - 保留 `selectedDirection`、`alignmentError`、`candidateCount`、`dragPx`、`angleDelta`、`score`、`attempts`。
- Discovery 流程保持原样：
  - 如果释放后验证码仍存在，继续写 `verification_state.json` 并等待人工处理。
  - 如果释放后页面恢复正常，标记 `verification_state.json.status="resolved"` 并继续采集素材。

**Test Plan**
- 更新单测覆盖：
  - 人工确认模式会 `mouse.down()` 一次，并最终 `mouse.up()` 一次。
  - 选择 `angle` 或 `360-angle` 中残差更小的方向。
  - 接近 `0°` 误判时走 fallback 候选，而不是不拖动。
  - 释放后结果包含 `releasedForManualConfirmation=true`。
- 运行：
  - `python -m unittest tests.test_slider_puzzle_solver tests.test_tiktok_keyword_discovery`
- 真实验证：
  - 启动 TikTok discovery：1 个搜索词、5 个素材、visible browser。
  - 触发验证码后检查滑块是否自动旋转到位并释放。
  - 人工接手确认后，确认 discovery 能继续或记录等待状态。

**Assumptions**
- “人工确认”指程序释放鼠标后，由人工在 TikTok 界面上点击/确认/继续处理。
- 只改人工确认路径；带 `success_selector` 的自动解法不改变释放逻辑。
- 如果释放瞬间 TikTok 判定失败并重置，后续再根据真实截图继续调识别和候选策略。
