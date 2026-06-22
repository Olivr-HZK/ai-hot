from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = SCRIPT_DIR.parent
BASE_DIR = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

from creator_pool import append_creator_urls, read_creator_pool
from env_utils import load_env
from ins_product_fit import apply_product_fit
from ins_rules import load_ins_rules, resolve_path
from ins_safety_review import apply_ins_safety_review
from ins_scoring import clean_text, normalize_ins_post, passes_media_policy, passes_quality, within_lookback
from ins_storage import save_posts
from provider_rapidapi import RapidApiCreatorSearchProvider, RapidApiInstagramProvider


DEBUG_DIR = BASE_DIR / "skill_runs" / "instagram"


def openrouter_json(model: str, prompt: str, *, max_tokens: int = 1200) -> dict[str, Any] | None:
    env = load_env()
    api_key = os.environ.get("OPENROUTER_API_KEY") or env.get("OPENROUTER_API_KEY", "")
    if not api_key:
        return None
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "max_tokens": max_tokens,
        },
        timeout=60,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"].get("content") or "{}"
    parsed = json.loads(content)
    return parsed if isinstance(parsed, dict) else None


def compact_post_sample(posts: list[dict[str, Any]], limit: int = 60) -> list[dict[str, Any]]:
    sample = []
    for item in posts[:limit]:
        sample.append(
            {
                "author": (item.get("authorMeta") or {}).get("nickName") if isinstance(item.get("authorMeta"), dict) else "",
                "text": clean_text(item.get("text") or item.get("title"), max_len=300),
                "hashtags": item.get("hashtags", [])[:12] if isinstance(item.get("hashtags"), list) else [],
                "mediaType": item.get("mediaType"),
                "likes": item.get("diggCount"),
                "comments": item.get("commentCount"),
                "productFit": item.get("insProductFit", {}),
            }
        )
    return sample


def fallback_search_queries(rules: dict[str, Any]) -> list[str]:
    queries = rules.get("creator_discovery", {}).get("default_search_queries", [])
    return [str(query).strip() for query in queries if str(query).strip()]


def learn_seed_queries(posts: list[dict[str, Any]], rules: dict[str, Any]) -> list[str]:
    cfg = rules.get("creator_discovery", {})
    model = str(cfg.get("model") or "qwen/qwen3.7-max")
    prompt = (
        "You are maintaining an Instagram creator pool for primary focus products Evoke, Toki, Kavi, and Avatar; "
        "learn the high-quality creator themes from these seed Instagram posts, then generate search queries for finding similar public creators. "
        "Prioritize image/carousel creators: real-person portraits, non-AI photography, fashion/editorial photos, "
        "family/couple/pet photos, makeup/hairstyle/outfit, wedding/graduation/holiday/travel photos, "
        "AI photo workflows, photo enhancement, creative portraits, and reusable UA ad templates. "
        "Return JSON: {\"searchQueries\": [string], \"positiveTraits\": [string], \"negativeTraits\": [string]}.\n"
        f"Seed posts JSON:\n{json.dumps(compact_post_sample(posts), ensure_ascii=False)}"
    )
    try:
        parsed = openrouter_json(model, prompt)
    except Exception as exc:
        print(f"  - INS creator query learning skipped: {exc}", flush=True)
        parsed = None
    queries = parsed.get("searchQueries", []) if isinstance(parsed, dict) else []
    cleaned = [clean_text(query) for query in queries if clean_text(query)]
    return cleaned[:12] or fallback_search_queries(rules)


def validate_creator_with_model(url: str, posts: list[dict[str, Any]], rules: dict[str, Any]) -> dict[str, Any]:
    cfg = rules.get("creator_discovery", {})
    model = str(cfg.get("model") or "qwen/qwen3.7-max")
    prompt = (
        "You are validating an Instagram creator for a high-quality AI creative and UA material pool. "
        "Accept only creators whose recent public posts are high-quality, safe, image/carousel-oriented, "
        "and relevant to Evoke photo enhancer, Toki photo-to-video, Kavi selfie-to-video/trending effects, "
        "Avatar profile-photo puzzle social loops, or non-AI visual material "
        "that can clearly become UA advertising creative. "
        "Reject generic meme pages, NSFW/edge-bait, hardware/news accounts, low-effort prompt spam, "
        "and unrelated lifestyle accounts. Return strict JSON: "
        "{\"isHighQualityCreator\": boolean, \"confidence\": number, \"contentThemes\": [string], "
        "\"productFit\": [\"evoke\"|\"toki\"|\"kavi\"|\"avatar_jigsaw\"], \"reason\": string}.\n"
        f"Creator URL: {url}\nRecent posts JSON:\n{json.dumps(compact_post_sample(posts, limit=20), ensure_ascii=False)}"
    )
    try:
        parsed = openrouter_json(model, prompt)
    except Exception as exc:
        return {"isHighQualityCreator": False, "confidence": 0, "reason": f"model validation failed: {exc}"}
    if not isinstance(parsed, dict):
        return {"isHighQualityCreator": False, "confidence": 0, "reason": "model returned no JSON object"}
    return parsed


