from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path
from typing import Any

from scoring import heat_score, normalize_platform


BASE_DIR = Path(__file__).resolve().parents[1]
RULES_FILE = BASE_DIR / "references" / "tiktok_feedback_optimization_rules.json"
TIKTOK_AI_QUERY_RE = re.compile(r"(^|[^a-z0-9])ai([^a-z0-9]|$)")
TIKTOK_AI_QUERY_PHRASES = (
    "special effects",
    "human special effects",
)


def is_tiktok_ai_query(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return bool(TIKTOK_AI_QUERY_RE.search(text)) or any(phrase in text for phrase in TIKTOK_AI_QUERY_PHRASES)


DEFAULT_RULES: dict[str, Any] = {
    "version": 1,
    "updated_at": "",
    "source": "default",
    "last_feedback_window": {"start_date": "", "end_date": "", "feedback_count": 0},
    "scrape": {
        "search_queries": [
            "ai before after photo",
            "ai photo",
            "special effects",
            "human special effects",
            "ai photo enhancer before after",
            "before after photo",
            "photo transition template",
            "sports poster edit",
            "character transformation edit",
            "tv show poster edit",
        ],
        "results_per_keyword": 35,
        "max_search_queries": 10,
        "ai_search_count": 5,
        "non_ai_search_count": 5,
        "keyword_tuning_window_days": 7,
        "keyword_allocation_min": 15,
        "keyword_allocation_max": 50,
        "keyword_allocation_total": 350,
        "keyword_allocations": {
            "ai before after photo": 40,
            "ai photo": 40,
            "special effects": 35,
            "human special effects": 35,
            "ai photo enhancer before after": 35,
            "before after photo": 35,
            "photo transition template": 35,
            "sports poster edit": 35,
            "character transformation edit": 30,
            "tv show poster edit": 30,
        },
        "hot_feed": {
            "enabled": True,
            "max_items": 100,
            "max_pages": 1,
            "path": "",
            "method": "GET",
        },
        "keyword_candidates": {
            "ai": [
                "photo to video ai",
                "ai action figure",
                "ai emote face animation",
                "ai selfie video",
                "ai viral effect 3d figure",
                "ai avatar jigsaw",
                "ai clay avatar puzzle",
                "ai photo enhancer before after",
                "ai portrait template",
                "ai photo trend",
                "ai image to video",
                "ai couple video",
                "ai family photo video",
                "ai old photo restoration",
                "ai avatar puzzle",
                "ai 3d figure",
                "ai collectible figure",
                "ai clay avatar",
                "ai face animation",
                "ai talking photo",
                "ai creator persona",
                "ai streamer transformation",
                "ai dress up template",
                "ai storybook portrait",
                "ai before after photo",
                "ai photo",
                "special effects",
                "human special effects",
            ],
            "non_ai": [
                "before after photo",
                "photo transition template",
                "avatar puzzle challenge",
                "portrait transition template",
                "before after photo template",
                "profile photo trend",
                "creator portrait template",
                "collectible figure trend",
                "photo slideshow template",
                "sports highlight template",
                "athlete celebration edit",
                "sports poster edit",
                "jersey portrait edit",
                "training transformation",
                "match entrance edit",
                "cinematic sports edit",
                "movie poster transition",
                "tv show poster edit",
                "character transformation edit",
                "cinematic trailer edit",
                "red carpet transition",
                "film look portrait",
                "character card edit",
            ],
        },
        "keyword_rotation": {
            "last_rotation_week": "",
            "replaced_keywords": [],
            "added_keywords": [],
            "reason": "",
        },
    },
    "x_scrape": {
        "search_queries": [
            "ChatGPT Seedance iPhone vlog workflow",
            "GPT Images Seedance Suno couple video",
            "GPT Images Seedance prompt workflow",
            "photo to video storyboard prompt",
            "Kavi selfie to video prompt workflow",
            "AI Avatar Jigsaw prompt workflow",
            "AI photo enhancer before after",
            "AI old photo restoration prompt",
            "AI action figure video prompt",
            "AI selfie video prompt",
            "AI viral effect 3D figure",
            "AI avatar jigsaw puzzle",
            "AI clay avatar prompt",
            "real person portrait photography",
            "editorial portrait photography",
            "family memory portrait photography",
            "couple photo storyboard photography",
            "old photo restoration reference",
            "creative portrait photography",
            "cinematic portrait photography",
        ],
        "results_per_keyword": 20,
        "max_search_queries": 20,
        "quality_creators_enabled": True,
        "quality_creators_sheet_url": "https://scnmrtumk0zm.feishu.cn/wiki/HLs9wvAACiq5HzkM7cDcmYkAnwf?sheet=yYzT06",
        "quality_creators_max_accounts": 20,
        "quality_creators_posts_per_account": 20,
        "quality_creators_pages_per_account": 1,
        "quality_creators_reduce_queries_per_hit": 2,
        "quality_creators_min_search_queries": 20,
    },
    "scoring": {
        "active_parameters": {
            "play_weight": 0.01,
            "like_weight": 1.0,
            "comment_weight": 5.0,
            "gravity": 1.8,
            "high_score_k": 500.0,
        },
        "bounds": {
            "play_weight": [0.001, 0.05],
            "like_weight": [0.2, 5.0],
            "comment_weight": [1.0, 20.0],
            "gravity": [0.8, 3.0],
            "high_score_k": [100.0, 10000.0],
        },
    },
    "x_scoring": {
        "active_parameters": {
            "play_weight": 0.01,
            "like_weight": 1.0,
            "comment_weight": 5.0,
            "gravity": 1.8,
            "high_score_k": 500.0,
        },
        "bounds": {
            "play_weight": [0.001, 0.05],
            "like_weight": [0.2, 5.0],
            "comment_weight": [1.0, 20.0],
            "gravity": [0.8, 3.0],
            "high_score_k": [100.0, 10000.0],
        },
    },
    "quality_thresholds": {
        "top_n": 10,
        "max_hours": 168,
        "max_duration_seconds": 30,
        "min_play_count": 10000,
        "min_comment_count": 20,
        "min_comment_rate": 0.002,
        "low_comment_rate_penalty": 0.65,
        "like_thresholds": [
            {"max_hours": 24, "min_digg_count": 150},
            {"max_hours": 72, "min_digg_count": 400},
        ],
        "preferred_keyword_boost": 1.35,
        "deprioritized_keyword_penalty": 0.45,
    },
    "x_quality_thresholds": {
        "min_comment_count": 16,
        "like_thresholds": [
            {"max_hours": 24, "min_digg_count": 160},
            {"max_hours": 72, "min_digg_count": 400},
        ],
    },
    "media_type_weights": {
        "tiktok": {"video": 1.0, "image": 0.5, "mixed": 0.75, "unknown": 1.0},
        "x": {"image": 1.2, "video": 1.0, "mixed": 1.1, "unknown": 0.9},
    },
    "audience_targeting": {
        "enabled": True,
        "ua_keywords": [],
        "product_keywords": [],
        "min_keyword_hits": 1,
    },
    "ua_material_review": {
        "enabled": True,
        "review_pool_size": 10,
        "daily_min": 1,
        "daily_max": 1,
        "require_model": True,
        "model": "qwen/qwen3.7-max",
    },
    "push_caps": {
        "enabled": True,
        "total_daily_max": 15,
    },
        "product_targeting": {
            "enabled": True,
            "toki_product_min_share": 0.7,
            "min_score": 2,
            "evoke": {"ua_keywords": [], "product_keywords": []},
            "toki": {"ua_keywords": [], "product_keywords": []},
            "kavi": {"ua_keywords": [], "product_keywords": []},
            "avatar_jigsaw": {"ua_keywords": [], "product_keywords": []},
            "exclude_for_product_keywords": [],
        },
    "x_photo_relevance": {
        "enabled": True,
        "require_image_or_mixed": True,
        "min_score": 3,
        "boost": 1.35,
        "penalty": 0.2,
        "strong_keywords": [
            "portrait",
            "real person",
            "art portrait",
            "photo shoot",
            "photoshoot",
            "fashion",
            "editorial",
            "fashion editorial",
            "stylized portrait",
            "style photo",
            "styled photo",
            "art photography",
            "creative photo",
            "old photo",
            "before after",
            "photo restoration",
            "profile photo",
            "avatar",
            "clay avatar",
            "jigsaw puzzle",
            "selfie",
            "holiday photo",
            "festival photo",
            "festival portrait",
            "wedding photo",
            "graduation photo",
            "lookbook",
            "outfit",
            "makeup",
            "hairstyle",
            "character generator",
            "original character",
            "\u771f\u4eba",
            "\u4eba\u50cf",
            "\u5199\u771f",
            "\u827a\u672f\u5199\u771f",
            "\u65f6\u5c1a\u5927\u7247",
            "\u8282\u65e5\u7167\u7247",
            "\u521b\u610f\u7167\u7247",
            "\u7a7f\u642d",
        ],
        "support_keywords": [
            "photo",
            "image",
            "picture",
            "shot",
            "iphone shot",
            "camera",
            "faces",
            "face",
            "people",
            "person",
            "human",
            "couple",
            "family",
            "model",
            "aesthetic",
            "cinematic",
            "visual medium",
            "visual mediums",
            "prompt",
            "jigsaw",
            "puzzle",
            "facebook instant game",
            "template",
            "effect",
            "outfits",
            "clothing",
            "\u7167\u7247",
            "\u56fe\u7247",
            "\u955c\u5934",
            "\u8138",
            "\u60c5\u4fa3",
            "\u5bb6\u5ead",
        ],
        "exclude_keywords": [
            "anthropic",
            "claude",
            "openai launches",
            "nvidia",
            "startup billboard",
            "billboard space",
            "stock",
            "crypto",
            "web3",
            "restaurant",
            "drive-thru",
            "kitchen",
            "paint my house",
            "house bid",
            "real estate",
            "algorithm",
            "github",
            "model benchmark",
            "api",
            "sdk",
            "course",
            "tutorial",
            "robot",
            "optimus",
            "teslaaibot",
            "anime-style",
            "anime style",
            "ai illustration",
            "aiart",
            "fanart",
            "genshin",
            "swimsuit",
            "paparazzi",
            "gossip",
            "spoiler",
            "leaked scene",
            "box office",
            "dating rumor",
            "celebrity news",
            "low quality cosplay",
        ],
        "exclude_keyword_groups": [
            ["ai", "deployment"],
            ["ai", "restaurant"],
            ["ai", "startup"],
            ["ai", "billboard"],
            ["ai", "algorithm"],
            ["ai", "github"],
            ["ai", "agent"],
            ["ai", "crypto"],
            ["ai", "web3"],
            ["ai", "hardware"],
            ["ai", "robot"],
            ["photo", "house"],
            ["photo", "billboard"],
        ],
    },
    "x_team_demand": {
        "enabled": True,
        "max_review_candidates": 20,
        "workflow_min_score": 4,
        "photo_min_score": 3,
        "workflow_tool_keywords": [
            "chatgpt",
            "gpt images",
            "gpt image",
            "seedance",
            "suno",
            "kavi",
            "avatar",
            "avatar jigsaw",
            "facebook instant game",
            "veo",
            "runway",
            "kling",
            "pika",
            "hailuo",
            "midjourney",
            "capcut",
            "gemini",
        ],
        "workflow_action_keywords": [
            "workflow",
            "prompt",
            "prompts",
            "tutorial",
            "step by step",
            "process",
            "production",
            "breakdown",
            "how to",
            "guide",
            "recipe",
            "made with",
            "created with",
            "generated with",
            "behind the scenes",
        ],
        "workflow_output_keywords": [
            "iphone vlog",
            "vlog",
            "photo album",
            "selfie video",
            "viral effect",
            "custom 3d figure",
            "avatar puzzle",
            "jigsaw puzzle",
            "clay avatar",
            "profile photo",
            "old photo restoration",
            "before after",
            "long video",
            "couple video",
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
            "ai template link",
            "ai creative editing",
            "ai photo editing",
            "ai editing photo effect",
            "hypic",
            "gemini ai photo edit",
            "one click",
            "cta",
            "end card",
            "couple",
            "image to video",
            "photo to video",
            "ai video",
            "ai image",
            "ai photo",
            "portrait",
            "cinematic",
        ],
        "photo_product_keywords": [
            "ai",
            "prompt",
            "workflow",
            "template",
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
            "ai template link",
            "ai creative editing",
            "ai photo editing",
            "ai editing photo effect",
            "hypic",
            "gemini ai photo edit",
            "one click",
            "cta",
            "end card",
            "mobile ad",
            "app store",
            "google play",
            "photo to video",
            "image to video",
            "before after",
            "before/after",
            "enhance",
            "restore",
            "restoration",
            "style transfer",
            "generated",
            "generator",
            "transformation",
            "ai portrait",
            "ai photo",
            "ai image",
            "iphone style",
            "vlog",
            "storyboard",
            "selfie video",
            "viral effect",
            "custom 3d figure",
            "avatar",
            "avatar puzzle",
            "jigsaw puzzle",
            "clay avatar",
            "profile photo",
            "facebook instant game",
            "old photo",
            "old photo restoration",
            "photo enhancer",
        ],
        "reject_keywords": [
            "anime",
            "manga",
            "ova",
            "cel shading",
            "cel-shading",
            "priestess",
            "salamander spirit",
            "fantasy character",
            "character design",
            "character sheet",
            "game character",
            "fanart",
            "genshin",
            "paparazzi",
            "celebrity",
            "celebrity portrait",
            "actor",
            "actress",
            "sadie sink",
            "sydney sweeney",
            "lindsay lohan",
            "street style",
            "booked their photoshoot",
            "engagement shoot",
            "wedding photographer",
            "photographer portfolio",
            "100k club",
            "hit that subscribe button",
            "subscribe button",
            "subscriber milestone",
            "follower milestone",
            "bikini",
            "swimsuit",
            "lingerie",
            "cleavage",
            "sexy",
            "seductive",
            "beach girl aesthetic",
            "sensual variation",
            "nsfw",
            "prompt gallery",
            "prompt library",
            "prompt resource",
            "free gallery",
            "viral prompts",
            "copy the ones",
            "meigen7982",
            "one-click makeup",
            "ai makeup",
            "beauty filter",
            "makeup filter",
            "bare face makeup",
            "generic ai portrait prompt",
            "face lock prompt",
            "high-fidelity ai portrait",
            "baseball spectator girl",
            "baseball broadcast girl",
            "korean baseball girl",
            "sports broadcast girl",
            "random spectator girl",
            "\u68d2\u7403\u5973\u5b69",
            "\u68d2\u7403\u89c2\u4f17\u5e2d\u5973\u5b69",
            "\u8d5b\u4e8b\u955c\u5934\u5973\u5b69",
            "\u7403\u573a\u5973\u5b69",
            "\u4e00\u952e\u7f8e\u5986",
            "\u7f8e\u5986\u6ee4\u955c",
            "\u7d20\u989c\u7f8e\u5986",
            "\u9ad8\u4fdd\u771fAI\u4eba\u50cf",
            "\u4eba\u50cf\u63d0\u793a\u8bcd",
            "\u5199\u771f\u63d0\u793a\u8bcd",
            "\u9762\u90e8\u7279\u5f81\u9501\u5b9a",
        ],
        "product_review_enabled": True,
        "product_review_model": "qwen/qwen3.7-max",
    },
    "filters": {
        "include_keywords": ["ai"],
        "exclude_keywords": [
            "non-ai content",
            "nsfw",
            "soft porn",
            "onlyfans",
            "lingerie",
            "bikini",
            "swimsuit",
            "nude",
            "cleavage",
            "beach girl aesthetic",
            "sensual variation",
            "100k club",
            "hit that subscribe button",
            "subscriber milestone",
            "follower milestone",
            "\u64e6\u8fb9",
            "\u8f6f\u8272\u60c5",
            "\u8272\u60c5",
            "\u660e\u661f\u8def\u900f",
            "prince harry",
            "celebrity street style",
            "xbox elite",
            "gaming controller",
            "controller leak",
            "hardware leak",
            "regulator leak",
            "google gemini rain",
            "gemini rain ai effect",
            "gemini rain ai filter",
            "creative rain ai effect",
            "rain ai effect",
            "airain",
            "rainaieffect",
            "ai couple embrace in the rain",
            "couple embrace in the rain",
            "rainy embrace",
            "rainy visuals",
            "portraits in the rain",
            "rain couple",
            "rain hug",
            "rain portrait",
            "\u96e8\u4e2d\u5199\u771f",
            "\u96e8\u4e2d\u62e5\u62b1",
            "ai cat video",
            "ai cat story",
            "ai anime",
            "\u0041\u0049\u52a8\u6f2b",
            "gen.pro",
            "script to video",
            "ai robot",
            "\u4eba\u5de5\u667a\u80fd\u673a\u5668\u4eba",
            "capcut beat edit",
            "one-click makeup",
            "ai makeup",
            "beauty filter",
            "makeup filter",
            "bare face makeup",
            "generic ai portrait prompt",
            "face lock prompt",
            "high-fidelity ai portrait",
            "baseball spectator girl",
            "baseball broadcast girl",
            "korean baseball girl",
            "sports broadcast girl",
            "random spectator girl",
            "\u68d2\u7403\u5973\u5b69",
            "\u68d2\u7403\u89c2\u4f17\u5e2d\u5973\u5b69",
            "\u8d5b\u4e8b\u955c\u5934\u5973\u5b69",
            "\u7403\u573a\u5973\u5b69",
            "\u4e00\u952e\u7f8e\u5986",
            "\u7f8e\u5986\u6ee4\u955c",
            "\u7d20\u989c\u7f8e\u5986",
        ],
        "exclude_keyword_groups": [
            ["pet", "story"],
            ["cat", "story"],
            ["dog", "story"],
            ["anime", "bikini"],
            ["anime", "sexy"],
            ["anime girl", "ai"],
            ["ai girl", "sexy"],
            ["ai girl", "bikini"],
            ["ai girlfriend", "sexy"],
            ["\u4e8c\u6b21\u5143", "\u64e6\u8fb9"],
            ["\u52a8\u6f2b", "\u64e6\u8fb9"],
            ["\u7f8e\u5973", "\u64e6\u8fb9"],
            ["makeup", "one click"],
            ["makeup", "capcut"],
            ["beauty", "filter"],
            ["\u7f8e\u5986", "\u4e00\u952e"],
            ["\u7f8e\u5986", "capcut"],
            ["\u7d20\u989c", "\u5986"],
            ["baseball", "girl"],
            ["baseball", "broadcast"],
            ["sports", "spectator"],
            ["sports", "broadcast girl"],
            ["\u68d2\u7403", "\u5973\u5b69"],
            ["\u68d2\u7403", "\u89c2\u4f17"],
            ["\u68d2\u7403", "\u8d5b\u4e8b"],
            ["portrait prompt", "face lock"],
            ["\u4eba\u50cf", "\u63d0\u793a\u8bcd", "\u9762\u90e8\u7279\u5f81"],
        ],
        "summary_exclude_keywords": ["pure story"],
        "preferred_keywords": ["pet dance", "expression sticker", "portrait effect", "transformation"],
        "deprioritized_keywords": [
            "fruit dance",
            "repost",
            "not reusable",
            "low engagement",
            "gemini rain ai effect",
            "gemini rain ai filter",
            "google gemini rain",
            "repeated gemini rain template",
            "rain couple",
            "rain hug",
            "repeated rain portrait",
            "ai cat video",
            "ai anime",
            "gen.pro script video",
            "ai robot",
            "fake ai capcut beat edit",
            "retro movie poster",
            "ai retro poster",
            "gemini ai photo edit",
            "ai avatar puzzle",
            "ai avatar jigsaw",
            "ai clay avatar puzzle",
            "before after photo template",
            "avatar puzzle challenge",
        ],
    },
    "analysis_prompt": {
        "global_feedback_guidance": "Prioritize reusable AI visual effects, broad creative templates, and strong engagement quality.",
        "ua_guidance": "UA feedback should favor clear first-three-second hooks and ad material reusability.",
        "product_guidance": "Product feedback should favor reusable video and image effects. Do not treat creator milestone/subscriber celebration posts or cinematic superhero/power-fantasy prompt posts as product opportunities unless they show reusable product value.",
        "risk_guidance": "Exclude NSFW, soft-porn, bikini/swimsuit beach-girl bait, creator follower/subscriber milestone posts, generic AI portrait prompt dumps, one-click makeup/beauty-filter retouch clips, baseball spectator/broadcast-girl fan edits, saturated Gemini Rain/rainy portrait/couple-rain templates, and low-reuse, controversial, duplicated, or weak-quality topics.",
        "priority_guidance": "\u9ad8=strong accept, \u4e2d=watch, \u4f4e=weak accept, \u5426\u51b3=demote or exclude.",
    },
    "learning_summary": [],
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key == "keyword_allocations":
            result[key] = value
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        elif (
            key
            in {
                "ua_keywords",
                "product_keywords",
                "workflow_tool_keywords",
                "workflow_action_keywords",
                "workflow_output_keywords",
                "photo_product_keywords",
                "reject_keywords",
            }
            and isinstance(value, list)
            and isinstance(result.get(key), list)
        ):
            result[key] = list(dict.fromkeys([*result[key], *value]))
        else:
            result[key] = value
    return result


def load_feedback_rules(path: Path = RULES_FILE) -> dict[str, Any]:
    if not path.exists():
        return copy.deepcopy(DEFAULT_RULES)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"Feedback rules must be a JSON object: {path}")
    rules = deep_merge(DEFAULT_RULES, data)
    validate_feedback_rules(rules)
    return rules


def validate_feedback_rules(rules: dict[str, Any]) -> None:
    for section in [
        "scrape",
        "x_scrape",
        "quality_thresholds",
        "x_quality_thresholds",
        "filters",
        "analysis_prompt",
        "learning_summary",
        "scoring",
        "x_scoring",
        "media_type_weights",
        "audience_targeting",
        "ua_material_review",
        "push_caps",
        "product_targeting",
        "x_photo_relevance",
        "x_team_demand",
    ]:
        if section not in rules:
            raise ValueError(f"Feedback rules missing section: {section}")
    for section in ["scrape", "x_scrape"]:
        queries = rules[section].get("search_queries", [])
        if not isinstance(queries, list) or not queries or not all(isinstance(item, str) and item.strip() for item in queries):
            raise ValueError(f"{section}.search_queries must be a non-empty list of strings")
        results_per_keyword = int(rules[section].get("results_per_keyword", 0))
        if results_per_keyword <= 0 or results_per_keyword > 100:
            raise ValueError(f"{section}.results_per_keyword must be between 1 and 100")
    scrape = rules["scrape"]
    tiktok_max_search_queries = int(scrape.get("max_search_queries", 10))
    tiktok_ai_search_count = int(scrape.get("ai_search_count", 5))
    tiktok_non_ai_search_count = int(scrape.get("non_ai_search_count", 5))
    tiktok_queries = scrape.get("search_queries", [])
    if tiktok_max_search_queries != 10 or len(tiktok_queries) != 10:
        raise ValueError("scrape.search_queries and max_search_queries must be fixed at 10")
    if tiktok_ai_search_count != 5 or tiktok_non_ai_search_count != 5:
        raise ValueError("scrape.ai_search_count and scrape.non_ai_search_count must be fixed at 5/5")
    tiktok_ai_queries = [item for item in tiktok_queries if is_tiktok_ai_query(item)]
    if len(tiktok_ai_queries) != 5:
        raise ValueError("scrape.search_queries must contain exactly 5 AI-related TikTok queries")
    if len(tiktok_queries) - len(tiktok_ai_queries) != 5:
        raise ValueError("scrape.search_queries must contain exactly 5 non-AI TikTok queries")
    keyword_window_days = int(scrape.get("keyword_tuning_window_days", 0))
    if keyword_window_days != 7:
        raise ValueError("scrape.keyword_tuning_window_days must be fixed at 7")
    allocation_min = int(scrape.get("keyword_allocation_min", 0))
    allocation_max = int(scrape.get("keyword_allocation_max", 0))
    allocation_total = int(scrape.get("keyword_allocation_total", 0))
    if allocation_min != 15 or allocation_max != 50 or allocation_total != 350:
        raise ValueError("scrape keyword allocation bounds must be min=15, max=50, total=350")
    allocations = scrape.get("keyword_allocations", {})
    if not isinstance(allocations, dict):
        raise ValueError("scrape.keyword_allocations must be an object")
    allocation_sum = 0
    for query in tiktok_queries:
        if query not in allocations:
            raise ValueError(f"scrape.keyword_allocations missing current query: {query}")
        value = int(allocations[query])
        if value < allocation_min or value > allocation_max:
            raise ValueError(f"scrape.keyword_allocations.{query} must be between 15 and 50")
        allocation_sum += value
    if allocation_sum != allocation_total:
        raise ValueError("scrape.keyword_allocations must sum to 350")
    candidates = scrape.get("keyword_candidates", {})
    if not isinstance(candidates, dict):
        raise ValueError("scrape.keyword_candidates must be an object")
    ai_candidates = candidates.get("ai", [])
    non_ai_candidates = candidates.get("non_ai", [])
    if not isinstance(ai_candidates, list) or not isinstance(non_ai_candidates, list) or not ai_candidates or not non_ai_candidates:
        raise ValueError("scrape.keyword_candidates.ai/non_ai must be non-empty lists")
    if not all(isinstance(item, str) and is_tiktok_ai_query(item) for item in ai_candidates):
        raise ValueError("scrape.keyword_candidates.ai must contain AI-related strings")
    if any(is_tiktok_ai_query(item) for item in non_ai_candidates):
        raise ValueError("scrape.keyword_candidates.non_ai must not contain AI query strings")
    rotation = scrape.get("keyword_rotation", {})
    if not isinstance(rotation, dict):
        raise ValueError("scrape.keyword_rotation must be an object")
    hot_feed = scrape.get("hot_feed", {})
    if hot_feed and not isinstance(hot_feed, dict):
        raise ValueError("scrape.hot_feed must be an object when present")
    if isinstance(hot_feed, dict):
        max_items = int(hot_feed.get("max_items", 100) or 100)
        max_pages = int(hot_feed.get("max_pages", 1) or 1)
        if max_items <= 0 or max_items > 200:
            raise ValueError("scrape.hot_feed.max_items must be between 1 and 200")
        if max_pages <= 0 or max_pages > 5:
            raise ValueError("scrape.hot_feed.max_pages must be between 1 and 5")
    x_max_search_queries = int(rules["x_scrape"].get("max_search_queries", 20))
    if x_max_search_queries <= 0 or x_max_search_queries > 20:
        raise ValueError("x_scrape.max_search_queries must be between 1 and 20")
    x_queries = rules["x_scrape"].get("search_queries", [])
    if len(x_queries) != 20 or x_max_search_queries != 20:
        raise ValueError("x_scrape.search_queries and max_search_queries must be fixed at 20")
    expected_workflow_queries = [
        "ChatGPT Seedance iPhone vlog workflow",
        "GPT Images Seedance Suno couple video",
        "GPT Images Seedance prompt workflow",
        "photo to video storyboard prompt",
        "Kavi selfie to video prompt workflow",
        "AI Avatar Jigsaw prompt workflow",
    ]
    if x_queries[:6] != expected_workflow_queries:
        raise ValueError("x_scrape.search_queries first 6 items must be the product-manual workflow query group")
    if not all(str(item).startswith("AI ") for item in x_queries[6:13]):
        raise ValueError("x_scrape.search_queries items 7-13 must start with 'AI '")
    real_photo_tokens = ("real person", "family", "couple", "old photo", "editorial", "creative", "cinematic", "portrait", "photography")
    if not all(not str(item).startswith("AI ") and any(token in str(item).lower() for token in real_photo_tokens) for item in x_queries[13:20]):
        raise ValueError("x_scrape.search_queries items 14-20 must be real-person photo material queries")
    thresholds = rules["quality_thresholds"]
    for key in ["top_n", "max_hours", "max_duration_seconds", "min_play_count", "min_comment_count"]:
        value = thresholds.get(key)
        if not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"quality_thresholds.{key} must be non-negative")
    for key in ["min_comment_rate", "low_comment_rate_penalty"]:
        value = thresholds.get(key)
        if not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"quality_thresholds.{key} must be non-negative")
    for item in thresholds.get("like_thresholds", []):
        if not isinstance(item, dict) or item.get("max_hours", 0) <= 0 or item.get("min_digg_count", 0) < 0:
            raise ValueError("Invalid like threshold item")
    x_thresholds = rules.get("x_quality_thresholds", {})
    if not isinstance(x_thresholds, dict):
        raise ValueError("x_quality_thresholds must be an object")
    for key in ["min_comment_count"]:
        value = x_thresholds.get(key)
        if not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"x_quality_thresholds.{key} must be non-negative")
    for item in x_thresholds.get("like_thresholds", []):
        if not isinstance(item, dict) or item.get("max_hours", 0) <= 0 or item.get("min_digg_count", 0) < 0:
            raise ValueError("Invalid X like threshold item")
    filters = rules["filters"]
    for key in ["include_keywords", "exclude_keywords", "summary_exclude_keywords", "preferred_keywords", "deprioritized_keywords"]:
        value = filters.get(key, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"filters.{key} must be a list of strings")
    for section in ["scoring", "x_scoring"]:
        active = rules.get(section, {}).get("active_parameters", {})
        for key in ["play_weight", "like_weight", "comment_weight", "gravity", "high_score_k"]:
            if key not in active:
                raise ValueError(f"{section}.active_parameters missing {key}")
            if not isinstance(active[key], (int, float)):
                raise ValueError(f"{section}.active_parameters.{key} must be numeric")
    for platform in ["tiktok", "x"]:
        weights = rules.get("media_type_weights", {}).get(platform, {})
        if not isinstance(weights, dict):
            raise ValueError(f"media_type_weights.{platform} must be an object")
        for key in ["image", "video", "mixed", "unknown"]:
            value = weights.get(key)
            if not isinstance(value, (int, float)) or value < 0:
                raise ValueError(f"media_type_weights.{platform}.{key} must be a non-negative number")
    audience = rules.get("audience_targeting", {})
    if not isinstance(audience, dict):
        raise ValueError("audience_targeting must be an object")
    for key in ["ua_keywords", "product_keywords"]:
        value = audience.get(key, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"audience_targeting.{key} must be a list of strings")
    min_keyword_hits = audience.get("min_keyword_hits", 1)
    if not isinstance(min_keyword_hits, (int, float)) or min_keyword_hits < 1:
        raise ValueError("audience_targeting.min_keyword_hits must be >= 1")
    ua_material = rules.get("ua_material_review", {})
    if not isinstance(ua_material, dict):
        raise ValueError("ua_material_review must be an object")
    for key in ["review_pool_size", "daily_min", "daily_max"]:
        value = ua_material.get(key)
        if not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"ua_material_review.{key} must be non-negative")
    require_model = ua_material.get("require_model", True)
    if not isinstance(require_model, bool):
        raise ValueError("ua_material_review.require_model must be boolean")
    model = ua_material.get("model", "")
    if not isinstance(model, str):
        raise ValueError("ua_material_review.model must be a string")
    push_caps = rules.get("push_caps", {})
    if not isinstance(push_caps, dict):
        raise ValueError("push_caps must be an object")
    enabled = push_caps.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("push_caps.enabled must be boolean")
    for key in ["total_daily_max"]:
        value = push_caps.get(key)
        if not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"push_caps.{key} must be non-negative")
    product_targeting = rules.get("product_targeting", {})
    if not isinstance(product_targeting, dict):
        raise ValueError("product_targeting must be an object")
    for removed_product in ["deepthink", "zensi"]:
        if removed_product in product_targeting:
            raise ValueError(f"product_targeting.{removed_product} is no longer supported")
    for key in ["toki_product_min_share", "min_score"]:
        value = product_targeting.get(key)
        if not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"product_targeting.{key} must be non-negative")
    product_keyword_schema = {
        "evoke": ["ua_keywords", "product_keywords"],
        "toki": ["ua_keywords", "product_keywords"],
        "kavi": ["ua_keywords", "product_keywords"],
        "avatar_jigsaw": ["ua_keywords", "product_keywords"],
    }
    for product, keys in product_keyword_schema.items():
        product_cfg = product_targeting.get(product, {})
        if not isinstance(product_cfg, dict):
            raise ValueError(f"product_targeting.{product} must be an object")
        for key in keys:
            value = product_cfg.get(key, [])
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError(f"product_targeting.{product}.{key} must be a list of strings")
    exclude_for_product = product_targeting.get("exclude_for_product_keywords", [])
    if not isinstance(exclude_for_product, list) or not all(isinstance(item, str) for item in exclude_for_product):
        raise ValueError("product_targeting.exclude_for_product_keywords must be a list of strings")
    x_photo = rules.get("x_photo_relevance", {})
    if not isinstance(x_photo, dict):
        raise ValueError("x_photo_relevance must be an object")
    for key in ["min_score", "boost", "penalty"]:
        value = x_photo.get(key)
        if not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"x_photo_relevance.{key} must be non-negative")
    for key in ["strong_keywords", "support_keywords", "exclude_keywords"]:
        value = x_photo.get(key, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"x_photo_relevance.{key} must be a list of strings")
    groups = x_photo.get("exclude_keyword_groups", [])
    if not isinstance(groups, list) or not all(isinstance(group, list) for group in groups):
        raise ValueError("x_photo_relevance.exclude_keyword_groups must be a list of lists")
    x_team = rules.get("x_team_demand", {})
    if not isinstance(x_team, dict):
        raise ValueError("x_team_demand must be an object")
    for key in ["max_review_candidates", "workflow_min_score", "photo_min_score"]:
        value = x_team.get(key)
        if not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"x_team_demand.{key} must be non-negative")
    product_review_enabled = x_team.get("product_review_enabled", True)
    if not isinstance(product_review_enabled, bool):
        raise ValueError("x_team_demand.product_review_enabled must be boolean")
    product_review_model = x_team.get("product_review_model", "")
    if not isinstance(product_review_model, str):
        raise ValueError("x_team_demand.product_review_model must be a string")
    for key in ["workflow_tool_keywords", "workflow_action_keywords", "workflow_output_keywords", "photo_product_keywords", "reject_keywords"]:
        value = x_team.get(key, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"x_team_demand.{key} must be a list of strings")


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        if "text" in value:
            return normalize_text(value.get("text"))
        return " ".join(normalize_text(v) for v in value.values() if v is not None)
    if isinstance(value, list):
        return " ".join(normalize_text(item) for item in value if item is not None)
    return str(value)


