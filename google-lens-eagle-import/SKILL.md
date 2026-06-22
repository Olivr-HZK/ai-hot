---
name: google-lens-eagle-import
description: Run the local Google Lens full-frame workflow for one or more user-provided images, verify the Lens URL uses the full original image, extract a broad Visual matches candidate pool, keep up to 10 matches related to visual language, visual communication, design references, image/video aesthetics, AI prompts, image/video generation, or generation-model/tool workflows, optionally extract Instagram permalinks from the raw Lens candidates and pass them through the local INS filters, and import Lens thumbnails with source URLs into Eagle. Use when the user provides image paths or images and asks to Lens search, reverse-image search, test Lens results, import visual-reference matches, batch process images, save visually similar results into Eagle, or filter Lens-discovered Instagram posts.
---

# Google Lens Eagle Import

## Overview

Use the existing local Google Lens workspace at `$GOOGLE_LENS_WORKSPACE`.
The canonical runtime is `scripts/full_frame_lens.mjs`; do not reimplement Lens URL encoding, Chrome upload, match extraction, or Eagle import logic.

This skill uploads each input image to Google Lens through Codex Chrome runtime, drives the visible search-area sliders to full frame when available, verifies the final selection, extracts a broad candidate pool of Visual matches, keeps up to 10 matches related to visual language, visual communication, design references, image/video aesthetics, AI prompts, image/video generation, or generation-model/tool workflows, cleans noisy Google UI text out of match titles, filters out Logo/site-icon/brand-icon thumbnails, and imports only those relevant match thumbnails into Eagle with source URLs. When Instagram post filtering is requested, preserve the raw Lens candidate pool, extract Instagram `/p/`, `/reel/`, and `/tv/` permalinks from it, and run `scripts/filter_instagram_matches.py` so only posts approved by the main project's INS filters are shown.

## Workflow

1. Confirm the input images are local absolute paths. If the user attaches images, use the resolved file paths from the prompt/context.
2. Run local preflight checks from `$GOOGLE_LENS_WORKSPACE`:
   - `node --check scripts/full_frame_lens.mjs`
   - `node scripts/full_frame_lens.test.mjs`
   - read dimensions with `sips -g pixelWidth -g pixelHeight`.
3. Use the Chrome plugin runtime through `node_repl`; load `chrome:control-chrome` guidance if not already loaded.
4. Convert `$GOOGLE_LENS_WORKSPACE` to a file URL as `workspaceFileUrl`, then import the module with a cache-busting file URL:
   ```js
   var lens = await import(workspaceFileUrl + "/scripts/full_frame_lens.mjs?run=" + Date.now());
   ```
5. For one image, call:
   ```js
   var result = await lens.runFullFrameLens(browser, imagePath, {
     trigger: "auto",
     visualMatchesLimit: 10,
     visualMatchesFilter: "visual-communication",
     visualMatchesCandidateLimit: 100,
     visualMatchesScrollAttempts: 5,
     visualMatchesRetryWaitMs: 1000
   });
   ```
6. For multiple images, call:
   ```js
   var result = await lens.runConcurrentFullFrameLensUploads(browser, imagePaths, {
     trigger: "auto",
     concurrency: imagePaths.length,
     visualMatchesLimit: 10,
     visualMatchesFilter: "visual-communication",
     visualMatchesCandidateLimit: 100,
     visualMatchesScrollAttempts: 5,
     visualMatchesRetryWaitMs: 1000
   });
   ```
7. After browser work, call `await browser.tabs.finalize({ keep: [] })` unless the user explicitly asks to keep result tabs open.

## Acceptance Checks

Treat a run as successful when every requested image reports:
- `status: "opened-results"`
- `selectionVerified: true`
- `vsintImageSize` equals the original image dimensions, or only `selectionWarnings` about Google's internal size rewrite appear
- `visualMatchesRequested: 10`
- `visualMatchesCandidateLimit: 100`
- `visualMatchesCandidatesFound`, `visualMatchesRelevantFound`, and `visualMatchesFilteredOut` are recorded
- `visualMatchesFound` is recorded and contains only visual-language, visual-communication, design-reference, image/video-aesthetic, AI/prompt, image/video-generation, or model-tool related matches; if fewer than 10 relevant matches exist, do not pad with unrelated results
- `visualMatches[].title` is a concise match title rather than a merged Google UI text block when the page exposes one
- `eagleImported` plus `eagleFailed` reflects the import outcome
- `eagleSkippedLogoThumbnails` is recorded when Google returns Logo/site-icon thumbnails that were intentionally not imported

For batch runs, report:
- requested/succeeded/failed images
- total relevant Visual matches found and, when useful, candidate/filter counts
- total Eagle imports, failures, and skipped Logo thumbnails
- first 1-3 sample matches per image, including `title`, `domain`, `platform`, and `sourceUrl`

## Topic Filter

