from __future__ import annotations

import argparse
import json
import math
import socket
import time
from dataclasses import asdict, dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover - exercised only when dependency is missing.
    raise RuntimeError("Pillow is required for slider puzzle solving. Install requirements.txt first.") from exc


ANGLE_SAMPLE_COUNT = 360
RAY_STEP_DEGREES = 5
RAY_WIDTH_PIXELS = 3
RAY_DESCRIPTOR_SAMPLES = 20
ZERO_FALLBACK_MIN_DEGREES = 20
ZERO_FALLBACK_MAX_DEGREES = 320
ANGLE_TOLERANCE_DEGREES = 2.5
DRAG_EFFECTIVE_MIN_PX = 8.0
CAPTCHA_STABLE_MAX_PIXEL_DIFF = 8.0
CAPTCHA_STABLE_WAIT_MS = 120
CAPTCHA_READY_TIMEOUT_MS = 2500
FUSION_AGREEMENT_MAX_DEGREES = 12.0
FUSION_WEIGHTS = {
    "ray": 0.30,
    "horizontal": 0.15,
    "vertical": 0.10,
    "neighbor": 0.10,
    "boundary": 0.35,
}
BLOCKED_PUBLIC_HOST_SUFFIXES = (
)


@dataclass(frozen=True)
class SliderPuzzleConfig:
    container_selector: str
    track_selector: str
    handle_selector: str
    inner_selector: str | None = None
    success_selector: str | None = None
    sample_dir: str | None = None
    rotation_degrees: float = 360
    inner_clockwise_rotation_degrees: float = 180.0
    outer_counterclockwise_rotation_degrees: float = 180.0
    manual_candidate_inner_rotation_degrees: tuple[float, ...] = ()
    manual_candidate_refine_inner_offsets: tuple[float, ...] = (-10.0, -5.0, 5.0, 10.0)
    manual_candidate_refine_top_k: int = 1
    max_attempts: int = 3
    tolerance_score: float = 0.92
    drag_probe_px: float = 12.0
    drag_probe_wait_ms: int = 120
    drag_strategy_max: int = 4
    drag_retry_reset_ms: int = 160
    hit_test_radius_px: float = 10.0
    max_no_effect_candidates: int = 2
    drag_effective_min_px: float = 12.0
    drag_effective_track_ratio: float = 0.04
    drag_effective_ratio: float = 0.50
    weak_drag_max_px: float = 12.0
    actual_target_tolerance_px: float = 4.0
    release_alignment_error_max: float = 8.0
    closed_loop_max_rounds: int = 1
    closed_loop_pixel_steps: tuple[float, ...] = ()
    closed_loop_inner_angle_steps: tuple[float, ...] = (12.0, 18.0)
    closed_loop_min_improvement: float = 2.0
    release_score_min: float = 0.45
    release_confidence_margin_min: float = 0.02
    release_require_effective: bool = True
    release_require_changed: bool = True
    horizontal_line_count: int = 5
    horizontal_line_span_ratio: float = 0.72
    horizontal_sample_step_px: int = 4
    horizontal_patch_height_px: int = 3
    vertical_line_count: int = 5
    vertical_line_span_ratio: float = 0.72
    vertical_sample_step_px: int = 4
    vertical_patch_width_px: int = 3
    neighbor_angle_offsets: tuple[float, ...] = (-8.0, 0.0, 8.0)
    neighbor_radius_offsets: tuple[float, ...] = (-4.0, 0.0, 4.0)
    neighbor_patch_size_px: int = 3
    neighbor_top_k: int = 2
    boundary_enabled: bool = True
    boundary_min_lines: int = 2
    boundary_min_line_span_degrees: float = 8.0
    boundary_min_line_separation_degrees: float = 20.0
    boundary_edge_threshold: float = 18.0
    boundary_inner_band_px: float = 10.0
    boundary_outer_band_px: float = 12.0
    boundary_gap_px: float = 2.0
    boundary_high_conf_min_max_span: float = 15.0
    boundary_high_conf_min_top2_avg_span: float = 12.0
    boundary_short_segment_span: float = 10.0
    boundary_refine_inner_offsets: tuple[float, ...] = (-18.0, -12.0, -6.0, -3.0, 3.0, 6.0, 12.0, 18.0)
    boundary_fast_path_enabled: bool = True
    boundary_fast_path_min_score: float = 0.55
    boundary_fast_path_min_margin: float = 0.05
    residual_trend_refine_enabled: bool = True
    residual_trend_refine_max: int = 2
    residual_trend_refine_min_error: float = 8.0
    residual_trend_refine_max_error: float = 70.0
    residual_trend_refine_inner_steps: tuple[float, ...] = (4.0, 8.0)
    residual_trend_boundary_quality_min: float = 0.35
    release_unchanged_alignment_error_max: float = 2.0
    release_unchanged_boundary_score_min: float = 0.95
    release_unchanged_confidence_margin_min: float = 0.10
    ray_fast_path_enabled: bool = True
    ray_fast_path_min_score: float = 0.90
    ray_fast_path_min_margin: float = 0.0
    ray_weight: float = 0.30
    horizontal_weight: float = 0.15
    vertical_weight: float = 0.10
    neighbor_weight: float = 0.10
    boundary_weight: float = 0.35
    fusion_agreement_max_degrees: float = FUSION_AGREEMENT_MAX_DEGREES
    fusion_confidence_margin_min: float = 0.02
    unstable_fusion_agreement_degrees: float = 45.0


@dataclass(frozen=True)
class SliderPuzzleResult:
    success: bool
    drag_px: float
    angle_delta: float
    score: float
    attempts: int
    error: str = ""
    held_for_manual_confirmation: bool = False
    released_for_manual_confirmation: bool = False
    selected_direction: str = ""
    alignment_error: float = 0.0
    candidate_count: int = 0
    sample_dir: str = ""
    sample_count: int = 0
    matched_ray_count: int = 0
    comparable_ray_count: int = 0
    ray_step_degrees: int = RAY_STEP_DEGREES
    ray_width_pixels: int = RAY_WIDTH_PIXELS
    bounded_fallback_applied: bool = False
    input_stable: bool = True
    drag_effective: bool = True
    handle_delta_px: float = 0.0
    pre_release_changed: bool = False
    confidence_margin: float = 0.0
    candidate_evaluations: list[dict[str, Any]] = field(default_factory=list)
    drag_strategy: str = ""
    drag_probe_effective: bool = False
    weak_drag_effect: bool = False
    closed_loop_rounds: int = 0
    closed_loop_improved: bool = False
    release_blocked_reason: str = ""
    slider_progress: float = 0.0
    inner_rotation_degrees: float = 0.0
    outer_rotation_degrees: float = 0.0
    relative_rotation_degrees: float = 0.0
    fusion_agreement_degrees: float = 0.0
    selected_method: str = ""
    local_refine_applied: bool = False
    candidate_diagnostics: dict[str, Any] = field(default_factory=dict)
    boundary_line_count: int = 0
    boundary_score: float = 0.0
    boundary_confidence_margin: float = 0.0
    boundary_angle_delta: float = 0.0
    boundary_top_angles: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class AngleEstimate:
    angle_delta: float
    score: float
    center_x: float
    center_y: float
    inner_radius: float
    matched_ray_count: int = 0
    comparable_ray_count: int = 0
    candidate_count: int = 0
    ray_step_degrees: int = RAY_STEP_DEGREES
    ray_width_pixels: int = RAY_WIDTH_PIXELS
    bounded_fallback_applied: bool = False
    confidence_margin: float = 0.0
    second_best_angle_delta: float = 0.0
    method_scores: dict[str, float] = field(default_factory=dict)
    method_angles: dict[str, float] = field(default_factory=dict)
    fusion_agreement_degrees: float = 0.0
    selected_method: str = "ray"
    boundary_line_count: int = 0
    boundary_score: float = 0.0
    boundary_confidence_margin: float = 0.0
    boundary_angle_delta: float = 0.0
    boundary_top_angles: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class _RayAlignmentCandidate:
    angle_delta: float
    score: float
    matched_ray_count: int
    comparable_ray_count: int
    candidate_count: int
    total_distance: float
    bounded_fallback_applied: bool = False
    confidence_margin: float = 0.0
    second_best_angle_delta: float = 0.0


@dataclass(frozen=True)
class _ManualDragCandidate:
    direction: str
    angle_delta: float
    target_x: float
    drag_px: float


@dataclass(frozen=True)
class _ManualDragEvaluation:
    candidate: _ManualDragCandidate
    estimate: AngleEstimate
    alignment_error: float


@dataclass(frozen=True)
class _AlignmentMethodCandidate:
    method: str
    weight: float
    candidate: _RayAlignmentCandidate


@dataclass(frozen=True)
class _BoundaryAlignmentResult:
    candidate: _RayAlignmentCandidate
    line_count: int = 0
    top_angles: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class _BoundaryDescriptor:
    values: list[float]
    edge_strength: float


@dataclass(frozen=True)
class _DragStrategy:
    name: str
    start_x: float
    start_y: float


def solve_slider_puzzle(page: Any, config: SliderPuzzleConfig) -> SliderPuzzleResult:
    """Solve a circular slider puzzle on a self-owned page using Playwright mouse input."""
    validation_error = _validate_config(config)
    if validation_error:
        return SliderPuzzleResult(False, 0.0, 0.0, 0.0, 0, validation_error)
    url_error = _validate_page_url(str(getattr(page, "url", "") or ""))
    if url_error:
        return SliderPuzzleResult(False, 0.0, 0.0, 0.0, 0, url_error)

    if not config.success_selector:
        return _drag_for_manual_confirmation(page, config)

    total_drag_px = 0.0
    last_angle = 0.0
    last_score = 0.0

    for attempt in range(1, max(1, int(config.max_attempts)) + 1):
        try:
            estimate = estimate_slider_angle_from_page(page, config)
            last_angle = estimate.angle_delta
            last_score = estimate.score
        except Exception as exc:
            return SliderPuzzleResult(False, total_drag_px, last_angle, last_score, attempt, _clean_error(exc))

        if _angle_is_zero(estimate.angle_delta, config.rotation_degrees):
            if _success_selector_visible(page, config):
                return SliderPuzzleResult(True, total_drag_px, estimate.angle_delta, estimate.score, attempt)
            if not config.success_selector:
                return SliderPuzzleResult(True, total_drag_px, estimate.angle_delta, estimate.score, attempt)

        try:
            track_box, handle_box = _track_and_handle_boxes(page, config)
        except Exception as exc:
            return SliderPuzzleResult(False, total_drag_px, estimate.angle_delta, estimate.score, attempt, _clean_error(exc))

        drag_px = drag_distance_for_angle(
            estimate.angle_delta,
            float(track_box["width"]),
            float(handle_box["width"]),
            _slider_relative_rotation_degrees(config),
        )
        if drag_px <= 0:
            return SliderPuzzleResult(False, total_drag_px, estimate.angle_delta, estimate.score, attempt, "computed drag distance is zero")

        try:
            _drag_handle(page, handle_box, drag_px)
            total_drag_px += drag_px
            page.wait_for_timeout(350)
        except Exception as exc:
            return SliderPuzzleResult(False, total_drag_px, estimate.angle_delta, estimate.score, attempt, _clean_error(exc))

        if _success_selector_visible(page, config):
            return SliderPuzzleResult(True, total_drag_px, estimate.angle_delta, estimate.score, attempt)

    attempts = max(1, int(config.max_attempts))
    return SliderPuzzleResult(False, total_drag_px, last_angle, last_score, attempts, "max attempts exhausted")


def estimate_slider_angle_from_page(page: Any, config: SliderPuzzleConfig) -> AngleEstimate:
    container = page.locator(config.container_selector).first
    container.wait_for(state="visible", timeout=5000)
    _ = _visible_bounding_box(page, config.track_selector)
    _ = _visible_bounding_box(page, config.handle_selector)
    stable_error = _wait_for_captcha_ready(page, config)
    if stable_error:
        raise RuntimeError(stable_error)
    container_box = container.bounding_box()
    if not container_box:
        raise RuntimeError(f"container has no bounding box: {config.container_selector}")
    inner_bbox = None
    if config.inner_selector:
        inner_box = _visible_bounding_box(page, config.inner_selector)
        screenshot_probe = Image.open(BytesIO(container.screenshot())).convert("RGBA")
        scale_x = screenshot_probe.width / max(1.0, float(container_box["width"]))
        scale_y = screenshot_probe.height / max(1.0, float(container_box["height"]))
        inner_bbox = (
            (float(inner_box["x"]) - float(container_box["x"])) * scale_x,
            (float(inner_box["y"]) - float(container_box["y"])) * scale_y,
            float(inner_box["width"]) * scale_x,
            float(inner_box["height"]) * scale_y,
        )
        image = screenshot_probe
    else:
        image = Image.open(BytesIO(container.screenshot())).convert("RGBA")
    return estimate_angle_from_image(image, inner_bbox=inner_bbox, config=config)


def _wait_for_captcha_ready(page: Any, config: SliderPuzzleConfig) -> str:
    deadline = _monotonic_time(page) + CAPTCHA_READY_TIMEOUT_MS / 1000.0
    last_image: Image.Image | None = None
    last_error = ""
    while _monotonic_time(page) <= deadline:
        try:
            container = page.locator(config.container_selector).first
            text = ""
            try:
                text = str(container.inner_text(timeout=200) or "").lower()
            except Exception:
                text = ""
            if any(marker in text for marker in ("verifying", "unable to verify", "try again")):
                last_error = "captcha_not_ready: challenge is verifying or showing an error"
                page.wait_for_timeout(CAPTCHA_STABLE_WAIT_MS)
                continue
            if text and not any(marker in text for marker in ("drag", "slider", "puzzle")):
                last_error = "captcha_not_ready: challenge prompt is not ready"
                page.wait_for_timeout(CAPTCHA_STABLE_WAIT_MS)
                continue
            image = Image.open(BytesIO(container.screenshot())).convert("RGBA")
            if last_image is not None and _mean_image_difference(last_image, image) <= CAPTCHA_STABLE_MAX_PIXEL_DIFF:
                return ""
            last_image = image
            last_error = "captcha_not_ready: screenshot is not stable"
        except Exception as exc:
            last_error = f"captcha_not_ready: {_clean_error(exc)}"
        page.wait_for_timeout(CAPTCHA_STABLE_WAIT_MS)
    if last_error == "captcha_not_ready: screenshot is not stable" and last_image is not None:
        return ""
    return last_error or "captcha_not_ready"