def video_haystack(video: dict[str, Any], include_summary: bool = False) -> str:
    parts = [
        normalize_text(video.get("text")),
        normalize_text(video.get("desc")),
        normalize_text((video.get("authorMeta") or {}).get("name")),
        normalize_text((video.get("authorMeta") or {}).get("nickName")),
        normalize_text(video.get("hotspotIntro")),
    ]
    hashtags = video.get("hashtags") or []
    if isinstance(hashtags, list):
        parts.extend(normalize_text(tag) for tag in hashtags)
    if include_summary:
        parts.append(normalize_text(video.get("video_summary")))
    return " ".join(part for part in parts if part).lower()


def media_type_haystack(item: dict[str, Any]) -> str:
    parts = [
        normalize_text(item.get("text")),
        normalize_text(item.get("desc")),
        normalize_text(item.get("title")),
        normalize_text(item.get("summary")),
        normalize_text(item.get("video_summary")),
        normalize_text(item.get("searchQuery")),
        normalize_text(item.get("search_term")),
        normalize_text(item.get("matched_search_terms")),
        normalize_text(item.get("candidate_categories")),
    ]
    hashtags = item.get("hashtags") or []
    if isinstance(hashtags, list):
        parts.extend(normalize_text(tag) for tag in hashtags)
    return " ".join(part for part in parts if part).lower()