By default, import Lens matches related to visual communication broadly. The target is 10 relevant matches after filtering, not the first 10 raw Google results. Relevant signals include visual language, visual communication, graphic design, art direction, creative direction, design references, moodboards, key visuals, composition, layout, typography, color palette, visual hierarchy, lighting, cinematography, photography style/reference, poster/editorial/brand/advertising/illustration/character/concept/motion design, plus AI/prompt/generation signals such as ChatGPT/GPT, prompt/prompting, Gemini, Midjourney, Stable Diffusion, Flux, DALL-E, ComfyUI, Civitai, Sora, Veo, Kling, Runway, Luma, Pika, text-to-image, image-to-video, AIGC, 提示词, 视觉语言, 视觉传达, 设计参考, 构图, 版式, 色彩搭配, 主视觉, 镜头语言, 摄影风格, 海报设计, 品牌视觉, 广告视觉, 插画风格, 概念艺术, 文生图, 图生图, 文生视频, 图生视频, 图片生成, and 视频生成.

If Google returns unrelated matches such as ordinary products, shopping, eBay, stock listings, celebrity gossip, generic social posts, command-prompt/software help, or generic image/video pages without visual-language, visual-communication, design-reference, aesthetic, AI, prompt, or generation context, skip them before Eagle import. The runner should search a larger candidate pool (`visualMatchesCandidateLimit: 100`) to find up to 10 relevant results. If fewer than 10 relevant matches exist in that pool, import fewer rather than padding with unrelated matches. Keep `visualMatchesFilter: "visual-communication"` unless the user explicitly asks for an unfiltered Lens import.

## Instagram Post Filter

When the user asks to filter Lens-discovered Instagram posts, first save the full raw candidate pool, then run:

```powershell
python google-lens-eagle-import/scripts/filter_instagram_matches.py --lens-run-dir <run-dir>
```

The script only treats `instagram.com/p/`, `instagram.com/reel/`, and `instagram.com/tv/` permalinks as Instagram posts. It dedupes by shortcode, enriches metadata through the project's existing Instagram cookie/yt-dlp path, and runs the same local INS normalization, engagement, product, safety, feedback, and visual-dedupe filters used by manual INS discovery. It writes local-only outputs in the Lens run directory: `instagram_candidates.json`, `instagram_enriched.json`, `instagram_blocked.json`, `instagram_approved.json`, `instagram_approved.md`, and `instagram_filter_report.json`. Do not write Feishu, push notifications, or import original Instagram source media into Eagle from this step.

## Keyword Images To Lens Pipeline

When the user asks for keyword image search followed by Lens expansion and INS filtering, run the independent local pipeline:

```powershell
python google-lens-eagle-import/scripts/google_images_keyword_lens_pipeline.py --keywords "<keyword 1>,<keyword 2>" --visible-browser
```

Defaults are small-batch validation settings: `--max-keywords 5`, `--images-per-keyword 30`, `--seeds-per-keyword 3`, and `--lens-candidates 100`. The pipeline uses a persistent local Chrome profile at `skill_runs/browser_profiles/google_images_keyword_lens`, waits for at most one human Google verification, and then marks the run `degraded` if verification repeats or times out. It does not use external search APIs, does not bypass CAPTCHA, and never writes Feishu, pushes notifications, or imports Eagle items.

Every stage writes local artifacts under `skill_runs/google_lens_eagle_import/keyword_lens_runs/<run_id>/`: Google Images raw candidates and downloads, seed product/safety/visual-dedupe outputs, per-seed Lens HTML/screenshot/raw matches, aggregated Lens matches, Instagram candidate/enrichment/filter outputs, `stage_report.json`, `run_manifest.json`, `final_approved.json`, and `final_approved.md`.

## Eagle Rules

Eagle must receive Lens thumbnails, not original source media from social sites.
Never import Logo, favicon, site-icon, app-icon, brandmark, social-platform logo, or placeholder brand thumbnails. These are not useful Visual matches. The runner filters these before Eagle import and reports them through `eagleSkipped` / `eagleSkippedLogoThumbnails`; do not treat skipped Logo thumbnails as failures.
Each imported item should include:
- image source: Lens thumbnail URL
- source URL: original match URL, stored as Eagle item `url`/`source.website`
- annotation line: `Source: ...`
- tags: `google-lens`, `lens-thumbnail`, `lens-rank-N`, `source-*`, and platform tags when available

If Eagle is unavailable or an item import fails, do not hide the Lens verification result. Report `eagleFailed`, `visualMatchesError`, and any failure summary.

## Notes

- The Codex Chrome extension must have "Allow access to file URLs" enabled.
- Eagle must be running with the local API server on `http://127.0.0.1:41596`.
- Do not use the legacy AppleScript/clipboard CLI path unless the user explicitly asks for the compatibility CLI.
- Do not import original Instagram, TikTok, YouTube, Facebook, or other source media; import only Lens thumbnails and source metadata.
- Prefer the slider-first extension workflow over URL-only `vsint` rewrites or repeated corner-click dragging. Drag fallback is only for cases where Google does not expose usable slider controls.
- For deeper field details, read `references/result-fields.md`.