def estimate_angle_from_image(
    image: Image.Image,
    inner_bbox: tuple[float, float, float, float] | None = None,
    config: SliderPuzzleConfig | None = None,
) -> AngleEstimate:
    if image.width < 20 or image.height < 20:
        raise RuntimeError("container screenshot is too small")
    rgba = image.convert("RGBA")
    center_x, center_y, inner_radius = infer_inner_circle(rgba, inner_bbox)
    if inner_radius < 8:
        raise RuntimeError("inner circle radius is too small")

    outer_radius = infer_outer_circle_radius(rgba, center_x, center_y, inner_radius)
    inner_start = max(2.0, inner_radius * 0.18)
    inner_end = min(inner_radius - 4.0, max(inner_start + 4.0, inner_radius * 0.94))
    outer_start = min(outer_radius - 4.0, inner_radius + 4.0)
    outer_end = max(outer_start + 4.0, outer_radius - 4.0)
    if inner_end <= inner_start or outer_end <= outer_start:
        raise RuntimeError("not enough circular ray area around the inner puzzle")

    if bool(getattr(config, "boundary_enabled", True)):
        boundary_result = best_boundary_alignment_angle(
            rgba,
            center_x,
            center_y,
            inner_radius,
            outer_radius,
            step_degrees=RAY_STEP_DEGREES,
            min_lines=max(1, int(getattr(config, "boundary_min_lines", 2))),
            min_line_span_degrees=float(getattr(config, "boundary_min_line_span_degrees", 8.0)),
            min_line_separation_degrees=float(getattr(config, "boundary_min_line_separation_degrees", 20.0)),
            edge_threshold=float(getattr(config, "boundary_edge_threshold", 18.0)),
            inner_band_px=float(getattr(config, "boundary_inner_band_px", 10.0)),
            outer_band_px=float(getattr(config, "boundary_outer_band_px", 12.0)),
            gap_px=float(getattr(config, "boundary_gap_px", 2.0)),
        )
    else:
        boundary_result = _BoundaryAlignmentResult(_empty_ray_alignment_candidate(0, bounded_fallback_applied=True))
    boundary_candidate = boundary_result.candidate
    boundary_fast_path = (
        config is not None
        and bool(getattr(config, "boundary_fast_path_enabled", True))
        and int(boundary_result.line_count) >= max(1, int(getattr(config, "boundary_min_lines", 2)))
        and float(boundary_candidate.score) >= float(getattr(config, "boundary_fast_path_min_score", 0.55))
        and float(boundary_candidate.confidence_margin) >= float(getattr(config, "boundary_fast_path_min_margin", 0.05))
    )
    if boundary_fast_path:
        return AngleEstimate(
            float(boundary_candidate.angle_delta),
            float(boundary_candidate.score),
            float(center_x),
            float(center_y),
            float(inner_radius),
            matched_ray_count=int(boundary_candidate.matched_ray_count),
            comparable_ray_count=int(boundary_candidate.comparable_ray_count),
            candidate_count=int(boundary_candidate.candidate_count),
            ray_step_degrees=RAY_STEP_DEGREES,
            ray_width_pixels=RAY_WIDTH_PIXELS,
            bounded_fallback_applied=False,
            confidence_margin=float(boundary_candidate.confidence_margin),
            second_best_angle_delta=float(boundary_candidate.second_best_angle_delta),
            method_scores={"boundary": float(boundary_candidate.score)},
            method_angles={"boundary": float(boundary_candidate.angle_delta)},
            fusion_agreement_degrees=0.0,
            selected_method="boundary",
            boundary_line_count=int(boundary_result.line_count),
            boundary_score=float(boundary_candidate.score),
            boundary_confidence_margin=float(boundary_candidate.confidence_margin),
            boundary_angle_delta=float(boundary_candidate.angle_delta),
            boundary_top_angles=list(boundary_result.top_angles),
        )

    inner_rays = radial_ray_descriptors(
        rgba,
        center_x,
        center_y,
        inner_start,
        inner_end,
        step_degrees=RAY_STEP_DEGREES,
        width_pixels=RAY_WIDTH_PIXELS,
        radial_samples=RAY_DESCRIPTOR_SAMPLES,
    )
    outer_rays = radial_ray_descriptors(
        rgba,
        center_x,
        center_y,
        outer_start,
        outer_end,
        step_degrees=RAY_STEP_DEGREES,
        width_pixels=RAY_WIDTH_PIXELS,
        radial_samples=RAY_DESCRIPTOR_SAMPLES,
    )
    ray_candidate = best_ray_alignment_angle(outer_rays, inner_rays, step_degrees=RAY_STEP_DEGREES)
    boundary_has_enough_lines = int(boundary_result.line_count) >= max(1, int(getattr(config, "boundary_min_lines", 2)))
    boundary_comparable = boundary_has_enough_lines and float(boundary_candidate.score) > 0.0
    ray_fast_path = (
        config is not None
        and bool(getattr(config, "ray_fast_path_enabled", True))
        and float(ray_candidate.score) >= float(getattr(config, "ray_fast_path_min_score", 0.90))
        and float(ray_candidate.confidence_margin) >= float(getattr(config, "ray_fast_path_min_margin", 0.0))
    )
    if ray_fast_path:
        method_scores = {"ray": float(ray_candidate.score), "boundary": float(boundary_candidate.score)}
        method_angles = {"ray": float(ray_candidate.angle_delta), "boundary": float(boundary_candidate.angle_delta)}
        fusion_agreement_degrees = (
            _angular_distance(
                float(ray_candidate.angle_delta),
                float(boundary_candidate.angle_delta),
                float(getattr(config, "rotation_degrees", 360.0)),
            )
            if boundary_comparable
            else 0.0
        )
        return AngleEstimate(
            float(ray_candidate.angle_delta),
            float(ray_candidate.score),
            float(center_x),
            float(center_y),
            float(inner_radius),
            matched_ray_count=int(ray_candidate.matched_ray_count),
            comparable_ray_count=int(ray_candidate.comparable_ray_count),
            candidate_count=int(ray_candidate.candidate_count),
            ray_step_degrees=RAY_STEP_DEGREES,
            ray_width_pixels=RAY_WIDTH_PIXELS,
            bounded_fallback_applied=bool(ray_candidate.bounded_fallback_applied),
            confidence_margin=float(ray_candidate.confidence_margin),
            second_best_angle_delta=float(ray_candidate.second_best_angle_delta),
            method_scores=method_scores,
            method_angles=method_angles,
            fusion_agreement_degrees=float(fusion_agreement_degrees),
            selected_method="ray",
            boundary_line_count=int(boundary_result.line_count),
            boundary_score=float(boundary_candidate.score),
            boundary_confidence_margin=float(boundary_candidate.confidence_margin),
            boundary_angle_delta=float(boundary_candidate.angle_delta),
            boundary_top_angles=list(boundary_result.top_angles),
        )
    horizontal_candidate = best_ray_alignment_angle(
        linear_strip_descriptors(
            rgba,
            center_x,
            center_y,
            outer_start,
            outer_end,
            orientation="horizontal",
            line_count=int(getattr(config, "horizontal_line_count", 5)),
            span_ratio=float(getattr(config, "horizontal_line_span_ratio", 0.72)),
            sample_step_px=int(getattr(config, "horizontal_sample_step_px", 4)),
            cross_patch_px=int(getattr(config, "horizontal_patch_height_px", 3)),
            step_degrees=RAY_STEP_DEGREES,
        ),
        linear_strip_descriptors(
            rgba,
            center_x,
            center_y,
            inner_start,
            inner_end,
            orientation="horizontal",
            line_count=int(getattr(config, "horizontal_line_count", 5)),
            span_ratio=float(getattr(config, "horizontal_line_span_ratio", 0.72)),
            sample_step_px=int(getattr(config, "horizontal_sample_step_px", 4)),
            cross_patch_px=int(getattr(config, "horizontal_patch_height_px", 3)),
            step_degrees=RAY_STEP_DEGREES,
        ),
        step_degrees=RAY_STEP_DEGREES,
    )
    vertical_candidate = best_ray_alignment_angle(
        linear_strip_descriptors(
            rgba,
            center_x,
            center_y,
            outer_start,
            outer_end,
            orientation="vertical",
            line_count=int(getattr(config, "vertical_line_count", 5)),
            span_ratio=float(getattr(config, "vertical_line_span_ratio", 0.72)),
            sample_step_px=int(getattr(config, "vertical_sample_step_px", 4)),
            cross_patch_px=int(getattr(config, "vertical_patch_width_px", 3)),
            step_degrees=RAY_STEP_DEGREES,
        ),
        linear_strip_descriptors(
            rgba,
            center_x,
            center_y,
            inner_start,
            inner_end,
            orientation="vertical",
            line_count=int(getattr(config, "vertical_line_count", 5)),
            span_ratio=float(getattr(config, "vertical_line_span_ratio", 0.72)),
            sample_step_px=int(getattr(config, "vertical_sample_step_px", 4)),
            cross_patch_px=int(getattr(config, "vertical_patch_width_px", 3)),
            step_degrees=RAY_STEP_DEGREES,
        ),
        step_degrees=RAY_STEP_DEGREES,
    )
    neighbor_candidate = best_ray_alignment_angle(
        neighbor_patch_descriptors(
            rgba,
            center_x,
            center_y,
            outer_start,
            outer_end,
            angle_offsets=tuple(getattr(config, "neighbor_angle_offsets", (-8.0, 0.0, 8.0))),
            radius_offsets=tuple(getattr(config, "neighbor_radius_offsets", (-4.0, 0.0, 4.0))),
            patch_size_px=int(getattr(config, "neighbor_patch_size_px", 3)),
            top_k=int(getattr(config, "neighbor_top_k", 2)),
            step_degrees=RAY_STEP_DEGREES,
        ),
        neighbor_patch_descriptors(
            rgba,
            center_x,
            center_y,
            inner_start,
            inner_end,
            angle_offsets=tuple(getattr(config, "neighbor_angle_offsets", (-8.0, 0.0, 8.0))),
            radius_offsets=tuple(getattr(config, "neighbor_radius_offsets", (-4.0, 0.0, 4.0))),
            patch_size_px=int(getattr(config, "neighbor_patch_size_px", 3)),
            top_k=int(getattr(config, "neighbor_top_k", 2)),
            step_degrees=RAY_STEP_DEGREES,
        ),
        step_degrees=RAY_STEP_DEGREES,
    )
    candidate, method_scores, method_angles, fusion_agreement_degrees, selected_method = fuse_alignment_candidates(
        [
            _AlignmentMethodCandidate("ray", float(getattr(config, "ray_weight", FUSION_WEIGHTS["ray"])), ray_candidate),
            _AlignmentMethodCandidate("horizontal", float(getattr(config, "horizontal_weight", FUSION_WEIGHTS["horizontal"])), horizontal_candidate),
            _AlignmentMethodCandidate("vertical", float(getattr(config, "vertical_weight", FUSION_WEIGHTS["vertical"])), vertical_candidate),
            _AlignmentMethodCandidate("neighbor", float(getattr(config, "neighbor_weight", FUSION_WEIGHTS["neighbor"])), neighbor_candidate),
            _AlignmentMethodCandidate("boundary", float(getattr(config, "boundary_weight", FUSION_WEIGHTS["boundary"])), boundary_result.candidate),
        ],
        rotation_degrees=float(getattr(config, "rotation_degrees", 360.0)),
        agreement_max_degrees=float(getattr(config, "fusion_agreement_max_degrees", FUSION_AGREEMENT_MAX_DEGREES)),
    )
    return AngleEstimate(
        float(candidate.angle_delta),
        float(candidate.score),
        float(center_x),
        float(center_y),
        float(inner_radius),
        matched_ray_count=candidate.matched_ray_count,
        comparable_ray_count=candidate.comparable_ray_count,
        candidate_count=candidate.candidate_count,
        ray_step_degrees=RAY_STEP_DEGREES,
        ray_width_pixels=RAY_WIDTH_PIXELS,
        bounded_fallback_applied=candidate.bounded_fallback_applied,
        confidence_margin=float(candidate.confidence_margin),
        second_best_angle_delta=float(candidate.second_best_angle_delta),
        method_scores=method_scores,
        method_angles=method_angles,
        fusion_agreement_degrees=float(fusion_agreement_degrees),
        selected_method=selected_method,
        boundary_line_count=int(boundary_result.line_count),
        boundary_score=float(boundary_result.candidate.score),
        boundary_confidence_margin=float(boundary_result.candidate.confidence_margin),
        boundary_angle_delta=float(boundary_result.candidate.angle_delta),
        boundary_top_angles=list(boundary_result.top_angles),
    )


def infer_inner_circle(image: Image.Image, inner_bbox: tuple[float, float, float, float] | None = None) -> tuple[float, float, float]:
    if inner_bbox:
        x, y, width, height = inner_bbox
        return x + width / 2.0, y + height / 2.0, min(width, height) / 2.0

    puzzle_bbox = _largest_square_content_component_bbox(image)
    if puzzle_bbox is not None:
        left, top, right, bottom = puzzle_bbox
        width = max(1, right - left)
        height = max(1, bottom - top)
        return left + width / 2.0, top + height / 2.0, min(width, height) * 0.25

    content_bbox = _visible_content_bbox(image)
    if content_bbox is None:
        return image.width / 2.0, image.height / 2.0, min(image.width, image.height) * 0.24

    left, top, right, bottom = content_bbox
    width = max(1, right - left)
    height = max(1, bottom - top)
    return left + width / 2.0, top + height / 2.0, min(width, height) * 0.25


def _largest_square_content_component_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    width = rgba.width
    height = rgba.height
    visited = bytearray(width * height)
    best_bbox: tuple[int, int, int, int] | None = None
    best_score = 0.0

    for start_y in range(height):
        for start_x in range(width):
            start_index = start_y * width + start_x
            if visited[start_index] or not _pixel_has_content(pixels[start_x, start_y]):
                visited[start_index] = 1
                continue
            stack = [(start_x, start_y)]
            visited[start_index] = 1
            left = right = start_x
            top = bottom = start_y
            area = 0
            while stack:
                x, y = stack.pop()
                area += 1
                left = min(left, x)
                right = max(right, x)
                top = min(top, y)
                bottom = max(bottom, y)
                for next_x, next_y in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if next_x < 0 or next_x >= width or next_y < 0 or next_y >= height:
                        continue
                    next_index = next_y * width + next_x
                    if visited[next_index]:
                        continue
                    visited[next_index] = 1
                    if _pixel_has_content(pixels[next_x, next_y]):
                        stack.append((next_x, next_y))
            box_width = right - left + 1
            box_height = bottom - top + 1
            if box_width < 40 or box_height < 40:
                continue
            ratio = box_width / max(1, box_height)
            if ratio < 0.65 or ratio > 1.45:
                continue
            fill_ratio = area / max(1, box_width * box_height)
            if fill_ratio < 0.08:
                continue
            score = area * (1.0 - min(0.5, abs(1.0 - ratio)))
            if score > best_score:
                best_score = score
                best_bbox = (left, top, right + 1, bottom + 1)
    return best_bbox


def infer_outer_circle_radius(image: Image.Image, center_x: float, center_y: float, inner_radius: float) -> float:
    max_radius = min(center_x, center_y, image.width - 1 - center_x, image.height - 1 - center_y)
    if max_radius <= inner_radius + 8:
        return max_radius
    pixels = image.load()
    best_radius = 0.0
    for radius in range(int(math.ceil(inner_radius + 8)), int(math.floor(max_radius)) + 1):
        content_count = 0
        total_count = 0
        for angle in range(0, 360, RAY_STEP_DEGREES):
            theta = math.radians(angle)
            x = int(round(center_x + radius * math.cos(theta)))
            y = int(round(center_y + radius * math.sin(theta)))
            if 0 <= x < image.width and 0 <= y < image.height:
                total_count += 1
                if _pixel_has_content(pixels[x, y]):
                    content_count += 1
        if total_count and content_count / total_count >= 0.30:
            best_radius = float(radius)
    if best_radius > inner_radius + 8:
        return best_radius
    return min(max_radius, max(inner_radius + 12.0, inner_radius * 1.85))


def radial_ray_descriptors(
    image: Image.Image,
    center_x: float,
    center_y: float,
    start_radius: float,
    end_radius: float,
    *,
    step_degrees: int = RAY_STEP_DEGREES,
    width_pixels: int = RAY_WIDTH_PIXELS,
    radial_samples: int = RAY_DESCRIPTOR_SAMPLES,
) -> list[list[float] | None]:
    return [
        _sample_ray_descriptor(
            image,
            center_x,
            center_y,
            float(angle),
            start_radius,
            end_radius,
            width_pixels=width_pixels,
            radial_samples=radial_samples,
        )
        for angle in range(0, 360, step_degrees)
    ]


def linear_strip_descriptors(
    image: Image.Image,
    center_x: float,
    center_y: float,
    start_radius: float,
    end_radius: float,
    *,
    orientation: str,
    line_count: int,
    span_ratio: float,
    sample_step_px: int,
    cross_patch_px: int,
    step_degrees: int = RAY_STEP_DEGREES,
) -> list[list[float] | None]:
    return [
        _sample_linear_strip_descriptor(
            image,
            center_x,
            center_y,
            float(angle),
            start_radius,
            end_radius,
            orientation=orientation,
            line_count=line_count,
            span_ratio=span_ratio,
            sample_step_px=sample_step_px,
            cross_patch_px=cross_patch_px,
        )
        for angle in range(0, 360, step_degrees)
    ]