def explicit_media_type(item: dict[str, Any]) -> str:
    raw_source = item.get("raw_source") if isinstance(item.get("raw_source"), dict) else {}
    raw_types: list[Any] = []
    for key in ["media_types", "mediaTypes"]:
        value = item.get(key) or raw_source.get(key)
        if isinstance(value, list):
            raw_types.extend(value)
        elif value:
            raw_types.append(value)
    normalized = {str(value or "").strip().lower() for value in raw_types if str(value or "").strip()}
    has_image = any(value in {"photo", "image", "animated_image"} or "photo" in value or "image" in value for value in normalized)
    has_video = any(value in {"video", "animated_gif", "gif"} or "video" in value or "gif" in value for value in normalized)
    if has_image and has_video:
        return "mixed"
    if has_image:
        return "image"
    if has_video:
        return "video"
    return ""


def text_media_type(item: dict[str, Any]) -> str:
    haystack = media_type_haystack(item)
    image_markers = [
        "aiphoto",
        "ai photo",
        "ai image",
        "image generation",
        "photo edit",
        "photo prompt",
        "portrait",
        "poster",
        "headshot",
        "\u56fe\u7247",
        "\u56fe\u50cf",
        "\u7167\u7247",
        "\u4eba\u50cf",
        "\u6d77\u62a5",
    ]
    video_markers = [
        "aivideo",
        "ai video",
        "photo to video",
        "image to video",
        "video generator",
        "static to motion",
        "static to dance",
        "animation",
        "animate",
        "dance",
        "\u89c6\u9891",
        "\u52a8\u753b",
        "\u821e\u8e48",
        "\u5361\u70b9",
    ]
    has_image = contains_any_keyword(haystack, image_markers)
    has_video = contains_any_keyword(haystack, video_markers)
    if has_image and has_video:
        return "mixed"
    if has_image:
        return "image"
    if has_video:
        return "video"
    return ""