def deterministic_creator_pass(posts: list[dict[str, Any]], rules: dict[str, Any]) -> bool:
    min_valid = int(rules.get("creator_discovery", {}).get("min_valid_posts", 2) or 2)
    valid = 0
    for item in posts:
        fit = item.get("insProductFit") if isinstance(item.get("insProductFit"), dict) else {}
        if fit.get("isRelevant") and passes_media_policy(item, rules) and passes_quality(item, rules):
            valid += 1
    return valid >= min_valid


def normalize_candidate_posts(raw_posts: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    lookback = int(rules.get("creator_pool", {}).get("lookback_hours", 48) or 48)
    normalized = [normalize_ins_post(item, rules) for item in raw_posts]
    save_posts(normalized, rules, stage="creator_discovery")
    normalized = [item for item in normalized if within_lookback(item, max(lookback, 336))]
    normalized = [item for item in normalized if passes_media_policy(item, rules)]
    normalized = apply_product_fit(normalized, rules)
    kept, _blocked = apply_ins_safety_review(normalized, rules)
    return kept


def make_manual_review_path() -> Path:
    review_dir = DEBUG_DIR / "manual_review"
    review_dir.mkdir(parents=True, exist_ok=True)
    return review_dir / f"ins_creator_review_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"


def write_manual_review_file(
    accepted: list[dict[str, Any]],
    report_path: Path | None = None,
    review_path: Path | None = None,
) -> Path:
    review_path = review_path or make_manual_review_path()
    review_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Instagram creator discovery manual review",
        f"# generated_at={datetime.now().isoformat()}",
    ]
    if report_path:
        lines.append(f"# report={report_path}")
    lines.append("# accepted creator profile URLs:")
    for item in accepted:
        url = clean_text(item.get("url"))
        if url:
            lines.append(url)
    review_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return review_path


