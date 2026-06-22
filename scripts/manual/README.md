# Manual tools

This directory is intentionally isolated from canonical pipeline outputs.

Rules for scripts in this directory:

- They must be launched manually and must not be imported or called by `run_pipeline.py`, cron scripts, or scheduled PowerShell scripts, unless a script is explicitly documented as a shared daily helper.
- They must not write Feishu records or send Feishu pushes by default.
- They must not overwrite canonical pipeline outputs such as `skill_runs/hotspots.json`.
- Audit outputs should go under `skill_runs/manual_audits/`.
- If a manual script needs to write Feishu or push messages, it must require an explicit command-line flag.
- `fetch_socialcrawl_tiktok_trending.py` also requires `--confirm-spend-credits` before it sends a SocialCrawl request.
- `ins_keyword_discovery.py` writes only to `skill_runs/instagram_keyword_discovery/` by default. It reads high-quality Instagram feedback seeds, learns search terms, maintains a persistent local keyword pool, searches Instagram with local account cookies, and audits candidates without writing Feishu or canonical hotspot files. The former 00:01 schedule is disabled by default; `scripts/cron_ins_keyword_discovery.sh` and `scripts/scheduled_ins_keyword_discovery.ps1` only run when `INS_KEYWORD_DISCOVERY_DAILY_ENABLED=true`. The 07:00 main pipeline only merges its approved report when `INS_KEYWORD_DISCOVERY_MERGE_ENABLED=true`.
