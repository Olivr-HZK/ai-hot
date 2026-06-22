# Result Fields

Core per-image fields:
- `status`: expected `opened-results`
- `lensUrl`: final Google Lens/Google Search URL
- `selectionVerified`: full-frame geometry verification
- `vsintImageSize`: decoded image size from final `vsint`
- `selectionWarnings`: non-fatal warnings, usually Google internal size rewrite
- `visualMatchesRequested`: default `10`
- `visualMatchesCandidateLimit`: default `100`
- `visualMatchesFound`: number of matches extracted
- `visualMatches`: public match summaries with `rank`, `title`, `thumbnailUrl`, `sourceUrl`, `domain`, `platform`, `isSocial`
- `eagleImport.summary`: total matches, requested imports, imported items, failed items, skipped items, skipped Logo thumbnails, social matches
- `eagleImported`: imported count
- `eagleFailed`: failed import count
- `eagleSkipped`: intentionally skipped count
- `eagleSkippedLogoThumbnails`: Logo/site-icon/brand-icon thumbnails intentionally not imported

Batch summary fields:
- `requested`
- `succeeded`
- `failed`
- `totalVisualMatchesFound`
- `totalEagleImported`
- `totalEagleFailed`
- `totalEagleSkipped`
- `totalEagleSkippedLogoThumbnails`
- `sharedClipboard: false`
- `sharedActiveTab: false`

Instagram filter outputs, when requested:
- `instagram_candidates.json`: deduped Instagram `/p/`, `/reel/`, and `/tv/` permalinks extracted from raw Lens candidates
- `instagram_enriched.json`: candidates successfully enriched through the local Instagram cookie/yt-dlp metadata path
- `instagram_blocked.json`: candidates blocked before or during filtering, with `reason`
- `instagram_approved.json`: posts approved by the existing local INS filters
- `instagram_approved.md`: readable approved-post summary for manual inspection
- `instagram_filter_report.json`: counts, filter stats, and output paths

Keyword Images -> Lens pipeline outputs:
- `keywords.json`: selected keyword list after dedupe and `--max-keywords`
- `google_images_raw_candidates.json`: normalized Google Images candidates with `keyword`, `sourceUrl`, `imageUrl`, `thumbnailUrl`, `domain`, and `rank`
- `google_images_downloaded.json`: downloaded seed image files plus fetch status
- `google_images_fetch_report.json`: per-keyword browser fetch status and saved page paths
- `seed_product_passed.json` / `seed_product_blocked.json`: product relevance review outputs
- `seed_safety_passed.json` / `seed_safety_blocked.json`: image safety review outputs
- `seed_visual_approved.json` / `seed_visual_deduped.json`: visual dedupe and per-keyword seed cap outputs
- `lens_seeds/<seed>/all_visual_matches.json`: raw Lens matches for one approved seed
- `lens_seeds/<seed>/lens_results_attr.json`: per-seed Lens status, seed metadata, and match list
- `lens_matches_all.json`: aggregated Lens matches with `seedId`, `seedKeyword`, `seedRank`, `seedImagePath`, and `seedRefs`
- `final_approved.json` / `final_approved.md`: final local-only INS posts that passed the full filter chain
- `stage_report.json`: counts, failures, and `degraded` reason for the whole run
- `run_manifest.json`: run parameters, profile path, cookie path, and local-only side-effect flags

Useful failure fields:
- `error`
- `visualMatchesError`
- `eagleImport.failures`
- `eagleImport.skipped`
