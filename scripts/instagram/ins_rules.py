from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from env_utils import env_bool, env_float, env_int, load_env


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
BASE_DIR = SCRIPTS_DIR.parent
RULES_FILE = BASE_DIR / "references" / "instagram_feedback_rules.json"


DEFAULT_RULES: dict[str, Any] = {
    "version": 2,
    "provider": "rapidapi",
    "creator_pool": {
        "csv_path": "AIGC-INS.csv",
        "lookback_hours": 48,
        "max_creators_per_run": 24,
    },
    "database": {
        "path": "skill_runs/instagram/instagram_hotspots.sqlite",
    },
    "rapidapi": {
        "host": "instagram120.p.rapidapi.com",
        "base_url": "https://instagram120.p.rapidapi.com",
        "posts_path": "/api/instagram/posts",
        "timeout_seconds": 45,
    },
    "content_mode": {
        "posts_only": True,
        "image_materials_only": True,
    },
    "quality": {
        "top_n": 5,
        "product_v2_top_n": 2,
        "min_like_count": 80,
        "min_comment_count": 2,
        "allow_zero_play_count": True,
    },
    "hot_post": {
        "enabled": True,
        "baseline_days": 7,
        "min_ratio_to_average": 0.5,
        "high_score_k": 600.0,
    },
    "scoring": {
        "like_weight": 1.0,
        "comment_weight": 8.0,
        "play_weight": 0.0,
        "recency_gravity": 0.8,
        "product_fit_boost": 1.35,
        "image_weight": 1.2,
        "carousel_weight": 1.15,
        "reel_weight": 0.3,
        "video_weight": 0.3,
        "unknown_weight": 0.8,
    },
    "product_fit": {
        "enabled": True,
        "min_score": 2,
        "toki_product_min_share": 0.7,
        "evoke": {
            "ua_keywords": [
                "old photo",
                "restore photo",
                "photo enhancer",
                "enhance photo",
                "colorize",
                "before after",
                "ai portrait",
                "dream portrait",
                "storybook portrait",
                "portrait to live moment",
                "single photo upload",
                "upload an image",
                "portrait",
                "photoshoot",
                "fashion photo",
                "creative photo",
                "photoreal",
                "ai photography",
                "style transfer",
                "family photo",
                "couple photo",
                "pet photo",
            ],
            "product_keywords": [
                "old photo",
                "photo restoration",
                "photo enhancer",
                "colorize",
                "damaged photo",
                "portrait generator",
                "ai portrait",
                "art photography",
                "fashion photoshoot",
                "editorial portrait",
                "photoreal",
                "photography",
                "ai photography",
                "creative portrait",
                "cinematic portrait",
                "style transfer",
                "photo style",
                "dream portrait",
                "storybook portrait",
                "portrait to live moment",
                "before after portrait",
                "photo style template",
            ],
        },
        "toki": {
            "ua_keywords": [
                "photo to video",
                "image to video",
                "ai action figure",
                "figurine",
                "labubu",
                "face animation",
                "ai transform",
                "ai hug",
                "ai couple",
                "pet animation",
                "cinematic",
                "dynamic pose",
                "motion",
                "emotional scene",
                "single photo upload",
                "upload an image",
                "portrait to live moment",
                "stream dream",
                "streamer transformation",
                "creator persona",
                "dream portrait",
                "storybook portrait",
                "princess portrait",
                "fairy portrait",
                "dress up template",
                "image/video template",
                "template library",
                "create now",
            ],
            "product_keywords": [
                "photo to video",
                "image to video",
                "ai video generator",
                "ai action figure",
                "figurine",
                "labubu",
                "ai emote",
                "face animation",
                "ai transform",
                "ai magic",
                "ai hug",
                "ai couple",
                "animate photo",
                "talking photo",
                "cinematic",
                "dynamic pose",
                "motion",
                "emotional scene",
                "video template",
                "single photo upload",
                "upload an image",
                "portrait to live moment",
                "stream dream",
                "streamer transformation",
                "creator persona",
                "dress up template",
                "image/video template",
                "template library",
                "create now",
            ],
        },
        "kavi": {
            "ua_keywords": [
                "kavi",
                "ai video generator",
                "photo to video",
                "image to video",
                "selfie video",
                "selfie animation",
                "viral ai effect",
                "trending ai effect",
                "single photo upload",
                "upload an image",
                "portrait to live moment",
                "stream dream",
                "streamer transformation",
                "creator persona",
                "dream portrait",
                "storybook portrait",
                "princess portrait",
                "fairy portrait",
                "dress up template",
                "image/video template",
                "template library",
                "create now",
                "stylized animation",
                "custom 3d figure",
                "3d figure",
                "one photo video",
            ],
            "product_keywords": [
                "kavi",
                "selfie to video",
                "photo to video",
                "image to video",
                "ai video maker",
                "single photo upload",
                "upload an image",
                "portrait to live moment",
                "stream dream",
                "streamer transformation",
                "creator persona",
                "dress up template",
                "image/video template",
                "template library",
                "create now",
                "viral video",
                "trending effect",
                "ai effect",
                "custom 3d figure",
                "3d figure",
                "lifelike motion",
                "short video style",
            ],
        },
        "avatar_jigsaw": {
            "ua_keywords": [
                "ai avatar jigsaw",
                "avatar jigsaw",
                "ai avatar",
                "clay avatar",
                "profile photo",
                "jigsaw puzzle",
                "facebook instant game",
                "share challenge",
                "friend challenge",
            ],
            "product_keywords": [
                "ai avatar jigsaw",
                "avatar puzzle",
                "profile photo puzzle",
                "clay avatar",
                "claymation avatar",
                "jigsaw puzzle",
                "puzzle pieces",
                "facebook instant game",
                "facebook gaming",
                "share loop",
                "invite friends",
            ],
        },
        "exclude_for_product_keywords": [
            "ai news",
            "model release",
            "funding",
            "hardware",
            "crypto",
            "politics",
        ],
    },
    "product_v2_review": {
        "enabled": True,
        "model": "qwen/qwen3.7-max",
    },
    "intro_analysis": {
        "enabled": True,
        "model": "qwen/qwen3.6-plus",
        "require_model": True,
        "timeout_seconds": 45,
        "max_images": 3,
    },
    "ua_material_review": {
        "enabled": True,
        "review_pool_size": 10,
        "daily_min": 1,
        "daily_max": 1,
        "require_model": True,
        "model": "qwen/qwen3.7-max",
    },
    "safety": {
        "enabled": True,
        "model": "qwen/qwen3.7-max",
        "blocked_categories": ["nsfw", "soft_porn", "edge_bait", "ai_girl_bait", "anime_soft_porn"],
        "high_risk_keywords": [
            "nsfw",
            "onlyfans",
            "lingerie",
            "bikini",
            "nude",
            "porn",
            "sexy girl",
            "ai girlfriend",
            "anime girl",
            "soft porn",
            "鎿﹁竟",
            "edge bait",
            "鑹叉儏",
            "鍐呰。",
            "娉宠",
        ],
    },
    "dedupe": {"enabled": True, "candidate_multiplier": 2},
    "creator_discovery": {
        "enabled": True,
        "dry_run": True,
        "model": "qwen/qwen3.7-max",
        "seed_creator_limit": 12,
        "search_limit_per_query": 10,
        "validation_limit": 10,
        "max_new_creators": 10,
        "min_valid_posts": 2,
        "default_search_queries": [
            "ai photo editor",
            "ai portrait generator",
            "creative portrait photography",
            "fashion photoshoot",
            "editorial portrait",
            "wedding photography",
            "family portrait photography",
            "couple photoshoot",
            "travel photography",
            "makeup look photography",
            "photo enhancer ai",
            "photo to video ai",
            "ai action figure photo",
        ],
    },
    "creator_search": {
        "provider": "rapidapi",
        "host": "instagram-statistics-api.p.rapidapi.com",
        "base_url": "https://instagram-statistics-api.p.rapidapi.com",
        "path": "/search",
        "method": "GET",
        "timeout_seconds": 30,
        "per_page": 10,
        "query_param": "",
        "query_param_candidates": ["q", "query", "keyword", "search", "username"],
        "default_params": {
            "page": 1,
            "perPage": 10,
            "sort": "-score",
            "socialTypes": "INST",
            "trackTotal": "true",
        },
    },
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        elif key in {"ua_keywords", "product_keywords"} and isinstance(value, list) and isinstance(result.get(key), list):
            result[key] = list(dict.fromkeys([*result[key], *value]))
        else:
            result[key] = value
    return result


def load_ins_rules(path: Path | None = None) -> dict[str, Any]:
    selected = path or RULES_FILE
    rules = copy.deepcopy(DEFAULT_RULES)
    if selected.exists():
        data = json.loads(selected.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError(f"Instagram rules must be a JSON object: {selected}")
        rules = deep_merge(rules, data)
    return apply_env_overrides(rules)


def apply_env_overrides(rules: dict[str, Any]) -> dict[str, Any]:
    env = load_env()
    rules["provider"] = os.environ.get("INS_PROVIDER") or env.get("INS_PROVIDER") or rules.get("provider", "rapidapi")

    pool = rules["creator_pool"]
    pool["csv_path"] = os.environ.get("INS_CREATOR_POOL_CSV") or env.get("INS_CREATOR_POOL_CSV") or pool["csv_path"]
    pool["lookback_hours"] = env_int("INS_LOOKBACK_HOURS", int(pool["lookback_hours"]), env)
    pool["max_creators_per_run"] = env_int("INS_MAX_CREATORS_PER_RUN", int(pool["max_creators_per_run"]), env)

    database = rules["database"]
    database["path"] = os.environ.get("INS_DATABASE_PATH") or env.get("INS_DATABASE_PATH") or database["path"]

    rapidapi = rules["rapidapi"]
    rapidapi["host"] = os.environ.get("INS_RAPIDAPI_HOST") or env.get("INS_RAPIDAPI_HOST") or rapidapi["host"]
    rapidapi["base_url"] = os.environ.get("INS_RAPIDAPI_BASE_URL") or env.get("INS_RAPIDAPI_BASE_URL") or rapidapi["base_url"]
    rapidapi["posts_path"] = os.environ.get("INS_RAPIDAPI_POSTS_PATH") or env.get("INS_RAPIDAPI_POSTS_PATH") or rapidapi["posts_path"]
    rapidapi["timeout_seconds"] = env_int("INS_RAPIDAPI_TIMEOUT_SECONDS", int(rapidapi["timeout_seconds"]), env)

    content = rules["content_mode"]
    content["posts_only"] = env_bool("INS_POSTS_ONLY", bool(content["posts_only"]), env)
    content["image_materials_only"] = env_bool("INS_IMAGE_MATERIALS_ONLY", bool(content["image_materials_only"]), env)

    quality = rules["quality"]
    quality["top_n"] = env_int("INS_TOP_N", int(quality["top_n"]), env)
    quality["product_v2_top_n"] = env_int("INS_PRODUCT_V2_TOP_N", int(quality["product_v2_top_n"]), env)
    quality["min_like_count"] = env_int("INS_MIN_LIKE_COUNT", int(quality["min_like_count"]), env)
    quality["min_comment_count"] = env_int("INS_MIN_COMMENT_COUNT", int(quality["min_comment_count"]), env)

    product_v2_review = rules["product_v2_review"]
    product_v2_review["enabled"] = env_bool("INS_PRODUCT_V2_REVIEW_ENABLED", bool(product_v2_review["enabled"]), env)
    product_v2_review["model"] = os.environ.get("INS_PRODUCT_REVIEW_MODEL") or env.get("INS_PRODUCT_REVIEW_MODEL") or product_v2_review["model"]

    intro_analysis = rules["intro_analysis"]
    intro_analysis["enabled"] = env_bool("INS_INTRO_ANALYSIS_ENABLED", bool(intro_analysis["enabled"]), env)
    intro_analysis["model"] = os.environ.get("INS_INTRO_ANALYSIS_MODEL") or env.get("INS_INTRO_ANALYSIS_MODEL") or intro_analysis["model"]
    intro_analysis["require_model"] = env_bool("INS_INTRO_ANALYSIS_REQUIRE_MODEL", bool(intro_analysis["require_model"]), env)
    intro_analysis["timeout_seconds"] = env_int("INS_INTRO_ANALYSIS_TIMEOUT_SECONDS", int(intro_analysis["timeout_seconds"]), env)
    intro_analysis["max_images"] = env_int("INS_INTRO_ANALYSIS_MAX_IMAGES", int(intro_analysis["max_images"]), env)

    ua_material_review = rules["ua_material_review"]
    ua_material_review["enabled"] = env_bool("UA_MATERIAL_REVIEW_ENABLED", bool(ua_material_review["enabled"]), env)
    ua_material_review["review_pool_size"] = env_int("UA_MATERIAL_REVIEW_POOL_SIZE", int(ua_material_review["review_pool_size"]), env)
    ua_material_review["daily_min"] = env_int("UA_MATERIAL_REVIEW_DAILY_MIN", int(ua_material_review["daily_min"]), env)
    ua_material_review["daily_max"] = env_int("UA_MATERIAL_REVIEW_DAILY_MAX", int(ua_material_review["daily_max"]), env)
    ua_material_review["require_model"] = env_bool("UA_MATERIAL_REVIEW_REQUIRE_MODEL", bool(ua_material_review["require_model"]), env)
    ua_material_review["model"] = os.environ.get("UA_MATERIAL_REVIEW_MODEL") or env.get("UA_MATERIAL_REVIEW_MODEL") or ua_material_review["model"]

    hot_post = rules["hot_post"]
    hot_post["enabled"] = env_bool("INS_HOT_POST_FILTER_ENABLED", bool(hot_post["enabled"]), env)
    hot_post["baseline_days"] = env_int("INS_HOT_BASELINE_DAYS", int(hot_post["baseline_days"]), env)
    hot_post["min_ratio_to_average"] = env_float(
        "INS_HOT_MIN_RATIO_TO_AVERAGE",
        float(hot_post.get("min_ratio_to_average", 1.0)),
        env,
    )

    safety = rules["safety"]
    safety["enabled"] = not env_bool("INS_SAFETY_REVIEW_DISABLE", not bool(safety["enabled"]), env)
    safety["model"] = os.environ.get("INS_SAFETY_REVIEW_MODEL") or env.get("INS_SAFETY_REVIEW_MODEL") or safety["model"]

    discovery = rules["creator_discovery"]
    discovery["enabled"] = env_bool("INS_DISCOVERY_ENABLED", bool(discovery["enabled"]), env)
    discovery["dry_run"] = env_bool("INS_DISCOVERY_DRY_RUN", bool(discovery["dry_run"]), env)
    discovery["model"] = os.environ.get("INS_DISCOVERY_MODEL") or env.get("INS_DISCOVERY_MODEL") or discovery["model"]
    discovery["validation_limit"] = env_int("INS_DISCOVERY_VALIDATION_LIMIT", int(discovery["validation_limit"]), env)
    discovery["max_new_creators"] = env_int("INS_DISCOVERY_MAX_NEW_CREATORS", int(discovery["max_new_creators"]), env)
    discovery["search_limit_per_query"] = env_int("INS_DISCOVERY_SEARCH_LIMIT_PER_QUERY", int(discovery["search_limit_per_query"]), env)

    creator_search = rules["creator_search"]
    creator_search["provider"] = os.environ.get("INS_CREATOR_SEARCH_PROVIDER") or env.get("INS_CREATOR_SEARCH_PROVIDER") or creator_search["provider"]
    creator_search["host"] = os.environ.get("INS_RAPIDAPI_SEARCH_HOST") or env.get("INS_RAPIDAPI_SEARCH_HOST") or creator_search["host"]
    creator_search["base_url"] = os.environ.get("INS_RAPIDAPI_SEARCH_BASE_URL") or env.get("INS_RAPIDAPI_SEARCH_BASE_URL") or creator_search["base_url"]
    creator_search["path"] = os.environ.get("INS_RAPIDAPI_SEARCH_PATH") or env.get("INS_RAPIDAPI_SEARCH_PATH") or creator_search["path"]
    creator_search["method"] = os.environ.get("INS_RAPIDAPI_SEARCH_METHOD") or env.get("INS_RAPIDAPI_SEARCH_METHOD") or creator_search["method"]
    creator_search["timeout_seconds"] = env_int("INS_RAPIDAPI_SEARCH_TIMEOUT_SECONDS", int(creator_search["timeout_seconds"]), env)
    creator_search["per_page"] = env_int("INS_RAPIDAPI_SEARCH_PER_PAGE", int(creator_search["per_page"]), env)
    creator_search["query_param"] = os.environ.get("INS_RAPIDAPI_SEARCH_QUERY_PARAM") or env.get("INS_RAPIDAPI_SEARCH_QUERY_PARAM") or creator_search.get("query_param", "")
    if isinstance(creator_search.get("default_params"), dict):
        creator_search["default_params"]["perPage"] = creator_search["per_page"]
    return rules


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else BASE_DIR / path