def media_type_from_urls(item: dict[str, Any]) -> str:
    raw_source = item.get("raw_source") if isinstance(item.get("raw_source"), dict) else {}
    image_values: list[Any] = []
    video_values: list[Any] = []
    for key in ["image_urls", "images", "mediaUrls", "media_urls"]:
        value = item.get(key) or raw_source.get(key)
        if isinstance(value, list):
            image_values.extend(value)
    video_meta = item.get("videoMeta") if isinstance(item.get("videoMeta"), dict) else {}
    for key in ["webVideoUrl", "downloadAddr", "playAddr"]:
        video_values.append(item.get(key))
        video_values.append(video_meta.get(key))
        video_values.append(raw_source.get(key))
    has_image = bool(image_values)
    has_video = any(str(value or "").strip() for value in video_values)
    if has_image and has_video:
        return "mixed"
    if has_image:
        return "image"
    if has_video:
        return "video"
    return ""


def detect_media_type(item: dict[str, Any]) -> str:
    platform = normalize_platform(item.get("hotspotPlatform") or item.get("sourcePlatform") or item.get("platform"))
    explicit = explicit_media_type(item)
    text_type = text_media_type(item)
    fallback = media_type_from_urls(item)
    if platform == "tiktok" and text_type:
        return text_type
    return explicit or text_type or fallback or "unknown"