def discover_and_update_creator_pool(
    *,
    rules: dict[str, Any] | None = None,
    dry_run: bool | None = None,
    max_new_creators: int | None = None,
    validation_limit: int | None = None,
    seed_raw_posts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rules = rules or load_ins_rules()
    cfg = rules.get("creator_discovery", {})
    if dry_run is None:
        dry_run = bool(cfg.get("dry_run", False))
    validate_limit = int(validation_limit if validation_limit is not None else cfg.get("validation_limit", 50) or 50)
    max_new = int(max_new_creators if max_new_creators is not None else cfg.get("max_new_creators", validate_limit) or validate_limit)
    pool_path = resolve_path(rules.get("creator_pool", {}).get("csv_path", "AIGC-INS.csv"))
    existing_urls = read_creator_pool(pool_path)
    provider = RapidApiInstagramProvider(rules)
    if not provider.available():
        raise RuntimeError("INS_RAPIDAPI_KEY is required for INS creator discovery")
    search_provider = RapidApiCreatorSearchProvider(rules)
    review_path = make_manual_review_path()
    write_manual_review_file([], review_path=review_path)

    if seed_raw_posts is None:
        seed_limit = int(cfg.get("seed_creator_limit", 12) or 12)
        print(f"  - INS creator discovery fetching seed posts from {seed_limit} existing creators", flush=True)
        seed_raw_posts = provider.fetch_profile_posts(existing_urls[:seed_limit])
    seed_posts = normalize_candidate_posts(seed_raw_posts, rules)
    queries = learn_seed_queries(seed_posts, rules)
    print(f"  - INS creator discovery generated {len(queries)} search queries", flush=True)

    search_limit = int(cfg.get("search_limit_per_query", 10) or 10)
    candidate_urls: list[str] = []
    search_errors: list[dict[str, Any]] = []
    for query in queries:
        print(f"  - INS creator discovery searching: {query}", flush=True)
        try:
            if not search_provider.available():
                raise RuntimeError("RapidAPI creator search provider is unavailable")
            results = search_provider.search_creators(query, limit=search_limit)
        except Exception as exc:
            message = clean_text(exc, max_len=300)
            search_errors.append({"query": query, "message": message})
            print(f"  - INS RapidAPI creator search skipped for {query!r}: {message}", flush=True)
            continue
        for url in results:
            if url and url not in existing_urls and url not in candidate_urls:
                candidate_urls.append(url)
        if len(candidate_urls) >= validate_limit * 2:
            break
    print(f"  - INS creator discovery found {len(candidate_urls)} candidate profile URLs", flush=True)
    if not candidate_urls:
        provider_errors = search_provider.usage.get("errors", []) if isinstance(search_provider.usage, dict) else []
        provider_queries = search_provider.usage.get("queries", []) if isinstance(search_provider.usage, dict) else []
        for error in provider_errors:
            search_errors.append({"query": clean_text(error.get("query")), "message": clean_text(error.get("message"), max_len=300)})
        for query_diag in provider_queries:
            if not int(query_diag.get("resultCount", 0) or 0):
                search_errors.append(
                    {
                        "query": clean_text(query_diag.get("query")),
                        "message": "RapidAPI creator search returned 0 Instagram profile URLs",
                        "diagnostics": query_diag.get("diagnostics", []),
                    }
                )

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    validated = 0
    for url in candidate_urls:
        if validated >= validate_limit:
            break
        validated += 1
        print(f"  - INS creator discovery validating {validated}/{validate_limit}: {url}", flush=True)
        try:
            raw_posts = provider.fetch_profile_posts([url])
            posts = normalize_candidate_posts(raw_posts, rules)
            model_review = validate_creator_with_model(url, posts, rules)
            deterministic_pass = deterministic_creator_pass(posts, rules)
            is_allowed = bool(model_review.get("isHighQualityCreator")) and deterministic_pass
            record = {"url": url, "review": model_review, "deterministicPass": deterministic_pass, "sampleCount": len(posts)}
            if is_allowed and len(accepted) < max_new:
                accepted.append(record)
                write_manual_review_file(accepted, review_path=review_path)
                print(f"    accepted: {url}", flush=True)
            else:
                rejected.append(record)
                print(f"    rejected: {url}", flush=True)
        except Exception as exc:
            rejected.append({"url": url, "review": {"reason": str(exc)}, "deterministicPass": False, "sampleCount": 0})
            print(f"    rejected: {url} ({exc})", flush=True)

    appended = [] if dry_run else append_creator_urls(pool_path, [item["url"] for item in accepted])
    search_usage_path = search_provider.write_usage(
        "creator_search",
        extra={"candidateCount": len(candidate_urls), "searchErrorCount": len(search_errors)},
    )
    usage_path = provider.write_usage("creator_discovery", extra={"validatedCandidates": validated, "acceptedCandidates": len(accepted)})
    report = {
        "generatedAt": datetime.now().isoformat(),
        "dryRun": dry_run,
        "queries": queries,
        "candidateCount": len(candidate_urls),
        "validatedCount": validated,
        "accepted": accepted,
        "rejected": rejected,
        "appendedUrls": appended,
        "searchProviderError": "; ".join(error["message"] for error in search_errors[:3]),
        "searchProviderErrors": search_errors,
        "searchUsagePath": str(search_usage_path),
        "usagePath": str(usage_path),
    }
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    report_path = DEBUG_DIR / f"ins_creator_discovery_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_manual_review_file(accepted, report_path=report_path, review_path=review_path)
    report["manualReviewPath"] = str(review_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"  - INS creator discovery validated {validated}; accepted {len(accepted)}; "
        f"appended {len(appended)}; review {review_path}; report {report_path}",
        flush=True,
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover and validate Instagram creators for the INS hotspot pool")
    parser.add_argument("--dry-run", action="store_true", help="Do not append accepted creators to AIGC-INS.csv")
    parser.add_argument("--max-new-creators", type=int)
    parser.add_argument("--validation-limit", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    load_env()
    args = parse_args()
    try:
        discover_and_update_creator_pool(
            dry_run=args.dry_run,
            max_new_creators=args.max_new_creators,
            validation_limit=args.validation_limit,
        )
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

