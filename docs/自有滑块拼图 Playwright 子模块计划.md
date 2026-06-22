# 自有滑块拼图 Playwright 子模块计划

## Summary
- 新增一个通用 Python 子模块，用 Playwright 打开自有页面、识别圆形拼图偏移、拖动底部滑块，让内外圈对齐。
- 使用 `Pillow` 做截图像素分析；模块提供可复用 API 和 CLI，便于接入现有脚本或单独调试。
- 边界明确：只用于自有页面/测试页面，不自动操作第三方平台验证弹窗。

## Public Interface
- 新增 `scripts/slider_puzzle_solver.py`：
  - `SliderPuzzleConfig(container_selector, track_selector, handle_selector, inner_selector=None, success_selector=None, rotation_degrees=360, max_attempts=3, tolerance_score=0.92)`
  - `solve_slider_puzzle(page, config) -> SliderPuzzleResult`
  - `SliderPuzzleResult(success, drag_px, angle_delta, score, attempts, error)`
- CLI：
  - `python scripts/slider_puzzle_solver.py --url <url> --container <selector> --track <selector> --handle <selector> --success <selector>`
  - 可选参数：`--inner-selector`、`--rotation-degrees`、`--headless/--visible-browser`、`--screenshot-out`。

## Implementation Changes
- 图像流程：
  - 等待拼图容器、轨道、滑块手柄可见。
  - 对容器截图，使用 Pillow 裁剪拼图区。
  - 通过 inner selector 的 bounding box 优先定位内圈；没有 inner selector 时用圆形边缘和透明/亮度变化推断中心与半径。
  - 将内圈边缘与外圈相邻环形区域转成极坐标采样，对 0-359 度做相关性匹配，得到最佳对齐角度。
  - 按 `drag_px = angle_delta / rotation_degrees * track_draggable_width` 映射滑块位移。
- Playwright 操作：
  - 使用 `page.mouse.move/down/move/up` 拖动滑块，不直接改 DOM 值。
  - 每次释放后等待页面状态稳定，再通过 `success_selector` 或重新计算对齐分数验证。
  - 最多重试 3 次，后续重试只做小幅修正。
- 依赖：
  - `requirements.txt` 增加 `Pillow>=10.0.0`。

## Test Plan
- 新增 `tests/test_slider_puzzle_solver.py`：
  - 用合成圆形拼图图片测试角度识别：0、45、90、180、270 度。
  - 测试拖动距离映射：角度到 track 宽度的换算。
  - 测试失败场景：缺少 selector、容器截图为空、分数低于阈值。
- 新增本地 fixture 页面，复刻你给的图片样式：圆形图片、旋转内圈、底部滑块、成功状态。
- Playwright 集成测试打开 fixture 页面，调用 `solve_slider_puzzle` 后断言成功状态出现。
- 验证命令：
  - `python -m unittest tests.test_slider_puzzle_solver`
  - `python -m py_compile scripts/slider_puzzle_solver.py`

## Assumptions
- 自有组件的滑块水平位移与内圈旋转角度线性对应，默认满轨道等于 `360` 度。
- 页面能提供稳定 selector；若能提供 `inner_selector`，识别会更可靠。
- 本模块不会默认接入 TikTok/X/Instagram 验证流程；如后续要接入，只接入你们自有页面或内部测试环境。