def _sample_linear_strip_descriptor(
    image: Image.Image,
    center_x: float,
    center_y: float,
    angle_degrees: float,
    start_radius: float,
    end_radius: float,
    *,
    orientation: str,
    line_count: int,
    span_ratio: float,
    sample_step_px: int,
    cross_patch_px: int,
) -> list[float] | None:
    if end_radius <= start_radius or line_count <= 0:
        return None
    pixels = image.load()
    theta = math.radians(angle_degrees)
    mid_radius = (start_radius + end_radius) / 2.0
    anchor_x = center_x + mid_radius * math.cos(theta)
    anchor_y = center_y + mid_radius * math.sin(theta)
    strip_span = max(2.0, (end_radius - start_radius) * max(0.1, min(1.0, span_ratio)))
    line_length = max(4.0, strip_span)
    step = max(1, int(sample_step_px))
    patch_half = max(0, int(cross_patch_px) // 2)
    line_offsets = _evenly_spaced_offsets(int(line_count), strip_span)
    descriptor: list[float] = []
    valid_lines = 0

    for line_offset in line_offsets:
        values: list[tuple[float, float, float, float, float, float, float]] = []
        for primary_offset in _integer_offsets(line_length, step):
            for patch_offset in range(-patch_half, patch_half + 1):
                if orientation == "vertical":
                    x = int(round(anchor_x + line_offset + patch_offset))
                    y = int(round(anchor_y + primary_offset))
                else:
                    x = int(round(anchor_x + primary_offset))
                    y = int(round(anchor_y + line_offset + patch_offset))
                feature = _sample_pixel_feature(pixels, image.width, image.height, x, y)
                if feature is not None:
                    values.append(feature)
        descriptor.extend(_average_feature_values(values))
        if values:
            valid_lines += 1

    if valid_lines < max(2, int(math.ceil(line_count * 0.50))):
        return None
    if _descriptor_variance(descriptor) < 3.0 or _descriptor_spatial_variance(descriptor, 7) < 3.0:
        return None
    return descriptor


def neighbor_patch_descriptors(
    image: Image.Image,
    center_x: float,
    center_y: float,
    start_radius: float,
    end_radius: float,
    *,
    angle_offsets: tuple[float, ...],
    radius_offsets: tuple[float, ...],
    patch_size_px: int,
    top_k: int,
    step_degrees: int = RAY_STEP_DEGREES,
) -> list[list[float] | None]:
    return [
        _sample_neighbor_patch_descriptor(
            image,
            center_x,
            center_y,
            float(angle),
            start_radius,
            end_radius,
            angle_offsets=angle_offsets,
            radius_offsets=radius_offsets,
            patch_size_px=patch_size_px,
            top_k=top_k,
        )
        for angle in range(0, 360, step_degrees)
    ]


def _sample_neighbor_patch_descriptor(
    image: Image.Image,
    center_x: float,
    center_y: float,
    angle_degrees: float,
    start_radius: float,
    end_radius: float,
    *,
    angle_offsets: tuple[float, ...],
    radius_offsets: tuple[float, ...],
    patch_size_px: int,
    top_k: int,
) -> list[float] | None:
    if end_radius <= start_radius or top_k <= 0:
        return None
    pixels = image.load()
    mid_radius = (start_radius + end_radius) / 2.0
    patch_half = max(0, int(patch_size_px) // 2)
    patches: list[tuple[float, list[float]]] = []
    for angle_offset in angle_offsets:
        theta = math.radians(angle_degrees + float(angle_offset))
        for radius_offset in radius_offsets:
            radius = max(start_radius, min(end_radius, mid_radius + float(radius_offset)))
            patch_values: list[tuple[float, float, float, float, float, float, float]] = []
            patch_x = center_x + radius * math.cos(theta)
            patch_y = center_y + radius * math.sin(theta)
            for dy in range(-patch_half, patch_half + 1):
                for dx in range(-patch_half, patch_half + 1):
                    feature = _sample_pixel_feature(
                        pixels,
                        image.width,
                        image.height,
                        int(round(patch_x + dx)),
                        int(round(patch_y + dy)),
                    )
                    if feature is not None:
                        patch_values.append(feature)
            averaged = _average_feature_values(patch_values)
            if patch_values:
                patches.append((averaged[-1], averaged))
    if not patches:
        return None
    patches.sort(key=lambda item: item[0], reverse=True)
    descriptor: list[float] = []
    for _, values in patches[:top_k]:
        descriptor.extend(values)
    while len(descriptor) < max(1, top_k) * 7:
        descriptor.extend([0.0] * 7)
    if _descriptor_variance(descriptor) < 3.0 or _descriptor_spatial_variance(descriptor, 7) < 3.0:
        return None
    return descriptor


def boundary_ring_descriptors(
    image: Image.Image,
    center_x: float,
    center_y: float,
    start_radius: float,
    end_radius: float,
    *,
    step_degrees: int = RAY_STEP_DEGREES,
    tangential_half_width_px: int = 1,
) -> list[_BoundaryDescriptor | None]:
    return [
        _sample_boundary_descriptor(
            image,
            center_x,
            center_y,
            float(angle),
            start_radius,
            end_radius,
            tangential_half_width_px=tangential_half_width_px,
        )
        for angle in range(0, 360, step_degrees)
    ]


def _sample_boundary_descriptor(
    image: Image.Image,
    center_x: float,
    center_y: float,
    angle_degrees: float,
    start_radius: float,
    end_radius: float,
    *,
    tangential_half_width_px: int,
) -> _BoundaryDescriptor | None:
    if end_radius <= start_radius:
        return None
    pixels = image.load()
    theta = math.radians(angle_degrees)
    cos_theta = math.cos(theta)
    sin_theta = math.sin(theta)
    values: list[tuple[float, float, float, float, float, float, float, float, float]] = []
    step = 1.0
    radius = float(start_radius)
    while radius <= float(end_radius) + 1e-6:
        for offset in range(-max(0, int(tangential_half_width_px)), max(0, int(tangential_half_width_px)) + 1):
            x = int(round(center_x + radius * cos_theta - offset * sin_theta))
            y = int(round(center_y + radius * sin_theta + offset * cos_theta))
            feature = _sample_boundary_feature(pixels, image.width, image.height, x, y, cos_theta, sin_theta)
            if feature is not None:
                values.append(feature)
        radius += step
    if len(values) < 3:
        return None
    averaged = [sum(value[index] for value in values) / len(values) for index in range(9)]
    edge_strength = averaged[6]
    if _descriptor_variance(averaged[:7]) < 1.0 and edge_strength < 1.0:
        return None
    return _BoundaryDescriptor(averaged, float(edge_strength))


def best_boundary_alignment_angle(
    image: Image.Image,
    center_x: float,
    center_y: float,
    inner_radius: float,
    outer_radius: float,
    *,
    step_degrees: int,
    min_lines: int,
    min_line_span_degrees: float,
    min_line_separation_degrees: float,
    edge_threshold: float,
    inner_band_px: float,
    outer_band_px: float,
    gap_px: float,
) -> _BoundaryAlignmentResult:
    candidate_count = max(1, int(round(360 / max(1, int(step_degrees)))))
    inner_start = max(2.0, float(inner_radius) - max(2.0, float(inner_band_px)))
    inner_end = max(inner_start + 1.0, float(inner_radius) - max(0.0, float(gap_px)))
    outer_start = min(float(outer_radius) - 1.0, float(inner_radius) + max(0.0, float(gap_px)))
    outer_end = min(float(outer_radius) - 1.0, outer_start + max(2.0, float(outer_band_px)))
    if inner_end <= inner_start or outer_end <= outer_start:
        return _BoundaryAlignmentResult(_empty_ray_alignment_candidate(candidate_count, bounded_fallback_applied=True))

    inner_descriptors = boundary_ring_descriptors(
        image,
        center_x,
        center_y,
        inner_start,
        inner_end,
        step_degrees=step_degrees,
    )
    outer_descriptors = boundary_ring_descriptors(
        image,
        center_x,
        center_y,
        outer_start,
        outer_end,
        step_degrees=step_degrees,
    )
    if len(inner_descriptors) != len(outer_descriptors) or not inner_descriptors:
        return _BoundaryAlignmentResult(_empty_ray_alignment_candidate(candidate_count, bounded_fallback_applied=True))

    candidate_count = len(inner_descriptors)
    edge_threshold = max(1.0, float(edge_threshold))
    candidates: list[tuple[_RayAlignmentCandidate, int, list[dict[str, Any]]]] = []
    for shift_index in range(candidate_count):
        comparable_count = 0
        weighted_distance = 0.0
        weight_total = 0.0
        raw_matches: list[bool] = []
        for angle_index, outer_descriptor in enumerate(outer_descriptors):
            inner_descriptor = inner_descriptors[(angle_index - shift_index) % candidate_count]
            if outer_descriptor is None or inner_descriptor is None:
                raw_matches.append(False)
                continue
            edge_strength = min(float(outer_descriptor.edge_strength), float(inner_descriptor.edge_strength))
            if edge_strength < edge_threshold:
                raw_matches.append(False)
                continue
            distance = _boundary_descriptor_distance(outer_descriptor.values, inner_descriptor.values)
            comparable_count += 1
            weight = max(1.0, edge_strength)
            weighted_distance += distance * weight
            weight_total += weight
            raw_matches.append(distance <= _boundary_match_threshold(edge_strength))

        average_distance = weighted_distance / weight_total if weight_total > 0 else float("inf")
        top_angles = _boundary_line_segments(
            raw_matches,
            step_degrees=step_degrees,
            min_span_degrees=min_line_span_degrees,
            min_separation_degrees=min_line_separation_degrees,
        )
        line_count = len(top_angles)
        matched_samples = sum(1 for matched in raw_matches if matched)
        match_ratio = matched_samples / comparable_count if comparable_count else 0.0
        line_ratio = min(1.0, line_count / max(1, int(min_lines)))
        if line_count >= max(1, int(min_lines)):
            score = min(1.0, 0.55 * line_ratio + 0.45 * match_ratio)
        else:
            score = min(0.18, match_ratio * 0.18)
        candidates.append(
            (
                _RayAlignmentCandidate(
                    angle_delta=float((shift_index * step_degrees) % 360),
                    score=float(score),
                    matched_ray_count=int(line_count),
                    comparable_ray_count=int(comparable_count),
                    candidate_count=int(candidate_count),
                    total_distance=float(average_distance),
                ),
                line_count,
                top_angles,
            )
        )

    valid = [item for item in candidates if item[0].comparable_ray_count > 0 and math.isfinite(item[0].total_distance)]
    if not valid:
        return _BoundaryAlignmentResult(_empty_ray_alignment_candidate(candidate_count, bounded_fallback_applied=True))
    valid.sort(
        key=lambda item: (
            0 if item[1] >= max(1, int(min_lines)) else 1,
            -int(item[1]),
            -float(item[0].score),
            float(item[0].total_distance),
            float(item[0].angle_delta),
        )
    )
    selected, line_count, top_angles = valid[0]
    second = next((item[0] for item in valid[1:] if abs(float(item[0].angle_delta) - float(selected.angle_delta)) > 1e-9), None)
    margin = 0.0
    second_angle = 0.0
    if second is not None:
        second_angle = float(second.angle_delta)
        if math.isfinite(selected.total_distance) and math.isfinite(second.total_distance):
            margin = max(0.0, (float(second.total_distance) - float(selected.total_distance)) / max(1.0, float(selected.total_distance)))
        if int(line_count) >= max(1, int(min_lines)):
            margin = max(margin, min(0.25, 0.08 * int(line_count)))
    selected_with_margin = _RayAlignmentCandidate(
        angle_delta=float(selected.angle_delta),
        score=float(selected.score),
        matched_ray_count=int(selected.matched_ray_count),
        comparable_ray_count=int(selected.comparable_ray_count),
        candidate_count=int(selected.candidate_count),
        total_distance=float(selected.total_distance),
        bounded_fallback_applied=False,
        confidence_margin=float(margin if line_count >= max(1, int(min_lines)) else 0.0),
        second_best_angle_delta=float(second_angle),
    )
    return _BoundaryAlignmentResult(selected_with_margin, int(line_count), list(top_angles[:5]))


def _sample_boundary_feature(
    pixels: Any,
    width: int,
    height: int,
    x: int,
    y: int,
    cos_theta: float,
    sin_theta: float,
) -> tuple[float, float, float, float, float, float, float, float, float] | None:
    if x < 0 or x >= width or y < 0 or y >= height:
        return None
    red, green, blue, alpha = pixels[x, y]
    if alpha <= 20:
        return None
    luma = red * 0.299 + green * 0.587 + blue * 0.114
    rg = red - green
    by = blue - (red + green) / 2.0
    gradient_x, gradient_y = _gradient_xy(pixels, width, height, x, y)
    gradient = math.sqrt(gradient_x * gradient_x + gradient_y * gradient_y)
    if gradient > 1e-6:
        radial = abs((gradient_x * cos_theta + gradient_y * sin_theta) / gradient)
        tangent = abs((-gradient_x * sin_theta + gradient_y * cos_theta) / gradient)
    else:
        radial = 0.0
        tangent = 0.0
    return (
        float(red),
        float(green),
        float(blue),
        float(luma),
        float(rg),
        float(by),
        float(gradient),
        float(radial),
        float(tangent),
    )


def _boundary_descriptor_distance(descriptor_a: list[float], descriptor_b: list[float]) -> float:
    if len(descriptor_a) != len(descriptor_b) or len(descriptor_a) < 9:
        return float("inf")
    color_sum = 0.0
    for index in range(6):
        delta = descriptor_a[index] - descriptor_b[index]
        color_sum += delta * delta
    color_distance = math.sqrt(color_sum / 6.0)
    gradient_distance = abs(descriptor_a[6] - descriptor_b[6])
    orientation_distance = (abs(descriptor_a[7] - descriptor_b[7]) + abs(descriptor_a[8] - descriptor_b[8])) * 80.0
    return color_distance * 0.55 + gradient_distance * 0.25 + orientation_distance * 0.20


def _boundary_match_threshold(edge_strength: float) -> float:
    return max(18.0, min(58.0, 12.0 + float(edge_strength) * 0.90))


def _boundary_line_segments(
    matches: list[bool],
    *,
    step_degrees: int,
    min_span_degrees: float,
    min_separation_degrees: float,
) -> list[dict[str, Any]]:
    if not matches:
        return []
    matches = _bridge_boundary_match_gaps(matches)
    count = len(matches)
    visited = [False] * count
    runs: list[list[int]] = []
    for start in range(count):
        if visited[start] or not matches[start]:
            continue
        run: list[int] = []
        index = start
        while matches[index] and not visited[index]:
            visited[index] = True
            run.append(index)
            index = (index + 1) % count
            if index == start:
                break
        runs.append(run)
    min_samples = max(1, int(math.ceil(float(min_span_degrees) / max(1, int(step_degrees)))))
    candidates: list[dict[str, Any]] = []
    for run in runs:
        if len(run) < min_samples:
            continue
        angles = [float((index * step_degrees) % 360) for index in run]
        center = _weighted_circular_mean([(angle, 1.0) for angle in angles], 360.0)
        candidates.append(
            {
                "angle": float(center),
                "spanDegrees": float(len(run) * max(1, int(step_degrees))),
                "sampleCount": int(len(run)),
            }
        )
    candidates.sort(key=lambda item: (float(item["spanDegrees"]), int(item["sampleCount"])), reverse=True)
    selected: list[dict[str, Any]] = []
    for candidate in candidates:
        if all(_angular_distance(float(candidate["angle"]), float(existing["angle"]), 360.0) >= float(min_separation_degrees) for existing in selected):
            selected.append(candidate)
    return selected


def _bridge_boundary_match_gaps(matches: list[bool]) -> list[bool]:
    if len(matches) < 3:
        return list(matches)
    bridged = list(matches)
    count = len(matches)
    for index, matched in enumerate(matches):
        if matched:
            continue
        if matches[(index - 1) % count] and matches[(index + 1) % count]:
            bridged[index] = True
    return bridged


def _evenly_spaced_offsets(count: int, span: float) -> list[float]:
    if count <= 1:
        return [0.0]
    return [-span / 2.0 + span * index / (count - 1) for index in range(count)]


def _integer_offsets(span: float, step: int) -> list[int]:
    half_span = max(1, int(round(span / 2.0)))
    return list(range(-half_span, half_span + 1, max(1, int(step))))


def _sample_pixel_feature(
    pixels: Any,
    width: int,
    height: int,
    x: int,
    y: int,
) -> tuple[float, float, float, float, float, float, float] | None:
    if x < 0 or x >= width or y < 0 or y >= height:
        return None
    red, green, blue, alpha = pixels[x, y]
    if alpha <= 20:
        return None
    luma = red * 0.299 + green * 0.587 + blue * 0.114
    rg = red - green
    by = blue - (red + green) / 2.0
    gradient = _gradient_features(pixels, width, height, x, y)
    return (float(red), float(green), float(blue), float(luma), float(rg), float(by), float(gradient))


def _average_feature_values(values: list[tuple[float, float, float, float, float, float, float]]) -> list[float]:
    if not values:
        return [0.0] * 7
    count = len(values)
    return [sum(value[index] for value in values) / count for index in range(7)]


def _sample_ray_descriptor(
    image: Image.Image,
    center_x: float,
    center_y: float,
    angle_degrees: float,
    start_radius: float,
    end_radius: float,
    *,
    width_pixels: int,
    radial_samples: int,
) -> list[float] | None:
    if end_radius <= start_radius or radial_samples <= 1:
        return None
    pixels = image.load()
    theta = math.radians(angle_degrees)
    cos_theta = math.cos(theta)
    sin_theta = math.sin(theta)
    half_width = max(0, int(width_pixels) // 2)
    offsets = list(range(-half_width, half_width + 1))
    descriptor: list[float] = []
    valid_samples = 0
    for sample_index in range(radial_samples):
        progress = sample_index / (radial_samples - 1)
        radius = start_radius + (end_radius - start_radius) * progress
        values: list[tuple[int, int, int, float, float, float, float]] = []
        for offset in offsets:
            x = int(round(center_x + radius * cos_theta - offset * sin_theta))
            y = int(round(center_y + radius * sin_theta + offset * cos_theta))
            if 0 <= x < image.width and 0 <= y < image.height:
                red, green, blue, alpha = pixels[x, y]
                if alpha > 20:
                    luma = red * 0.299 + green * 0.587 + blue * 0.114
                    rg = red - green
                    by = blue - (red + green) / 2.0
                    gradient = _gradient_features(pixels, image.width, image.height, x, y)
                    values.append((red, green, blue, luma, rg, by, gradient))
        if not values:
            descriptor.extend([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
            continue
        valid_samples += 1
        count = len(values)
        descriptor.extend(
            [
                sum(value[0] for value in values) / count,
                sum(value[1] for value in values) / count,
                sum(value[2] for value in values) / count,
                sum(value[3] for value in values) / count,
                sum(value[4] for value in values) / count,
                sum(value[5] for value in values) / count,
                sum(value[6] for value in values) / count,
            ]
        )
    if valid_samples < max(4, int(radial_samples * 0.65)):
        return None
    if _descriptor_variance(descriptor) < 4.0 or _descriptor_spatial_variance(descriptor, 7) < 4.0:
        return None
    return descriptor


def best_ray_alignment_angle(
    outer_rays: list[list[float] | None],
    inner_rays: list[list[float] | None],
    *,
    step_degrees: int = RAY_STEP_DEGREES,
) -> _RayAlignmentCandidate:
    if len(outer_rays) != len(inner_rays):
        raise RuntimeError("ray descriptor counts do not match")
    candidate_count = len(outer_rays)
    if candidate_count <= 0:
        return _empty_ray_alignment_candidate(candidate_count, bounded_fallback_applied=True)

    matrix: list[list[float | None]] = []
    for shift_index in range(candidate_count):
        distances: list[float | None] = []
        for ray_index, outer_descriptor in enumerate(outer_rays):
            inner_descriptor = inner_rays[(ray_index - shift_index) % candidate_count]
            if outer_descriptor is None or inner_descriptor is None:
                distances.append(None)
                continue
            distances.append(_ray_descriptor_distance(outer_descriptor, inner_descriptor))
        matrix.append(distances)

    best_per_ray: list[float | None] = []
    for ray_index in range(candidate_count):
        ray_distances = [
            distances[ray_index]
            for distances in matrix
            if distances[ray_index] is not None
        ]
        best_per_ray.append(min(ray_distances) if ray_distances else None)

    candidates: list[_RayAlignmentCandidate] = []
    for shift_index, distances in enumerate(matrix):
        matched_count = 0
        comparable_count = 0
        total_distance = 0.0
        for ray_index, distance in enumerate(distances):
            best_distance = best_per_ray[ray_index]
            if distance is None or best_distance is None:
                continue
            comparable_count += 1
            total_distance += distance
            tolerance = max(10.0, best_distance * 0.18)
            if distance <= best_distance + tolerance:
                matched_count += 1
        score = matched_count / comparable_count if comparable_count else 0.0
        candidates.append(
            _RayAlignmentCandidate(
                angle_delta=float(shift_index * step_degrees),
                score=float(score),
                matched_ray_count=matched_count,
                comparable_ray_count=comparable_count,
                candidate_count=candidate_count,
                total_distance=total_distance if comparable_count else float("inf"),
            )
        )

    if not candidates:
        return _empty_ray_alignment_candidate(candidate_count, bounded_fallback_applied=True)
    sorted_candidates = sorted(candidates, key=_ray_candidate_sort_key)
    selected = _candidate_with_margin(sorted_candidates[0], sorted_candidates)
    if selected.angle_delta < ZERO_FALLBACK_MIN_DEGREES or selected.angle_delta > ZERO_FALLBACK_MAX_DEGREES:
        bounded_candidates = [
            candidate
            for candidate in candidates
            if ZERO_FALLBACK_MIN_DEGREES <= candidate.angle_delta <= ZERO_FALLBACK_MAX_DEGREES
        ]
        if bounded_candidates:
            bounded_sorted = sorted(bounded_candidates, key=_ray_candidate_sort_key)
            bounded = _candidate_with_margin(bounded_sorted[0], bounded_sorted)
            selected = _RayAlignmentCandidate(
                angle_delta=bounded.angle_delta,
                score=bounded.score,
                matched_ray_count=bounded.matched_ray_count,
                comparable_ray_count=bounded.comparable_ray_count,
                candidate_count=bounded.candidate_count,
                total_distance=bounded.total_distance,
                bounded_fallback_applied=True,
                confidence_margin=bounded.confidence_margin,
                second_best_angle_delta=bounded.second_best_angle_delta,
            )
    return selected


def _ray_candidate_sort_key(candidate: _RayAlignmentCandidate) -> tuple[int, float, float]:
    return (-int(candidate.matched_ray_count), float(candidate.total_distance), float(candidate.angle_delta))


def _candidate_with_margin(
    selected: _RayAlignmentCandidate,
    sorted_candidates: list[_RayAlignmentCandidate],
) -> _RayAlignmentCandidate:
    second = next(
        (candidate for candidate in sorted_candidates if abs(candidate.angle_delta - selected.angle_delta) > 1e-9),
        None,
    )
    margin = 0.0
    second_angle = 0.0
    if second is not None:
        second_angle = float(second.angle_delta)
        if math.isfinite(selected.total_distance) and math.isfinite(second.total_distance):
            margin = max(0.0, (float(second.total_distance) - float(selected.total_distance)) / max(1.0, float(selected.total_distance)))
        elif second.matched_ray_count != selected.matched_ray_count:
            margin = abs(second.matched_ray_count - selected.matched_ray_count) / max(1.0, float(selected.comparable_ray_count or 1))
    return _RayAlignmentCandidate(
        angle_delta=selected.angle_delta,
        score=selected.score,
        matched_ray_count=selected.matched_ray_count,
        comparable_ray_count=selected.comparable_ray_count,
        candidate_count=selected.candidate_count,
        total_distance=selected.total_distance,
        bounded_fallback_applied=selected.bounded_fallback_applied,
        confidence_margin=float(margin),
        second_best_angle_delta=float(second_angle),
    )


def _empty_ray_alignment_candidate(candidate_count: int, *, bounded_fallback_applied: bool) -> _RayAlignmentCandidate:
    return _RayAlignmentCandidate(
        angle_delta=float(ZERO_FALLBACK_MIN_DEGREES),
        score=0.0,
        matched_ray_count=0,
        comparable_ray_count=0,
        candidate_count=candidate_count,
        total_distance=float("inf"),
        bounded_fallback_applied=bounded_fallback_applied,
        confidence_margin=0.0,
        second_best_angle_delta=0.0,
    )


def fuse_alignment_candidates(
    methods: list[_AlignmentMethodCandidate],
    *,
    rotation_degrees: float,
    agreement_max_degrees: float,
) -> tuple[_RayAlignmentCandidate, dict[str, float], dict[str, float], float, str]:
    method_scores = {
        method.method: float(method.candidate.score)
        for method in methods
    }
    method_angles = {
        method.method: float(method.candidate.angle_delta)
        for method in methods
    }
    valid_methods = [
        method
        for method in methods
        if method.weight > 0
        and method.candidate.comparable_ray_count > 0
        and math.isfinite(method.candidate.total_distance)
        and method.candidate.score > 0.0
    ]
    if not valid_methods:
        fallback = methods[0].candidate if methods else _empty_ray_alignment_candidate(0, bounded_fallback_applied=True)
        return fallback, method_scores, method_angles, 0.0, methods[0].method if methods else "ray"

    selected_method = max(
        valid_methods,
        key=lambda method: (
            float(method.weight) * float(method.candidate.score),
            float(method.candidate.confidence_margin),
            -float(method.candidate.total_distance),
        ),
    )
    selected_angle = float(selected_method.candidate.angle_delta)
    material_methods = [
        method
        for method in valid_methods
        if method.candidate.score >= max(0.10, selected_method.candidate.score * 0.65)
    ]
    agreement = 0.0
    if material_methods:
        agreement = max(
            _angular_distance(selected_angle, float(method.candidate.angle_delta), rotation_degrees)
            for method in material_methods
        )
    agreeing_methods = [
        method
        for method in material_methods
        if _angular_distance(selected_angle, float(method.candidate.angle_delta), rotation_degrees) <= agreement_max_degrees
    ]
    if len(agreeing_methods) >= 2:
        fused_angle = _weighted_circular_mean(
            [
                (
                    float(method.candidate.angle_delta),
                    max(0.001, float(method.weight) * max(0.001, float(method.candidate.score))),
                )
                for method in agreeing_methods
            ],
            rotation_degrees,
        )
        weight_total = sum(float(method.weight) for method in agreeing_methods)
        weighted_score = sum(float(method.weight) * float(method.candidate.score) for method in agreeing_methods) / max(0.001, weight_total)
        confidence_margin = max(
            float(selected_method.candidate.confidence_margin),
            (max(0.0, agreement_max_degrees - agreement) / max(1.0, agreement_max_degrees)) * 0.05,
        )
        score = max(float(selected_method.candidate.score), float(weighted_score))
    else:
        fused_angle = selected_angle
        score = float(selected_method.candidate.score)
        confidence_margin = float(selected_method.candidate.confidence_margin)

    boundary_can_carry_confidence = (
        selected_method.method == "boundary"
        and int(selected_method.candidate.matched_ray_count) >= 2
        and float(selected_method.candidate.confidence_margin) > 0.0
    )
    if agreement > agreement_max_degrees and not boundary_can_carry_confidence:
        confidence_margin = min(confidence_margin, 0.0)

    selected = selected_method.candidate
    fused_candidate = _RayAlignmentCandidate(
        angle_delta=float(fused_angle % rotation_degrees),
        score=max(0.0, min(1.0, float(score))),
        matched_ray_count=selected.matched_ray_count,
        comparable_ray_count=selected.comparable_ray_count,
        candidate_count=selected.candidate_count,
        total_distance=selected.total_distance,
        bounded_fallback_applied=selected.bounded_fallback_applied,
        confidence_margin=float(confidence_margin),
        second_best_angle_delta=float(selected.second_best_angle_delta),
    )
    return fused_candidate, method_scores, method_angles, float(agreement), selected_method.method


def _angular_distance(angle_a: float, angle_b: float, rotation_degrees: float) -> float:
    if rotation_degrees <= 0:
        return abs(angle_a - angle_b)
    delta = abs((float(angle_a) - float(angle_b)) % float(rotation_degrees))
    return min(delta, abs(float(rotation_degrees) - delta))


def _weighted_circular_mean(items: list[tuple[float, float]], rotation_degrees: float) -> float:
    if not items or rotation_degrees <= 0:
        return 0.0
    sin_sum = 0.0
    cos_sum = 0.0
    for angle, weight in items:
        radians = float(angle) / float(rotation_degrees) * math.pi * 2.0
        sin_sum += math.sin(radians) * float(weight)
        cos_sum += math.cos(radians) * float(weight)
    if abs(sin_sum) <= 1e-12 and abs(cos_sum) <= 1e-12:
        return float(items[0][0]) % float(rotation_degrees)
    radians = math.atan2(sin_sum, cos_sum)
    return (radians / (math.pi * 2.0) * float(rotation_degrees)) % float(rotation_degrees)


def _ray_descriptor_distance(descriptor_a: list[float], descriptor_b: list[float]) -> float:
    if len(descriptor_a) != len(descriptor_b) or not descriptor_a:
        return float("inf")
    mean_a = sum(descriptor_a) / len(descriptor_a)
    mean_b = sum(descriptor_b) / len(descriptor_b)
    raw_sum = 0.0
    centered_sum = 0.0
    for value_a, value_b in zip(descriptor_a, descriptor_b):
        raw_delta = value_a - value_b
        centered_delta = (value_a - mean_a) - (value_b - mean_b)
        raw_sum += raw_delta * raw_delta
        centered_sum += centered_delta * centered_delta
    raw_rms = math.sqrt(raw_sum / len(descriptor_a))
    centered_rms = math.sqrt(centered_sum / len(descriptor_a))
    return centered_rms * 0.65 + raw_rms * 0.35


def _descriptor_variance(descriptor: list[float]) -> float:
    if not descriptor:
        return 0.0
    mean = sum(descriptor) / len(descriptor)
    return sum((value - mean) * (value - mean) for value in descriptor) / len(descriptor)


def _descriptor_spatial_variance(descriptor: list[float], feature_count: int) -> float:
    if feature_count <= 0 or len(descriptor) < feature_count * 2:
        return 0.0
    variances: list[float] = []
    for offset in range(feature_count):
        values = descriptor[offset::feature_count]
        if not values:
            continue
        mean = sum(values) / len(values)
        variances.append(sum((value - mean) * (value - mean) for value in values) / len(values))
    return max(variances) if variances else 0.0


def _gradient_features(pixels: Any, width: int, height: int, x: int, y: int) -> float:
    gradient_x, gradient_y = _gradient_xy(pixels, width, height, x, y)
    return math.sqrt(gradient_x * gradient_x + gradient_y * gradient_y)


def _gradient_xy(pixels: Any, width: int, height: int, x: int, y: int) -> tuple[float, float]:
    left = _pixel_luma(pixels[max(0, x - 1), y])
    right = _pixel_luma(pixels[min(width - 1, x + 1), y])
    top = _pixel_luma(pixels[x, max(0, y - 1)])
    bottom = _pixel_luma(pixels[x, min(height - 1, y + 1)])
    return float(right - left), float(bottom - top)


def _pixel_luma(pixel: tuple[int, int, int, int]) -> float:
    red, green, blue, alpha = pixel
    if alpha <= 20:
        return 0.0
    return red * 0.299 + green * 0.587 + blue * 0.114


def _mean_image_difference(image_a: Image.Image, image_b: Image.Image) -> float:
    if image_a.size != image_b.size:
        image_b = image_b.resize(image_a.size)
    a = image_a.convert("RGBA")
    b = image_b.convert("RGBA")
    pixels_a = a.load()
    pixels_b = b.load()
    total = 0.0
    count = 0
    step_x = max(1, a.width // 96)
    step_y = max(1, a.height // 96)
    for y in range(0, a.height, step_y):
        for x in range(0, a.width, step_x):
            red_a, green_a, blue_a, alpha_a = pixels_a[x, y]
            red_b, green_b, blue_b, alpha_b = pixels_b[x, y]
            if alpha_a <= 20 and alpha_b <= 20:
                continue
            total += (
                abs(red_a - red_b)
                + abs(green_a - green_b)
                + abs(blue_a - blue_b)
            ) / 3.0
            count += 1
    return total / count if count else 0.0


def _container_screenshot(page: Any, config: SliderPuzzleConfig) -> Image.Image | None:
    try:
        return Image.open(BytesIO(page.locator(config.container_selector).first.screenshot())).convert("RGBA")
    except Exception:
        return None


def _image_fingerprint_changed(before: Image.Image | None, after: Image.Image | None) -> bool:
    if before is None or after is None:
        return False
    return _mean_image_difference(before, after) > CAPTCHA_STABLE_MAX_PIXEL_DIFF


def _monotonic_time(page: Any) -> float:
    _ = page
    return time.monotonic()


def polar_profile(image: Image.Image, center_x: float, center_y: float, radii: list[float], samples: int = ANGLE_SAMPLE_COUNT) -> list[tuple[float, float, float] | None]:
    profile: list[tuple[float, float, float] | None] = []
    pixels = image.load()
    for index in range(samples):
        theta = math.radians(index * 360.0 / samples)
        cos_theta = math.cos(theta)
        sin_theta = math.sin(theta)
        values: list[tuple[int, int, int]] = []
        for radius in radii:
            x = int(round(center_x + radius * cos_theta))
            y = int(round(center_y + radius * sin_theta))
            if 0 <= x < image.width and 0 <= y < image.height:
                red, green, blue, alpha = pixels[x, y]
                if alpha > 20:
                    values.append((red, green, blue))
        if not values:
            profile.append(None)
            continue
        count = len(values)
        profile.append(
            (
                sum(value[0] for value in values) / count,
                sum(value[1] for value in values) / count,
                sum(value[2] for value in values) / count,
            )
        )
    return profile


def best_profile_alignment_angle(
    outer_profile: list[tuple[float, float, float] | None],
    inner_profile: list[tuple[float, float, float] | None],
) -> tuple[int, float]:
    if len(outer_profile) != len(inner_profile):
        raise RuntimeError("profile lengths do not match")
    best_angle = 0
    best_score = -1.0
    for angle in range(len(outer_profile)):
        score = shifted_profile_correlation(outer_profile, inner_profile, angle)
        if score > best_score:
            best_score = score
            best_angle = angle
    return best_angle, max(0.0, min(1.0, best_score))


def shifted_profile_correlation(
    outer_profile: list[tuple[float, float, float] | None],
    inner_profile: list[tuple[float, float, float] | None],
    angle_delta: int,
) -> float:
    values_a: list[float] = []
    values_b: list[float] = []
    count = len(outer_profile)
    for index, outer_value in enumerate(outer_profile):
        inner_value = inner_profile[(index - angle_delta) % count]
        if outer_value is None or inner_value is None:
            continue
        values_a.extend(outer_value)
        values_b.extend(inner_value)
    if len(values_a) < 90:
        return 0.0
    mean_a = sum(values_a) / len(values_a)
    mean_b = sum(values_b) / len(values_b)
    numerator = 0.0
    denom_a = 0.0
    denom_b = 0.0
    for value_a, value_b in zip(values_a, values_b):
        centered_a = value_a - mean_a
        centered_b = value_b - mean_b
        numerator += centered_a * centered_b
        denom_a += centered_a * centered_a
        denom_b += centered_b * centered_b
    if denom_a <= 1e-9 or denom_b <= 1e-9:
        return 0.0
    return numerator / math.sqrt(denom_a * denom_b)


def _slider_relative_rotation_degrees(config: SliderPuzzleConfig) -> float:
    inner_degrees = abs(float(config.inner_clockwise_rotation_degrees))
    outer_degrees = abs(float(config.outer_counterclockwise_rotation_degrees))
    return max(1.0, inner_degrees + outer_degrees)


def _slider_progress_from_handle_x(
    handle_x: float,
    track_box: dict[str, float],
    handle_box: dict[str, float],
) -> float:
    min_x = float(track_box["x"]) + float(handle_box["width"]) / 2.0
    max_x = float(track_box["x"]) + float(track_box["width"]) - float(handle_box["width"]) / 2.0
    travel = max(1.0, max_x - min_x)
    return max(0.0, min(1.0, (float(handle_x) - min_x) / travel))


def _slider_rotation_components(
    progress: float,
    config: SliderPuzzleConfig,
) -> dict[str, float]:
    clamped = max(0.0, min(1.0, float(progress)))
    inner_rotation = clamped * abs(float(config.inner_clockwise_rotation_degrees))
    outer_rotation = -clamped * abs(float(config.outer_counterclockwise_rotation_degrees))
    return {
        "sliderProgress": float(clamped),
        "innerRotationDegrees": float(inner_rotation),
        "outerRotationDegrees": float(outer_rotation),
        "relativeRotationDegrees": float(inner_rotation - outer_rotation),
    }


def _slider_rotation_components_for_handle(
    handle_x: float,
    track_box: dict[str, float],
    handle_box: dict[str, float],
    config: SliderPuzzleConfig,
) -> dict[str, float]:
    return _slider_rotation_components(
        _slider_progress_from_handle_x(handle_x, track_box, handle_box),
        config,
    )


def _relative_rotation_for_inner_angle(inner_angle_degrees: float, config: SliderPuzzleConfig) -> float:
    inner_max = max(1.0, abs(float(config.inner_clockwise_rotation_degrees)))
    progress = max(0.0, min(1.0, float(inner_angle_degrees) / inner_max))
    return progress * _slider_relative_rotation_degrees(config)


def _inner_angle_for_relative_rotation(relative_angle_degrees: float, config: SliderPuzzleConfig) -> float:
    relative_max = _slider_relative_rotation_degrees(config)
    progress = max(0.0, min(1.0, float(relative_angle_degrees) / relative_max))
    return progress * abs(float(config.inner_clockwise_rotation_degrees))


def drag_distance_for_angle(angle_delta: float, track_width: float, handle_width: float, rotation_degrees: float = 360) -> float:
    draggable_width = max(0.0, float(track_width) - float(handle_width))
    if draggable_width <= 0 or rotation_degrees <= 0:
        return 0.0
    normalized_angle = float(angle_delta) % float(rotation_degrees)
    if _angle_is_zero(normalized_angle, rotation_degrees):
        return 0.0
    return draggable_width * normalized_angle / float(rotation_degrees)


def manual_confirmation_drag_distance_for_angle(
    angle_delta: float,
    track_width: float,
    handle_width: float,
    rotation_degrees: float = 360,
) -> float:
    drag_px = drag_distance_for_angle(angle_delta, track_width, handle_width, rotation_degrees)
    if drag_px > 0:
        return drag_px
    draggable_width = max(0.0, float(track_width) - float(handle_width))
    return draggable_width / 2.0 if draggable_width > 0 else 0.0


def _manual_confirmation_candidates(
    angle_delta: float,
    track_box: dict[str, float],
    handle_box: dict[str, float],
    rotation_degrees: float,
    slider_rotation_degrees: float | None = None,
    fixed_inner_rotation_degrees: tuple[float, ...] = (),
    fixed_inner_rotation_max_degrees: float = 180.0,
    include_wide_prediction_offsets: bool = False,
    min_effective_drag_px: float = 0.0,
) -> list[_ManualDragCandidate]:
    track_width = float(track_box["width"])
    handle_width = float(handle_box["width"])
    slider_rotation = float(slider_rotation_degrees or rotation_degrees)
    min_x = float(track_box["x"]) + handle_width / 2.0
    max_x = float(track_box["x"]) + track_width - handle_width / 2.0
    if max_x <= min_x:
        return []

    if fixed_inner_rotation_degrees:
        inner_max = max(1.0, abs(float(fixed_inner_rotation_max_degrees)))
        candidate_angles = [
            (f"inner{inner_angle:g}", float(inner_angle) / inner_max * slider_rotation)
            for inner_angle in fixed_inner_rotation_degrees
            if 0.0 < float(inner_angle) < inner_max
        ]
    else:
        normalized = float(angle_delta) % float(rotation_degrees)
        base_angle = ZERO_FALLBACK_MIN_DEGREES if _angle_is_zero(normalized, rotation_degrees) else normalized
        inverse = (-base_angle) % float(rotation_degrees)
        offsets = (0.0, -5.0, 5.0, -10.0, 10.0)
        if include_wide_prediction_offsets:
            offsets = (0.0, -5.0, 5.0, -10.0, 10.0, -15.0, 15.0, -20.0, 20.0)
        candidate_angles = []
        for offset in offsets:
            angle = (base_angle + offset) % float(rotation_degrees)
            if not _angle_is_zero(angle, rotation_degrees):
                candidate_angles.append(("raw" if offset == 0 else f"raw{offset:+.0f}", angle))
        if not _angle_is_zero(inverse, rotation_degrees):
            for offset in offsets:
                angle = (inverse + offset) % float(rotation_degrees)
                if not _angle_is_zero(angle, rotation_degrees):
                    candidate_angles.append(("inverse" if offset == 0 else f"inverse{offset:+.0f}", angle))

    if not candidate_angles:
        candidate_angles = [
            ("raw", max(1.0, min(float(rotation_degrees) - 1.0, ZERO_FALLBACK_MIN_DEGREES))),
        ]

    candidates: list[_ManualDragCandidate] = []
    seen_targets: list[float] = []
    for direction, candidate_angle in candidate_angles:
        drag_px = drag_distance_for_angle(candidate_angle, track_width, handle_width, slider_rotation)
        if drag_px <= 0:
            continue
        if 0.0 < drag_px < float(min_effective_drag_px):
            drag_px = min(max(0.0, float(min_effective_drag_px)), max(0.0, track_width - handle_width))
            if drag_px <= 0:
                continue
            candidate_angle = drag_px / max(1.0, track_width - handle_width) * slider_rotation
            direction = f"{direction}_min_effective"
        target_x = max(min_x, min(max_x, min_x + drag_px))
        if any(abs(target_x - seen_target) <= 0.5 for seen_target in seen_targets):
            continue
        seen_targets.append(target_x)
        candidates.append(_ManualDragCandidate(direction, float(candidate_angle), target_x, target_x - min_x))
    return candidates


def _manual_candidate_for_inner_angle(
    direction: str,
    inner_angle: float,
    track_box: dict[str, float],
    handle_box: dict[str, float],
    config: SliderPuzzleConfig,
) -> _ManualDragCandidate | None:
    inner_max = max(1.0, abs(float(config.inner_clockwise_rotation_degrees)))
    refined_inner = float(inner_angle)
    if refined_inner <= 0.0 or refined_inner >= inner_max:
        return None
    refined_angle = _relative_rotation_for_inner_angle(refined_inner, config)
    refined_drag_px = drag_distance_for_angle(
        refined_angle,
        float(track_box["width"]),
        float(handle_box["width"]),
        _slider_relative_rotation_degrees(config),
    )
    min_x = float(track_box["x"]) + float(handle_box["width"]) / 2.0
    max_x = float(track_box["x"]) + float(track_box["width"]) - float(handle_box["width"]) / 2.0
    refined_target_x = max(min_x, min(max_x, min_x + refined_drag_px))
    return _ManualDragCandidate(direction, float(refined_angle), float(refined_target_x), float(refined_target_x - min_x))


def _residual_trend_refine_candidates(
    evaluations: list[_ManualDragEvaluation],
    candidate_evaluations: list[dict[str, Any]],
    seen_candidate_targets: set[float],
    track_box: dict[str, float],
    handle_box: dict[str, float],
    config: SliderPuzzleConfig,
) -> list[_ManualDragCandidate]:
    if not bool(config.residual_trend_refine_enabled) or int(config.residual_trend_refine_max) <= 0:
        return []
    effective_by_direction = {
        str(item.get("direction", "")): bool(item.get("dragEffective", False))
        for item in candidate_evaluations
    }
    points: list[tuple[float, float, _ManualDragEvaluation]] = []
    for evaluation in evaluations:
        if not effective_by_direction.get(evaluation.candidate.direction, False):
            continue
        if float(evaluation.alignment_error) <= float(config.release_alignment_error_max):
            continue
        if float(evaluation.alignment_error) > float(config.residual_trend_refine_max_error):
            continue
        if int(evaluation.estimate.boundary_line_count) < max(1, int(config.boundary_min_lines)):
            continue
        if float(_boundary_quality_metrics(evaluation.estimate, config)["boundaryQuality"]) < float(config.residual_trend_boundary_quality_min):
            continue
        inner = _inner_angle_for_relative_rotation(evaluation.candidate.angle_delta, config)
        points.append((float(inner), float(evaluation.alignment_error), evaluation))
    if not points:
        return []

    points.sort(key=lambda item: item[0])
    best_index, best_point = min(enumerate(points), key=lambda item: (item[1][1], abs(item[1][0] - 90.0)))
    best_inner, best_error, _ = best_point
    if best_error < float(config.residual_trend_refine_min_error) or best_error > float(config.residual_trend_refine_max_error):
        return []

    left = points[best_index - 1] if best_index > 0 else None
    right = points[best_index + 1] if best_index + 1 < len(points) else None
    direction = 0.0
    if left is not None and right is not None:
        if left[1] < right[1]:
            direction = -1.0
        elif right[1] < left[1]:
            direction = 1.0
    elif left is not None:
        direction = -1.0 if left[1] < best_error else 1.0
    elif right is not None:
        direction = 1.0 if right[1] < best_error else -1.0

    raw_targets: list[float] = []
    steps = [float(step) for step in config.residual_trend_refine_inner_steps if float(step) > 0.0]
    if direction:
        raw_targets = [best_inner + direction * step for step in steps]
    elif steps:
        raw_targets = [best_inner - steps[0], best_inner + steps[0]]

    candidates: list[_ManualDragCandidate] = []
    for target_inner in raw_targets:
        if len(candidates) >= max(0, int(config.residual_trend_refine_max)):
            break
        candidate = _manual_candidate_for_inner_angle(f"trend_inner{target_inner:g}", target_inner, track_box, handle_box, config)
        if candidate is None:
            continue
        target_key = round(float(candidate.target_x), 1)
        if target_key in seen_candidate_targets:
            continue
        seen_candidate_targets.add(target_key)
        candidates.append(candidate)
    return candidates


def _alignment_error_for_angle(angle_delta: float, rotation_degrees: float) -> float:
    normalized = float(angle_delta) % float(rotation_degrees)
    return min(normalized, abs(float(rotation_degrees) - normalized))


def _estimate_fusion_unstable(estimate: AngleEstimate, config: SliderPuzzleConfig) -> bool:
    method_angles = dict(estimate.method_angles or {})
    if len(method_angles) < 2:
        return False
    return float(estimate.fusion_agreement_degrees) > float(config.unstable_fusion_agreement_degrees)


def _boundary_quality_metrics(estimate: AngleEstimate, config: SliderPuzzleConfig | None = None) -> dict[str, float]:
    top_angles = list(estimate.boundary_top_angles or [])
    spans = sorted(
        [float(item.get("spanDegrees", 0.0) or 0.0) for item in top_angles if isinstance(item, dict)],
        reverse=True,
    )
    max_span = spans[0] if spans else 0.0
    top2_avg = sum(spans[:2]) / 2.0 if len(spans) >= 2 else max_span
    short_limit = float(config.boundary_short_segment_span) if config is not None else 10.0
    short_count = sum(1 for span in spans if span <= short_limit)
    min_max_span = float(config.boundary_high_conf_min_max_span) if config is not None else 15.0
    min_top2_avg = float(config.boundary_high_conf_min_top2_avg_span) if config is not None else 12.0
    min_lines = max(1, int(config.boundary_min_lines)) if config is not None else 2
    line_score = min(1.0, float(estimate.boundary_line_count) / max(1.0, float(min_lines + 2)))
    max_span_score = min(1.0, max_span / max(1.0, min_max_span))
    top2_score = min(1.0, top2_avg / max(1.0, min_top2_avg))
    short_penalty = min(0.35, short_count * 0.06)
    quality = max(0.0, min(1.0, max_span_score * 0.40 + top2_score * 0.40 + line_score * 0.20 - short_penalty))
    return {
        "boundaryQuality": float(quality),
        "boundaryMaxSpanDegrees": float(max_span),
        "boundaryTop2AvgSpanDegrees": float(top2_avg),
        "boundaryShortSegmentCount": float(short_count),
    }


def _boundary_high_confidence(estimate: AngleEstimate, config: SliderPuzzleConfig) -> bool:
    metrics = _boundary_quality_metrics(estimate, config)
    return (
        int(estimate.boundary_line_count) >= max(1, int(config.boundary_min_lines))
        and float(metrics["boundaryMaxSpanDegrees"]) >= float(config.boundary_high_conf_min_max_span)
        and float(metrics["boundaryTop2AvgSpanDegrees"]) >= float(config.boundary_high_conf_min_top2_avg_span)
        and float(metrics["boundaryQuality"]) >= 0.55
    )


def _candidate_sort_key(evaluation: _ManualDragEvaluation, config: SliderPuzzleConfig | None = None) -> tuple[float, float, float, float, float, float, int, float]:
    release_error_max = float(config.release_alignment_error_max) if config is not None else 8.0
    unstable = _estimate_fusion_unstable(evaluation.estimate, config) if config is not None else False
    boundary_quality = float(_boundary_quality_metrics(evaluation.estimate, config)["boundaryQuality"])
    return (
        0 if float(evaluation.alignment_error) <= release_error_max else 1,
        evaluation.alignment_error,
        1 if unstable else 0,
        -boundary_quality,
        -float(evaluation.estimate.confidence_margin),
        -float(evaluation.estimate.score),
        _candidate_direction_priority(evaluation.candidate.direction),
        abs(float(evaluation.candidate.drag_px)),
    )


def _candidate_direction_priority(direction: str) -> int:
    if direction in {"raw", "inverse"}:
        return 0
    if direction.startswith("raw") or direction.startswith("inverse"):
        return 1
    return 2


def _estimate_payload(estimate: AngleEstimate, rotation_degrees: float) -> dict[str, Any]:
    boundary_quality = _boundary_quality_metrics(estimate)
    return {
        "angleDelta": float(estimate.angle_delta),
        "alignmentError": float(_alignment_error_for_angle(estimate.angle_delta, rotation_degrees)),
        "score": float(estimate.score),
        "centerX": float(estimate.center_x),
        "centerY": float(estimate.center_y),
        "innerRadius": float(estimate.inner_radius),
        "matchedRayCount": int(estimate.matched_ray_count),
        "comparableRayCount": int(estimate.comparable_ray_count),
        "candidateCount": int(estimate.candidate_count),
        "rayStepDegrees": int(estimate.ray_step_degrees),
        "rayWidthPixels": int(estimate.ray_width_pixels),
        "boundedFallbackApplied": bool(estimate.bounded_fallback_applied),
        "confidenceMargin": float(estimate.confidence_margin),
        "secondBestAngleDelta": float(estimate.second_best_angle_delta),
        "methodScores": dict(estimate.method_scores),
        "methodAngles": dict(estimate.method_angles),
        "fusionAgreementDegrees": float(estimate.fusion_agreement_degrees),
        "selectedMethod": str(estimate.selected_method),
        "boundaryLineCount": int(estimate.boundary_line_count),
        "boundaryScore": float(estimate.boundary_score),
        "boundaryConfidenceMargin": float(estimate.boundary_confidence_margin),
        "boundaryAngleDelta": float(estimate.boundary_angle_delta),
        "boundaryTopAngles": list(estimate.boundary_top_angles),
        **boundary_quality,
    }


def _evaluation_diagnostic_payload(
    evaluation: _ManualDragEvaluation,
    config: SliderPuzzleConfig,
    *,
    effective: bool,
) -> dict[str, Any]:
    sort_key = _candidate_sort_key(evaluation, config)
    boundary_quality = _boundary_quality_metrics(evaluation.estimate, config)
    return {
        "releaseEligibleByAlignment": bool(float(evaluation.alignment_error) <= float(config.release_alignment_error_max)),
        "fusionUnstable": bool(_estimate_fusion_unstable(evaluation.estimate, config)),
        "fusionAgreementDegrees": float(evaluation.estimate.fusion_agreement_degrees),
        "selectedMethod": str(evaluation.estimate.selected_method),
        "methodAngles": dict(evaluation.estimate.method_angles),
        "methodScores": dict(evaluation.estimate.method_scores),
        "boundaryLineCount": int(evaluation.estimate.boundary_line_count),
        "boundaryTopAngles": list(evaluation.estimate.boundary_top_angles),
        "boundaryScore": float(evaluation.estimate.boundary_score),
        "boundaryConfidenceMargin": float(evaluation.estimate.boundary_confidence_margin),
        "boundaryAngleDelta": float(evaluation.estimate.boundary_angle_delta),
        "boundaryMinLinesSatisfied": bool(evaluation.estimate.boundary_line_count >= int(config.boundary_min_lines)),
        "boundaryHighConfidence": bool(_boundary_high_confidence(evaluation.estimate, config)),
        **boundary_quality,
        "rankKey": [float(item) if isinstance(item, float) else int(item) for item in sort_key],
        "rankBucket": "release_ready" if float(evaluation.alignment_error) <= float(config.release_alignment_error_max) else "needs_refine",
        "effectiveRankBucket": "effective" if effective else "ineffective",
    }


def _candidate_review_diagnostics(candidate_evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    if not candidate_evaluations:
        return {
            "candidateEvaluationCount": 0,
            "coarseCount": 0,
            "refineCount": 0,
            "trendRefineCount": 0,
            "releaseEligibleCount": 0,
            "fusionUnstableCount": 0,
            "boundaryLineCount": 0,
            "boundaryTopAngles": [],
            "boundaryScore": 0.0,
            "boundaryConfidenceMargin": 0.0,
            "boundaryQuality": 0.0,
            "bestAlignmentError": 0.0,
            "bestDirection": "",
            "bestInnerRotationDegrees": 0.0,
        }
    best = min(candidate_evaluations, key=lambda item: float(item.get("alignmentError", 9999.0) or 9999.0))
    best_boundary = max(
        candidate_evaluations,
        key=lambda item: (
            int(item.get("boundaryLineCount", 0) or 0),
            float(item.get("boundaryScore", 0.0) or 0.0),
            float(item.get("boundaryQuality", 0.0) or 0.0),
            float(item.get("boundaryConfidenceMargin", 0.0) or 0.0),
        ),
    )
    return {
        "candidateEvaluationCount": len(candidate_evaluations),
        "coarseCount": sum(1 for item in candidate_evaluations if item.get("phase") == "coarse"),
        "refineCount": sum(1 for item in candidate_evaluations if item.get("phase") == "refine"),
        "boundaryRefineCount": sum(1 for item in candidate_evaluations if item.get("phase") == "boundary_refine"),
        "trendRefineCount": sum(1 for item in candidate_evaluations if item.get("phase") == "trend_refine"),
        "closedLoopCount": sum(1 for item in candidate_evaluations if str(item.get("direction", "")).startswith("closed_loop")),
        "releaseEligibleCount": sum(1 for item in candidate_evaluations if bool(item.get("releaseEligibleByAlignment", False))),
        "fusionUnstableCount": sum(1 for item in candidate_evaluations if bool(item.get("fusionUnstable", False))),
        "boundaryLineCount": int(best_boundary.get("boundaryLineCount", 0) or 0),
        "boundaryTopAngles": list(best_boundary.get("boundaryTopAngles", []) or []),
        "boundaryScore": float(best_boundary.get("boundaryScore", 0.0) or 0.0),
        "boundaryConfidenceMargin": float(best_boundary.get("boundaryConfidenceMargin", 0.0) or 0.0),
        "boundaryQuality": float(best_boundary.get("boundaryQuality", 0.0) or 0.0),
        "boundaryMaxSpanDegrees": float(best_boundary.get("boundaryMaxSpanDegrees", 0.0) or 0.0),
        "boundaryTop2AvgSpanDegrees": float(best_boundary.get("boundaryTop2AvgSpanDegrees", 0.0) or 0.0),
        "boundaryBestDirection": str(best_boundary.get("direction", "")),
        "bestAlignmentError": float(best.get("alignmentError", 0.0) or 0.0),
        "bestDirection": str(best.get("direction", "")),
        "bestInnerRotationDegrees": float(best.get("innerRotationDegrees", 0.0) or 0.0),
        "bestRelativeRotationDegrees": float(best.get("relativeRotationDegrees", 0.0) or 0.0),
        "angleTable": [
            {
                "phase": str(item.get("phase", "")),
                "direction": str(item.get("direction", "")),
                "innerRotationDegrees": float(item.get("innerRotationDegrees", 0.0) or 0.0),
                "relativeRotationDegrees": float(item.get("relativeRotationDegrees", 0.0) or 0.0),
                "alignmentError": float(item.get("alignmentError", 0.0) or 0.0),
                "score": float(item.get("score", 0.0) or 0.0),
                "confidenceMargin": float(item.get("confidenceMargin", 0.0) or 0.0),
                "fusionAgreementDegrees": float(item.get("fusionAgreementDegrees", 0.0) or 0.0),
                "fusionUnstable": bool(item.get("fusionUnstable", False)),
                "boundaryLineCount": int(item.get("boundaryLineCount", 0) or 0),
                "boundaryScore": float(item.get("boundaryScore", 0.0) or 0.0),
                "boundaryConfidenceMargin": float(item.get("boundaryConfidenceMargin", 0.0) or 0.0),
                "boundaryQuality": float(item.get("boundaryQuality", 0.0) or 0.0),
                "boundaryMaxSpanDegrees": float(item.get("boundaryMaxSpanDegrees", 0.0) or 0.0),
                "boundaryTop2AvgSpanDegrees": float(item.get("boundaryTop2AvgSpanDegrees", 0.0) or 0.0),
                "boundaryAngleDelta": float(item.get("boundaryAngleDelta", 0.0) or 0.0),
                "boundaryMinLinesSatisfied": bool(item.get("boundaryMinLinesSatisfied", False)),
                "boundaryHighConfidence": bool(item.get("boundaryHighConfidence", False)),
            }
            for item in candidate_evaluations
        ],
    }


def _write_manual_sample(page: Any, config: SliderPuzzleConfig, label: str, payload: dict[str, Any]) -> bool:
    if not config.sample_dir:
        return False
    sample_dir = Path(config.sample_dir)
    sample_dir.mkdir(parents=True, exist_ok=True)
    safe_label = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in label)[:80]
    image_path = sample_dir / f"{safe_label}.png"
    json_path = sample_dir / f"{safe_label}.json"
    sample_payload = dict(payload)
    sample_payload["label"] = safe_label
    sample_payload["imagePath"] = str(image_path)
    try:
        page.locator(config.container_selector).first.screenshot(path=str(image_path))
    except Exception as exc:
        sample_payload["imageError"] = _clean_error(exc)
    json_path.write_text(json.dumps(sample_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def _drag_strategy_points(
    page: Any,
    config: SliderPuzzleConfig,
    track_box: dict[str, float],
    handle_box: dict[str, float],
) -> list[_DragStrategy]:
    handle_center_x = float(handle_box["x"]) + float(handle_box["width"]) / 2.0
    handle_center_y = float(handle_box["y"]) + float(handle_box["height"]) / 2.0
    track_start_x = float(track_box["x"]) + float(handle_box["width"]) / 2.0
    track_center_y = float(track_box["y"]) + float(track_box["height"]) / 2.0
    strategies = [
        _DragStrategy("handle_center", handle_center_x, handle_center_y),
    ]
    hit_point = _hit_test_drag_point(page, config, handle_box)
    if hit_point is not None:
        strategies.append(_DragStrategy("handle_hit_child", float(hit_point[0]), float(hit_point[1])))
    strategies.extend(
        [
            _DragStrategy("track_start_center", track_start_x, track_center_y),
            _DragStrategy("playwright_drag_to", handle_center_x, handle_center_y),
        ]
    )
    deduped: list[_DragStrategy] = []
    for strategy in strategies:
        if strategy.name != "playwright_drag_to" and any(
            abs(strategy.start_x - existing.start_x) <= 0.5 and abs(strategy.start_y - existing.start_y) <= 0.5
            for existing in deduped
        ):
            continue
        deduped.append(strategy)
    return deduped[: max(1, int(config.drag_strategy_max))]


def _hit_test_drag_point(
    page: Any,
    config: SliderPuzzleConfig,
    handle_box: dict[str, float],
) -> tuple[float, float] | None:
    center_x = float(handle_box["x"]) + float(handle_box["width"]) / 2.0
    center_y = float(handle_box["y"]) + float(handle_box["height"]) / 2.0
    radius = max(1.0, float(config.hit_test_radius_px))
    try:
        result = page.evaluate(
            """({ centerX, centerY, radius }) => {
                const visible = (element) => {
                    if (!element || !element.getBoundingClientRect) return false;
                    const style = window.getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    return style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && style.pointerEvents !== 'none'
                        && Number(style.opacity || 1) > 0.05
                        && rect.width > 0
                        && rect.height > 0;
                };
                const points = [
                    [centerX, centerY],
                    [centerX - radius, centerY],
                    [centerX + radius, centerY],
                    [centerX, centerY - radius],
                    [centerX, centerY + radius],
                ];
                let best = null;
                for (const [x, y] of points) {
                    const element = document.elementFromPoint(x, y);
                    if (!visible(element)) continue;
                    const rect = element.getBoundingClientRect();
                    const area = rect.width * rect.height;
                    if (!best || area < best.area) {
                        best = { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2, area };
                    }
                }
                return best ? { x: best.x, y: best.y } : null;
            }""",
            {"centerX": center_x, "centerY": center_y, "radius": radius},
        )
    except Exception:
        return None
    if not isinstance(result, dict):
        return None
    x = result.get("x")
    y = result.get("y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return None
    return float(x), float(y)


def _drag_effective_threshold(config: SliderPuzzleConfig, track_box: dict[str, float]) -> float:
    return max(float(config.drag_effective_min_px), float(track_box["width"]) * float(config.drag_effective_track_ratio))


def _classify_drag_effect(
    config: SliderPuzzleConfig,
    track_box: dict[str, float],
    initial_x: float,
    target_x: float,
    actual_x: float,
) -> tuple[bool, bool]:
    target_delta = abs(float(target_x) - float(initial_x))
    actual_delta = abs(float(actual_x) - float(initial_x))
    threshold = _drag_effective_threshold(config, track_box)
    weak = 0.0 < actual_delta < max(float(config.weak_drag_max_px), threshold)
    effective = actual_delta >= threshold and actual_delta >= target_delta * float(config.drag_effective_ratio)
    return bool(effective), bool(weak)


def _activate_drag_strategy(
    page: Any,
    config: SliderPuzzleConfig,
    strategy: _DragStrategy,
    track_box: dict[str, float],
    handle_box: dict[str, float],
) -> tuple[bool, float, float, float]:
    initial_x = float(handle_box["x"]) + float(handle_box["width"]) / 2.0
    start_y = float(handle_box["y"]) + float(handle_box["height"]) / 2.0
    max_pointer_x = float(track_box["x"]) + float(track_box["width"]) - float(handle_box["width"]) / 2.0
    probe_target = min(max_pointer_x, float(strategy.start_x) + max(1.0, float(config.drag_probe_px)))
    page.mouse.move(float(strategy.start_x), float(strategy.start_y))
    page.wait_for_timeout(80)
    page.mouse.down()
    page.wait_for_timeout(120)
    _drag_held_handle(page, float(strategy.start_x), float(strategy.start_y), probe_target)
    page.wait_for_timeout(max(0, int(config.drag_probe_wait_ms)))
    try:
        _, probe_handle_box = _track_and_handle_boxes(page, config)
        probe_x = float(probe_handle_box["x"]) + float(probe_handle_box["width"]) / 2.0
    except Exception:
        probe_x = initial_x
    probe_delta = abs(probe_x - initial_x)
    probe_effective = probe_delta >= min(float(config.drag_probe_px) * 0.50, _drag_effective_threshold(config, track_box))
    if not probe_effective:
        return False, initial_x, initial_x, start_y

    _drag_held_handle(page, probe_target, float(strategy.start_y), float(strategy.start_x))
    page.wait_for_timeout(max(0, int(config.drag_probe_wait_ms)))
    try:
        _, reset_handle_box = _track_and_handle_boxes(page, config)
        current_x = float(reset_handle_box["x"]) + float(reset_handle_box["width"]) / 2.0
        start_y = float(reset_handle_box["y"]) + float(reset_handle_box["height"]) / 2.0
    except Exception:
        current_x = initial_x
    return True, initial_x, current_x, start_y


def _move_handle_to_target(
    page: Any,
    config: SliderPuzzleConfig,
    current_x: float,
    start_y: float,
    target_x: float,
    track_box: dict[str, float],
    handle_box: dict[str, float],
) -> float:
    min_x = float(track_box["x"]) + float(handle_box["width"]) / 2.0
    max_x = float(track_box["x"]) + float(track_box["width"]) - float(handle_box["width"]) / 2.0
    clamped_target = max(min_x, min(max_x, float(target_x)))
    if abs(clamped_target - float(current_x)) > 0.5:
        _drag_held_handle(page, float(current_x), float(start_y), clamped_target)
        page.wait_for_timeout(160)
    try:
        _, moved_handle_box = _track_and_handle_boxes(page, config)
        actual_x = float(moved_handle_box["x"]) + float(moved_handle_box["width"]) / 2.0
        if abs(actual_x - clamped_target) > float(config.actual_target_tolerance_px):
            compensation = max(min_x, min(max_x, clamped_target + (clamped_target - actual_x)))
            if abs(compensation - actual_x) > 0.5:
                _drag_held_handle(page, actual_x, float(start_y), compensation)
                page.wait_for_timeout(120)
                _, compensated_handle_box = _track_and_handle_boxes(page, config)
                actual_x = float(compensated_handle_box["x"]) + float(compensated_handle_box["width"]) / 2.0
        return actual_x
    except Exception:
        return clamped_target


def _release_with_locator_drag_to(
    page: Any,
    config: SliderPuzzleConfig,
    current_x: float,
    start_y: float,
    track_box: dict[str, float],
    handle_box: dict[str, float],
) -> str:
    try:
        handle_locator = page.locator(config.handle_selector).first
        track_locator = page.locator(config.track_selector).first
        source_position = {
            "x": max(1.0, float(handle_box["width"]) / 2.0),
            "y": max(1.0, float(handle_box["height"]) / 2.0),
        }
        target_position = {
            "x": max(1.0, min(float(track_box["width"]) - 1.0, float(current_x) - float(track_box["x"]))),
            "y": max(1.0, min(float(track_box["height"]) - 1.0, float(start_y) - float(track_box["y"]))),
        }
        handle_locator.drag_to(
            track_locator,
            source_position=source_position,
            target_position=target_position,
            force=True,
            timeout=3000,
        )
        page.wait_for_timeout(160)
        return "locator_drag_to"
    except Exception:
        page.mouse.up()
        page.wait_for_timeout(160)
        return "mouse_up_fallback"


def _angle_for_handle_x(
    handle_x: float,
    track_box: dict[str, float],
    handle_box: dict[str, float],
    rotation_degrees: float,
) -> float:
    progress = _slider_progress_from_handle_x(handle_x, track_box, handle_box)
    return max(0.0, min(float(rotation_degrees), progress * float(rotation_degrees)))


def _release_blocked_reason(
    evaluation: _ManualDragEvaluation,
    *,
    drag_effective: bool,
    weak_drag_effect: bool,
    pre_release_changed: bool,
    config: SliderPuzzleConfig,
) -> str:
    if weak_drag_effect:
        return "weak_drag_effect"
    if config.release_require_effective and not drag_effective:
        return "auto_drag_no_effect"
    if float(evaluation.alignment_error) > float(config.release_alignment_error_max):
        return "alignment_error_too_high"
    if (
        str(evaluation.estimate.selected_method) == "boundary"
        and int(evaluation.estimate.boundary_line_count) < max(1, int(config.boundary_min_lines))
    ):
        return "boundary_line_count_below_min"
    if _estimate_fusion_unstable(evaluation.estimate, config):
        return "fusion_agreement_too_high"
    if float(evaluation.estimate.score) < float(config.release_score_min):
        return "score_below_release_min"
    if float(evaluation.estimate.confidence_margin) < float(config.release_confidence_margin_min):
        return "confidence_margin_below_release_min"
    if (
        config.release_require_changed
        and not pre_release_changed
        and not _allow_unchanged_pre_release(evaluation, drag_effective=drag_effective, config=config)
    ):
        return "pre_release_not_changed"
    return ""


def _allow_unchanged_pre_release(
    evaluation: _ManualDragEvaluation,
    *,
    drag_effective: bool,
    config: SliderPuzzleConfig,
) -> bool:
    if not drag_effective:
        return False
    if float(evaluation.alignment_error) > float(config.release_unchanged_alignment_error_max):
        return False
    if int(evaluation.estimate.boundary_line_count) < max(1, int(config.boundary_min_lines)):
        return False
    if float(evaluation.estimate.boundary_score) < float(config.release_unchanged_boundary_score_min):
        return False
    if float(evaluation.estimate.boundary_confidence_margin) < float(config.release_unchanged_confidence_margin_min):
        return False
    return _boundary_high_confidence(evaluation.estimate, config) or float(evaluation.estimate.score) >= float(config.release_unchanged_boundary_score_min)


def _candidate_can_stop_after_estimate(
    evaluation: _ManualDragEvaluation,
    *,
    drag_effective: bool,
    weak_drag_effect: bool,
    config: SliderPuzzleConfig,
) -> bool:
    if weak_drag_effect or not drag_effective:
        return False
    if float(evaluation.alignment_error) > float(config.release_alignment_error_max):
        return False
    if (
        str(evaluation.estimate.selected_method) == "boundary"
        and int(evaluation.estimate.boundary_line_count) < max(1, int(config.boundary_min_lines))
    ):
        return False
    if _estimate_fusion_unstable(evaluation.estimate, config):
        return False
    if float(evaluation.estimate.score) < float(config.release_score_min):
        return False
    if float(evaluation.estimate.confidence_margin) < float(config.release_confidence_margin_min):
        return False
    selected_method = str(evaluation.estimate.selected_method or "")
    if (
        selected_method == "boundary"
        and int(evaluation.estimate.boundary_line_count) >= max(1, int(config.boundary_min_lines))
        and float(evaluation.estimate.boundary_score) >= float(config.boundary_fast_path_min_score)
        and float(evaluation.estimate.boundary_confidence_margin) >= float(config.boundary_fast_path_min_margin)
        and _boundary_high_confidence(evaluation.estimate, config)
    ):
        return True
    if (
        selected_method == "ray"
        and float(evaluation.estimate.score) >= float(config.ray_fast_path_min_score)
        and float(evaluation.estimate.confidence_margin) >= float(config.ray_fast_path_min_margin)
    ):
        return True
    if float(evaluation.estimate.score) < float(config.tolerance_score):
        return False
    return True


def _closed_loop_sign_order(angle_delta: float, rotation_degrees: float) -> tuple[float, float]:
    normalized = float(angle_delta) % max(1.0, float(rotation_degrees))
    if _angle_is_zero(normalized, rotation_degrees):
        return (1.0, -1.0)
    if normalized <= float(rotation_degrees) / 2.0:
        return (1.0, -1.0)
    return (-1.0, 1.0)


def _closed_loop_correct(
    page: Any,
    config: SliderPuzzleConfig,
    *,
    initial_x: float,
    current_x: float,
    start_y: float,
    track_box: dict[str, float],
    handle_box: dict[str, float],
    before_image: Image.Image | None,
    selected_evaluation: _ManualDragEvaluation,
    candidate_evaluations: list[dict[str, Any]],
) -> tuple[float, _ManualDragEvaluation, int, bool, Image.Image | None, bool, bool]:
    best_x = float(current_x)
    best_evaluation = selected_evaluation
    best_image = _container_screenshot(page, config)
    best_pre_changed = _image_fingerprint_changed(before_image, best_image)
    best_effective, best_weak = _classify_drag_effect(config, track_box, initial_x, best_x, best_x)
    improved = False
    rounds = 0
    max_rounds = max(0, int(config.closed_loop_max_rounds))
    draggable_width = max(1.0, float(track_box["width"]) - float(handle_box["width"]))
    inner_max = max(1.0, abs(float(config.inner_clockwise_rotation_degrees)))
    step_specs: list[tuple[str, float]] = []
    for step in config.closed_loop_inner_angle_steps:
        angle_step = float(step)
        if angle_step > 0:
            step_specs.append((f"{angle_step:g}deg", draggable_width * angle_step / inner_max))
    for step in config.closed_loop_pixel_steps:
        pixel_step = float(step)
        if pixel_step > 0 and not any(abs(pixel_step - existing_step) <= 0.5 for _, existing_step in step_specs):
            step_specs.append((f"{pixel_step:g}px", pixel_step))

    for round_index in range(max_rounds):
        reason = _release_blocked_reason(
            best_evaluation,
            drag_effective=best_effective,
            weak_drag_effect=best_weak,
            pre_release_changed=best_pre_changed,
            config=config,
        )
        if not reason:
            break
        if reason not in {"alignment_error_too_high", "fusion_agreement_too_high", "score_below_release_min", "confidence_margin_below_release_min"}:
            break

        base_error = float(best_evaluation.alignment_error)
        round_best_x = best_x
        round_best_evaluation = best_evaluation
        round_best_image = best_image
        round_best_effective = best_effective
        round_best_weak = best_weak
        probe_current_x = best_x
        release_ready_candidate = False
        sign_order = _closed_loop_sign_order(best_evaluation.estimate.angle_delta, config.rotation_degrees)
        for step_label, step in step_specs:
            for sign in sign_order:
                target_x = best_x + sign * step
                actual_x = _move_handle_to_target(page, config, probe_current_x, start_y, target_x, track_box, handle_box)
                probe_current_x = actual_x
                candidate_angle = _angle_for_handle_x(actual_x, track_box, handle_box, _slider_relative_rotation_degrees(config))
                try:
                    estimate = estimate_slider_angle_from_page(page, config)
                except Exception:
                    estimate = AngleEstimate(
                        candidate_angle,
                        0.0,
                        selected_evaluation.estimate.center_x,
                        selected_evaluation.estimate.center_y,
                        selected_evaluation.estimate.inner_radius,
                        candidate_count=selected_evaluation.estimate.candidate_count,
                    )
                alignment_error = _alignment_error_for_angle(estimate.angle_delta, config.rotation_degrees)
                effective, weak = _classify_drag_effect(config, track_box, initial_x, target_x, actual_x)
                rotation_components = _slider_rotation_components_for_handle(actual_x, track_box, handle_box, config)
                evaluation = _ManualDragEvaluation(
                    _ManualDragCandidate(f"closed_loop_{round_index + 1}_{sign:+.0f}_{step_label}", candidate_angle, actual_x, actual_x - initial_x),
                    estimate,
                    alignment_error,
                )
                candidate_evaluations.append(
                    {
                        "direction": evaluation.candidate.direction,
                        "angleDelta": float(candidate_angle),
                        "targetX": float(target_x),
                        "actualX": float(actual_x),
                        "targetDeltaPx": float(abs(target_x - initial_x)),
                        "handleDeltaPx": float(actual_x - initial_x),
                        "dragEffective": bool(effective),
                        "weakDragEffect": bool(weak),
                        "alignmentError": float(alignment_error),
                        "score": float(estimate.score),
                        "confidenceMargin": float(estimate.confidence_margin),
                        "closedLoopRound": int(round_index + 1),
                        "closedLoopStep": step_label,
                        **_evaluation_diagnostic_payload(evaluation, config, effective=effective),
                        **rotation_components,
                    }
                )
                if effective and _candidate_sort_key(evaluation, config) < _candidate_sort_key(round_best_evaluation, config):
                    round_best_x = actual_x
                    round_best_evaluation = evaluation
                    round_best_image = _container_screenshot(page, config)
                    round_best_effective = effective
                    round_best_weak = weak
                    if _candidate_can_stop_after_estimate(
                        evaluation,
                        drag_effective=effective,
                        weak_drag_effect=weak,
                        config=config,
                    ):
                        release_ready_candidate = True
                        break
            if release_ready_candidate:
                break

        if (
            not release_ready_candidate
            and base_error - float(round_best_evaluation.alignment_error) < float(config.closed_loop_min_improvement)
        ):
            if abs(probe_current_x - best_x) > 0.5:
                _move_handle_to_target(page, config, probe_current_x, start_y, best_x, track_box, handle_box)
            break

        rounds += 1
        improved = True
        best_x = round_best_x
        best_evaluation = round_best_evaluation
        best_image = round_best_image
        best_effective = round_best_effective
        best_weak = round_best_weak
        best_pre_changed = _image_fingerprint_changed(before_image, best_image)
        if abs(probe_current_x - best_x) > 0.5:
            _move_handle_to_target(page, config, probe_current_x, start_y, best_x, track_box, handle_box)
        if release_ready_candidate:
            break

    return best_x, best_evaluation, rounds, improved, best_image, best_effective, best_weak


def _drag_for_manual_confirmation(page: Any, config: SliderPuzzleConfig) -> SliderPuzzleResult:
    total_drag_px = 0.0
    last_angle = 0.0
    last_score = 0.0
    attempts = 0
    mouse_down = False
    start_y = 0.0
    current_x = 0.0
    initial_x = 0.0
    candidate_count = 0
    sample_count = 0
    selected_angle = 0.0
    selected_direction = ""
    bounded_fallback_applied = False
    selected_evaluation: _ManualDragEvaluation | None = None
    candidate_evaluations: list[dict[str, Any]] = []
    before_image: Image.Image | None = None
    selected_image: Image.Image | None = None
    handle_delta_px = 0.0
    drag_effective = False
    input_stable = True
    drag_strategy = ""
    drag_probe_effective = False
    weak_drag_effect = False
    closed_loop_rounds = 0
    closed_loop_improved = False
    release_blocked_reason = ""

    try:
        track_box, handle_box = _track_and_handle_boxes(page, config)
        before_image = _container_screenshot(page, config)
        activated = False
        for strategy in _drag_strategy_points(page, config, track_box, handle_box):
            try:
                track_box, handle_box = _track_and_handle_boxes(page, config)
                probe_effective, initial_x, current_x, start_y = _activate_drag_strategy(page, config, strategy, track_box, handle_box)
                mouse_down = True
                if probe_effective:
                    drag_strategy = strategy.name
                    drag_probe_effective = True
                    activated = True
                    break
                page.mouse.up()
                mouse_down = False
                page.wait_for_timeout(max(0, int(config.drag_retry_reset_ms)))
            except Exception:
                if mouse_down:
                    try:
                        page.mouse.up()
                    except Exception:
                        pass
                    mouse_down = False
                page.wait_for_timeout(max(0, int(config.drag_retry_reset_ms)))
        if not activated:
            return SliderPuzzleResult(
                False,
                0.0,
                0.0,
                0.0,
                attempts,
                "drag_strategy_exhausted",
                sample_dir=str(config.sample_dir or ""),
                input_stable=input_stable,
                drag_effective=False,
                drag_strategy=drag_strategy,
                drag_probe_effective=False,
                release_blocked_reason="drag_strategy_exhausted",
            )

        attempts += 1
        try:
            initial_estimate = estimate_slider_angle_from_page(page, config)
            last_angle = initial_estimate.angle_delta
            last_score = initial_estimate.score
        except Exception as exc:
            input_stable = "captcha_not_ready" not in str(exc)
            return SliderPuzzleResult(
                False,
                total_drag_px,
                last_angle,
                last_score,
                attempts,
                _clean_error(exc),
                input_stable=input_stable,
                drag_effective=False,
                drag_strategy=drag_strategy,
                drag_probe_effective=drag_probe_effective,
                release_blocked_reason=_clean_error(exc),
            )
        if _write_manual_sample(
            page,
            config,
            "00_initial",
            {
                "stage": "initial",
                "currentX": float(current_x),
                "initialX": float(initial_x),
                "trackBox": track_box,
                "handleBox": handle_box,
                "dragStrategy": drag_strategy,
                "dragProbeEffective": bool(drag_probe_effective),
                "estimate": _estimate_payload(initial_estimate, config.rotation_degrees),
            },
        ):
            sample_count += 1

        candidate_count = int(initial_estimate.candidate_count or max(1, round(config.rotation_degrees / RAY_STEP_DEGREES)))
        include_wide_prediction_offsets = (
            float(initial_estimate.score) < float(config.tolerance_score)
            or float(initial_estimate.confidence_margin) < 0.08
            or _angle_is_zero(initial_estimate.angle_delta, config.rotation_degrees)
        )
        candidates = _manual_confirmation_candidates(
            initial_estimate.angle_delta,
            track_box,
            handle_box,
            config.rotation_degrees,
            slider_rotation_degrees=_slider_relative_rotation_degrees(config),
            fixed_inner_rotation_degrees=(),
            fixed_inner_rotation_max_degrees=abs(float(config.inner_clockwise_rotation_degrees)),
            include_wide_prediction_offsets=include_wide_prediction_offsets,
            min_effective_drag_px=_drag_effective_threshold(config, track_box),
        )
        bounded_fallback_applied = bool(initial_estimate.bounded_fallback_applied)
        if not candidates:
            return SliderPuzzleResult(
                False,
                total_drag_px,
                initial_estimate.angle_delta,
                initial_estimate.score,
                attempts,
                "computed drag distance is zero",
                candidate_count=candidate_count,
                sample_dir=str(config.sample_dir or ""),
                sample_count=sample_count,
                matched_ray_count=int(initial_estimate.matched_ray_count),
                comparable_ray_count=int(initial_estimate.comparable_ray_count),
                ray_step_degrees=int(initial_estimate.ray_step_degrees),
                ray_width_pixels=int(initial_estimate.ray_width_pixels),
                bounded_fallback_applied=bounded_fallback_applied,
                input_stable=input_stable,
                drag_effective=False,
                confidence_margin=float(initial_estimate.confidence_margin),
                drag_strategy=drag_strategy,
                drag_probe_effective=drag_probe_effective,
                release_blocked_reason="computed drag distance is zero",
            )

        evaluations: list[_ManualDragEvaluation] = []
        no_effect_candidates = 0
        seen_candidate_targets = {round(float(candidate.target_x), 1) for candidate in candidates}

        def evaluate_candidate(candidate: _ManualDragCandidate, phase: str) -> bool:
            nonlocal current_x, start_y, track_box, handle_box, total_drag_px, drag_effective, weak_drag_effect, no_effect_candidates
            try:
                refreshed_track_box, refreshed_handle_box = _track_and_handle_boxes(page, config)
                current_x = float(refreshed_handle_box["x"]) + float(refreshed_handle_box["width"]) / 2.0
                start_y = float(refreshed_handle_box["y"]) + float(refreshed_handle_box["height"]) / 2.0
                track_box = refreshed_track_box
                handle_box = refreshed_handle_box
            except Exception:
                pass
            if abs(candidate.target_x - current_x) > 0.5:
                current_x = _move_handle_to_target(page, config, current_x, start_y, candidate.target_x, track_box, handle_box)
            try:
                after_track_box, after_handle_box = _track_and_handle_boxes(page, config)
                track_box = after_track_box
                handle_box = after_handle_box
                actual_x = float(after_handle_box["x"]) + float(after_handle_box["width"]) / 2.0
            except Exception:
                actual_x = current_x
            current_x = actual_x
            total_drag_px = current_x - initial_x
            target_delta = abs(candidate.target_x - initial_x)
            candidate_drag_effective, candidate_weak_drag = _classify_drag_effect(config, track_box, initial_x, candidate.target_x, current_x)
            try:
                estimate = estimate_slider_angle_from_page(page, config)
            except Exception:
                estimate = AngleEstimate(
                    candidate.angle_delta,
                    0.0,
                    initial_estimate.center_x,
                    initial_estimate.center_y,
                    initial_estimate.inner_radius,
                    candidate_count=candidate_count,
                )
            alignment_error = _alignment_error_for_angle(estimate.angle_delta, config.rotation_degrees)
            rotation_components = _slider_rotation_components_for_handle(current_x, track_box, handle_box, config)
            evaluation = _ManualDragEvaluation(candidate, estimate, alignment_error)
            evaluations.append(evaluation)
            candidate_evaluations.append(
                {
                    "phase": phase,
                    "direction": candidate.direction,
                    "angleDelta": float(candidate.angle_delta),
                    "targetX": float(candidate.target_x),
                    "actualX": float(current_x),
                    "targetDeltaPx": float(target_delta),
                    "handleDeltaPx": float(current_x - initial_x),
                    "dragEffective": bool(candidate_drag_effective),
                    "weakDragEffect": bool(candidate_weak_drag),
                    "alignmentError": float(alignment_error),
                    "score": float(estimate.score),
                    "confidenceMargin": float(estimate.confidence_margin),
                    "dragStrategy": drag_strategy,
                    **_evaluation_diagnostic_payload(evaluation, config, effective=candidate_drag_effective),
                    **rotation_components,
                }
            )
            if candidate_drag_effective:
                drag_effective = True
                no_effect_candidates = 0
            else:
                weak_drag_effect = weak_drag_effect or candidate_weak_drag
                no_effect_candidates += 1
                if no_effect_candidates >= max(1, int(config.max_no_effect_candidates)) and not drag_effective:
                    return False
            return True

        for candidate in candidates:
            if not evaluate_candidate(candidate, "coarse"):
                break
            if evaluations and _candidate_can_stop_after_estimate(
                evaluations[-1],
                drag_effective=bool(candidate_evaluations[-1].get("dragEffective", False)),
                weak_drag_effect=bool(candidate_evaluations[-1].get("weakDragEffect", False)),
                config=config,
            ):
                break

        stop_ready_after_coarse = any(
            _candidate_can_stop_after_estimate(
                evaluation,
                drag_effective=bool(item.get("dragEffective", False)),
                weak_drag_effect=bool(item.get("weakDragEffect", False)),
                config=config,
            )
            for evaluation, item in zip(evaluations, candidate_evaluations)
        )
        if evaluations and not stop_ready_after_coarse and int(config.manual_candidate_refine_top_k) > 0 and tuple(config.manual_candidate_refine_inner_offsets):
            effective_by_direction_for_refine = {
                str(item["direction"]): bool(item["dragEffective"])
                for item in candidate_evaluations
            }
            ranked_for_refine = sorted(
                evaluations,
                key=lambda evaluation: (
                    0 if effective_by_direction_for_refine.get(evaluation.candidate.direction, False) else 1,
                    *_candidate_sort_key(evaluation, config),
                ),
            )
            refine_candidates: list[_ManualDragCandidate] = []
            refine_top_k = max(0, int(config.manual_candidate_refine_top_k))
            for evaluation in ranked_for_refine[:refine_top_k]:
                base_inner = _inner_angle_for_relative_rotation(evaluation.candidate.angle_delta, config)
                for offset in config.manual_candidate_refine_inner_offsets:
                    refined_inner = base_inner + float(offset)
                    if refined_inner <= 0 or refined_inner >= abs(float(config.inner_clockwise_rotation_degrees)):
                        continue
                    refined_angle = _relative_rotation_for_inner_angle(refined_inner, config)
                    refined_drag_px = drag_distance_for_angle(refined_angle, float(track_box["width"]), float(handle_box["width"]), _slider_relative_rotation_degrees(config))
                    min_x = float(track_box["x"]) + float(handle_box["width"]) / 2.0
                    max_x = float(track_box["x"]) + float(track_box["width"]) - float(handle_box["width"]) / 2.0
                    refined_target_x = max(min_x, min(max_x, min_x + refined_drag_px))
                    target_key = round(float(refined_target_x), 1)
                    if target_key in seen_candidate_targets:
                        continue
                    seen_candidate_targets.add(target_key)
                    refine_candidates.append(
                        _ManualDragCandidate(
                            f"inner{refined_inner:g}",
                            float(refined_angle),
                            float(refined_target_x),
                            float(refined_target_x - min_x),
                        )
                    )
            for candidate in refine_candidates:
                if not evaluate_candidate(candidate, "refine"):
                    break
                if evaluations and _candidate_can_stop_after_estimate(
                    evaluations[-1],
                    drag_effective=bool(candidate_evaluations[-1].get("dragEffective", False)),
                    weak_drag_effect=bool(candidate_evaluations[-1].get("weakDragEffect", False)),
                    config=config,
                ):
                    break

        has_release_ready_candidate = any(
            _candidate_can_stop_after_estimate(
                evaluation,
                drag_effective=bool(item.get("dragEffective", False)),
                weak_drag_effect=bool(item.get("weakDragEffect", False)),
                config=config,
            )
            for evaluation, item in zip(evaluations, candidate_evaluations)
        )
        if (
            evaluations
            and bool(config.boundary_enabled)
            and not has_release_ready_candidate
            and tuple(config.boundary_refine_inner_offsets)
        ):
            boundary_ranked = sorted(
                evaluations,
                key=lambda evaluation: (
                    0 if int(evaluation.estimate.boundary_line_count) >= max(1, int(config.boundary_min_lines)) else 1,
                    -float(evaluation.estimate.boundary_score),
                    -float(evaluation.estimate.boundary_confidence_margin),
                    float(evaluation.alignment_error),
                ),
            )
            boundary_base = boundary_ranked[0]
            if int(boundary_base.estimate.boundary_line_count) >= max(1, int(config.boundary_min_lines)):
                boundary_refine_candidates: list[_ManualDragCandidate] = []
                base_inner = _inner_angle_for_relative_rotation(boundary_base.candidate.angle_delta, config)
                for offset in config.boundary_refine_inner_offsets:
                    refined_inner = base_inner + float(offset)
                    if refined_inner <= 0 or refined_inner >= abs(float(config.inner_clockwise_rotation_degrees)):
                        continue
                    refined_angle = _relative_rotation_for_inner_angle(refined_inner, config)
                    refined_drag_px = drag_distance_for_angle(refined_angle, float(track_box["width"]), float(handle_box["width"]), _slider_relative_rotation_degrees(config))
                    min_x = float(track_box["x"]) + float(handle_box["width"]) / 2.0
                    max_x = float(track_box["x"]) + float(track_box["width"]) - float(handle_box["width"]) / 2.0
                    refined_target_x = max(min_x, min(max_x, min_x + refined_drag_px))
                    target_key = round(float(refined_target_x), 1)
                    if target_key in seen_candidate_targets:
                        continue
                    seen_candidate_targets.add(target_key)
                    boundary_refine_candidates.append(
                        _ManualDragCandidate(
                            f"boundary_inner{refined_inner:g}",
                            float(refined_angle),
                            float(refined_target_x),
                            float(refined_target_x - min_x),
                        )
                    )
                for candidate in boundary_refine_candidates:
                    if not evaluate_candidate(candidate, "boundary_refine"):
                        break
                    if evaluations and _candidate_can_stop_after_estimate(
                        evaluations[-1],
                        drag_effective=bool(candidate_evaluations[-1].get("dragEffective", False)),
                        weak_drag_effect=bool(candidate_evaluations[-1].get("weakDragEffect", False)),
                        config=config,
                    ):
                        break
        has_release_ready_candidate = any(
            _candidate_can_stop_after_estimate(
                evaluation,
                drag_effective=bool(item.get("dragEffective", False)),
                weak_drag_effect=bool(item.get("weakDragEffect", False)),
                config=config,
            )
            for evaluation, item in zip(evaluations, candidate_evaluations)
        )
        if evaluations and not has_release_ready_candidate:
            trend_refine_candidates = _residual_trend_refine_candidates(
                evaluations,
                candidate_evaluations,
                seen_candidate_targets,
                track_box,
                handle_box,
                config,
            )
            for candidate in trend_refine_candidates:
                if not evaluate_candidate(candidate, "trend_refine"):
                    break
                if evaluations and _candidate_can_stop_after_estimate(
                    evaluations[-1],
                    drag_effective=bool(candidate_evaluations[-1].get("dragEffective", False)),
                    weak_drag_effect=bool(candidate_evaluations[-1].get("weakDragEffect", False)),
                    config=config,
                ):
                    break
        if not evaluations:
            return SliderPuzzleResult(
                False,
                total_drag_px,
                initial_estimate.angle_delta,
                initial_estimate.score,
                attempts,
                "no candidate evaluations",
                candidate_count=candidate_count,
                sample_dir=str(config.sample_dir or ""),
                sample_count=sample_count,
                input_stable=input_stable,
                drag_effective=False,
                confidence_margin=float(initial_estimate.confidence_margin),
                candidate_evaluations=candidate_evaluations,
                drag_strategy=drag_strategy,
                drag_probe_effective=drag_probe_effective,
                release_blocked_reason="no candidate evaluations",
            )
        effective_by_direction = {
            str(item["direction"]): bool(item["dragEffective"])
            for item in candidate_evaluations
        }
        weak_by_direction = {
            str(item["direction"]): bool(item.get("weakDragEffect", False))
            for item in candidate_evaluations
        }
        selected_evaluation = min(
            evaluations,
            key=lambda evaluation: (
                0 if effective_by_direction.get(evaluation.candidate.direction, False) else 1,
                *_candidate_sort_key(evaluation, config),
            ),
        )
        selected_candidate = selected_evaluation.candidate
        if abs(selected_candidate.target_x - current_x) > 0.5:
            current_x = _move_handle_to_target(page, config, current_x, start_y, selected_candidate.target_x, track_box, handle_box)
            try:
                final_track_box, final_handle_box = _track_and_handle_boxes(page, config)
                track_box = final_track_box
                handle_box = final_handle_box
                current_x = float(final_handle_box["x"]) + float(final_handle_box["width"]) / 2.0
            except Exception:
                pass
        total_drag_px = current_x - initial_x
        handle_delta_px = total_drag_px
        selected_angle = float(selected_candidate.angle_delta)
        selected_direction = selected_candidate.direction
        selected_drag_effective = effective_by_direction.get(selected_direction, False)
        selected_weak_drag = weak_by_direction.get(selected_direction, False)
        current_x, selected_evaluation, closed_loop_rounds, closed_loop_improved, selected_image, selected_drag_effective, selected_weak_drag = _closed_loop_correct(
            page,
            config,
            initial_x=initial_x,
            current_x=current_x,
            start_y=start_y,
            track_box=track_box,
            handle_box=handle_box,
            before_image=before_image,
            selected_evaluation=selected_evaluation,
            candidate_evaluations=candidate_evaluations,
        )
        total_drag_px = current_x - initial_x
        handle_delta_px = total_drag_px
        selected_angle = float(selected_evaluation.candidate.angle_delta)
        selected_direction = selected_evaluation.candidate.direction
        final_rotation_components = _slider_rotation_components_for_handle(current_x, track_box, handle_box, config)
        selected_drag_effective = bool(selected_drag_effective)
        selected_weak_drag = bool(selected_weak_drag)
        weak_drag_effect = weak_drag_effect or selected_weak_drag
        pre_release_changed = _image_fingerprint_changed(before_image, selected_image)
        release_blocked_reason = _release_blocked_reason(
            selected_evaluation,
            drag_effective=selected_drag_effective,
            weak_drag_effect=selected_weak_drag,
            pre_release_changed=pre_release_changed,
            config=config,
        )
        local_refine_applied = any(str(item.get("phase", "")) in {"refine", "boundary_refine"} for item in candidate_evaluations)
        candidate_diagnostics = _candidate_review_diagnostics(candidate_evaluations)
        if _write_manual_sample(
            page,
            config,
            "99_selected_pre_release",
            {
                "stage": "selected_pre_release",
                "direction": selected_direction,
                "candidateAngleDelta": float(selected_angle),
                "candidateDragPx": float(selected_evaluation.candidate.drag_px),
                "targetX": float(selected_evaluation.candidate.target_x),
                "currentX": float(current_x),
                "totalDragPx": float(total_drag_px),
                "selectedEstimate": _estimate_payload(selected_evaluation.estimate, config.rotation_degrees),
                "selectedAlignmentError": float(selected_evaluation.alignment_error),
                "candidateEvaluations": candidate_evaluations,
                "boundedFallbackApplied": bounded_fallback_applied,
                "dragEffective": bool(selected_drag_effective),
                "handleDeltaPx": float(handle_delta_px),
                "preReleaseChanged": bool(pre_release_changed),
                "dragStrategy": drag_strategy,
                "dragProbeEffective": bool(drag_probe_effective),
                "weakDragEffect": bool(selected_weak_drag),
                "closedLoopRounds": int(closed_loop_rounds),
                "closedLoopImproved": bool(closed_loop_improved),
                "releaseBlockedReason": release_blocked_reason,
                "localRefineApplied": bool(local_refine_applied),
                "candidateDiagnostics": candidate_diagnostics,
                **final_rotation_components,
            },
        ):
            sample_count += 1

        if release_blocked_reason:
            _release_with_locator_drag_to(page, config, current_x, start_y, track_box, handle_box)
            mouse_down = False
            page.wait_for_timeout(300)
            total_drag_px = current_x - initial_x
            return SliderPuzzleResult(
                False,
                total_drag_px,
                selected_angle,
                selected_evaluation.estimate.score,
                attempts,
                release_blocked_reason,
                released_for_manual_confirmation=True,
                selected_direction=selected_direction,
                alignment_error=float(selected_evaluation.alignment_error),
                candidate_count=candidate_count,
                sample_dir=str(config.sample_dir or ""),
                sample_count=sample_count,
                matched_ray_count=int(selected_evaluation.estimate.matched_ray_count),
                comparable_ray_count=int(selected_evaluation.estimate.comparable_ray_count),
                ray_step_degrees=int(selected_evaluation.estimate.ray_step_degrees),
                ray_width_pixels=int(selected_evaluation.estimate.ray_width_pixels),
                bounded_fallback_applied=bounded_fallback_applied,
                input_stable=input_stable,
                drag_effective=bool(selected_drag_effective),
                handle_delta_px=float(handle_delta_px),
                pre_release_changed=bool(pre_release_changed),
                confidence_margin=float(selected_evaluation.estimate.confidence_margin),
                candidate_evaluations=candidate_evaluations,
                drag_strategy=drag_strategy,
                drag_probe_effective=drag_probe_effective,
                weak_drag_effect=bool(selected_weak_drag),
                closed_loop_rounds=int(closed_loop_rounds),
                closed_loop_improved=bool(closed_loop_improved),
                release_blocked_reason=release_blocked_reason,
                slider_progress=float(final_rotation_components["sliderProgress"]),
                inner_rotation_degrees=float(final_rotation_components["innerRotationDegrees"]),
                outer_rotation_degrees=float(final_rotation_components["outerRotationDegrees"]),
                relative_rotation_degrees=float(final_rotation_components["relativeRotationDegrees"]),
                fusion_agreement_degrees=float(selected_evaluation.estimate.fusion_agreement_degrees),
                selected_method=str(selected_evaluation.estimate.selected_method),
                local_refine_applied=bool(local_refine_applied),
                candidate_diagnostics=candidate_diagnostics,
                boundary_line_count=int(selected_evaluation.estimate.boundary_line_count),
                boundary_score=float(selected_evaluation.estimate.boundary_score),
                boundary_confidence_margin=float(selected_evaluation.estimate.boundary_confidence_margin),
                boundary_angle_delta=float(selected_evaluation.estimate.boundary_angle_delta),
                boundary_top_angles=list(selected_evaluation.estimate.boundary_top_angles),
            )

        _release_with_locator_drag_to(page, config, current_x, start_y, track_box, handle_box)
        mouse_down = False
        page.wait_for_timeout(500)
        total_drag_px = current_x - initial_x
        return SliderPuzzleResult(
            True,
            total_drag_px,
            selected_angle,
            selected_evaluation.estimate.score,
            attempts,
            "",
            released_for_manual_confirmation=True,
            selected_direction=selected_direction,
            alignment_error=float(selected_evaluation.alignment_error),
            candidate_count=candidate_count,
            sample_dir=str(config.sample_dir or ""),
            sample_count=sample_count,
            matched_ray_count=int(selected_evaluation.estimate.matched_ray_count),
            comparable_ray_count=int(selected_evaluation.estimate.comparable_ray_count),
            ray_step_degrees=int(selected_evaluation.estimate.ray_step_degrees),
            ray_width_pixels=int(selected_evaluation.estimate.ray_width_pixels),
            bounded_fallback_applied=bounded_fallback_applied,
            input_stable=input_stable,
            drag_effective=bool(selected_drag_effective),
            handle_delta_px=float(handle_delta_px),
            pre_release_changed=bool(pre_release_changed),
            confidence_margin=float(selected_evaluation.estimate.confidence_margin),
            candidate_evaluations=candidate_evaluations,
            drag_strategy=drag_strategy,
            drag_probe_effective=drag_probe_effective,
            weak_drag_effect=bool(selected_weak_drag),
            closed_loop_rounds=int(closed_loop_rounds),
            closed_loop_improved=bool(closed_loop_improved),
            release_blocked_reason="",
            slider_progress=float(final_rotation_components["sliderProgress"]),
            inner_rotation_degrees=float(final_rotation_components["innerRotationDegrees"]),
            outer_rotation_degrees=float(final_rotation_components["outerRotationDegrees"]),
            relative_rotation_degrees=float(final_rotation_components["relativeRotationDegrees"]),
            fusion_agreement_degrees=float(selected_evaluation.estimate.fusion_agreement_degrees),
            selected_method=str(selected_evaluation.estimate.selected_method),
            local_refine_applied=bool(local_refine_applied),
            candidate_diagnostics=candidate_diagnostics,
            boundary_line_count=int(selected_evaluation.estimate.boundary_line_count),
            boundary_score=float(selected_evaluation.estimate.boundary_score),
            boundary_confidence_margin=float(selected_evaluation.estimate.boundary_confidence_margin),
            boundary_angle_delta=float(selected_evaluation.estimate.boundary_angle_delta),
            boundary_top_angles=list(selected_evaluation.estimate.boundary_top_angles),
        )
    finally:
        if mouse_down:
            try:
                page.wait_for_timeout(160)
                page.mouse.up()
            except Exception:
                pass


def _drag_handle(page: Any, handle_box: dict[str, float], drag_px: float) -> None:
    start_x = float(handle_box["x"]) + float(handle_box["width"]) / 2.0
    start_y = float(handle_box["y"]) + float(handle_box["height"]) / 2.0
    target_x = start_x + drag_px
    page.mouse.move(start_x, start_y)
    page.wait_for_timeout(80)
    page.mouse.down()
    page.wait_for_timeout(120)
    _drag_held_handle(page, start_x, start_y, target_x)
    page.wait_for_timeout(160)
    page.mouse.up()


def _drag_held_handle(page: Any, start_x: float, start_y: float, target_x: float) -> None:
    drag_px = target_x - start_x
    steps = max(16, min(48, int(abs(drag_px) / 5) + 1))
    for index in range(1, steps + 1):
        progress = index / steps
        eased = 1.0 - (1.0 - progress) * (1.0 - progress)
        x = start_x + drag_px * eased
        y = start_y + math.sin(progress * math.pi * 2.0) * 1.5
        page.mouse.move(x, y)
        page.wait_for_timeout(12)
    page.mouse.move(target_x, start_y)


def _visible_bounding_box(page: Any, selector: str) -> dict[str, float]:
    locator = page.locator(selector).first
    locator.wait_for(state="visible", timeout=5000)
    box = locator.bounding_box()
    if not box:
        raise RuntimeError(f"element has no bounding box: {selector}")
    if float(box.get("width", 0)) <= 0 or float(box.get("height", 0)) <= 0:
        raise RuntimeError(f"element has empty bounding box: {selector}")
    return box


def _track_and_handle_boxes(page: Any, config: SliderPuzzleConfig) -> tuple[dict[str, float], dict[str, float]]:
    try:
        track_box = _visible_bounding_box(page, config.track_selector)
        handle_box = _visible_bounding_box(page, config.handle_selector)
    except Exception:
        inferred_boxes = _infer_track_and_handle_boxes_from_container(page, config.container_selector)
        if inferred_boxes:
            return inferred_boxes
        raise
    if float(track_box["width"]) > float(handle_box["width"]) * 1.25:
        return track_box, handle_box
    inferred = _infer_track_box_from_handle(page, config.handle_selector)
    if inferred and float(inferred["width"]) > float(handle_box["width"]) * 1.25:
        return inferred, handle_box
    return track_box, handle_box


def _infer_track_and_handle_boxes_from_container(page: Any, container_selector: str) -> tuple[dict[str, float], dict[str, float]] | None:
    locator = page.locator(container_selector).first
    try:
        result = locator.evaluate(
            """(root) => {
                const visible = (element) => {
                    if (!element || !element.getBoundingClientRect) return false;
                    const style = window.getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    return style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && Number(style.opacity || 1) > 0.05
                        && rect.width > 0
                        && rect.height > 0;
                };
                const collect = (node, out) => {
                    if (!node) return;
                    const children = node.children ? Array.from(node.children) : [];
                    for (const child of children) {
                        out.push(child);
                        if (child.shadowRoot) collect(child.shadowRoot, out);
                        collect(child, out);
                    }
                };
                const rootRect = root.getBoundingClientRect();
                const elements = [];
                collect(root, elements);
                const rects = elements
                    .filter(visible)
                    .map((element) => {
                        const rect = element.getBoundingClientRect();
                        return {
                            x: rect.x,
                            y: rect.y,
                            width: rect.width,
                            height: rect.height,
                            centerX: rect.x + rect.width / 2,
                            centerY: rect.y + rect.height / 2,
                            area: rect.width * rect.height,
                        };
                    })
                    .filter((rect) =>
                        rect.x >= rootRect.x - 2
                        && rect.x + rect.width <= rootRect.x + rootRect.width + 2
                        && rect.y >= rootRect.y + rootRect.height * 0.45
                        && rect.y + rect.height <= rootRect.y + rootRect.height + 4
                    );
                const tracks = rects
                    .filter((rect) =>
                        rect.width >= rootRect.width * 0.55
                        && rect.height >= 24
                        && rect.height <= 80
                    )
                    .sort((a, b) => (b.width - a.width) || (b.y - a.y));
                const track = tracks[0];
                if (!track) return null;
                const handles = rects
                    .filter((rect) =>
                        rect.width >= 32
                        && rect.width <= Math.min(110, track.width * 0.45)
                        && rect.height >= 24
                        && rect.height <= Math.max(90, track.height * 1.8)
                        && Math.abs(rect.centerY - track.centerY) <= Math.max(18, track.height * 0.75)
                        && rect.x >= track.x - 8
                        && rect.x + rect.width <= track.x + track.width + 8
                    )
                    .sort((a, b) => Math.abs(a.centerY - track.centerY) - Math.abs(b.centerY - track.centerY)
                        || Math.abs(a.height - track.height) - Math.abs(b.height - track.height)
                        || b.area - a.area);
                const handle = handles[0] || {
                    x: track.x,
                    y: track.y,
                    width: Math.min(64, Math.max(40, track.height * 1.6)),
                    height: track.height,
                };
                return {
                    track: { x: track.x, y: track.y, width: track.width, height: track.height },
                    handle: { x: handle.x, y: handle.y, width: handle.width, height: handle.height },
                };
            }"""
        )
    except Exception:
        return None
    if not isinstance(result, dict):
        return None
    track = result.get("track")
    handle = result.get("handle")
    if not isinstance(track, dict) or not isinstance(handle, dict):
        return None
    if float(track.get("width", 0) or 0) <= 0 or float(track.get("height", 0) or 0) <= 0:
        return None
    if float(handle.get("width", 0) or 0) <= 0 or float(handle.get("height", 0) or 0) <= 0:
        return None
    return track, handle


def _infer_track_box_from_handle(page: Any, handle_selector: str) -> dict[str, float] | None:
    locator = page.locator(handle_selector).first
    try:
        box = locator.evaluate(
            """(node) => {
                const visible = (element) => {
                    if (!element || !element.getBoundingClientRect) return false;
                    const style = window.getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    return style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && Number(style.opacity || 1) > 0.05
                        && rect.width > 0
                        && rect.height > 0;
                };
                const nextParent = (element) => {
                    if (element.parentElement) return element.parentElement;
                    const root = element.getRootNode && element.getRootNode();
                    return root && root.host ? root.host : null;
                };
                const handleRect = node.getBoundingClientRect();
                let current = nextParent(node);
                for (let depth = 0; current && depth < 8; depth += 1) {
                    if (visible(current)) {
                        const rect = current.getBoundingClientRect();
                        const centerDelta = Math.abs((rect.top + rect.height / 2) - (handleRect.top + handleRect.height / 2));
                        if (rect.width > handleRect.width * 1.25
                            && rect.height >= handleRect.height * 0.45
                            && centerDelta <= Math.max(rect.height, handleRect.height)) {
                            return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
                        }
                    }
                    current = nextParent(current);
                }
                return null;
            }"""
        )
    except Exception:
        return None
    if not isinstance(box, dict):
        return None
    if float(box.get("width", 0) or 0) <= 0 or float(box.get("height", 0) or 0) <= 0:
        return None
    return box


def _success_selector_visible(page: Any, config: SliderPuzzleConfig) -> bool:
    if not config.success_selector:
        return False
    try:
        return bool(page.locator(config.success_selector).first.is_visible(timeout=300))
    except Exception:
        return False


def _validate_config(config: SliderPuzzleConfig) -> str:
    if not config.container_selector:
        return "container_selector is required"
    if not config.track_selector:
        return "track_selector is required"
    if not config.handle_selector:
        return "handle_selector is required"
    if config.rotation_degrees <= 0:
        return "rotation_degrees must be positive"
    if config.max_attempts <= 0:
        return "max_attempts must be positive"
    if not 0 < config.tolerance_score <= 1:
        return "tolerance_score must be in (0, 1]"
    return ""


def _validate_page_url(page_url: str) -> str:
    parsed = urlparse(page_url)
    host = (parsed.hostname or "").lower().strip(".")
    if not host or host in {"localhost", "127.0.0.1", "::1"}:
        return ""
    try:
        if host == socket.gethostname().lower():
            return ""
    except Exception:
        pass
    if any(host == suffix or host.endswith(f".{suffix}") for suffix in BLOCKED_PUBLIC_HOST_SUFFIXES):
        return f"refusing to solve slider puzzle on third-party public host: {host}"
    return ""


def _angle_is_aligned(angle_delta: float, rotation_degrees: float) -> bool:
    normalized = float(angle_delta) % float(rotation_degrees)
    return normalized <= ANGLE_TOLERANCE_DEGREES or normalized >= float(rotation_degrees) - ANGLE_TOLERANCE_DEGREES


def _angle_is_zero(angle_delta: float, rotation_degrees: float) -> bool:
    normalized = float(angle_delta) % float(rotation_degrees)
    return normalized <= 1e-6


def _bounded_radii(start: float, end: float, width: int, height: int, center_x: float, center_y: float) -> list[float]:
    max_radius = min(center_x, center_y, width - 1 - center_x, height - 1 - center_y)
    lower = max(1.0, start)
    upper = min(max_radius, end)
    if upper < lower:
        return []
    return [float(value) for value in range(int(math.ceil(lower)), int(math.floor(upper)) + 1)]


def _visible_content_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    pixels = image.convert("RGBA").load()
    left = image.width
    top = image.height
    right = -1
    bottom = -1
    for y in range(image.height):
        for x in range(image.width):
            if not _pixel_has_content(pixels[x, y]):
                continue
            left = min(left, x)
            top = min(top, y)
            right = max(right, x)
            bottom = max(bottom, y)
    if right < left or bottom < top:
        return None
    return left, top, right + 1, bottom + 1


def _pixel_has_content(pixel: tuple[int, int, int, int]) -> bool:
    red, green, blue, alpha = pixel
    if alpha <= 20:
        return False
    return not (red > 246 and green > 246 and blue > 246)


def _clean_error(exc: Exception) -> str:
    return " ".join(str(exc).split())[:500]


def _write_result(result: SliderPuzzleResult) -> None:
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Solve a self-owned circular slider puzzle with Playwright.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--container", required=True, dest="container_selector")
    parser.add_argument("--track", required=True, dest="track_selector")
    parser.add_argument("--handle", required=True, dest="handle_selector")
    parser.add_argument("--inner-selector", default=None)
    parser.add_argument("--success", default=None, dest="success_selector")
    parser.add_argument("--sample-dir", default=None)
    parser.add_argument("--rotation-degrees", type=float, default=360)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--tolerance-score", type=float, default=0.92)
    parser.add_argument("--headless", dest="headless", action="store_true", default=True)
    parser.add_argument("--visible-browser", dest="headless", action="store_false")
    parser.add_argument("--screenshot-out", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    config = SliderPuzzleConfig(
        container_selector=args.container_selector,
        track_selector=args.track_selector,
        handle_selector=args.handle_selector,
        inner_selector=args.inner_selector,
        success_selector=args.success_selector,
        sample_dir=args.sample_dir,
        rotation_degrees=args.rotation_degrees,
        max_attempts=args.max_attempts,
        tolerance_score=args.tolerance_score,
    )
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        result = SliderPuzzleResult(False, 0.0, 0.0, 0.0, 0, _clean_error(exc))
        _write_result(result)
        return 2

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=bool(args.headless))
        try:
            page = browser.new_page(viewport={"width": 900, "height": 700})
            page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
            result = solve_slider_puzzle(page, config)
            if args.screenshot_out:
                page.screenshot(path=str(Path(args.screenshot_out)))
            _write_result(result)
            return 0 if result.success else 1
        finally:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