def media_type_weight(item: dict[str, Any], rules: dict[str, Any]) -> float:
    platform = normalize_platform(item.get("hotspotPlatform") or item.get("sourcePlatform") or item.get("platform"))
    media_type = detect_media_type(item)
    weights = rules.get("media_type_weights", {}).get(platform, {})
    try:
        return float(weights.get(media_type, weights.get("unknown", 1.0)) or 1.0)
    except (TypeError, ValueError):
        return 1.0


def contains_any_keyword(haystack: str, keywords: list[str]) -> bool:
    return any(keyword.strip().lower() in haystack for keyword in keywords if keyword.strip())


def contains_keyword_group(haystack: str, groups: list[list[str]]) -> bool:
    for group in groups:
        cleaned = [item.strip().lower() for item in group if item.strip()]
        if cleaned and all(item in haystack for item in cleaned):
            return True
    return False


def keyword_hits(haystack: str, keywords: list[str]) -> list[str]:
    return [keyword for keyword in keywords if keyword.strip() and keyword.strip().lower() in haystack]


def x_photo_relevance_details(item: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    config = rules.get("x_photo_relevance", {})
    platform = normalize_platform(item.get("hotspotPlatform") or item.get("sourcePlatform") or item.get("platform"))
    media_type = detect_media_type(item)
    details: dict[str, Any] = {
        "isRelevant": True,
        "applied": False,
        "score": 0,
        "mediaType": media_type,
        "strongHits": [],
        "supportHits": [],
        "excludeHits": [],
        "reason": "",
    }
    if not config.get("enabled", True) or platform != "x":
        details["reason"] = "not an enabled X relevance check"
        return details

    details["applied"] = True
    if config.get("require_image_or_mixed", True) and media_type not in {"image", "mixed", "video"}:
        details["isRelevant"] = False
        details["reason"] = f"media type {media_type} is not an X visual material"
        return details

    haystack = video_haystack(item, include_summary=True)
    strong_hits = keyword_hits(haystack, config.get("strong_keywords", []))
    support_hits = keyword_hits(haystack, config.get("support_keywords", []))
    exclude_hits = keyword_hits(haystack, config.get("exclude_keywords", []))
    group_hit = contains_keyword_group(haystack, config.get("exclude_keyword_groups", []))
    score = len(strong_hits) * 2 + min(len(support_hits), 3)
    if exclude_hits:
        score -= len(exclude_hits) * 3
    if group_hit:
        score -= 4

    min_score = int(config.get("min_score", 3) or 3)
    is_relevant = bool(score >= min_score and strong_hits and support_hits and not exclude_hits and not group_hit)
    details.update(
        {
            "isRelevant": is_relevant,
            "score": score,
            "strongHits": strong_hits[:8],
            "supportHits": support_hits[:8],
            "excludeHits": exclude_hits[:8],
            "reason": "real-person visual material matched" if is_relevant else "not a real-person photo/material reference",
        }
    )
    return details


def passes_x_photo_relevance(item: dict[str, Any], rules: dict[str, Any]) -> bool:
    return bool(x_photo_relevance_details(item, rules).get("isRelevant", True))


def passes_include_keywords(video: dict[str, Any], rules: dict[str, Any]) -> bool:
    platform = normalize_platform(video.get("hotspotPlatform") or video.get("sourcePlatform") or video.get("platform"))
    if platform == "x" and passes_x_photo_relevance(video, rules):
        return True
    source_query = str(video.get("sourceQuery") or video.get("searchQuery") or "").strip().lower()
    non_ai_queries = {
        str(query or "").strip().lower()
        for query in rules.get("scrape", {}).get("search_queries", [])
        if query and "ai" not in str(query).strip().lower()
    }
    if platform != "x" and source_query and source_query in non_ai_queries:
        return True
    keywords = rules.get("filters", {}).get("include_keywords", [])
    if not keywords:
        return True
    return contains_any_keyword(video_haystack(video), keywords)


def is_excluded_by_rules(video: dict[str, Any], rules: dict[str, Any], include_summary: bool = False) -> bool:
    filters = rules.get("filters", {})
    haystack = video_haystack(video, include_summary=include_summary)
    if contains_any_keyword(haystack, filters.get("exclude_keywords", [])):
        return True
    if include_summary and contains_any_keyword(haystack, filters.get("summary_exclude_keywords", [])):
        return True
    return contains_keyword_group(haystack, filters.get("exclude_keyword_groups", []))


def ranking_score(video: dict[str, Any], rules: dict[str, Any]) -> float:
    score = float(video.get("heatValue") or heat_score(video, rules=rules))
    filters = rules.get("filters", {})
    thresholds = rules.get("quality_thresholds", {})
    haystack = video_haystack(video, include_summary=True)
    if contains_any_keyword(haystack, filters.get("preferred_keywords", [])):
        score *= float(thresholds.get("preferred_keyword_boost", 1.0) or 1.0)
    if contains_any_keyword(haystack, filters.get("deprioritized_keywords", [])):
        score *= float(thresholds.get("deprioritized_keyword_penalty", 1.0) or 1.0)
    platform = normalize_platform(video.get("hotspotPlatform") or video.get("sourcePlatform") or video.get("platform"))
    if platform == "x":
        relevance = video.get("xPhotoRelevance") if isinstance(video.get("xPhotoRelevance"), dict) else x_photo_relevance_details(video, rules)
        x_photo_config = rules.get("x_photo_relevance", {})
        if relevance.get("applied"):
            score *= float(x_photo_config.get("boost" if relevance.get("isRelevant") else "penalty", 1.0) or 1.0)
    min_comment_rate = float(thresholds.get("min_comment_rate", 0) or 0)
    if min_comment_rate > 0:
        plays = float(video.get("playCount") or video.get("view_count") or video.get("views") or 0)
        comments = float(video.get("commentCount") or video.get("reply_count") or video.get("comments") or 0)
        comment_rate = comments / plays if plays > 0 else 0.0
        if comment_rate < min_comment_rate:
            score *= float(thresholds.get("low_comment_rate_penalty", 1.0) or 1.0)
    score *= media_type_weight(video, rules)
    return score


def get_like_threshold(hours_old: float, rules: dict[str, Any]) -> int:
    thresholds = sorted(
        rules.get("quality_thresholds", {}).get("like_thresholds", []),
        key=lambda item: float(item.get("max_hours", math.inf)),
    )
    for item in thresholds:
        if hours_old <= float(item.get("max_hours", math.inf)):
            return int(item.get("min_digg_count", 0) or 0)
    return 0

