from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from contextlib import AbstractContextManager
from datetime import date, datetime, timedelta
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlencode, urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(BASE_DIR / "feedback_loop"))

from env_utils import env_bool, env_float, env_int, load_env
from feedback_field_utils import normalize_acceptance
from feedback_rules import load_feedback_rules
from feishu_feedback import collect_recent_feedback
from phase1_scrape import process_scraper_output


RUN_ROOT = BASE_DIR / "skill_runs" / "tiktok_keyword_discovery"
LOCK_FILE = BASE_DIR / "skill_runs" / "locks" / "tiktok_keyword_discovery.lock"
DEFAULT_COOKIE_FILE = BASE_DIR / "www.tiktok.com_cookies.txt"
DEFAULT_PRODUCT_DOC = BASE_DIR / "references" / "product_material_requirements.md"
DEFAULT_LAYER_CONFIG = BASE_DIR / "references" / "tiktok_discovery_keyword_layers.json"
DEFAULT_MAX_TERMS = 100
DEFAULT_TERMS_PER_SEED = 5
DEFAULT_ALLOCATION = 50
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_BROWSER_CHANNEL = "msedge"
DEFAULT_MAX_SCROLLS = 40
DEFAULT_WAIT_MS = 1400
DEFAULT_DETAIL_HEADLESS = True
DEFAULT_SCROLL_WAIT_MIN_MS = 2000
DEFAULT_SCROLL_WAIT_MAX_MS = 4000
DEFAULT_MAX_NO_GROWTH_ROUNDS = 6
DEFAULT_VERIFICATION_POLL_SECONDS = 5
DEFAULT_VERIFICATION_WAIT_SECONDS = 200
DEFAULT_EXTERNAL_SOURCE_TIMEOUT_SECONDS = 8
DEFAULT_SLIDER_PUZZLE_CONTAINER_SELECTOR = '.captcha_verify_container, .captcha-verify-container, [class*="captcha"], [id*="captcha"]'
DEFAULT_SLIDER_PUZZLE_TRACK_SELECTOR = '[class*="secsdk-captcha-drag"], [class*="captcha_drag"], [class*="captcha-slider"], [role="slider"]'
DEFAULT_SLIDER_PUZZLE_HANDLE_SELECTOR = '[class*="captcha_drag_icon"], [class*="captcha-slider-btn"], [class*="secsdk-captcha-drag-icon"], [role="slider"]'
DEFAULT_SLIDER_PUZZLE_INNER_SELECTOR = ""
DEFAULT_SLIDER_PUZZLE_MAX_ATTEMPTS = 8
DEFAULT_SLIDER_PUZZLE_AUTO_ATTEMPTS = 3
DEFAULT_SLIDER_PUZZLE_TOLERANCE_SCORE = 0.25
DEFAULT_SLIDER_PUZZLE_ROTATION_DEGREES = 360.0
FORBIDDEN_EXTERNAL_HOST_TOKENS = ("rapidapi", "apify", "socialcrawl")
SEARCH_JSON_URL_MARKERS = (
    "/api/search/",
    "/api/recommend/",
    "/api/post/item_list/",
    "/api/item/list/",
    "/api/explore/",
)
KEYWORD_LAYERS = ("evergreen", "hot", "preheat")
CANONICAL_STAGES = ("stage0", "stage1", "stage2", "stage3", "stage4", "stage5")
STAGE_ALIASES = {
    "keywords": "stage0",
    "search": "stage2",
    "details": "stage3",
    "filter": "stage4",
    "report": "stage5",
}
DEFAULT_KEYWORD_LAYER_CONFIG: dict[str, Any] = {
    "version": 1,
    "layer_counts": {"evergreen": 5, "hot": 10, "preheat": 5},
    "allocations": {"evergreen": 45, "hot": 70, "preheat": 45},
    "feedback_tuning": {
        "enabled": True,
        "lookback_days": 7,
        "replace_counts": {"evergreen": 1, "hot": 2, "preheat": 1},
        "allocation_min_multiplier": 0.6,
        "allocation_max_multiplier": 1.4,
    },
    "country_pool": {
        "US": {"enabled": True, "aliases": ["United States", "USA"]},
        "Europe": {"enabled": True, "aliases": ["UK", "Germany", "France", "Spain", "Italy"]},
        "Mexico": {"enabled": True, "aliases": []},
        "Brazil": {"enabled": True, "aliases": []},
        "Australia": {"enabled": True, "aliases": []},
        "India": {"enabled": True, "aliases": []},
    },
    "evergreen": {
        "lookback_days": 30,
        "fallback_keywords": [
            "photo to video ai",
            "ai face animation",
            "before after photo",
            "ai avatar puzzle",
            "ai action figure",
        ],
        "candidate_keywords": [
            "photo to video ai",
            "ai face animation",
            "ai emote face animation",
            "ai action figure",
            "ai image to video",
            "selfie to video ai",
            "ai viral effect",
            "ai portrait template",
            "creator transformation edit",
            "before after photo",
            "old photo restoration",
            "ai photo enhancer before after",
            "ai avatar puzzle",
            "avatar puzzle challenge",
            "clay avatar puzzle",
        ],
    },
    "hot": {
        "history_lookback_hours": 72,
        "max_history_terms": 20,
        "event_keywords": [
            "world cup poster",
            "world cup jersey edit",
            "football celebration edit",
            "match entrance edit",
            "world cup ai photo",
            "football card edit",
        ],
        "fallback_keywords": [
            "world cup poster",
            "world cup jersey edit",
            "football celebration edit",
            "match entrance edit",
            "world cup ai photo",
            "football card edit",
            "sports poster edit",
            "jersey portrait edit",
            "cinematic sports edit",
            "training transformation",
        ],
        "ad_material_keywords": [
            "poster",
            "jersey",
            "celebration",
            "entrance",
            "card",
            "portrait",
            "transition",
            "template",
            "training",
            "transformation",
            "cinematic",
            "fireworks",
            "family",
            "slideshow",
            "photo",
            "edit",
        ],
    },
    "preheat": {
        "event_window_days": 30,
        "boost_window_days": 14,
        "active_after_days": 2,
        "max_terms_per_event": 3,
        "fallback_keywords": [
            "fathers day photo template",
            "dad photo slideshow",
            "family memory photo",
            "4th of july photo template",
            "fireworks portrait edit",
        ],
        "events": [
            {
                "name": "Father's Day 2026",
                "type": "holiday",
                "date": "2026-06-21",
                "countries": ["US", "Europe", "Mexico", "Brazil", "Australia", "India"],
                "keywords": [
                    "fathers day photo template",
                    "dad photo slideshow",
                    "family memory photo",
                    "dad old photo restoration",
                    "fathers day photo to video ai",
                ],
            },
            {
                "name": "Independence Day / America250",
                "type": "holiday",
                "date": "2026-07-04",
                "countries": ["US"],
                "keywords": [
                    "4th of july photo template",
                    "fireworks portrait edit",
                    "usa flag transition",
                    "independence day poster",
                    "america 250 celebration",
                ],
            },
        ],
    },
    "external_sources": {
        "enabled": True,
        "hot": {
            "tiktok_creative_center": {
                "enabled": True,
                "timeout_seconds": DEFAULT_EXTERNAL_SOURCE_TIMEOUT_SECONDS,
                "top_n": 30,
                "urls": [
                    "https://ads.tiktok.com/business/creativecenter/inspiration/popular/hashtag/mobile/en",
                    "https://ads.tiktok.com/business/creativecenter/inspiration/popular/music/mobile/en",
                    "https://ads.tiktok.com/business/creativecenter/inspiration/popular/video/mobile/en",
                ],
                "keyword_templates": [
                    "{trend} edit",
                    "{trend} poster",
                    "{trend} photo template",
                    "{trend} transition",
                    "{trend} jersey edit",
                ],
            },
            "google_trends": {
                "enabled": True,
                "timeout_seconds": DEFAULT_EXTERNAL_SOURCE_TIMEOUT_SECONDS,
                "top_n": 30,
                "countries": ["US", "GB", "DE", "FR", "ES", "IT", "MX", "BR", "AU", "IN"],
                "rss_url": "https://trends.google.com/trending/rss?geo={country}",
                "keyword_templates": [
                    "{trend} edit",
                    "{trend} poster",
                    "{trend} photo template",
                    "{trend} transition",
                    "{trend} celebration edit",
                ],
            },
            "recent_discovery_history": {
                "enabled": True,
                "lookback_hours": 72,
                "max_terms": 20,
            },
        },
        "preheat": {
            "nager_date": {
                "enabled": True,
                "timeout_seconds": DEFAULT_EXTERNAL_SOURCE_TIMEOUT_SECONDS,
                "lookahead_days": 45,
                "countries": ["US", "GB", "DE", "FR", "ES", "IT", "MX", "BR", "AU", "IN"],
                "url": "https://date.nager.at/api/v3/PublicHolidays/{year}/{country}",
            },
            "thesportsdb": {
                "enabled": True,
                "timeout_seconds": DEFAULT_EXTERNAL_SOURCE_TIMEOUT_SECONDS,
                "lookahead_days": 45,
                "api_key": "3",
                "url": "https://www.thesportsdb.com/api/v1/json/{api_key}/eventsnextleague.php?{query}",
                "leagues": [
                    {"name": "FIFA World Cup", "id": "4429", "sport": "Soccer"},
                    {"name": "English Premier League", "id": "4328", "sport": "Soccer"},
                    {"name": "NBA", "id": "4387", "sport": "Basketball"},
                ],
            },
            "liquipedia": {
                "enabled": True,
                "timeout_seconds": DEFAULT_EXTERNAL_SOURCE_TIMEOUT_SECONDS,
                "lookahead_days": 60,
                "calendar_path": "references/liquipedia_esports_events.json",
                "events": [],
                "urls": [],
                "games": ["league of legends", "valorant", "cs2", "dota 2"],
            },
        },
    },
    "risk_keywords": [
        "score",
        "highlights",
        "news",
        "gossip",
        "paparazzi",
        "leak",
        "spoiler",
        "politics",
        "war",
        "nsfw",
        "bikini",
        "sexy",
        "onlyfans",
        "crypto",
        "web3",
        "meme",
    ],
}


PRODUCT_SIGNALS: dict[str, list[str]] = {
    "toki": [
        "photo to video ai",
        "image to video template",
        "ai action figure",
        "ai figurine template",
        "ai emote face animation",
        "ai dance template",
        "ai hug couple video",
        "talking photo ai",
        "portrait to live moment",
        "single photo video template",
    ],
    "kavi": [
        "selfie to video ai",
        "viral ai effect",
        "creator persona transformation",
        "streamer transformation",
        "stream dream portrait",
        "custom 3d figure video",
        "storybook portrait video",
        "dress up template",
        "dream portrait template",
        "portrait animation effect",
    ],
    "evoke": [
        "old photo restoration",
        "old photo to video",
        "photo enhancer before after",
        "black and white photo colorize",
        "scratch photo repair",
        "ai portrait enhancer",
        "family memory photo",
        "wedding photo restoration",
        "blurry photo clear",
        "before after photo template",
    ],
    "avatar_jigsaw": [
        "ai avatar jigsaw",
        "avatar puzzle challenge",
        "clay avatar puzzle",
        "profile photo jigsaw",
        "facebook instant game avatar",
        "avatar puzzle pieces",
        "ai profile photo puzzle",
        "clay avatar challenge",
        "share avatar puzzle",
        "avatar friends challenge",
    ],
}

NEGATIVE_SIGNALS = [
    "nsfw",
    "onlyfans",
    "nude",
    "lingerie",
    "bikini",
    "swimsuit",
    "sexy",
    "anime",
    "manga",
    "fanart",
    "celebrity gossip",
    "paparazzi",
    "leak",
    "spoiler",
    "crypto",
    "web3",
    "election",
    "politics",
    "war",
    "hardware",
    "ai news",
]

MATERIAL_TEMPLATE_TOKENS = {
    "edit",
    "poster",
    "photo",
    "template",
    "transition",
    "jersey",
    "celebration",
    "portrait",
    "card",
    "slideshow",
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def run_id_from_now() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def clean_text(value: Any, max_len: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if max_len is not None and len(text) > max_len:
        return text[: max_len - 3].rstrip() + "..."
    return text


def normalize_keyword(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = text.replace("\u2019", "'")
    text = re.sub(r"([a-z0-9])'s\b", r"\1s", text)
    text = text.replace("'", "")
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9 +]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -_+")
    words = [word for word in text.split() if word not in {"the", "and", "for", "with", "from", "tiktok", "viral", "trending"}]
    return " ".join(words[:7]).strip()


def keyword_allowed(value: str) -> tuple[bool, list[str]]:
    keyword = normalize_keyword(value)
    hits = [signal for signal in NEGATIVE_SIGNALS if signal in keyword]
    if hits:
        return False, hits
    if len(keyword.split()) < 2 or not re.search(r"[a-z]", keyword):
        return False, ["too_short"]
    return True, []


def is_low_semantic_external_trend(value: Any) -> bool:
    normalized = normalize_keyword(value)
    all_tokens = [token for token in normalized.split() if token]
    tokens = [token for token in all_tokens if token not in MATERIAL_TEMPLATE_TOKENS]
    if all_tokens and not tokens:
        return len(all_tokens) <= 2 or len(set(all_tokens)) < len(all_tokens)
    if not tokens:
        return False
    if any(re.search(r"[g-z]", token) for token in tokens):
        return False
    if any(len(token) >= 4 and re.search(r"[a-z]", token) and not re.fullmatch(r"[a-f0-9]+", token) for token in tokens):
        return False
    return all(re.fullmatch(r"[a-f0-9]{1,8}", token) for token in tokens)


def relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(BASE_DIR.resolve()).as_posix()
    except ValueError:
        return str(path)


def resolve_repo_path(raw: str | None, default: Path) -> Path:
    if not raw:
        return default
    path = Path(raw)
    return path if path.is_absolute() else BASE_DIR / path


def resolve_optional_repo_path(raw: str | None) -> Path | None:
    text = clean_text(raw)
    if not text:
        return None
    path = Path(text)
    return path if path.is_absolute() else BASE_DIR / path


def normalize_stage_name(value: Any) -> str:
    stage = clean_text(value or "all").lower()
    if stage == "all":
        return "all"
    return STAGE_ALIASES.get(stage, stage)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def slug(value: str, fallback: str = "keyword") -> str:
    text = normalize_keyword(value)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:80]
    return text or fallback


class DiscoveryLock(AbstractContextManager["DiscoveryLock"]):
    def __init__(self, path: Path, enabled: bool = True) -> None:
        self.path = path
        self.enabled = enabled
        self.fd: int | None = None

    def __enter__(self) -> "DiscoveryLock":
        if not self.enabled:
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(self.fd, f"{os.getpid()} {now_iso()}\n".encode("utf-8"))
        except FileExistsError as exc:
            raise RuntimeError(f"TikTok keyword discovery already running; lock exists: {self.path}") from exc
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        if self.enabled:
            try:
                self.path.unlink(missing_ok=True)
            except Exception:
                pass
        return False


def build_config(args: argparse.Namespace, env: dict[str, str]) -> dict[str, Any]:
    root = resolve_repo_path(args.root or env.get("TIKTOK_KEYWORD_DISCOVERY_ROOT"), RUN_ROOT)
    run_id = args.run_id or run_id_from_now()
    run_dir = root / "runs" / run_id
    requested_stage = clean_text(getattr(args, "stage", None) or "all").lower()
    stage = normalize_stage_name(requested_stage)
    target_date_raw = clean_text(getattr(args, "target_date", None) or env.get("TIKTOK_KEYWORD_DISCOVERY_TARGET_DATE"))
    target_date_value = date.today()
    if target_date_raw:
        try:
            target_date_value = date.fromisoformat(target_date_raw)
        except ValueError as exc:
            raise ValueError("TIKTOK_KEYWORD_DISCOVERY_TARGET_DATE / --target-date must be YYYY-MM-DD") from exc
    scroll_wait_min_ms = max(
        0,
        int(getattr(args, "scroll_wait_min_ms", None) or env_int("TIKTOK_KEYWORD_DISCOVERY_SCROLL_WAIT_MIN_MS", DEFAULT_SCROLL_WAIT_MIN_MS, env)),
    )
    scroll_wait_max_ms = max(
        scroll_wait_min_ms,
        int(getattr(args, "scroll_wait_max_ms", None) or env_int("TIKTOK_KEYWORD_DISCOVERY_SCROLL_WAIT_MAX_MS", DEFAULT_SCROLL_WAIT_MAX_MS, env)),
    )
    slider_puzzle_enabled_arg = getattr(args, "slider_puzzle_enabled", None)
    return {
        "runId": run_id,
        "root": root,
        "runDir": run_dir,
        "latestPath": root / "latest.json",
        "targetDate": target_date_value.isoformat(),
        "cookieFile": resolve_repo_path(args.cookie_file or env.get("TIKTOK_KEYWORD_DISCOVERY_COOKIE_FILE"), DEFAULT_COOKIE_FILE),
        "productDocPath": resolve_repo_path(args.product_doc or env.get("TIKTOK_KEYWORD_DISCOVERY_PRODUCT_DOC_PATH"), DEFAULT_PRODUCT_DOC),
        "layeredKeywords": {
            "enabled": (
                bool(getattr(args, "layered_keywords", None))
                if getattr(args, "layered_keywords", None) is not None
                else env_bool("TIKTOK_KEYWORD_DISCOVERY_LAYERED_ENABLED", False, env)
            ),
            "configPath": resolve_repo_path(getattr(args, "layer_config", None) or env.get("TIKTOK_KEYWORD_DISCOVERY_LAYER_CONFIG"), DEFAULT_LAYER_CONFIG),
        },
        "maxTerms": max(1, int(args.max_terms or env_int("TIKTOK_KEYWORD_DISCOVERY_MAX_TERMS", DEFAULT_MAX_TERMS, env))),
        "termsPerSeed": max(1, int(args.terms_per_seed or env_int("TIKTOK_KEYWORD_DISCOVERY_TERMS_PER_SEED", DEFAULT_TERMS_PER_SEED, env))),
        "allocation": max(1, int(args.allocation or env_int("TIKTOK_KEYWORD_DISCOVERY_ALLOCATION", DEFAULT_ALLOCATION, env))),
        "lookbackDays": max(1, int(args.lookback_days or env_int("TIKTOK_KEYWORD_DISCOVERY_LOOKBACK_DAYS", DEFAULT_LOOKBACK_DAYS, env))),
        "headless": args.headless if args.headless is not None else env_bool("TIKTOK_KEYWORD_DISCOVERY_HEADLESS", True, env),
        "detailHeadless": (
            getattr(args, "detail_headless", None)
            if getattr(args, "detail_headless", None) is not None
            else env_bool("TIKTOK_KEYWORD_DISCOVERY_DETAIL_HEADLESS", DEFAULT_DETAIL_HEADLESS, env)
        ),
        "browserChannel": clean_text(args.browser_channel or env.get("TIKTOK_KEYWORD_DISCOVERY_BROWSER_CHANNEL") or DEFAULT_BROWSER_CHANNEL),
        "browserExecutable": resolve_optional_repo_path(args.browser_executable or env.get("TIKTOK_KEYWORD_DISCOVERY_BROWSER_EXECUTABLE")),
        "maxScrolls": max(0, int(args.max_scrolls or env_int("TIKTOK_KEYWORD_DISCOVERY_MAX_SCROLLS", DEFAULT_MAX_SCROLLS, env))),
        "waitMs": max(0, int(args.wait_ms or env_int("TIKTOK_KEYWORD_DISCOVERY_WAIT_MS", DEFAULT_WAIT_MS, env))),
        "scrollWaitMinMs": scroll_wait_min_ms,
        "scrollWaitMaxMs": scroll_wait_max_ms,
        "maxNoGrowthRounds": max(
            1,
            int(getattr(args, "max_no_growth_rounds", None) or env_int("TIKTOK_KEYWORD_DISCOVERY_MAX_NO_GROWTH_ROUNDS", DEFAULT_MAX_NO_GROWTH_ROUNDS, env)),
        ),
        "verificationPollSeconds": max(
            1,
            int(getattr(args, "verification_poll_seconds", None) or env_int("TIKTOK_KEYWORD_DISCOVERY_VERIFICATION_POLL_SECONDS", DEFAULT_VERIFICATION_POLL_SECONDS, env)),
        ),
        "verificationWaitSeconds": max(
            0,
            int(getattr(args, "verification_wait_seconds", None) or env_int("TIKTOK_KEYWORD_DISCOVERY_VERIFICATION_WAIT_SECONDS", DEFAULT_VERIFICATION_WAIT_SECONDS, env)),
        ),
        "sliderPuzzle": {
            "enabled": (
                bool(slider_puzzle_enabled_arg)
                if slider_puzzle_enabled_arg is not None
                else env_bool("TIKTOK_KEYWORD_DISCOVERY_SLIDER_PUZZLE_ENABLED", True, env)
            ),
            "containerSelector": clean_text(
                getattr(args, "slider_puzzle_container_selector", None)
                or env.get("TIKTOK_KEYWORD_DISCOVERY_SLIDER_PUZZLE_CONTAINER_SELECTOR")
                or DEFAULT_SLIDER_PUZZLE_CONTAINER_SELECTOR
            ),
            "trackSelector": clean_text(
                getattr(args, "slider_puzzle_track_selector", None)
                or env.get("TIKTOK_KEYWORD_DISCOVERY_SLIDER_PUZZLE_TRACK_SELECTOR")
                or DEFAULT_SLIDER_PUZZLE_TRACK_SELECTOR
            ),
            "handleSelector": clean_text(
                getattr(args, "slider_puzzle_handle_selector", None)
                or env.get("TIKTOK_KEYWORD_DISCOVERY_SLIDER_PUZZLE_HANDLE_SELECTOR")
                or DEFAULT_SLIDER_PUZZLE_HANDLE_SELECTOR
            ),
            "innerSelector": clean_text(
                getattr(args, "slider_puzzle_inner_selector", None)
                or env.get("TIKTOK_KEYWORD_DISCOVERY_SLIDER_PUZZLE_INNER_SELECTOR")
                or DEFAULT_SLIDER_PUZZLE_INNER_SELECTOR
            ),
            "successSelector": clean_text(
                getattr(args, "slider_puzzle_success_selector", None)
                or env.get("TIKTOK_KEYWORD_DISCOVERY_SLIDER_PUZZLE_SUCCESS_SELECTOR")
                or ""
            ),
            "maxAttempts": max(
                1,
                int(
                    getattr(args, "slider_puzzle_max_attempts", None)
                    or env_int("TIKTOK_KEYWORD_DISCOVERY_SLIDER_PUZZLE_MAX_ATTEMPTS", DEFAULT_SLIDER_PUZZLE_MAX_ATTEMPTS, env)
                ),
            ),
            "autoAttempts": min(
                3,
                max(
                    1,
                    int(
                        getattr(args, "slider_puzzle_auto_attempts", None)
                        or env_int("TIKTOK_KEYWORD_DISCOVERY_SLIDER_PUZZLE_AUTO_ATTEMPTS", DEFAULT_SLIDER_PUZZLE_AUTO_ATTEMPTS, env)
                    ),
                ),
            ),
            "toleranceScore": max(
                0.0,
                min(
                    1.0,
                    float(
                        getattr(args, "slider_puzzle_tolerance_score", None)
                        or env_float("TIKTOK_KEYWORD_DISCOVERY_SLIDER_PUZZLE_TOLERANCE_SCORE", DEFAULT_SLIDER_PUZZLE_TOLERANCE_SCORE, env)
                    ),
                ),
            ),
            "rotationDegrees": max(
                1.0,
                float(
                    getattr(args, "slider_puzzle_rotation_degrees", None)
                    or env_float("TIKTOK_KEYWORD_DISCOVERY_SLIDER_PUZZLE_ROTATION_DEGREES", DEFAULT_SLIDER_PUZZLE_ROTATION_DEGREES, env)
                ),
            ),
        },
        "externalSourcesEnabled": (
            bool(getattr(args, "external_sources", None))
            if getattr(args, "external_sources", None) is not None
            else env_bool("TIKTOK_KEYWORD_DISCOVERY_EXTERNAL_SOURCES_ENABLED", True, env)
        ),
        "stage4Profile": clean_text(
            getattr(args, "stage4_profile", None)
            or getattr(args, "route_profile", None)
            or env.get("TIKTOK_KEYWORD_DISCOVERY_STAGE4_PROFILE")
            or "main"
        ).lower(),
        "stage": stage,
        "requestedStage": requested_stage,
        "resume": bool(args.resume),
        "noLock": bool(args.no_lock),
    }


def public_config(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "runId": config["runId"],
        "stage": config["stage"],
        "requestedStage": config.get("requestedStage", config["stage"]),
        "root": relative_path(Path(config["root"])),
        "runDir": relative_path(Path(config["runDir"])),
        "cookieFile": relative_path(Path(config["cookieFile"])),
        "productDocPath": relative_path(Path(config["productDocPath"])),
        "layeredKeywords": {
            "enabled": bool((config.get("layeredKeywords") or {}).get("enabled")),
            "configPath": relative_path(Path((config.get("layeredKeywords") or {}).get("configPath", DEFAULT_LAYER_CONFIG))),
        },
        "maxTerms": config["maxTerms"],
        "termsPerSeed": config["termsPerSeed"],
        "allocation": config["allocation"],
        "lookbackDays": config["lookbackDays"],
        "headless": config["headless"],
        "detailHeadless": config["detailHeadless"],
        "browserChannel": config["browserChannel"],
        "browserExecutable": relative_path(Path(config["browserExecutable"])) if config.get("browserExecutable") else "",
        "maxScrolls": config["maxScrolls"],
        "waitMs": config["waitMs"],
        "scrollWaitMinMs": config["scrollWaitMinMs"],
        "scrollWaitMaxMs": config["scrollWaitMaxMs"],
        "maxNoGrowthRounds": config["maxNoGrowthRounds"],
        "verificationPollSeconds": config["verificationPollSeconds"],
        "verificationWaitSeconds": config["verificationWaitSeconds"],
        "sliderPuzzle": config["sliderPuzzle"],
        "externalSourcesEnabled": bool(config.get("externalSourcesEnabled")),
        "stage4Profile": config.get("stage4Profile", "main"),
        "forbiddenExternalHosts": list(FORBIDDEN_EXTERNAL_HOST_TOKENS),
    }


def row_platform(row: dict[str, Any]) -> str:
    text = clean_text(row.get("platform")).lower()
    if text in {"tik tok", "tt"}:
        return "tiktok"
    return text


def safe_float(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def load_feedback_seeds(config: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.seeds_file:
        payload = read_json(resolve_repo_path(args.seeds_file, Path(args.seeds_file)), [])
        rows = payload if isinstance(payload, list) else []
    else:
        rows = collect_recent_feedback(days=int(config["lookbackDays"]))
    seeds: list[dict[str, Any]] = []
    for row in rows:
        if row_platform(row) != "tiktok":
            continue
        if normalize_acceptance(row.get("material_acceptance")) != "\u9ad8":
            continue
        url = clean_text(row.get("url"))
        if not url:
            continue
        seeds.append(
            {
                "recordId": clean_text(row.get("record_id")),
                "pushDate": str(row.get("push_date") or ""),
                "platform": "TikTok",
                "url": url,
                "intro": clean_text(row.get("intro"), max_len=1200),
                "materialReason": clean_text(row.get("material_reason"), max_len=800),
                "heat": clean_text(row.get("heat")),
                "plays": clean_text(row.get("plays")),
                "likes": clean_text(row.get("likes")),
                "comments": clean_text(row.get("comments")),
                "materialAcceptance": clean_text(row.get("material_acceptance")),
            }
        )
    seeds.sort(key=lambda item: (item.get("pushDate") or "", safe_float(item.get("heat"))), reverse=True)
    return seeds


def product_doc_signals(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    lowered = text.lower()
    positive = sorted(
        {
            term
            for terms in PRODUCT_SIGNALS.values()
            for term in terms
            if not lowered or term in lowered or any(token in lowered for token in term.split()[:2])
        }
    )
    negative = [term for term in NEGATIVE_SIGNALS if not lowered or term in lowered]
    return {
        "path": relative_path(path),
        "exists": path.exists(),
        "chars": len(text),
        "positiveSignals": positive,
        "negativeSignals": negative,
        "products": list(PRODUCT_SIGNALS.keys()),
    }


def matched_products(text: str) -> list[str]:
    haystack = text.lower()
    scores: list[tuple[int, str]] = []
    for product, terms in PRODUCT_SIGNALS.items():
        score = sum(1 for term in terms if any(token in haystack for token in term.split()))
        if product in haystack:
            score += 3
        if score:
            scores.append((score, product))
    scores.sort(reverse=True)
    return [product for _score, product in scores] or ["toki", "kavi", "evoke", "avatar_jigsaw"]


def generate_seed_keyword_candidates(seed: dict[str, Any], doc: dict[str, Any], terms_per_seed: int) -> dict[str, Any]:
    haystack = " ".join([clean_text(seed.get("intro")), clean_text(seed.get("materialReason"))]).lower()
    products = matched_products(haystack)
    ordered_terms: list[tuple[str, str, list[str]]] = []
    for product in products:
        for term in PRODUCT_SIGNALS.get(product, []):
            hits = [token for token in term.split() if token in haystack]
            ordered_terms.append((term, product, hits))
    for product, terms in PRODUCT_SIGNALS.items():
        if product in products:
            continue
        for term in terms:
            ordered_terms.append((term, product, []))

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for term, product, hits in ordered_terms:
        keyword = normalize_keyword(term)
        if keyword in seen:
            continue
        seen.add(keyword)
        allowed, reject_hits = keyword_allowed(keyword)
        payload = {
            "keyword": keyword,
            "sourceSeedUrl": seed.get("url", ""),
            "matchedProduct": product,
            "matchedDocSignals": hits or [term],
            "rejectedDocSignals": reject_hits,
            "generationReason": "matched seed/product document signals" if hits else "product document fallback",
        }
        if allowed:
            accepted.append(payload)
        else:
            rejected.append(payload)
        if len(accepted) >= terms_per_seed:
            break
    return {
        "seedUrl": seed.get("url", ""),
        "terms": accepted[:terms_per_seed],
        "rejectedTerms": rejected,
    }


def main_scrape_queries() -> list[str]:
    rules = load_feedback_rules()
    queries = rules.get("scrape", {}).get("search_queries", [])
    if not isinstance(queries, list):
        return []
    result: list[str] = []
    for query in queries:
        keyword = normalize_keyword(query)
        if keyword and keyword not in result:
            result.append(keyword)
    return result[:10]


def build_search_plan(
    main_queries: list[str],
    keyword_candidates: list[dict[str, Any]],
    *,
    max_terms: int,
    allocation: int,
) -> list[dict[str, Any]]:
    plan_by_keyword: dict[str, dict[str, Any]] = {}

    def add(keyword: str, source: str, context: dict[str, Any] | None = None) -> None:
        normalized = normalize_keyword(keyword)
        if not normalized:
            return
        item = plan_by_keyword.setdefault(
            normalized,
            {
                "keyword": normalized,
                "allocation": allocation,
                "sources": [],
                "productContexts": [],
                "isMainPipelineQuery": False,
            },
        )
        if source not in item["sources"]:
            item["sources"].append(source)
        if source == "main_pipeline":
            item["isMainPipelineQuery"] = True
        if context:
            item["productContexts"].append(context)

    for query in main_queries:
        add(query, "main_pipeline")
    for entry in keyword_candidates:
        for term in entry.get("terms", []):
            if len(plan_by_keyword) >= max_terms:
                break
            add(term.get("keyword", ""), "feedback_seed_product_doc", term)
        if len(plan_by_keyword) >= max_terms:
            break
    return list(plan_by_keyword.values())[:max_terms]


def recursive_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = recursive_merge(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def load_keyword_layer_config(path: Path | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    config_path = path or DEFAULT_LAYER_CONFIG
    if config_path.exists():
        raw = read_json(config_path, {})
        if isinstance(raw, dict):
            payload = raw
    return recursive_merge(DEFAULT_KEYWORD_LAYER_CONFIG, payload)


def keyword_layer_counts(layer_config: dict[str, Any]) -> dict[str, int]:
    raw = layer_config.get("layer_counts") if isinstance(layer_config.get("layer_counts"), dict) else {}
    return {
        layer: max(0, int(raw.get(layer, DEFAULT_KEYWORD_LAYER_CONFIG["layer_counts"][layer]) or 0))
        for layer in KEYWORD_LAYERS
    }


def keyword_layer_allocations(layer_config: dict[str, Any]) -> dict[str, int]:
    raw = layer_config.get("allocations") if isinstance(layer_config.get("allocations"), dict) else {}
    return {
        layer: max(1, int(raw.get(layer, DEFAULT_KEYWORD_LAYER_CONFIG["allocations"][layer]) or 1))
        for layer in KEYWORD_LAYERS
    }


def enabled_country_codes(layer_config: dict[str, Any]) -> set[str]:
    pool = layer_config.get("country_pool") if isinstance(layer_config.get("country_pool"), dict) else {}
    result: set[str] = set()
    for country, details in pool.items():
        if isinstance(details, dict) and details.get("enabled") is False:
            continue
        if str(country or "").strip():
            result.add(str(country).strip())
    return result


def parse_layer_event_date(value: Any) -> date | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def keyword_contains_signal(keyword: str, signals: list[str]) -> bool:
    normalized = normalize_keyword(keyword)
    return any(normalize_keyword(signal) and normalize_keyword(signal) in normalized for signal in signals)


def is_layer_keyword_blocked(keyword: str, layer_config: dict[str, Any]) -> tuple[bool, list[str]]:
    risk = layer_config.get("risk_keywords")
    risk_keywords = risk if isinstance(risk, list) else DEFAULT_KEYWORD_LAYER_CONFIG["risk_keywords"]
    hits = [signal for signal in risk_keywords if keyword_contains_signal(keyword, [str(signal)])]
    allowed, reject_hits = keyword_allowed(keyword)
    if layer_config.get("allow_single_token") and reject_hits == ["too_short"]:
        reject_hits = []
        allowed = True
    return bool(hits or not allowed), [*hits, *reject_hits]


def product_context_for_keyword(keyword: str) -> dict[str, Any] | None:
    normalized = normalize_keyword(keyword)
    best: tuple[int, str, str] | None = None
    for product, terms in PRODUCT_SIGNALS.items():
        for term in terms:
            term_key = normalize_keyword(term)
            term_tokens = [token for token in term_key.split() if token]
            keyword_tokens = set(normalized.split())
            score = len([token for token in term_tokens if token in keyword_tokens])
            if term_key and (term_key in normalized or normalized in term_key):
                score += 3
            if score and (best is None or score > best[0]):
                best = (score, product, term)
    if best is None:
        return None
    _score, product, term = best
    return {
        "keyword": normalized,
        "matchedProduct": product,
        "matchedDocSignals": [term],
        "generationReason": "layered keyword matched product signals",
    }


def ad_material_fit(keyword: str, layer_config: dict[str, Any]) -> bool:
    hot_cfg = layer_config.get("hot") if isinstance(layer_config.get("hot"), dict) else {}
    signals = hot_cfg.get("ad_material_keywords")
    ad_signals = signals if isinstance(signals, list) else DEFAULT_KEYWORD_LAYER_CONFIG["hot"]["ad_material_keywords"]
    return keyword_contains_signal(keyword, [str(signal) for signal in ad_signals])


def keyword_fit_type(keyword: str, layer: str, layer_config: dict[str, Any]) -> str:
    product_context = product_context_for_keyword(keyword)
    ad_fit = ad_material_fit(keyword, layer_config)
    if product_context and (ad_fit or layer == "hot"):
        return "both"
    if product_context:
        return "product"
    if ad_fit:
        return "ad_material"
    return "none"


def acceptance_from_row(row: dict[str, Any]) -> str:
    return normalize_acceptance(row.get("material_acceptance") or row.get("materialAcceptance") or row.get("acceptance"))


def feedback_row_text(row: dict[str, Any]) -> str:
    return " ".join(
        clean_text(row.get(key), max_len=1200)
        for key in ["intro", "material_reason", "materialReason", "text", "summary"]
    ).lower()


def keyword_feedback_score(keyword: str, rows: list[dict[str, Any]]) -> tuple[float, int]:
    normalized = normalize_keyword(keyword)
    tokens = [token for token in normalized.split() if token not in {"ai", "photo", "edit", "template"}]
    if not tokens:
        tokens = normalized.split()
    score = 0.0
    hits = 0
    for row in rows:
        if row_platform(row) and row_platform(row) != "tiktok":
            continue
        haystack = feedback_row_text(row)
        if not haystack:
            continue
        phrase_hit = normalized and normalized in normalize_keyword(haystack)
        token_hit_count = sum(1 for token in tokens if token in haystack)
        if not phrase_hit and token_hit_count < max(1, min(2, len(tokens))):
            continue
        hits += 1
        acceptance = acceptance_from_row(row)
        if acceptance == "\u9ad8":
            score += 3.0
        elif acceptance == "\u4e2d":
            score += 1.0
        elif acceptance in {"\u4f4e", "\u5426\u51b3"}:
            score -= 2.0
        else:
            score += 0.2
        score += min(1.0, token_hit_count * 0.2)
    return score, hits


def external_sources_config(layer_config: dict[str, Any]) -> dict[str, Any]:
    configured = layer_config.get("external_sources") if isinstance(layer_config.get("external_sources"), dict) else {}
    defaults = DEFAULT_KEYWORD_LAYER_CONFIG["external_sources"]
    return recursive_merge(defaults, configured)


def nested_external_source_config(layer_config: dict[str, Any], layer: str, source: str) -> dict[str, Any]:
    cfg = external_sources_config(layer_config)
    layer_cfg = cfg.get(layer) if isinstance(cfg.get(layer), dict) else {}
    source_cfg = layer_cfg.get(source) if isinstance(layer_cfg.get(source), dict) else {}
    return source_cfg


def external_source_enabled(layer_config: dict[str, Any], layer: str, source: str) -> bool:
    cfg = external_sources_config(layer_config)
    if cfg.get("enabled") is False:
        return False
    source_cfg = nested_external_source_config(layer_config, layer, source)
    return source_cfg.get("enabled") is not False


def timeout_seconds(cfg: dict[str, Any]) -> int:
    try:
        return max(1, int(cfg.get("timeout_seconds", DEFAULT_EXTERNAL_SOURCE_TIMEOUT_SECONDS) or DEFAULT_EXTERNAL_SOURCE_TIMEOUT_SECONDS))
    except (TypeError, ValueError):
        return DEFAULT_EXTERNAL_SOURCE_TIMEOUT_SECONDS


def fetch_url_text(url: str, timeout: int = DEFAULT_EXTERNAL_SOURCE_TIMEOUT_SECONDS) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; TikTokKeywordDiscovery/1.0)",
            "Accept": "text/html,application/xhtml+xml,application/xml,application/json;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def fetch_url_json(url: str, timeout: int = DEFAULT_EXTERNAL_SOURCE_TIMEOUT_SECONDS) -> Any:
    return json.loads(fetch_url_text(url, timeout=timeout))


def source_record(
    *,
    source: str,
    title: str,
    source_url: str = "",
    score: float = 0.0,
    raw: dict[str, Any] | None = None,
    region: str = "",
) -> dict[str, Any]:
    keyword = normalize_keyword(title)
    return {
        "source": source,
        "externalSource": source,
        "title": clean_text(title, max_len=160),
        "keyword": keyword,
        "sourceUrl": clean_text(source_url, max_len=600),
        "score": float(score or 0.0),
        "region": clean_text(region, max_len=40),
        "rawTrend": raw or {},
    }


def unique_external_records(records: list[dict[str, Any]], limit: int = 100) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for record in records:
        key = normalize_keyword(record.get("keyword") or record.get("title"))
        if not key:
            continue
        if is_low_semantic_external_trend(key):
            continue
        item = dict(record)
        item["keyword"] = key
        existing = by_key.get(key)
        if not existing or float(item.get("score", 0.0) or 0.0) > float(existing.get("score", 0.0) or 0.0):
            by_key[key] = item
        elif existing:
            sources = unique_strings([*(existing.get("sources") or [existing.get("source")]), item.get("source")])
            existing["sources"] = sources
    return sorted(by_key.values(), key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)[:limit]


def extract_hashtag_like_terms(text: str) -> list[str]:
    terms: list[str] = []
    for match in re.findall(r"#[A-Za-z0-9_]{2,80}", text or ""):
        readable = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", match.lstrip("#").replace("_", " "))
        keyword = normalize_keyword(readable)
        if keyword and keyword not in terms:
            terms.append(keyword)
    for pattern in [
        r'"hashtag(?:Name|_name|Title|title)?"\s*:\s*"([^"]{2,120})"',
        r'"challengeName"\s*:\s*"([^"]{2,120})"',
        r'"songName"\s*:\s*"([^"]{2,120})"',
        r'"creatorName"\s*:\s*"([^"]{2,120})"',
    ]:
        for value in re.findall(pattern, text or "", flags=re.IGNORECASE):
            keyword = normalize_keyword(html.unescape(value))
            if keyword and keyword not in terms:
                terms.append(keyword)
    return terms


def collect_tiktok_creative_center_trends(layer_config: dict[str, Any], fetch_text_fn: Any = fetch_url_text) -> list[dict[str, Any]]:
    cfg = nested_external_source_config(layer_config, "hot", "tiktok_creative_center")
    if not external_source_enabled(layer_config, "hot", "tiktok_creative_center"):
        return []
    records: list[dict[str, Any]] = []
    top_n = max(1, int(cfg.get("top_n", 30) or 30))
    urls = [clean_text(url) for url in cfg.get("urls", []) if clean_text(url)]
    for url_index, url in enumerate(urls):
        text = fetch_text_fn(url, timeout_seconds(cfg))
        for rank, term in enumerate(extract_hashtag_like_terms(text), start=1):
            records.append(
                source_record(
                    source="tiktok_creative_center",
                    title=term,
                    source_url=url,
                    score=92.0 - url_index * 2.0 - rank * 0.05,
                    raw={"rank": rank, "urlIndex": url_index},
                )
            )
    return unique_external_records(records, top_n)


def parse_google_trends_rss(text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        root = None
    if root is not None:
        for rank, item in enumerate(root.findall(".//item"), start=1):
            title_node = item.find("title")
            link_node = item.find("link")
            title = clean_text(title_node.text if title_node is not None else "")
            if not title:
                continue
            records.append(
                source_record(
                    source="google_trends",
                    title=title,
                    source_url=clean_text(link_node.text if link_node is not None else ""),
                    score=82.0 - rank * 0.04,
                    raw={"rank": rank},
                )
            )
        return records
    for rank, title in enumerate(re.findall(r"<title>([^<]{2,160})</title>", text or "", flags=re.IGNORECASE), start=1):
        title = html.unescape(title)
        if normalize_keyword(title) not in {"trending now google trends", "google trends"}:
            records.append(source_record(source="google_trends", title=title, score=82.0 - rank * 0.04, raw={"rank": rank}))
    return records


def collect_google_trends(layer_config: dict[str, Any], fetch_text_fn: Any = fetch_url_text) -> list[dict[str, Any]]:
    cfg = nested_external_source_config(layer_config, "hot", "google_trends")
    if not external_source_enabled(layer_config, "hot", "google_trends"):
        return []
    records: list[dict[str, Any]] = []
    top_n = max(1, int(cfg.get("top_n", 30) or 30))
    template = clean_text(cfg.get("rss_url")) or DEFAULT_KEYWORD_LAYER_CONFIG["external_sources"]["hot"]["google_trends"]["rss_url"]
    countries = [clean_text(country).upper() for country in cfg.get("countries", []) if clean_text(country)]
    for country in countries:
        url = template.format(country=quote(country))
        text = fetch_text_fn(url, timeout_seconds(cfg))
        for record in parse_google_trends_rss(text):
            record = dict(record)
            record["region"] = country
            record["sourceUrl"] = record.get("sourceUrl") or url
            records.append(record)
    return unique_external_records(records, top_n)


def trend_keyword_templates(layer_config: dict[str, Any], source: str) -> list[str]:
    cfg = nested_external_source_config(layer_config, "hot", source)
    templates = cfg.get("keyword_templates")
    if isinstance(templates, list) and templates:
        return [clean_text(template) for template in templates if clean_text(template)]
    return [
        "{trend} edit",
        "{trend} poster",
        "{trend} photo template",
        "{trend} transition",
        "{trend} jersey edit",
    ]


def external_hot_trend_candidates(layer_config: dict[str, Any], records: list[dict[str, Any]], allocation: int) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for record in records:
        source = clean_text(record.get("source") or record.get("externalSource")) or "external_hot"
        trend = normalize_keyword(record.get("keyword") or record.get("title"))
        if not trend or is_low_semantic_external_trend(trend):
            continue
        raw_terms = [trend]
        if not ad_material_fit(trend, layer_config):
            for template in trend_keyword_templates(layer_config, source):
                raw_terms.append(template.format(trend=trend))
        for index, keyword in enumerate(raw_terms):
            blocked, blocked_hits = is_layer_keyword_blocked(keyword, layer_config)
            fit_type = keyword_fit_type(keyword, "hot", layer_config)
            if blocked or fit_type == "none":
                continue
            base_score = float(record.get("score", 0.0) or 0.0)
            candidates.append(
                make_layer_candidate(
                    keyword,
                    layer="hot",
                    allocation=allocation,
                    source=source,
                    score=base_score - index * 0.05,
                    score_details={
                        "externalSource": source,
                        "externalScore": base_score,
                        "templateRank": index,
                        "blockedHits": blocked_hits,
                    },
                    fit_type=fit_type,
                    external_source=source,
                    source_url=clean_text(record.get("sourceUrl")),
                    raw_trend=record,
                )
            )
    return candidates


def countries_for_nager(layer_config: dict[str, Any]) -> list[str]:
    cfg = nested_external_source_config(layer_config, "preheat", "nager_date")
    countries = [clean_text(country).upper() for country in cfg.get("countries", []) if clean_text(country)]
    return countries or ["US"]


def collect_nager_date_events(layer_config: dict[str, Any], today: date, fetch_json_fn: Any = fetch_url_json) -> list[dict[str, Any]]:
    cfg = nested_external_source_config(layer_config, "preheat", "nager_date")
    if not external_source_enabled(layer_config, "preheat", "nager_date"):
        return []
    lookahead = max(1, int(cfg.get("lookahead_days", 45) or 45))
    years = sorted({today.year, (today + timedelta(days=lookahead)).year})
    url_template = clean_text(cfg.get("url")) or DEFAULT_KEYWORD_LAYER_CONFIG["external_sources"]["preheat"]["nager_date"]["url"]
    events: list[dict[str, Any]] = []
    for country in countries_for_nager(layer_config):
        for year in years:
            url = url_template.format(year=year, country=quote(country))
            payload = fetch_json_fn(url, timeout_seconds(cfg))
            holidays = payload if isinstance(payload, list) else []
            for holiday in holidays:
                if not isinstance(holiday, dict):
                    continue
                name = clean_text(holiday.get("name") or holiday.get("localName"))
                event_date = parse_layer_event_date(holiday.get("date"))
                if not name or event_date is None:
                    continue
                events.append(
                    {
                        "source": "nager_date",
                        "externalSource": "nager_date",
                        "name": name,
                        "type": "holiday",
                        "date": event_date.isoformat(),
                        "countries": [country],
                        "sourceUrl": url,
                        "rawEvent": holiday,
                    }
                )
    return events


def collect_thesportsdb_events(layer_config: dict[str, Any], fetch_json_fn: Any = fetch_url_json) -> list[dict[str, Any]]:
    cfg = nested_external_source_config(layer_config, "preheat", "thesportsdb")
    if not external_source_enabled(layer_config, "preheat", "thesportsdb"):
        return []
    api_key = clean_text(os.environ.get("THESPORTSDB_API_KEY") or cfg.get("api_key") or "3")
    url_template = clean_text(cfg.get("url")) or DEFAULT_KEYWORD_LAYER_CONFIG["external_sources"]["preheat"]["thesportsdb"]["url"]
    events: list[dict[str, Any]] = []
    for league in cfg.get("leagues", []) or []:
        if not isinstance(league, dict):
            continue
        league_id = clean_text(league.get("id"))
        if not league_id:
            continue
        query = urlencode({"id": league_id})
        url = url_template.format(api_key=quote(api_key), query=query, league_id=quote(league_id))
        payload = fetch_json_fn(url, timeout_seconds(cfg))
        raw_events = payload.get("events") if isinstance(payload, dict) else []
        for raw_event in raw_events or []:
            if not isinstance(raw_event, dict):
                continue
            name = clean_text(raw_event.get("strEvent") or raw_event.get("strFilename") or raw_event.get("strLeague"))
            event_date = parse_layer_event_date(raw_event.get("dateEvent"))
            if not name or event_date is None:
                continue
            events.append(
                {
                    "source": "thesportsdb",
                    "externalSource": "thesportsdb",
                    "name": name,
                    "type": "sports",
                    "date": event_date.isoformat(),
                    "countries": [],
                    "sport": clean_text(raw_event.get("strSport") or league.get("sport")),
                    "league": clean_text(raw_event.get("strLeague") or league.get("name")),
                    "sourceUrl": url,
                    "rawEvent": raw_event,
                }
            )
    return events


def normalize_external_event(raw: dict[str, Any], source: str, source_url: str = "") -> dict[str, Any] | None:
    name = clean_text(raw.get("name") or raw.get("event") or raw.get("title"))
    event_date = parse_layer_event_date(raw.get("date") or raw.get("eventDate") or raw.get("startDate"))
    if not name or event_date is None:
        return None
    countries = raw.get("countries") if isinstance(raw.get("countries"), list) else []
    return {
        "source": source,
        "externalSource": source,
        "name": name,
        "type": clean_text(raw.get("type") or ("esports" if source == "liquipedia" else "event")),
        "date": event_date.isoformat(),
        "countries": [clean_text(country) for country in countries if clean_text(country)],
        "sport": clean_text(raw.get("sport")),
        "game": clean_text(raw.get("game")),
        "league": clean_text(raw.get("league")),
        "sourceUrl": clean_text(raw.get("sourceUrl") or source_url),
        "rawEvent": raw,
    }


def collect_liquipedia_events(layer_config: dict[str, Any], fetch_text_fn: Any = fetch_url_text) -> list[dict[str, Any]]:
    cfg = nested_external_source_config(layer_config, "preheat", "liquipedia")
    if not external_source_enabled(layer_config, "preheat", "liquipedia"):
        return []
    events: list[dict[str, Any]] = []
    for raw_event in cfg.get("events", []) or []:
        if isinstance(raw_event, dict):
            normalized = normalize_external_event(raw_event, "liquipedia")
            if normalized:
                events.append(normalized)
    calendar_path = resolve_repo_path(clean_text(cfg.get("calendar_path")), BASE_DIR / clean_text(cfg.get("calendar_path", "")))
    if calendar_path.exists():
        payload = read_json(calendar_path, [])
        for raw_event in payload if isinstance(payload, list) else []:
            if isinstance(raw_event, dict):
                normalized = normalize_external_event(raw_event, "liquipedia", source_url=clean_text(raw_event.get("sourceUrl")))
                if normalized:
                    events.append(normalized)
    for url in [clean_text(url) for url in cfg.get("urls", []) if clean_text(url)]:
        text = fetch_text_fn(url, timeout_seconds(cfg))
        for match in re.finditer(r"([A-Z][A-Za-z0-9: .'-]{4,80}).{0,120}?(\d{4}-\d{2}-\d{2})", text or "", flags=re.DOTALL):
            normalized = normalize_external_event(
                {"name": html.unescape(match.group(1)), "date": match.group(2), "type": "esports"},
                "liquipedia",
                source_url=url,
            )
            if normalized:
                events.append(normalized)
    return events


def event_keywords(event: dict[str, Any]) -> list[str]:
    name = normalize_keyword(event.get("name"))
    if not name:
        return []
    event_type = clean_text(event.get("type")).lower()
    sport = normalize_keyword(event.get("sport") or event.get("league"))
    game = normalize_keyword(event.get("game"))
    if "esport" in event_type or game:
        base = name
        return unique_strings(
            [
                f"{base} esports poster",
                f"{base} team edit",
                f"{base} championship edit",
                f"{game} team edit" if game else "",
                f"{game} poster edit" if game else "",
            ]
        )
    if "sport" in event_type or sport:
        return unique_strings(
            [
                f"{name} poster edit",
                f"{name} jersey edit",
                f"{name} celebration edit",
                f"{name} match entrance edit",
                f"{name} card edit",
            ]
        )
    return unique_strings(
        [
            f"{name} photo template",
            f"{name} photo slideshow",
            f"{name} portrait edit",
            f"{name} family photo",
            f"{name} photo to video ai",
        ]
    )


def preheat_candidates_from_events(
    layer_config: dict[str, Any],
    events: list[dict[str, Any]],
    today: date,
    allocation: int,
    *,
    source_default: str,
) -> list[dict[str, Any]]:
    cfg = layer_config.get("preheat") if isinstance(layer_config.get("preheat"), dict) else {}
    window_days = int(cfg.get("event_window_days", 30) or 30)
    boost_days = int(cfg.get("boost_window_days", 14) or 14)
    active_after_days = int(cfg.get("active_after_days", 2) or 2)
    countries = enabled_country_codes(layer_config)
    candidates: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        event_date = parse_layer_event_date(event.get("date"))
        if event_date is None:
            continue
        event_countries = {str(country).strip() for country in event.get("countries", []) if str(country).strip()}
        if countries and event_countries and not (countries & event_countries):
            continue
        days_to_event = (event_date - today).days
        if days_to_event > window_days or days_to_event < -active_after_days:
            continue
        timing_score = 45.0
        if days_to_event >= 0:
            timing_score += max(0.0, window_days - days_to_event) * 1.2
            if days_to_event <= boost_days:
                timing_score += 20.0
        else:
            timing_score += max(0.0, active_after_days + days_to_event) * 4.0
        source = clean_text(event.get("source") or event.get("externalSource") or source_default)
        event_context = {
            "name": clean_text(event.get("name")),
            "type": clean_text(event.get("type")),
            "date": event_date.isoformat(),
            "daysToEvent": days_to_event,
            "countries": sorted(event_countries),
            "source": source,
            "sourceUrl": clean_text(event.get("sourceUrl")),
            "sport": clean_text(event.get("sport")),
            "game": clean_text(event.get("game")),
            "league": clean_text(event.get("league")),
        }
        for index, keyword in enumerate(event.get("keywords", []) or event_keywords(event)):
            blocked, blocked_hits = is_layer_keyword_blocked(str(keyword), layer_config)
            fit_type = keyword_fit_type(str(keyword), "preheat", layer_config)
            if blocked or fit_type == "none":
                continue
            candidates.append(
                make_layer_candidate(
                    str(keyword),
                    layer="preheat",
                    allocation=allocation,
                    source=source,
                    score=timing_score - index * 0.05,
                    score_details={
                        "timingScore": timing_score,
                        "daysToEvent": days_to_event,
                        "blockedHits": blocked_hits,
                        "externalSource": source if source != "event_calendar" else "",
                    },
                    fit_type=fit_type,
                    event_context=event_context,
                    external_source=source if source != "event_calendar" else "",
                    source_url=clean_text(event.get("sourceUrl")),
                    raw_trend=event.get("rawEvent") if isinstance(event.get("rawEvent"), dict) else event,
                )
            )
    return candidates


def collect_external_keyword_sources(
    layer_config: dict[str, Any],
    *,
    root: Path,
    run_dir: Path,
    today: date,
    enabled: bool,
    fetch_text_fn: Any = fetch_url_text,
    fetch_json_fn: Any = fetch_url_json,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    hot_report: dict[str, Any] = {"enabled": bool(enabled), "records": [], "errors": []}
    preheat_report: dict[str, Any] = {"enabled": bool(enabled), "events": [], "errors": []}
    if not enabled or external_sources_config(layer_config).get("enabled") is False:
        write_json(run_dir / "02_external_hot_trends.json", hot_report)
        write_json(run_dir / "02_external_preheat_events.json", preheat_report)
        return [], []
    hot_collectors = [
        ("tiktok_creative_center", lambda: collect_tiktok_creative_center_trends(layer_config, fetch_text_fn)),
        ("google_trends", lambda: collect_google_trends(layer_config, fetch_text_fn)),
    ]
    for source, collector in hot_collectors:
        if not external_source_enabled(layer_config, "hot", source):
            continue
        try:
            hot_report["records"].extend(collector())
        except Exception as exc:
            hot_report["errors"].append({"source": source, "error": clean_text(exc, max_len=240)})
    if external_source_enabled(layer_config, "hot", "recent_discovery_history"):
        cfg = nested_external_source_config(layer_config, "hot", "recent_discovery_history")
        hot_report["records"].extend(
            history_hot_records(
                layer_config,
                root,
                hours=int(cfg.get("lookback_hours", 72) or 72),
                max_terms=int(cfg.get("max_terms", 20) or 20),
            )
        )
    preheat_collectors = [
        ("nager_date", lambda: collect_nager_date_events(layer_config, today, fetch_json_fn)),
        ("thesportsdb", lambda: collect_thesportsdb_events(layer_config, fetch_json_fn)),
        ("liquipedia", lambda: collect_liquipedia_events(layer_config, fetch_text_fn)),
    ]
    for source, collector in preheat_collectors:
        if not external_source_enabled(layer_config, "preheat", source):
            continue
        try:
            preheat_report["events"].extend(collector())
        except Exception as exc:
            preheat_report["errors"].append({"source": source, "error": clean_text(exc, max_len=240)})
    hot_report["records"] = unique_external_records(hot_report["records"], 100)
    write_json(run_dir / "02_external_hot_trends.json", hot_report)
    write_json(run_dir / "02_external_preheat_events.json", preheat_report)
    return list(hot_report["records"]), list(preheat_report["events"])


def make_layer_candidate(
    keyword: str,
    *,
    layer: str,
    allocation: int,
    source: str,
    score: float,
    score_details: dict[str, Any],
    fit_type: str,
    event_context: dict[str, Any] | None = None,
    external_source: str = "",
    source_url: str = "",
    raw_trend: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = normalize_keyword(keyword)
    product_context = product_context_for_keyword(normalized)
    item = {
        "keyword": normalized,
        "allocation": allocation,
        "sources": [source],
        "source": source,
        "productContexts": [product_context] if product_context else [],
        "isMainPipelineQuery": False,
        "layer": layer,
        "score": round(float(score), 4),
        "scoreDetails": score_details,
        "fitType": fit_type,
    }
    if event_context:
        item["eventContext"] = event_context
    if clean_text(external_source):
        item["externalSource"] = clean_text(external_source)
    if clean_text(source_url):
        item["sourceUrl"] = clean_text(source_url, max_len=600)
    if raw_trend:
        item["rawTrend"] = raw_trend
    return item


def merge_layer_candidate(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    if float(incoming.get("score", 0.0) or 0.0) > float(existing.get("score", 0.0) or 0.0):
        primary = dict(incoming)
        secondary = existing
    else:
        primary = dict(existing)
        secondary = incoming
    primary["sources"] = unique_strings(list(existing.get("sources") or []) + list(incoming.get("sources") or []))
    primary["externalSources"] = unique_strings(
        [
            existing.get("externalSource"),
            incoming.get("externalSource"),
            *(existing.get("externalSources") or []),
            *(incoming.get("externalSources") or []),
        ]
    )
    if not primary["externalSources"]:
        primary.pop("externalSources", None)
    if not primary.get("sourceUrl") and secondary.get("sourceUrl"):
        primary["sourceUrl"] = secondary["sourceUrl"]
    if not primary.get("rawTrend") and isinstance(secondary.get("rawTrend"), dict):
        primary["rawTrend"] = secondary["rawTrend"]
    contexts = []
    for context in list(existing.get("productContexts") or []) + list(incoming.get("productContexts") or []):
        if isinstance(context, dict) and context not in contexts:
            contexts.append(context)
    primary["productContexts"] = contexts
    if existing.get("fitType") != incoming.get("fitType") and "none" not in {existing.get("fitType"), incoming.get("fitType")}:
        primary["fitType"] = "both"
    primary.setdefault("source", primary["sources"][0] if primary["sources"] else secondary.get("source", "layered"))
    return primary


def select_layer_candidates(candidates: list[dict[str, Any]], target_count: int) -> list[dict[str, Any]]:
    by_keyword: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        keyword = normalize_keyword(candidate.get("keyword"))
        if not keyword:
            continue
        candidate = dict(candidate)
        candidate["keyword"] = keyword
        if keyword in by_keyword:
            by_keyword[keyword] = merge_layer_candidate(by_keyword[keyword], candidate)
        else:
            by_keyword[keyword] = candidate
    ranked = sorted(
        by_keyword.values(),
        key=lambda item: (
            float(item.get("score", 0.0) or 0.0),
            1 if item.get("fitType") == "both" else 0,
            -len(str(item.get("keyword") or "")),
        ),
        reverse=True,
    )
    return ranked[:target_count]


def select_preheat_layer_candidates(layer_config: dict[str, Any], candidates: list[dict[str, Any]], target_count: int) -> list[dict[str, Any]]:
    cfg = layer_config.get("preheat") if isinstance(layer_config.get("preheat"), dict) else {}
    max_per_event = max(1, int(cfg.get("max_terms_per_event", 3) or 3))
    ranked = select_layer_candidates(candidates, len(candidates))
    selected: list[dict[str, Any]] = []
    event_counts: dict[str, int] = {}
    deferred: list[dict[str, Any]] = []
    for candidate in ranked:
        context = candidate.get("eventContext") if isinstance(candidate.get("eventContext"), dict) else {}
        event_key = clean_text(context.get("name")) or clean_text(candidate.get("source")) or "fallback"
        if event_counts.get(event_key, 0) >= max_per_event:
            deferred.append(candidate)
            continue
        event_counts[event_key] = event_counts.get(event_key, 0) + 1
        selected.append(candidate)
        if len(selected) >= target_count:
            return selected
    for candidate in deferred:
        if len(selected) >= target_count:
            break
        selected.append(candidate)
    return selected[:target_count]


def evergreen_layer_candidates(layer_config: dict[str, Any], rows: list[dict[str, Any]], allocation: int) -> list[dict[str, Any]]:
    cfg = layer_config.get("evergreen") if isinstance(layer_config.get("evergreen"), dict) else {}
    raw_candidates = list(cfg.get("fallback_keywords") or [])
    raw_candidates.extend(cfg.get("candidate_keywords") or [])
    for terms in PRODUCT_SIGNALS.values():
        raw_candidates.extend(terms)
    candidates: list[dict[str, Any]] = []
    for index, keyword in enumerate(raw_candidates):
        blocked, blocked_hits = is_layer_keyword_blocked(str(keyword), layer_config)
        fit_type = keyword_fit_type(str(keyword), "evergreen", layer_config)
        if blocked or fit_type == "none":
            continue
        feedback_score, feedback_hits = keyword_feedback_score(str(keyword), rows)
        base = 50.0 - index * 0.02
        candidates.append(
            make_layer_candidate(
                str(keyword),
                layer="evergreen",
                allocation=allocation,
                source="product_doc_feedback",
                score=base + feedback_score,
                score_details={
                    "base": base,
                    "feedbackScore": feedback_score,
                    "feedbackHits": feedback_hits,
                    "blockedHits": blocked_hits,
                },
                fit_type=fit_type,
            )
        )
    return candidates


def iter_recent_discovery_artifact_items(root: Path, hours: int, max_files: int = 40) -> list[dict[str, Any]]:
    runs_dir = root / "runs"
    if not runs_dir.exists():
        return []
    cutoff = datetime.now().timestamp() - max(1, hours) * 3600
    paths: list[Path] = []
    for name in ["10_approved.json", "08_filtered.json", "07_candidates.json"]:
        paths.extend(path for path in runs_dir.glob(f"*/{name}") if path.exists())
    fresh = []
    for path in paths:
        try:
            if path.stat().st_mtime >= cutoff:
                fresh.append(path)
        except OSError:
            continue
    fresh = sorted(fresh, key=lambda path: path.stat().st_mtime, reverse=True)[:max_files]
    items: list[dict[str, Any]] = []
    for path in fresh:
        payload = read_json(path, [])
        if isinstance(payload, list):
            items.extend(item for item in payload if isinstance(item, dict))
    return items


def discovery_item_text(item: dict[str, Any]) -> str:
    values = [
        item.get("text"),
        item.get("title"),
        item.get("description"),
        item.get("sourceQuery"),
        item.get("searchQuery"),
        " ".join(str(tag) for tag in item.get("hashtags", []) if tag),
    ]
    return " ".join(clean_text(value, max_len=800) for value in values if value).lower()


def discovery_history_terms_from_item(item: dict[str, Any], layer_config: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    for key in ["sourceQuery", "searchQuery"]:
        keyword = normalize_keyword(item.get(key))
        if keyword and ad_material_fit(keyword, layer_config):
            terms.append(keyword)
    for raw_tag in item.get("hashtags", []) or []:
        tag = normalize_keyword(raw_tag)
        if len(tag.split()) >= 2 and ad_material_fit(tag, layer_config):
            terms.append(tag)
    haystack = discovery_item_text(item)
    normalized_haystack = normalize_keyword(haystack)
    title_terms = extract_hashtag_like_terms(haystack)
    for term in title_terms:
        if ad_material_fit(term, layer_config):
            terms.append(term)
    for signal in (layer_config.get("hot") or {}).get("ad_material_keywords") or DEFAULT_KEYWORD_LAYER_CONFIG["hot"]["ad_material_keywords"]:
        signal_key = normalize_keyword(signal)
        if not signal_key or signal_key not in normalized_haystack:
            continue
        for base in [normalize_keyword(item.get("sourceQuery")), normalize_keyword(item.get("searchQuery"))]:
            if base and signal_key not in base:
                terms.append(f"{base} {signal_key}")
        if not terms and signal_key:
            terms.append(f"{signal_key} edit")
    return unique_strings(terms)


def history_hot_records(layer_config: dict[str, Any], root: Path, *, hours: int, max_terms: int) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    urls: dict[str, str] = {}
    for item in iter_recent_discovery_artifact_items(root, hours):
        url = clean_text(item.get("hotspotUrl") or item.get("webVideoUrl") or item.get("url"))
        for keyword in discovery_history_terms_from_item(item, layer_config):
            counts[keyword] = counts.get(keyword, 0) + 1
            if url and keyword not in urls:
                urls[keyword] = url
    records: list[dict[str, Any]] = []
    for keyword, count in sorted(counts.items(), key=lambda pair: pair[1], reverse=True)[:max_terms]:
        records.append(
            source_record(
                source="recent_discovery_history",
                title=keyword,
                source_url=urls.get(keyword, ""),
                score=70.0 + count,
                raw={"historyHits": count, "lookbackHours": hours},
            )
        )
    return records


def history_hot_layer_candidates(layer_config: dict[str, Any], root: Path, allocation: int) -> list[dict[str, Any]]:
    cfg = layer_config.get("hot") if isinstance(layer_config.get("hot"), dict) else {}
    external_cfg = nested_external_source_config(layer_config, "hot", "recent_discovery_history")
    hours = int(external_cfg.get("lookback_hours", cfg.get("history_lookback_hours", 72)) or 72)
    max_terms = int(external_cfg.get("max_terms", cfg.get("max_history_terms", 20)) or 20)
    candidates: list[dict[str, Any]] = []
    for record in history_hot_records(layer_config, root, hours=hours, max_terms=max_terms):
        keyword = normalize_keyword(record.get("keyword"))
        count = int((record.get("rawTrend") or {}).get("historyHits") or 0)
        blocked, blocked_hits = is_layer_keyword_blocked(keyword, layer_config)
        fit_type = keyword_fit_type(keyword, "hot", layer_config)
        if blocked or fit_type == "none":
            continue
        candidates.append(
            make_layer_candidate(
                keyword,
                layer="hot",
                allocation=allocation,
                source="recent_discovery_history",
                score=65.0 + count,
                score_details={"historyHits": count, "blockedHits": blocked_hits, "externalSource": "recent_discovery_history"},
                fit_type=fit_type,
                external_source="recent_discovery_history",
                source_url=clean_text(record.get("sourceUrl")),
                raw_trend=record,
            )
        )
    return candidates


def hot_layer_candidates(
    layer_config: dict[str, Any],
    root: Path,
    allocation: int,
    external_hot_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    cfg = layer_config.get("hot") if isinstance(layer_config.get("hot"), dict) else {}
    raw_keywords = list(cfg.get("event_keywords") or [])
    raw_keywords.extend(cfg.get("fallback_keywords") or [])
    candidates: list[dict[str, Any]] = []
    for index, keyword in enumerate(raw_keywords):
        blocked, blocked_hits = is_layer_keyword_blocked(str(keyword), layer_config)
        fit_type = keyword_fit_type(str(keyword), "hot", layer_config)
        if blocked or fit_type == "none":
            continue
        candidates.append(
            make_layer_candidate(
                str(keyword),
                layer="hot",
                allocation=allocation,
                source="hot_event_seed",
                score=85.0 - index * 0.05,
                score_details={"eventSeedRank": index + 1, "blockedHits": blocked_hits},
                fit_type=fit_type,
            )
        )
    if external_hot_records is not None:
        candidates.extend(external_hot_trend_candidates(layer_config, external_hot_records, allocation))
    else:
        candidates.extend(history_hot_layer_candidates(layer_config, root, allocation))
    return candidates


def preheat_layer_candidates(
    layer_config: dict[str, Any],
    today: date,
    allocation: int,
    external_preheat_events: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    cfg = layer_config.get("preheat") if isinstance(layer_config.get("preheat"), dict) else {}
    window_days = int(cfg.get("event_window_days", 30) or 30)
    boost_days = int(cfg.get("boost_window_days", 14) or 14)
    active_after_days = int(cfg.get("active_after_days", 2) or 2)
    countries = enabled_country_codes(layer_config)
    candidates: list[dict[str, Any]] = []
    local_events = [event for event in cfg.get("events") or [] if isinstance(event, dict)]
    candidates.extend(preheat_candidates_from_events(layer_config, local_events, today, allocation, source_default="event_calendar"))
    if external_preheat_events:
        candidates.extend(preheat_candidates_from_events(layer_config, external_preheat_events, today, allocation, source_default="external_preheat"))
    for index, keyword in enumerate(cfg.get("fallback_keywords") or []):
        blocked, blocked_hits = is_layer_keyword_blocked(str(keyword), layer_config)
        fit_type = keyword_fit_type(str(keyword), "preheat", layer_config)
        if blocked or fit_type == "none":
            continue
        candidates.append(
            make_layer_candidate(
                str(keyword),
                layer="preheat",
                allocation=allocation,
                source="preheat_fallback",
                score=40.0 - index * 0.05,
                score_details={"fallbackRank": index + 1, "blockedHits": blocked_hits},
                fit_type=fit_type,
            )
        )
    return candidates


def build_layered_candidate_pool(
    layer_config: dict[str, Any],
    *,
    feedback_rows: list[dict[str, Any]] | None = None,
    today: date | None = None,
    root: Path | None = None,
    external_hot_records: list[dict[str, Any]] | None = None,
    external_preheat_events: list[dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    feedback_rows = feedback_rows or []
    today = today or date.today()
    root = root or RUN_ROOT
    allocations = keyword_layer_allocations(layer_config)
    return {
        "evergreen": evergreen_layer_candidates(layer_config, feedback_rows, allocations["evergreen"]),
        "hot": hot_layer_candidates(layer_config, root, allocations["hot"], external_hot_records=external_hot_records),
        "preheat": preheat_layer_candidates(layer_config, today, allocations["preheat"], external_preheat_events=external_preheat_events),
    }


def select_layered_search_plan(layer_config: dict[str, Any], candidates_by_layer: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    counts = keyword_layer_counts(layer_config)
    allocations = keyword_layer_allocations(layer_config)
    plan: list[dict[str, Any]] = []
    selected_keywords: set[str] = set()
    for layer in KEYWORD_LAYERS:
        selected: list[dict[str, Any]] = []
        layer_selected = (
            select_preheat_layer_candidates(layer_config, candidates_by_layer.get(layer, []), counts[layer])
            if layer == "preheat"
            else select_layer_candidates(candidates_by_layer.get(layer, []), counts[layer])
        )
        for candidate in layer_selected:
            key = normalize_keyword(candidate.get("keyword"))
            if not key or key in selected_keywords:
                continue
            selected_keywords.add(key)
            selected.append(candidate)
        if len(selected) < counts[layer]:
            cfg = layer_config.get(layer) if isinstance(layer_config.get(layer), dict) else {}
            for keyword in cfg.get("fallback_keywords") or []:
                key = normalize_keyword(keyword)
                if not key or key in selected_keywords:
                    continue
                blocked, _blocked_hits = is_layer_keyword_blocked(key, layer_config)
                fit_type = keyword_fit_type(key, layer, layer_config)
                if blocked or fit_type == "none":
                    continue
                selected_keywords.add(key)
                selected.append(
                    make_layer_candidate(
                        key,
                        layer=layer,
                        allocation=allocations[layer],
                        source=f"{layer}_fallback",
                        score=1.0,
                        score_details={"fallbackFill": True},
                        fit_type=fit_type,
                    )
                )
                if len(selected) >= counts[layer]:
                    break
        plan.extend(selected[: counts[layer]])
    return plan


def build_layered_search_plan(
    layer_config: dict[str, Any],
    *,
    feedback_rows: list[dict[str, Any]] | None = None,
    today: date | None = None,
    root: Path | None = None,
    external_hot_records: list[dict[str, Any]] | None = None,
    external_preheat_events: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    candidates_by_layer = build_layered_candidate_pool(
        layer_config,
        feedback_rows=feedback_rows,
        today=today,
        root=root,
        external_hot_records=external_hot_records,
        external_preheat_events=external_preheat_events,
    )
    return select_layered_search_plan(layer_config, candidates_by_layer)


def keyword_layer_summary(search_plan: list[dict[str, Any]]) -> dict[str, Any]:
    layers: dict[str, dict[str, Any]] = {
        layer: {"plannedTerms": 0, "targetAllocation": 0, "keywords": []}
        for layer in KEYWORD_LAYERS
    }
    unknown = {"plannedTerms": 0, "targetAllocation": 0, "keywords": []}
    for entry in search_plan:
        layer = clean_text(entry.get("layer")) or "legacy"
        bucket = layers.setdefault(layer, {"plannedTerms": 0, "targetAllocation": 0, "keywords": []}) if layer in layers else unknown
        bucket["plannedTerms"] += 1
        bucket["targetAllocation"] += int(entry.get("allocation") or 0)
        bucket["keywords"].append(clean_text(entry.get("keyword")))
    summary = {layer: payload for layer, payload in layers.items() if payload["plannedTerms"]}
    if unknown["plannedTerms"]:
        summary["legacy"] = unknown
    return {
        "layers": summary,
        "targetCandidateTotal": sum(int(entry.get("allocation") or 0) for entry in search_plan),
    }


def sanitize_search_plan_entries(search_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in search_plan:
        if not isinstance(entry, dict):
            continue
        keyword = normalize_keyword(entry.get("keyword"))
        if not keyword or keyword in seen:
            continue
        layer = clean_text(entry.get("layer"))
        if layer == "hot" and is_low_semantic_external_trend(keyword):
            continue
        item = dict(entry)
        item["keyword"] = keyword
        cleaned.append(item)
        seen.add(keyword)
    return cleaned


def feedback_tuning_config(layer_config: dict[str, Any]) -> dict[str, Any]:
    configured = layer_config.get("feedback_tuning") if isinstance(layer_config.get("feedback_tuning"), dict) else {}
    defaults = DEFAULT_KEYWORD_LAYER_CONFIG["feedback_tuning"]
    return recursive_merge(defaults, configured)


def feedback_acceptance_values(row: dict[str, Any]) -> list[str]:
    values = row.get("material_acceptance_values")
    if not isinstance(values, list) or not values:
        values = [
            row.get("material_acceptance"),
            row.get("materialAcceptance"),
            row.get("acceptance"),
        ]
    normalized = [normalize_acceptance(value) for value in values if value not in (None, "")]
    return [value for value in normalized if value]


def feedback_signal(row: dict[str, Any]) -> dict[str, Any]:
    values = feedback_acceptance_values(row)
    if "\u9ad8" in values:
        return {"score": 2.0, "high": 1, "usable": 0, "useless": 0, "values": values}
    if "\u4e2d" in values:
        return {"score": 0.5, "high": 0, "usable": 1, "useless": 0, "values": values}
    if any(value in {"\u4f4e", "\u5426\u51b3"} for value in values):
        return {"score": -1.5, "high": 0, "usable": 0, "useless": 1, "values": values}
    return {"score": 0.0, "high": 0, "usable": 0, "useless": 0, "values": values}


def discovery_url_keys(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    canonical = canonical_tiktok_url(text)
    normalized = (canonical or text).split("?")[0].split("#")[0].rstrip("/").lower()
    keys = [normalized] if normalized else []
    match = re.search(r"/video/(\d+)", normalized) or re.search(r"\b(\d{12,})\b", normalized)
    if match:
        keys.append(f"video:{match.group(1)}")
    return list(dict.fromkeys(keys))


def discovery_item_url_keys(item: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for field in ["hotspotUrl", "webVideoUrl", "url", "shareUrl", "id"]:
        keys.extend(discovery_url_keys(item.get(field)))
    video_meta = item.get("videoMeta")
    if isinstance(video_meta, dict):
        keys.extend(discovery_url_keys(video_meta.get("webVideoUrl")))
    return list(dict.fromkeys(keys))


def discovery_keyword_refs_from_item(item: dict[str, Any]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []

    def add_ref(keyword: Any, layer: Any = "", fit_type: Any = "", source: Any = "") -> None:
        normalized = normalize_keyword(keyword)
        if not normalized:
            return
        ref = {
            "keyword": normalized,
            "layer": clean_text(layer),
            "fitType": clean_text(fit_type),
            "source": clean_text(source),
        }
        if ref not in refs:
            refs.append(ref)

    tkd = item.get("tiktokKeywordDiscovery") if isinstance(item.get("tiktokKeywordDiscovery"), dict) else {}
    item_layer = clean_text(item.get("tiktokKeywordDiscoveryLayer"))
    item_fit_type = clean_text(item.get("tiktokKeywordDiscoveryFitType"))
    for entry in tkd.get("planEntries") or []:
        if isinstance(entry, dict):
            add_ref(entry.get("keyword"), entry.get("layer") or item_layer, entry.get("fitType") or item_fit_type, entry.get("source"))
    for keyword in tkd.get("sourceQueries") or []:
        add_ref(keyword, item_layer, item_fit_type, "sourceQueries")
    for field in ["sourceQuery", "searchQuery"]:
        add_ref(item.get(field), item_layer, item_fit_type, field)
    return refs


def build_discovery_feedback_index(root: Path, days: int) -> dict[str, list[dict[str, str]]]:
    index: dict[str, list[dict[str, str]]] = {}
    for item in iter_recent_discovery_artifact_items(root, max(1, days) * 24, max_files=240):
        refs = discovery_keyword_refs_from_item(item)
        if not refs:
            continue
        for key in discovery_item_url_keys(item):
            bucket = index.setdefault(key, [])
            for ref in refs:
                if ref not in bucket:
                    bucket.append(ref)
    return index


def feedback_row_url(row: dict[str, Any]) -> str:
    for field in ["url", "hotspotUrl", "webVideoUrl", "shareUrl"]:
        value = clean_text(row.get(field))
        if value:
            return value
    return ""


def feedback_keyword_tokens(keyword: str) -> list[str]:
    return [
        token
        for token in normalize_keyword(keyword).split()
        if len(token) >= 4 and token not in {"photo", "video", "edit", "template", "with", "from"}
    ]


def feedback_row_keyword_matches(row: dict[str, Any], keyword: str) -> bool:
    normalized = normalize_keyword(keyword)
    if not normalized:
        return False
    haystack = normalize_keyword(feedback_row_text(row))
    if not haystack:
        return False
    if normalized in haystack:
        return True
    tokens = feedback_keyword_tokens(normalized)
    if not tokens:
        return False
    return sum(1 for token in tokens if token in haystack) >= max(1, min(2, len(tokens)))


def empty_keyword_feedback_stat(keyword: str, layer: str = "") -> dict[str, Any]:
    return {
        "keyword": keyword,
        "layer": layer,
        "feedbackCount": 0,
        "highQualityCount": 0,
        "usableCount": 0,
        "uselessCount": 0,
        "score": 0.0,
        "matchSources": [],
    }


def update_keyword_feedback_stat(stat: dict[str, Any], row: dict[str, Any], *, match_source: str) -> None:
    signal = feedback_signal(row)
    stat["feedbackCount"] = int(stat.get("feedbackCount", 0) or 0) + 1
    stat["highQualityCount"] = int(stat.get("highQualityCount", 0) or 0) + int(signal["high"])
    stat["usableCount"] = int(stat.get("usableCount", 0) or 0) + int(signal["usable"])
    stat["uselessCount"] = int(stat.get("uselessCount", 0) or 0) + int(signal["useless"])
    stat["score"] = round(float(stat.get("score", 0.0) or 0.0) + float(signal["score"]), 4)
    sources = stat.setdefault("matchSources", [])
    if match_source not in sources:
        sources.append(match_source)


def discovery_keyword_performance(
    search_plan: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    *,
    root: Path,
    today: date,
    days: int,
) -> dict[str, Any]:
    stats: dict[str, dict[str, Any]] = {}
    keyword_by_key: dict[str, str] = {}
    layer_by_key: dict[str, str] = {}
    for entry in search_plan:
        keyword = normalize_keyword(entry.get("keyword"))
        if not keyword:
            continue
        key = normalize_keyword(keyword)
        keyword_by_key[key] = keyword
        layer_by_key[key] = clean_text(entry.get("layer"))
        stats[keyword] = empty_keyword_feedback_stat(keyword, layer_by_key[key])

    index = build_discovery_feedback_index(root, days)
    matched_rows = 0
    unmatched_rows = 0
    matched_feedback_events = 0
    for row in rows:
        platform = row_platform(row)
        if platform and platform != "tiktok":
            continue
        matched_keys: set[str] = set()
        for key in discovery_url_keys(feedback_row_url(row)):
            for ref in index.get(key, []):
                keyword_key = normalize_keyword(ref.get("keyword"))
                if keyword_key in keyword_by_key:
                    matched_keys.add(keyword_key)
        match_source = "url"
        if not matched_keys:
            match_source = "text"
            for keyword_key in keyword_by_key:
                if feedback_row_keyword_matches(row, keyword_key):
                    matched_keys.add(keyword_key)
        if not matched_keys:
            unmatched_rows += 1
            continue
        matched_rows += 1
        matched_feedback_events += len(matched_keys)
        for keyword_key in sorted(matched_keys):
            update_keyword_feedback_stat(stats[keyword_by_key[keyword_key]], row, match_source=match_source)
    return {
        "generatedAt": now_iso(),
        "windowDays": days,
        "windowEnd": today.isoformat(),
        "sourceIndexSize": len(index),
        "matchedFeedbackRows": matched_rows,
        "unmatchedFeedbackRows": unmatched_rows,
        "matchedFeedbackEvents": matched_feedback_events,
        "keywords": stats,
    }


def keyword_text_feedback_stat(keyword: str, layer: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    stat = empty_keyword_feedback_stat(keyword, layer)
    for row in rows:
        platform = row_platform(row)
        if platform and platform != "tiktok":
            continue
        if feedback_row_keyword_matches(row, keyword):
            update_keyword_feedback_stat(stat, row, match_source="candidate_text")
    return stat


def allocate_feedback_layer(
    entries: list[dict[str, Any]],
    stats: dict[str, dict[str, Any]],
    *,
    total: int,
    base_allocation: int,
    min_multiplier: float,
    max_multiplier: float,
) -> dict[str, int]:
    keywords = [normalize_keyword(entry.get("keyword")) for entry in entries if normalize_keyword(entry.get("keyword"))]
    if not keywords:
        return {}
    if len(keywords) == 1:
        return {keywords[0]: max(1, total)}
    min_alloc = max(1, int(base_allocation * min_multiplier))
    max_alloc = max(min_alloc, int(round(base_allocation * max_multiplier)))
    if min_alloc * len(keywords) > total:
        min_alloc = max(1, total // len(keywords))
    if max_alloc * len(keywords) < total:
        max_alloc = max(min_alloc, (total + len(keywords) - 1) // len(keywords))
    allocations = {keyword: min_alloc for keyword in keywords}
    remaining = total - sum(allocations.values())
    weights: dict[str, float] = {}
    for keyword in keywords:
        stat = stats.get(keyword, {})
        feedback_count = int(stat.get("feedbackCount", 0) or 0)
        score = float(stat.get("score", 0.0) or 0.0)
        weights[keyword] = max(0.15, 1.0 + score) if feedback_count else 1.0
    weight_sum = sum(weights.values()) or 1.0
    fractional: list[tuple[float, float, str]] = []
    for keyword in keywords:
        raw_add = remaining * weights[keyword] / weight_sum
        add = min(max_alloc - min_alloc, max(0, int(raw_add)))
        allocations[keyword] += add
        fractional.append((raw_add - add, float(stats.get(keyword, {}).get("score", 0.0) or 0.0), keyword))
    leftover = total - sum(allocations.values())
    for _fraction, _score, keyword in sorted(fractional, reverse=True):
        if leftover <= 0:
            break
        if allocations[keyword] < max_alloc:
            allocations[keyword] += 1
            leftover -= 1
    while leftover > 0:
        progressed = False
        for keyword in sorted(keywords, key=lambda value: (float(stats.get(value, {}).get("score", 0.0) or 0.0), -allocations[value]), reverse=True):
            if allocations[keyword] >= max_alloc:
                continue
            allocations[keyword] += 1
            leftover -= 1
            progressed = True
            if leftover <= 0:
                break
        if not progressed:
            allocations[keywords[0]] += leftover
            break
    return allocations


def candidate_allowed_for_feedback_replacement(candidate: dict[str, Any], layer_config: dict[str, Any]) -> bool:
    keyword = normalize_keyword(candidate.get("keyword"))
    if not keyword:
        return False
    blocked, _hits = is_layer_keyword_blocked(keyword, layer_config)
    if blocked:
        return False
    return clean_text(candidate.get("fitType")) != "none"


def apply_discovery_feedback_tuning(
    initial_plan: list[dict[str, Any]],
    layer_config: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    root: Path,
    today: date,
    candidate_pool: dict[str, list[dict[str, Any]]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cfg = feedback_tuning_config(layer_config)
    days = max(1, int(cfg.get("lookback_days", 7) or 7))
    performance = discovery_keyword_performance(initial_plan, rows, root=root, today=today, days=days)
    stats_by_keyword = {
        normalize_keyword(keyword): value
        for keyword, value in (performance.get("keywords") or {}).items()
        if normalize_keyword(keyword)
    }
    replace_counts_raw = cfg.get("replace_counts") if isinstance(cfg.get("replace_counts"), dict) else {}
    replace_counts = {
        layer: max(0, int(replace_counts_raw.get(layer, DEFAULT_KEYWORD_LAYER_CONFIG["feedback_tuning"]["replace_counts"][layer]) or 0))
        for layer in KEYWORD_LAYERS
    }
    candidate_pool = candidate_pool or {}
    selected_by_layer: dict[str, list[dict[str, Any]]] = {layer: [] for layer in KEYWORD_LAYERS}
    for entry in initial_plan:
        layer = clean_text(entry.get("layer")) or "legacy"
        if layer in selected_by_layer:
            selected_by_layer[layer].append(copy.deepcopy(entry))
    selected_keys = {normalize_keyword(entry.get("keyword")) for entry in initial_plan if normalize_keyword(entry.get("keyword"))}
    replacements: list[dict[str, Any]] = []
    final_by_layer: dict[str, list[dict[str, Any]]] = {}
    for layer in KEYWORD_LAYERS:
        selected = selected_by_layer[layer]
        layer_feedback_count = sum(int(stats_by_keyword.get(normalize_keyword(entry.get("keyword")), {}).get("feedbackCount", 0) or 0) for entry in selected)
        replace_limit = min(replace_counts[layer], len(selected))
        if replace_limit <= 0 or layer_feedback_count < max(2, replace_limit):
            final_by_layer[layer] = selected
            continue
        weak_entries = sorted(
            [
                (float(stats_by_keyword.get(normalize_keyword(entry.get("keyword")), {}).get("score", 0.0) or 0.0), index, entry)
                for index, entry in enumerate(selected)
                if int(stats_by_keyword.get(normalize_keyword(entry.get("keyword")), {}).get("feedbackCount", 0) or 0) > 0
                and float(stats_by_keyword.get(normalize_keyword(entry.get("keyword")), {}).get("score", 0.0) or 0.0) < 0
            ],
            key=lambda item: (item[0], item[1]),
        )[:replace_limit]
        if not weak_entries:
            final_by_layer[layer] = selected
            continue
        replacement_candidates: list[tuple[float, float, int, dict[str, Any], dict[str, Any]]] = []
        seen_candidate_keys: set[str] = set()
        for index, candidate in enumerate(select_layer_candidates(candidate_pool.get(layer, []), len(candidate_pool.get(layer, [])))):
            candidate_key = normalize_keyword(candidate.get("keyword"))
            if not candidate_key or candidate_key in selected_keys or candidate_key in seen_candidate_keys:
                continue
            if clean_text(candidate.get("layer")) != layer:
                continue
            if not candidate_allowed_for_feedback_replacement(candidate, layer_config):
                continue
            candidate_stat = keyword_text_feedback_stat(candidate_key, layer, rows)
            replacement_candidates.append(
                (
                    float(candidate_stat.get("score", 0.0) or 0.0),
                    float(candidate.get("score", 0.0) or 0.0),
                    -index,
                    copy.deepcopy(candidate),
                    candidate_stat,
                )
            )
            seen_candidate_keys.add(candidate_key)
        ranked_replacements = sorted(replacement_candidates, reverse=True)
        updated = list(selected)
        used_replacement_keys: set[str] = set()
        for weak_score, weak_index, weak_entry in weak_entries:
            replacement: dict[str, Any] | None = None
            replacement_stat: dict[str, Any] | None = None
            for _candidate_feedback_score, _candidate_source_score, _candidate_index, candidate, candidate_stat in ranked_replacements:
                candidate_key = normalize_keyword(candidate.get("keyword"))
                if not candidate_key or candidate_key in used_replacement_keys:
                    continue
                if float(candidate_stat.get("score", 0.0) or 0.0) <= weak_score and float(candidate.get("score", 0.0) or 0.0) <= float(weak_entry.get("score", 0.0) or 0.0):
                    continue
                replacement = candidate
                replacement_stat = candidate_stat
                used_replacement_keys.add(candidate_key)
                break
            if replacement is None:
                continue
            removed_key = normalize_keyword(weak_entry.get("keyword"))
            added_key = normalize_keyword(replacement.get("keyword"))
            selected_keys.discard(removed_key)
            selected_keys.add(added_key)
            stats_by_keyword.setdefault(added_key, replacement_stat or empty_keyword_feedback_stat(added_key, layer))
            updated[weak_index] = replacement
            replacements.append(
                {
                    "layer": layer,
                    "removed": clean_text(weak_entry.get("keyword")),
                    "added": clean_text(replacement.get("keyword")),
                    "removedScore": weak_score,
                    "addedScore": float((replacement_stat or {}).get("score", 0.0) or 0.0),
                }
            )
        final_by_layer[layer] = updated

    min_multiplier = float(cfg.get("allocation_min_multiplier", 0.6) or 0.6)
    max_multiplier = float(cfg.get("allocation_max_multiplier", 1.4) or 1.4)
    default_allocations = keyword_layer_allocations(layer_config)
    final_plan: list[dict[str, Any]] = []
    allocation_changes: list[dict[str, Any]] = []
    for layer in KEYWORD_LAYERS:
        entries = final_by_layer.get(layer, [])
        layer_total = sum(int(entry.get("allocation") or 0) for entry in selected_by_layer.get(layer, []))
        if layer_total <= 0:
            layer_total = default_allocations[layer] * len(entries)
        allocations = allocate_feedback_layer(
            entries,
            stats_by_keyword,
            total=layer_total,
            base_allocation=default_allocations[layer],
            min_multiplier=min_multiplier,
            max_multiplier=max_multiplier,
        )
        for entry in entries:
            keyword = normalize_keyword(entry.get("keyword"))
            before = int(entry.get("allocation") or default_allocations[layer])
            after = int(allocations.get(keyword, before))
            tuned = copy.deepcopy(entry)
            tuned["allocation"] = after
            stat = stats_by_keyword.get(keyword, empty_keyword_feedback_stat(keyword, layer))
            score_details = dict(tuned.get("scoreDetails") or {})
            score_details["feedbackTuning"] = {
                "feedbackCount": int(stat.get("feedbackCount", 0) or 0),
                "highQualityCount": int(stat.get("highQualityCount", 0) or 0),
                "usableCount": int(stat.get("usableCount", 0) or 0),
                "uselessCount": int(stat.get("uselessCount", 0) or 0),
                "score": float(stat.get("score", 0.0) or 0.0),
                "allocationBefore": before,
                "allocationAfter": after,
            }
            tuned["scoreDetails"] = score_details
            final_plan.append(tuned)
            if before != after:
                allocation_changes.append({"layer": layer, "keyword": keyword, "before": before, "after": after})
    tuning_report = {
        "schemaVersion": 1,
        "enabled": bool(cfg.get("enabled", True)),
        "generatedAt": now_iso(),
        "windowDays": days,
        "matchedFeedbackCount": int(performance.get("matchedFeedbackRows", 0) or 0),
        "unmatchedFeedbackCount": int(performance.get("unmatchedFeedbackRows", 0) or 0),
        "replacements": replacements,
        "allocationChanges": allocation_changes,
        "performance": performance,
        "layerSummaryBefore": keyword_layer_summary(initial_plan)["layers"],
        "layerSummaryAfter": keyword_layer_summary(final_plan)["layers"],
    }
    return final_plan, tuning_report


def cookie_header_to_playwright_cookies(header: str, domain: str) -> list[dict[str, Any]]:
    parsed = SimpleCookie()
    parsed.load(header or "")
    cookies: list[dict[str, Any]] = []
    for name, morsel in parsed.items():
        if not name:
            continue
        cookies.append(
            {
                "name": name,
                "value": morsel.value,
                "domain": domain,
                "path": morsel["path"] or "/",
                "secure": True,
                "httpOnly": False,
            }
        )
    return cookies


def read_json_cookies(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    cookies: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        for domain in ["tiktok.com", "www.tiktok.com", ".tiktok.com"]:
            raw = payload.get(domain)
            if isinstance(raw, str) and raw.strip():
                cookies.extend(cookie_header_to_playwright_cookies(raw, domain.lstrip(".")))
        return cookies
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            domain = clean_text(item.get("domain"))
            name = clean_text(item.get("name"))
            value = clean_text(item.get("value"))
            if not name or not value or "tiktok.com" not in domain:
                continue
            cookie = {
                "name": name,
                "value": value,
                "domain": domain,
                "path": clean_text(item.get("path")) or "/",
                "secure": bool(item.get("secure", True)),
                "httpOnly": bool(item.get("httpOnly", item.get("http_only", False))),
            }
            expires = item.get("expires") or item.get("expirationDate")
            try:
                expires_int = int(float(expires))
            except (TypeError, ValueError):
                expires_int = 0
            if expires_int > 0:
                cookie["expires"] = expires_int
            cookies.append(cookie)
    return cookies


def read_netscape_cookies(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".json":
        return read_json_cookies(path)
    cookies: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        http_only = line.startswith("#HttpOnly_")
        if http_only:
            line = line[len("#HttpOnly_") :]
        parts = line.split("\t")
        if len(parts) != 7:
            continue
        domain, _include_subdomains, cookie_path, secure, expires, name, value = parts
        if "tiktok.com" not in domain or not name:
            continue
        cookie: dict[str, Any] = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": cookie_path or "/",
            "httpOnly": http_only,
            "secure": secure.upper() == "TRUE",
        }
        try:
            expiry = int(float(expires))
        except (TypeError, ValueError):
            expiry = 0
        if expiry > 0:
            cookie["expires"] = expiry
        cookies.append(cookie)
    return cookies


def canonical_tiktok_url(url: str) -> str:
    text = html.unescape(unquote(str(url or "").replace("\\/", "/"))).strip()
    if text.startswith("/@"):
        text = f"https://www.tiktok.com{text}"
    match = re.search(r"tiktok\.com/(@[^/?#\s\"']+)/video/(\d+)", text, flags=re.IGNORECASE)
    if not match:
        return ""
    return f"https://www.tiktok.com/{match.group(1)}/video/{match.group(2)}"


def video_id_from_url(url: str) -> str:
    match = re.search(r"/video/(\d+)", url)
    return match.group(1) if match else ""


def author_from_url(url: str) -> str:
    match = re.search(r"tiktok\.com/(@[^/?#\s\"']+)/video/\d+", canonical_tiktok_url(url), flags=re.IGNORECASE)
    return match.group(1).lstrip("@") if match else ""


def video_timestamp_from_id(video_id: str) -> int:
    try:
        timestamp = int(str(video_id)) >> 32
    except (TypeError, ValueError):
        return 0
    if timestamp < 1_400_000_000 or timestamp > 2_200_000_000:
        return 0
    return timestamp


def video_time_fields_from_id(video_id: str) -> dict[str, Any]:
    timestamp = video_timestamp_from_id(video_id)
    if not timestamp:
        return {}
    dt = datetime.fromtimestamp(timestamp)
    return {
        "createTime": timestamp,
        "createTimeISO": dt.isoformat(timespec="seconds"),
    }


def _legacy_parse_metric_value_unused(value: Any) -> int:
    text = clean_text(value).lower()
    if not text:
        return 0
    multiplier = 1.0
    if text.endswith("k"):
        multiplier = 1_000.0
        text = text[:-1]
    elif text.endswith("m"):
        multiplier = 1_000_000.0
        text = text[:-1]
    elif text.endswith("b"):
        multiplier = 1_000_000_000.0
        text = text[:-1]
    elif text.endswith("万"):
        multiplier = 10_000.0
        text = text[:-1]
    elif text.endswith("亿"):
        multiplier = 100_000_000.0
        text = text[:-1]
    text = re.sub(r"[^0-9.]+", "", text)
    try:
        return int(float(text or "0") * multiplier)
    except (TypeError, ValueError):
        return 0


def _legacy_extract_metric_stats_from_text_unused(text: str) -> dict[str, Any]:
    normalized = clean_text(text).lower()
    stats: dict[str, Any] = {}
    patterns = [
        ("playCount", r"([0-9][0-9,]*(?:\.[0-9]+)?\s*[kmb万亿]?)\s*(?:views?|plays?|播放|观看)"),
        ("diggCount", r"([0-9][0-9,]*(?:\.[0-9]+)?\s*[kmb万亿]?)\s*(?:likes?|点赞)"),
        ("commentCount", r"([0-9][0-9,]*(?:\.[0-9]+)?\s*[kmb万亿]?)\s*(?:comments?|评论|回复)"),
        ("shareCount", r"([0-9][0-9,]*(?:\.[0-9]+)?\s*[kmb万亿]?)\s*(?:shares?|分享|转发)"),
    ]
    for key, pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            stats[key] = parse_metric_value(match.group(1))
    unlabeled = re.findall(r"(?<![a-z0-9])([0-9][0-9,]*(?:\.[0-9]+)?\s*[kmb万亿])(?![a-z])", normalized)
    if unlabeled:
        stats["unlabeledMetrics"] = [parse_metric_value(value) for value in unlabeled]
    return stats


def parse_metric_value(value: Any) -> int:
    text = clean_text(value).lower()
    if not text:
        return 0
    multiplier = 1.0
    if text.endswith("k"):
        multiplier = 1_000.0
        text = text[:-1]
    elif text.endswith("m"):
        multiplier = 1_000_000.0
        text = text[:-1]
    elif text.endswith("b"):
        multiplier = 1_000_000_000.0
        text = text[:-1]
    elif text.endswith("\u4e07"):
        multiplier = 10_000.0
        text = text[:-1]
    elif text.endswith("\u4ebf"):
        multiplier = 100_000_000.0
        text = text[:-1]
    text = re.sub(r"[^0-9.]+", "", text)
    try:
        return int(float(text or "0") * multiplier)
    except (TypeError, ValueError):
        return 0


def has_numeric_metric_value(value: Any) -> bool:
    if isinstance(value, (int, float)):
        return True
    text = clean_text(value).lower()
    return bool(re.search(r"\d", text))


def normalized_metric_value(value: Any) -> int | None:
    if not has_numeric_metric_value(value):
        return None
    return parse_metric_value(value)


def extract_metric_stats_from_text(text: str) -> dict[str, Any]:
    normalized = clean_text(text).lower()
    stats: dict[str, Any] = {}
    suffix = r"[kmb\u4e07\u4ebf]?"
    number = rf"([0-9][0-9,]*(?:\.[0-9]+)?\s*{suffix})"
    patterns = [
        ("playCount", rf"{number}\s*(?:views?|plays?|\u64ad\u653e|\u89c2\u770b)"),
        ("diggCount", rf"{number}\s*(?:likes?|\u70b9\u8d5e)"),
        ("commentCount", rf"{number}\s*(?:comments?|\u8bc4\u8bba|\u56de\u590d)"),
        ("shareCount", rf"{number}\s*(?:shares?|\u5206\u4eab|\u8f6c\u53d1)"),
    ]
    for key, pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            stats[key] = parse_metric_value(match.group(1))
    unlabeled = re.findall(rf"(?<![a-z0-9]){number}(?![a-z])", normalized)
    if unlabeled:
        stats["unlabeledMetrics"] = [parse_metric_value(value) for value in unlabeled]
    return stats


def extract_metric_stats_from_html_attrs(content: str) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    e2e_map = {
        "playCount": [
            "video-views",
            "search-card-video-views",
            "browse-video-views",
            "play-count",
            "view-count",
        ],
        "diggCount": [
            "like-count",
            "browse-like-count",
            "video-like-count",
            "search-card-like-count",
        ],
        "commentCount": [
            "comment-count",
            "browse-comment-count",
            "video-comment-count",
            "search-card-comment-count",
        ],
        "shareCount": [
            "share-count",
            "browse-share-count",
            "video-share-count",
            "search-card-share-count",
        ],
    }
    for key, e2e_names in e2e_map.items():
        for name in e2e_names:
            pattern = rf"<[^>]+data-e2e=[\"']{re.escape(name)}[\"'][^>]*>(.*?)</[^>]+>"
            match = re.search(pattern, content or "", flags=re.IGNORECASE | re.DOTALL)
            if not match:
                continue
            text = re.sub(r"<[^>]+>", " ", match.group(1))
            value = normalized_metric_value(html.unescape(text))
            if value is not None:
                stats[key] = value
                break
    return stats


def compact_fields_from_search_dom_row(row: dict[str, Any]) -> dict[str, Any]:
    structured = row.get("structured") if isinstance(row.get("structured"), dict) else {}
    fields: dict[str, Any] = {}
    play_count = normalized_metric_value(structured.get("playCountText"))
    if play_count is not None:
        fields["playCount"] = play_count
    caption = clean_text(structured.get("caption"), max_len=1200)
    if caption:
        fields["text"] = caption
        fields["hashtags"] = hashtag_list_from_values(caption)
    author_unique_id = clean_text(structured.get("authorUniqueId") or author_from_url(clean_text(structured.get("authorHref"))))
    if author_unique_id:
        fields["authorUniqueId"] = author_unique_id.lstrip("@")
    return fields


def extract_tiktok_links_from_html(content: str, limit: int) -> list[str]:
    links: list[str] = []
    patterns = [
        r"https?:\\?/\\?/(?:www\.)?tiktok\.com\\?/(@[^/\"'<>\s]+)\\?/video\\?/(\d+)",
        r"https?://(?:www\.)?tiktok\.com/(@[^/\"'<>\s]+)/video/(\d+)",
        r"href=[\"'](/@[^\"']+/video/\d+)[\"']",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, content or "", flags=re.IGNORECASE):
            raw = match.group(0)
            if match.lastindex == 2:
                raw = f"https://www.tiktok.com/{match.group(1).replace('\\/', '/')}/video/{match.group(2)}"
            elif match.lastindex == 1:
                raw = match.group(1)
            clean = canonical_tiktok_url(raw)
            if clean and clean not in links:
                links.append(clean)
            if len(links) >= limit:
                return links
    return links


def extract_tiktok_links_from_page(page: Any, limit: int) -> list[str]:
    links: list[str] = []
    try:
        hrefs = page.evaluate(
            """() => Array.from(document.querySelectorAll('a[href]'))
                .map((anchor) => anchor.href || anchor.getAttribute('href') || '')
                .filter(Boolean)"""
        )
    except Exception:
        hrefs = []
    for href in hrefs or []:
        clean = canonical_tiktok_url(str(href))
        if clean and clean not in links:
            links.append(clean)
        if len(links) >= limit:
            return links
    for link in extract_tiktok_links_from_html(page.content(), limit):
        if link not in links:
            links.append(link)
        if len(links) >= limit:
            break
    return links


def is_tiktok_web_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in {"www.tiktok.com", "m.tiktok.com"} or host.endswith(".tiktok.com")


def looks_like_search_json_url(url: str) -> bool:
    parsed = urlparse(url)
    path = (parsed.path or "").lower()
    return any(marker in path for marker in SEARCH_JSON_URL_MARKERS)


def unwrap_video_object(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    for key in ["itemStruct", "aweme_info", "awemeInfo", "aweme", "item"]:
        nested = value.get(key)
        if isinstance(nested, dict):
            return nested
    if any(key in value for key in ["stats", "statsV2", "statistics", "video", "author", "desc", "description"]):
        return value
    return None


def item_identity_from_object(item: dict[str, Any]) -> str:
    fields = compact_video_fields_from_object(item)
    return clean_text(fields.get("id")) or clean_text(first_from_dicts([item], ["id", "awemeId", "aweme_id", "itemId", "item_id", "videoId", "video_id"]))


def extract_search_response_items(payload: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_item(raw: Any) -> None:
        item = unwrap_video_object(raw)
        if not isinstance(item, dict):
            return
        identity = item_identity_from_object(item) or hashlib.sha1(json.dumps(item, sort_keys=True, default=str).encode("utf-8", errors="ignore")).hexdigest()
        if identity in seen:
            return
        seen.add(identity)
        items.append(item)

    def visit(value: Any, depth: int = 0) -> None:
        if depth > 8:
            return
        if isinstance(value, dict):
            if "itemStruct" in value or "aweme_info" in value or "awemeInfo" in value:
                add_item(value)
            for key in ["item_list", "itemList", "items", "data", "aweme_list", "awemeList", "video_list", "videoList"]:
                nested = value.get(key)
                if isinstance(nested, list):
                    for entry in nested:
                        add_item(entry)
                        visit(entry, depth + 1)
                elif isinstance(nested, dict):
                    add_item(nested)
                    visit(nested, depth + 1)
            direct = unwrap_video_object(value)
            if direct is value:
                add_item(value)
            for child in value.values():
                if isinstance(child, (dict, list)):
                    visit(child, depth + 1)
        elif isinstance(value, list):
            for entry in value:
                add_item(entry)
                visit(entry, depth + 1)

    visit(payload)
    return items


def canonical_url_from_video_item(item: dict[str, Any], fields: dict[str, Any], fallback_url: str = "") -> str:
    video = first_from_dicts([item], ["video", "videoMeta"])
    video = video if isinstance(video, dict) else {}
    raw_url = clean_text(first_from_dicts([fields, item, video], ["webVideoUrl", "url", "shareUrl", "share_url", "videoUrl", "downloadAddr"]))
    canonical = canonical_tiktok_url(raw_url)
    if canonical:
        return canonical
    video_id = clean_text(fields.get("id"))
    author = clean_text(fields.get("authorUniqueId")).lstrip("@")
    if video_id and author:
        return f"https://www.tiktok.com/@{author}/video/{video_id}"
    return canonical_tiktok_url(fallback_url)


def compact_search_response_item(item: dict[str, Any], *, source_url: str, keyword: str, query_variant: str, scroll_round: int) -> dict[str, Any] | None:
    fields = compact_video_fields_from_object(item)
    if not fields:
        return None
    canonical_url = canonical_url_from_video_item(item, fields)
    if not canonical_url:
        video_id = clean_text(fields.get("id"))
        author = clean_text(fields.get("authorUniqueId")).lstrip("@")
        if video_id and author:
            canonical_url = f"https://www.tiktok.com/@{author}/video/{video_id}"
    if not canonical_url:
        return None
    return {
        "url": canonical_url,
        "videoId": video_id_from_url(canonical_url) or clean_text(fields.get("id")),
        "sourceKeyword": keyword,
        "queryVariant": query_variant,
        "scrollRound": scroll_round,
        "responseUrl": source_url,
        "fields": fields,
        "parseSources": ["search_network_json"],
    }


class TikTokSearchResponseRecorder:
    def __init__(self, keyword: str, output_path: Path) -> None:
        self.keyword = keyword
        self.output_path = output_path
        self.records: list[dict[str, Any]] = []
        self.query_variant = ""
        self.scroll_round = 0

    def set_context(self, query_variant: str, scroll_round: int) -> None:
        self.query_variant = query_variant
        self.scroll_round = scroll_round

    def handle_response(self, response: Any) -> None:
        url = str(getattr(response, "url", "") or "")
        if not is_tiktok_web_host(url):
            return
        headers = getattr(response, "headers", {}) or {}
        content_type = clean_text(headers.get("content-type") or headers.get("Content-Type")).lower()
        should_try = looks_like_search_json_url(url) or "json" in content_type
        if not should_try:
            return
        try:
            status = int(getattr(response, "status", 0) or 0)
        except Exception:
            status = 0
        if status and status >= 400:
            return
        try:
            text = response.text()
        except Exception:
            return
        if not text or len(text) > 8_000_000:
            return
        try:
            payload = json.loads(text)
        except Exception:
            return
        raw_items = extract_search_response_items(payload)
        if not raw_items and not looks_like_search_json_url(url):
            return
        compact_items: list[dict[str, Any]] = []
        for item in raw_items:
            compact = compact_search_response_item(
                item,
                source_url=url,
                keyword=self.keyword,
                query_variant=self.query_variant,
                scroll_round=self.scroll_round,
            )
            if compact:
                compact_items.append(compact)
        if not compact_items and not looks_like_search_json_url(url):
            return
        self.records.append(
            {
                "url": url,
                "queryVariant": self.query_variant,
                "scrollRound": self.scroll_round,
                "status": status,
                "itemCount": len(raw_items),
                "candidateCount": len(compact_items),
                "capturedAt": now_iso(),
                "bodyHash": hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest(),
                "items": compact_items,
            }
        )

    def flush(self) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with self.output_path.open("w", encoding="utf-8") as handle:
            for record in self.records:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    @property
    def response_count(self) -> int:
        return len(self.records)

    @property
    def item_count(self) -> int:
        return sum(int(record.get("itemCount") or 0) for record in self.records)

    @property
    def candidate_count(self) -> int:
        return sum(int(record.get("candidateCount") or 0) for record in self.records)


def unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = clean_text(value)
        if text and text not in result:
            result.append(text)
    return result


def extract_dom_search_cards_from_page(page: Any, limit: int) -> list[dict[str, Any]]:
    try:
        rows = page.evaluate(
            """(limit) => {
                const anchors = Array.from(document.querySelectorAll('a[href*="/video/"]'));
                const seen = new Set();
                const results = [];
                const textOf = (root, selector) => {
                    const node = root && root.querySelector ? root.querySelector(selector) : null;
                    return node ? (node.innerText || node.textContent || '').trim() : '';
                };
                const attrOf = (root, selector, attr) => {
                    const node = root && root.querySelector ? root.querySelector(selector) : null;
                    return node ? (node.getAttribute(attr) || '') : '';
                };
                const rootFor = (anchor) => {
                    const direct = anchor.closest('[data-e2e="search_video-item"]');
                    if (direct) return direct;
                    const grid = anchor.closest('[id^="grid-item-container-"]');
                    if (grid) return grid;
                    let best = anchor;
                    let node = anchor.parentElement;
                    for (let depth = 0; node && depth < 5; depth += 1, node = node.parentElement) {
                        const text = (node.innerText || '').trim();
                        if (text.length > 2200) break;
                        best = node;
                    }
                    return best;
                };
                for (const anchor of anchors) {
                    const href = anchor.href || anchor.getAttribute('href') || '';
                    if (!href || seen.has(href)) continue;
                    seen.add(href);
                    const best = rootFor(anchor);
                    const imageUrls = Array.from(best.querySelectorAll ? best.querySelectorAll('img') : [])
                        .map((img) => img.currentSrc || img.src || img.getAttribute('src') || '')
                        .filter(Boolean)
                        .slice(0, 8);
                    const e2eTexts = {};
                    for (const node of Array.from(best.querySelectorAll ? best.querySelectorAll('[data-e2e]') : [])) {
                        const key = node.getAttribute('data-e2e') || '';
                        if (!key || e2eTexts[key]) continue;
                        const value = (node.innerText || node.textContent || node.getAttribute('aria-label') || '').trim();
                        if (value) e2eTexts[key] = value.slice(0, 500);
                    }
                    results.push({
                        href,
                        rawText: (best.innerText || anchor.innerText || '').trim().slice(0, 4000),
                        anchorText: (anchor.innerText || '').trim().slice(0, 1000),
                        imageUrls,
                        structured: {
                            playCountText: textOf(best, '[data-e2e="video-views"]'),
                            caption: textOf(best, '[data-e2e="search-card-video-caption"]'),
                            authorUniqueId: textOf(best, '[data-e2e="search-card-user-unique-id"]'),
                            authorHref: attrOf(best, '[data-e2e="search-card-user-link"]', 'href'),
                            timeText: textOf(best, '[class*="DivTimeTag"]'),
                            ariaLabel: best.getAttribute ? (best.getAttribute('aria-label') || '') : '',
                            e2eTexts,
                        },
                        htmlSnippet: (best.outerHTML || '').slice(0, 8000),
                    });
                    if (results.length >= limit) break;
                }
                return results;
            }""",
            limit,
        )
    except Exception:
        return []
    return rows if isinstance(rows, list) else []


def extract_detail_dom_fields_from_page(page: Any) -> dict[str, Any]:
    try:
        payload = page.evaluate(
            """() => {
                const textOf = (selector) => {
                    const node = document.querySelector(selector);
                    return node ? (node.innerText || node.textContent || '').trim() : '';
                };
                const e2eTexts = {};
                for (const node of Array.from(document.querySelectorAll('[data-e2e]'))) {
                    const key = node.getAttribute('data-e2e') || '';
                    if (!key || e2eTexts[key]) continue;
                    const value = (node.innerText || node.textContent || node.getAttribute('aria-label') || '').trim();
                    if (value) e2eTexts[key] = value.slice(0, 500);
                }
                return {
                    caption: textOf('[data-e2e="browse-video-desc"], [data-e2e="video-desc"], [data-e2e="search-card-video-caption"]'),
                    authorUniqueId: textOf('[data-e2e="browse-username"], [data-e2e="video-author-uniqueid"], [data-e2e="search-card-user-unique-id"]'),
                    e2eTexts,
                };
            }"""
        )
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    e2e = payload.get("e2eTexts") if isinstance(payload.get("e2eTexts"), dict) else {}
    fields: dict[str, Any] = {}
    metric_aliases = {
        "playCount": ["video-views", "browse-video-views", "play-count", "view-count"],
        "diggCount": ["like-count", "browse-like-count", "video-like-count"],
        "commentCount": ["comment-count", "browse-comment-count", "video-comment-count"],
        "shareCount": ["share-count", "browse-share-count", "video-share-count"],
    }
    for field, names in metric_aliases.items():
        for name in names:
            metric = normalized_metric_value(e2e.get(name))
            if metric is not None:
                fields[field] = metric
                break
    caption = clean_text(payload.get("caption"), max_len=1200)
    if caption:
        fields["text"] = caption
        fields["hashtags"] = hashtag_list_from_values(caption)
    author = clean_text(payload.get("authorUniqueId"))
    if author:
        fields["authorUniqueId"] = author.lstrip("@")
    return fields


def merge_search_card(target: dict[str, Any], update: dict[str, Any]) -> None:
    for key in ["rawText", "anchorText", "htmlSnippet"]:
        if not target.get(key) and update.get(key):
            target[key] = update[key]
    target["coverCandidates"] = unique_strings(
        list(target.get("coverCandidates") or [])
        + list(update.get("coverCandidates") or [])
        + list(update.get("imageUrls") or [])
    )
    stats = dict(target.get("rawStats") or {})
    stats.update(update.get("rawStats") or {})
    target["rawStats"] = stats
    sources = set(target.get("parseSources") or [])
    sources.update(update.get("parseSources") or [])
    target["parseSources"] = sorted(sources)
    if update.get("embeddedFields"):
        fields = dict(target.get("embeddedFields") or {})
        for field, value in update["embeddedFields"].items():
            if value not in (None, "", [], {}) and field not in fields:
                fields[field] = value
        target["embeddedFields"] = fields


def extract_tiktok_search_cards_from_page(page: Any, keyword: str, limit: int) -> list[dict[str, Any]]:
    cards_by_url: dict[str, dict[str, Any]] = {}
    dom_rows = extract_dom_search_cards_from_page(page, limit * 3)
    for rank, row in enumerate(dom_rows, start=1):
        url = canonical_tiktok_url(str(row.get("href") or ""))
        if not url:
            continue
        card = cards_by_url.setdefault(
            url,
            {
                "url": url,
                "videoId": video_id_from_url(url),
                "rank": rank,
                "sourceKeyword": keyword,
                "parseSources": [],
            },
        )
        raw_text = clean_text(row.get("rawText"), max_len=4000)
        structured_fields = compact_fields_from_search_dom_row(row)
        raw_stats = extract_metric_stats_from_text(raw_text)
        for metric_key in ["playCount", "diggCount", "commentCount", "shareCount"]:
            if metric_key in structured_fields:
                raw_stats[metric_key] = structured_fields[metric_key]
        merge_search_card(
            card,
            {
                "rawText": raw_text,
                "anchorText": clean_text(row.get("anchorText"), max_len=1000),
                "htmlSnippet": clean_text(row.get("htmlSnippet"), max_len=8000),
                "coverCandidates": row.get("imageUrls") or [],
                "rawStats": raw_stats,
                "embeddedFields": structured_fields,
                "parseSources": ["search_card_dom"],
            },
        )

    content = ""
    objects: list[dict[str, Any]] = []
    try:
        content = page.content()
        objects = load_embedded_json_objects(content)
    except Exception:
        objects = []
    html_links = extract_tiktok_links_from_html(content, limit * 3) if content else []
    for rank, url in enumerate(html_links, start=1):
        cards_by_url.setdefault(
            url,
            {
                "url": url,
                "videoId": video_id_from_url(url),
                "rank": rank,
                "sourceKeyword": keyword,
                "parseSources": [],
            },
        )

    for url, card in cards_by_url.items():
        video_id = video_id_from_url(url)
        obj = choose_video_object(objects, video_id) if objects else {}
        fields = compact_video_fields_from_object(obj)
        if fields:
            merge_search_card(
                card,
                {
                    "embeddedFields": fields,
                    "parseSources": ["search_embedded_json"],
                    "coverCandidates": [fields.get("coverUrl")],
                },
            )

    cards = sorted(cards_by_url.values(), key=lambda item: int(item.get("rank") or 999999))
    return cards[:limit]


def is_forbidden_external_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(token in host for token in FORBIDDEN_EXTERNAL_HOST_TOKENS)


def is_target_closed_error(message: Any) -> bool:
    text = str(message or "").lower()
    return "target page" in text and ("closed" in text or "browser has been closed" in text or "context" in text)


def random_wait_ms(min_ms: int, max_ms: int, rng: random.Random | None = None) -> int:
    lower = max(0, int(min_ms))
    upper = max(lower, int(max_ms))
    source = rng or random
    return source.randint(lower, upper) if upper > lower else lower


def hashtag_variant(keyword: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "", keyword or "")
    return f"#{text}" if text else ""


def keyword_variants(keyword: str) -> list[str]:
    normalized = clean_text(keyword).strip()
    variants = [
        normalized,
        f'"{normalized}"' if normalized else "",
        f"{normalized} template" if normalized else "",
        f"{normalized} trend" if normalized else "",
        hashtag_variant(normalized),
    ]
    result: list[str] = []
    for variant in variants:
        text = clean_text(variant)
        if text and text not in result:
            result.append(text)
    return result


def detect_page_state_from_snapshot(url: str, body: str, html: str | None = None) -> dict[str, str]:
    current_url = str(url or "").lower()
    text = str(body or "").lower()
    html_text = str(body if html is None else html or "").lower()
    parsed = urlparse(current_url)
    route = f"{parsed.hostname or ''}{parsed.path or ''}".lower()
    if any(marker in route for marker in ["/login", "login.tiktok.com"]):
        return {"state": "login_required", "reason": "login_url"}
    verification_url_markers = ["captcha", "verify", "verification", "challenge"]
    if any(marker in route for marker in verification_url_markers):
        return {"state": "verification_required", "reason": "verification_url"}
    verification_body_markers = [
        "verify to continue",
        "security check",
        "drag the slider",
        "slide to verify",
        "prove you are not a robot",
        "fit the puzzle",
    ]
    if any(marker in text for marker in verification_body_markers):
        return {"state": "verification_required", "reason": "verification_body"}
    if "login" in text and ("password" in text or "phone" in text or "email" in text):
        return {"state": "login_required", "reason": "login_body"}
    if "/video/" in current_url:
        detail_markers = [
            "itemstruct",
            "diggcount",
            "commentcount",
            "playcount",
            "like-count",
            "browse-video-desc",
            "og:description",
            "application/ld+json",
        ]
        shell_markers = ["pumbaa-rule", "make your day", "tiktok_webapp"]
        if not any(marker in html_text for marker in detail_markers) and any(marker in html_text for marker in shell_markers):
            return {"state": "empty_shell", "reason": "detail_shell_without_video_data"}
    compact = re.sub(r"\s+", "", text)
    if len(compact) < 120 and not any(marker in current_url for marker in ["search", "/video/"]):
        return {"state": "empty_shell", "reason": "short_body"}
    return {"state": "ok", "reason": ""}


def search_stop_reason(link_count: int, limit: int, no_growth_rounds: int, max_no_growth_rounds: int, scroll_rounds: int, max_scrolls: int) -> str:
    if link_count >= limit:
        return "target_reached"
    if no_growth_rounds >= max_no_growth_rounds:
        return "no_growth"
    if scroll_rounds >= max_scrolls:
        return "max_scrolls"
    return "incomplete"


class VerificationRequiredError(RuntimeError):
    def __init__(self, state: str, reason: str, timeout: bool = False) -> None:
        self.state = state
        self.reason = reason
        self.timeout = timeout
        super().__init__(reason)


def _float_tuple(value: Any, default: tuple[float, ...]) -> tuple[float, ...]:
    if value is None:
        return default
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, (list, tuple)):
        parts = list(value)
    else:
        return default
    parsed: list[float] = []
    for part in parts:
        try:
            parsed.append(float(part))
        except (TypeError, ValueError):
            return default
    return tuple(parsed) if parsed else default


def slider_attempt_retryable_without_release(result: dict[str, Any]) -> bool:
    reason = clean_text(result.get("releaseBlockedReason") or result.get("error"), max_len=120)
    return reason in {
        "alignment_error_too_high",
        "score_below_release_min",
        "confidence_margin_below_release_min",
        "pre_release_not_changed",
        "weak_drag_effect",
        "auto_drag_no_effect",
        "closed_loop_not_converged",
    }


def solve_tiktok_slider_puzzle(page: Any, config: dict[str, Any]) -> dict[str, Any]:
    if not config.get("enabled", True):
        return {"attempted": False, "success": False, "reason": "disabled"}
    try:
        from slider_puzzle_solver import SliderPuzzleConfig, solve_slider_puzzle

        solver_config = SliderPuzzleConfig(
            container_selector=clean_text(config.get("containerSelector")),
            track_selector=clean_text(config.get("trackSelector")),
            handle_selector=clean_text(config.get("handleSelector")),
            inner_selector=clean_text(config.get("innerSelector")) or None,
            success_selector=clean_text(config.get("successSelector")) or None,
            sample_dir=clean_text(config.get("sampleDir")) or None,
            rotation_degrees=float(config.get("rotationDegrees") or DEFAULT_SLIDER_PUZZLE_ROTATION_DEGREES),
            inner_clockwise_rotation_degrees=float(config.get("innerClockwiseRotationDegrees") or 180.0),
            outer_counterclockwise_rotation_degrees=float(config.get("outerCounterclockwiseRotationDegrees") or 180.0),
            manual_candidate_inner_rotation_degrees=_float_tuple(
                config.get("manualCandidateInnerRotationDegrees"),
                (),
            ),
            manual_candidate_refine_inner_offsets=_float_tuple(
                config.get("manualCandidateRefineInnerOffsets"),
                (-10.0, -5.0, 5.0, 10.0),
            ),
            manual_candidate_refine_top_k=max(0, int(config.get("manualCandidateRefineTopK") or 1)),
            max_attempts=max(1, int(config.get("maxAttempts") or DEFAULT_SLIDER_PUZZLE_MAX_ATTEMPTS)),
            tolerance_score=float(config.get("toleranceScore") or DEFAULT_SLIDER_PUZZLE_TOLERANCE_SCORE),
            drag_probe_px=float(config.get("dragProbePx") or 12.0),
            drag_probe_wait_ms=max(0, int(config.get("dragProbeWaitMs") or 120)),
            drag_strategy_max=max(1, int(config.get("dragStrategyMax") or 4)),
            drag_retry_reset_ms=max(0, int(config.get("dragRetryResetMs") or 160)),
            hit_test_radius_px=float(config.get("hitTestRadiusPx") or 10.0),
            max_no_effect_candidates=max(1, int(config.get("maxNoEffectCandidates") or 2)),
            drag_effective_min_px=float(config.get("dragEffectiveMinPx") or 12.0),
            drag_effective_track_ratio=float(config.get("dragEffectiveTrackRatio") or 0.04),
            drag_effective_ratio=float(config.get("dragEffectiveRatio") or 0.50),
            weak_drag_max_px=float(config.get("weakDragMaxPx") or 12.0),
            actual_target_tolerance_px=float(config.get("actualTargetTolerancePx") or 4.0),
            release_alignment_error_max=float(config.get("releaseAlignmentErrorMax") or 8.0),
            closed_loop_max_rounds=max(0, int(config.get("closedLoopMaxRounds") or 1)),
            closed_loop_pixel_steps=_float_tuple(config.get("closedLoopPixelSteps"), ()),
            closed_loop_inner_angle_steps=_float_tuple(config.get("closedLoopInnerAngleSteps"), (12.0, 18.0)),
            closed_loop_min_improvement=float(config.get("closedLoopMinImprovement") or 2.0),
            release_score_min=float(config.get("releaseScoreMin") or 0.45),
            release_confidence_margin_min=float(config.get("releaseConfidenceMarginMin") or 0.02),
            release_require_effective=bool(config.get("releaseRequireEffective", True)),
            release_require_changed=bool(config.get("releaseRequireChanged", True)),
            horizontal_line_count=max(1, int(config.get("horizontalLineCount") or 5)),
            horizontal_line_span_ratio=float(config.get("horizontalLineSpanRatio") or 0.72),
            horizontal_sample_step_px=max(1, int(config.get("horizontalSampleStepPx") or 4)),
            horizontal_patch_height_px=max(1, int(config.get("horizontalPatchHeightPx") or 3)),
            vertical_line_count=max(1, int(config.get("verticalLineCount") or 5)),
            vertical_line_span_ratio=float(config.get("verticalLineSpanRatio") or 0.72),
            vertical_sample_step_px=max(1, int(config.get("verticalSampleStepPx") or 4)),
            vertical_patch_width_px=max(1, int(config.get("verticalPatchWidthPx") or 3)),
            neighbor_angle_offsets=_float_tuple(config.get("neighborAngleOffsets"), (-8.0, 0.0, 8.0)),
            neighbor_radius_offsets=_float_tuple(config.get("neighborRadiusOffsets"), (-4.0, 0.0, 4.0)),
            neighbor_patch_size_px=max(1, int(config.get("neighborPatchSizePx") or 3)),
            neighbor_top_k=max(1, int(config.get("neighborTopK") or 2)),
            boundary_enabled=bool(config.get("boundaryEnabled", True)),
            boundary_min_lines=max(1, int(config.get("boundaryMinLines") or 2)),
            boundary_min_line_span_degrees=float(config.get("boundaryMinLineSpanDegrees") or 8.0),
            boundary_min_line_separation_degrees=float(config.get("boundaryMinLineSeparationDegrees") or 20.0),
            boundary_edge_threshold=float(config.get("boundaryEdgeThreshold") or 18.0),
            boundary_inner_band_px=float(config.get("boundaryInnerBandPx") or 10.0),
            boundary_outer_band_px=float(config.get("boundaryOuterBandPx") or 12.0),
            boundary_gap_px=float(config.get("boundaryGapPx") or 2.0),
            boundary_high_conf_min_max_span=float(config.get("boundaryHighConfMinMaxSpan") or 15.0),
            boundary_high_conf_min_top2_avg_span=float(config.get("boundaryHighConfMinTop2AvgSpan") or 12.0),
            boundary_short_segment_span=float(config.get("boundaryShortSegmentSpan") or 10.0),
            boundary_refine_inner_offsets=_float_tuple(
                config.get("boundaryRefineInnerOffsets"),
                (-18.0, -12.0, -6.0, -3.0, 3.0, 6.0, 12.0, 18.0),
            ),
            boundary_fast_path_enabled=bool(config.get("boundaryFastPathEnabled", True)),
            boundary_fast_path_min_score=float(config.get("boundaryFastPathMinScore") or 0.55),
            boundary_fast_path_min_margin=float(config.get("boundaryFastPathMinMargin") or 0.05),
            residual_trend_refine_enabled=bool(config.get("residualTrendRefineEnabled", True)),
            residual_trend_refine_max=max(0, int(config.get("residualTrendRefineMax") or 2)),
            residual_trend_refine_min_error=float(config.get("residualTrendRefineMinError") or 8.0),
            residual_trend_refine_max_error=float(config.get("residualTrendRefineMaxError") or 70.0),
            residual_trend_refine_inner_steps=_float_tuple(config.get("residualTrendRefineInnerSteps"), (4.0, 8.0)),
            residual_trend_boundary_quality_min=float(config.get("residualTrendBoundaryQualityMin") or 0.35),
            release_unchanged_alignment_error_max=float(config.get("releaseUnchangedAlignmentErrorMax") or 2.0),
            release_unchanged_boundary_score_min=float(config.get("releaseUnchangedBoundaryScoreMin") or 0.95),
            release_unchanged_confidence_margin_min=float(config.get("releaseUnchangedConfidenceMarginMin") or 0.10),
            ray_fast_path_enabled=bool(config.get("rayFastPathEnabled", True)),
            ray_fast_path_min_score=float(config.get("rayFastPathMinScore") or 0.90),
            ray_fast_path_min_margin=float(config.get("rayFastPathMinMargin") or 0.0),
            ray_weight=float(config.get("rayWeight") or 0.30),
            horizontal_weight=float(config.get("horizontalWeight") or 0.15),
            vertical_weight=float(config.get("verticalWeight") or 0.10),
            neighbor_weight=float(config.get("neighborWeight") or 0.10),
            boundary_weight=float(config.get("boundaryWeight") or 0.35),
            fusion_agreement_max_degrees=float(config.get("fusionAgreementMaxDegrees") or 12.0),
            fusion_confidence_margin_min=float(config.get("fusionConfidenceMarginMin") or 0.02),
            unstable_fusion_agreement_degrees=float(config.get("UnstableFusionAgreementDegrees") or config.get("unstableFusionAgreementDegrees") or 45.0),
        )
        result = solve_slider_puzzle(page, solver_config)
        return {
            "attempted": True,
            "success": bool(getattr(result, "success", False)),
            "dragPx": float(getattr(result, "drag_px", 0.0) or 0.0),
            "angleDelta": float(getattr(result, "angle_delta", 0.0) or 0.0),
            "score": float(getattr(result, "score", 0.0) or 0.0),
            "attempts": int(getattr(result, "attempts", 0) or 0),
            "error": clean_text(getattr(result, "error", ""), max_len=300),
            "heldForManualConfirmation": bool(getattr(result, "held_for_manual_confirmation", False)),
            "releasedForManualConfirmation": bool(getattr(result, "released_for_manual_confirmation", False)),
            "selectedDirection": clean_text(getattr(result, "selected_direction", ""), max_len=80),
            "alignmentError": float(getattr(result, "alignment_error", 0.0) or 0.0),
            "candidateCount": int(getattr(result, "candidate_count", 0) or 0),
            "sampleDir": clean_text(getattr(result, "sample_dir", ""), max_len=300),
            "sampleCount": int(getattr(result, "sample_count", 0) or 0),
            "matchedRayCount": int(getattr(result, "matched_ray_count", 0) or 0),
            "comparableRayCount": int(getattr(result, "comparable_ray_count", 0) or 0),
            "rayStepDegrees": int(getattr(result, "ray_step_degrees", 0) or 0),
            "rayWidthPixels": int(getattr(result, "ray_width_pixels", 0) or 0),
            "boundedFallbackApplied": bool(getattr(result, "bounded_fallback_applied", False)),
            "inputStable": bool(getattr(result, "input_stable", True)),
            "dragEffective": bool(getattr(result, "drag_effective", True)),
            "handleDeltaPx": float(getattr(result, "handle_delta_px", 0.0) or 0.0),
            "preReleaseChanged": bool(getattr(result, "pre_release_changed", False)),
            "confidenceMargin": float(getattr(result, "confidence_margin", 0.0) or 0.0),
            "candidateEvaluations": list(getattr(result, "candidate_evaluations", []) or []),
            "dragStrategy": clean_text(getattr(result, "drag_strategy", ""), max_len=80),
            "dragProbeEffective": bool(getattr(result, "drag_probe_effective", False)),
            "weakDragEffect": bool(getattr(result, "weak_drag_effect", False)),
            "closedLoopRounds": int(getattr(result, "closed_loop_rounds", 0) or 0),
            "closedLoopImproved": bool(getattr(result, "closed_loop_improved", False)),
            "releaseBlockedReason": clean_text(getattr(result, "release_blocked_reason", ""), max_len=120),
            "sliderProgress": float(getattr(result, "slider_progress", 0.0) or 0.0),
            "innerRotationDegrees": float(getattr(result, "inner_rotation_degrees", 0.0) or 0.0),
            "outerRotationDegrees": float(getattr(result, "outer_rotation_degrees", 0.0) or 0.0),
            "relativeRotationDegrees": float(getattr(result, "relative_rotation_degrees", 0.0) or 0.0),
            "fusionAgreementDegrees": float(getattr(result, "fusion_agreement_degrees", 0.0) or 0.0),
            "selectedMethod": clean_text(getattr(result, "selected_method", ""), max_len=80),
            "localRefineApplied": bool(getattr(result, "local_refine_applied", False)),
            "candidateDiagnostics": dict(getattr(result, "candidate_diagnostics", {}) or {}),
            "boundaryLineCount": int(getattr(result, "boundary_line_count", 0) or 0),
            "boundaryScore": float(getattr(result, "boundary_score", 0.0) or 0.0),
            "boundaryConfidenceMargin": float(getattr(result, "boundary_confidence_margin", 0.0) or 0.0),
            "boundaryAngleDelta": float(getattr(result, "boundary_angle_delta", 0.0) or 0.0),
            "boundaryTopAngles": list(getattr(result, "boundary_top_angles", []) or []),
        }
    except Exception as exc:
        return {
            "attempted": True,
            "success": False,
            "error": clean_text(str(exc), max_len=300),
        }


class TikTokCookieSearchClient:
    def __init__(
        self,
        cookie_file: Path,
        *,
        headless: bool,
        detail_headless: bool,
        browser_channel: str,
        browser_executable: Path | None,
        max_scrolls: int,
        wait_ms: int,
        scroll_wait_min_ms: int,
        scroll_wait_max_ms: int,
        max_no_growth_rounds: int,
        verification_poll_seconds: int,
        verification_wait_seconds: int,
        slider_puzzle_config: dict[str, Any] | None,
    ) -> None:
        self.cookie_file = cookie_file
        self.headless = headless
        self.detail_headless = detail_headless
        self.browser_channel = browser_channel or DEFAULT_BROWSER_CHANNEL
        self.browser_executable = browser_executable
        self.max_scrolls = max_scrolls
        self.wait_ms = wait_ms
        self.scroll_wait_min_ms = max(0, scroll_wait_min_ms)
        self.scroll_wait_max_ms = max(self.scroll_wait_min_ms, scroll_wait_max_ms)
        self.max_no_growth_rounds = max(1, max_no_growth_rounds)
        self.verification_poll_seconds = max(1, verification_poll_seconds)
        self.verification_wait_seconds = max(0, verification_wait_seconds)
        self.slider_puzzle_config = slider_puzzle_config or {"enabled": False}

    def _cookies(self) -> list[dict[str, Any]]:
        if not self.cookie_file.exists():
            raise RuntimeError(f"TikTok cookies file not found: {self.cookie_file}")
        cookies = read_netscape_cookies(self.cookie_file)
        if not cookies:
            raise RuntimeError(f"TikTok cookies file is empty or invalid: {self.cookie_file}")
        return cookies

    def _install_route_guard(self, context: Any) -> None:
        def guard(route: Any) -> None:
            url = route.request.url
            if is_forbidden_external_host(url):
                route.abort()
                return
            route.continue_()

        context.route("**/*", guard)

    def _launch_browser(self, pw: Any, *, headless: bool | None = None) -> Any:
        effective_headless = self.headless if headless is None else bool(headless)
        launch_kwargs: dict[str, Any] = {"headless": effective_headless}
        if self.browser_executable:
            if not self.browser_executable.exists():
                raise RuntimeError(f"Microsoft Edge executable not found: {self.browser_executable}")
            launch_kwargs["executable_path"] = str(self.browser_executable)
        else:
            launch_kwargs["channel"] = self.browser_channel
        try:
            return pw.chromium.launch(**launch_kwargs)
        except Exception as exc:
            executable = str(self.browser_executable) if self.browser_executable else ""
            raise RuntimeError(
                "Failed to launch Microsoft Edge for TikTok keyword discovery "
                f"(browserChannel={self.browser_channel}, browserExecutable={executable or '<channel>'}, "
                f"headless={effective_headless})."
            ) from exc

    def collect_search(self, search_plan: list[dict[str, Any]], run_dir: Path, resume: bool) -> list[dict[str, Any]]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("playwright is not installed. Install project requirements before running Edge discovery.") from exc
        cookies = self._cookies()
        link_dir = run_dir / "05_search_links"
        card_dir = run_dir / "05_search_cards"
        response_dir = run_dir / "05_search_responses"
        link_dir.mkdir(parents=True, exist_ok=True)
        card_dir.mkdir(parents=True, exist_ok=True)
        response_dir.mkdir(parents=True, exist_ok=True)
        rejected: list[dict[str, Any]] = []
        with sync_playwright() as pw:
            browser = None
            context = None

            def open_context() -> Any:
                nonlocal browser, context
                if context is not None:
                    try:
                        context.close()
                    except Exception:
                        pass
                if browser is not None:
                    try:
                        browser.close()
                    except Exception:
                        pass
                browser = self._launch_browser(pw)
                context = browser.new_context(locale="en-US")
                self._install_route_guard(context)
                context.add_cookies(cookies)
                return context

            context = open_context()
            try:
                for entry in search_plan:
                    keyword = entry["keyword"]
                    link_path = link_dir / f"{slug(keyword)}.json"
                    card_path = card_dir / f"{slug(keyword)}.json"
                    response_path = response_dir / f"{slug(keyword)}.jsonl"
                    if resume and link_path.exists() and card_path.exists() and response_path.exists():
                        link_report = read_json(link_path, {})
                        card_report = read_json(card_path, {})
                    else:
                        try:
                            page = context.new_page()
                        except Exception:
                            context = open_context()
                            page = context.new_page()
                        link_report, card_report = self.search_keyword(page, keyword, int(entry["allocation"]), run_dir)
                        write_json(link_path, link_report)
                        write_json(card_path, card_report)
                        try:
                            if not page.is_closed():
                                page.close()
                        except Exception:
                            pass
                        if is_target_closed_error(link_report.get("error")):
                            context = open_context()
                    if link_report.get("status") != "success":
                        rejected.append({"stage": "search", "keyword": keyword, "reason": link_report.get("error") or link_report.get("status")})
                    if card_report.get("status") not in {"success", "partial"}:
                        rejected.append({"stage": "search_card", "keyword": keyword, "reason": card_report.get("error") or card_report.get("status")})
            finally:
                if context is not None:
                    try:
                        context.close()
                    except Exception:
                        pass
                if browser is not None:
                    try:
                        browser.close()
                    except Exception:
                        pass
        return rejected

    def resolve_candidates(self, search_plan: list[dict[str, Any]], run_dir: Path, resume: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        metadata_by_url, rejected = load_search_metadata(search_plan, run_dir)
        detail_dir = run_dir / "06_detail_raw"
        html_dir = run_dir / "06_detail_html"
        detail_dir.mkdir(parents=True, exist_ok=True)
        html_dir.mkdir(parents=True, exist_ok=True)
        candidates: list[dict[str, Any]] = []
        browser = None
        context = None
        detail_page = None
        playwright_cm = None

        def ensure_detail_page() -> Any:
            nonlocal browser, context, detail_page, playwright_cm
            if detail_page is not None:
                return detail_page
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as exc:
                raise RuntimeError("playwright is not installed. Install project requirements before running Edge discovery.") from exc
            playwright_cm = sync_playwright()
            pw = playwright_cm.__enter__()
            browser = self._launch_browser(pw, headless=self.detail_headless)
            context = browser.new_context(locale="en-US")
            self._install_route_guard(context)
            context.add_cookies(self._cookies())
            detail_page = context.new_page()
            return detail_page

        try:
            for url, meta in metadata_by_url.items():
                video_id = video_id_from_url(url) or str(abs(hash(url)))
                detail_path = detail_dir / f"{video_id}.json"
                if resume and detail_path.exists():
                    detail_report = read_json(detail_path, {})
                else:
                    detail_report = self.resolve_url_candidate(url, meta, ensure_detail_page)
                    write_json(detail_path, detail_report)
                    if detail_report.get("htmlSnippet"):
                        (html_dir / f"{video_id}.html").write_text(str(detail_report["htmlSnippet"]), encoding="utf-8")
                if detail_report.get("status") == "success" and isinstance(detail_report.get("candidate"), dict):
                    candidates.append(detail_report["candidate"])
                else:
                    rejected.append(
                        {
                            "stage": "detail",
                            "url": url,
                            "reason": detail_report.get("error") or detail_report.get("status"),
                            "missingFields": detail_report.get("missingFields", []),
                        }
                    )
        finally:
            if context is not None:
                context.close()
            if browser is not None:
                browser.close()
            if playwright_cm is not None:
                playwright_cm.__exit__(None, None, None)
        return candidates, rejected

    def detect_page_state(self, page: Any) -> dict[str, str]:
        try:
            has_captcha = page.evaluate(
                """() => {
                    const looksLikeCaptcha = (node) => {
                        const className = String(node.className || '').toLowerCase();
                        const id = String(node.id || '').toLowerCase();
                        return className.includes('captcha') || className.includes('cap-slider') || id.includes('captcha');
                    };
                    const isVisible = (node) => {
                        const style = window.getComputedStyle(node);
                        const rect = node.getBoundingClientRect();
                        return style.display !== 'none'
                            && style.visibility !== 'hidden'
                            && Number(style.opacity || 1) > 0.05
                            && rect.width > 40
                            && rect.height > 40;
                    };
                    const hasChallengeSignal = (node) => {
                        const text = String(node.innerText || node.textContent || '').toLowerCase();
                        return /verify|captcha|security check|drag|slider|puzzle|robot/.test(text)
                            || Boolean(node.querySelector('canvas, iframe, button, img'));
                    };
                    return Array.from(document.querySelectorAll('body *')).some(
                        (node) => looksLikeCaptcha(node) && isVisible(node) && hasChallengeSignal(node)
                    );
                }"""
            )
            if has_captcha:
                return {"state": "verification_required", "reason": "captcha_dom"}
        except Exception:
            pass
        try:
            search_has_results = page.evaluate(
                """() => {
                    const url = String(window.location.href || '').toLowerCase();
                    if (!url.includes('/search/')) return false;
                    return Boolean(
                        document.querySelector('a[href*="/video/"], [data-e2e="search_video-item"], [id^="grid-item-container-"]')
                    );
                }"""
            )
            if search_has_results:
                return {"state": "ok", "reason": "search_results_visible"}
        except Exception:
            pass
        try:
            body = page.inner_text("body", timeout=3000)
        except Exception:
            try:
                body = page.content()
            except Exception:
                body = ""
        try:
            content = page.content()
        except Exception:
            content = ""
        return detect_page_state_from_snapshot(str(getattr(page, "url", "") or ""), body[:6000], content[:12000])

    def assert_page_ok(self, page: Any) -> None:
        state = self.detect_page_state(page)
        if state.get("state") != "ok":
            raise RuntimeError(f"TikTok page state is {state.get('state')}: {state.get('reason')}")

    def verification_file_hash(self, path: Path) -> str:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except Exception:
            return ""

    def capture_captcha_element_screenshot(self, page: Any, output_path: Path) -> str:
        selectors = unique_strings(
            [
                clean_text(self.slider_puzzle_config.get("containerSelector")),
                DEFAULT_SLIDER_PUZZLE_CONTAINER_SELECTOR,
            ]
        )
        for selector in selectors:
            if not selector:
                continue
            try:
                locator = page.locator(selector).first
                locator.screenshot(path=str(output_path), timeout=1500)
                if output_path.exists():
                    return relative_path(output_path)
            except Exception:
                continue
        return ""

    def capture_verification_snapshot(
        self,
        page: Any,
        run_dir: Path,
        *,
        keyword: str,
        attempt_dir_name: str,
        phase: str,
        state: dict[str, str],
        collected_count: int,
        slider_puzzle_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        attempt_dir = run_dir / "verification" / "captcha_attempts" / slug(keyword) / attempt_dir_name
        attempt_dir.mkdir(parents=True, exist_ok=True)
        full_path = attempt_dir / f"{phase}_full.png"
        captcha_path = attempt_dir / f"{phase}_captcha.png"
        html_path = attempt_dir / f"{phase}.html"
        full_rel = ""
        captcha_rel = ""
        html_rel = ""
        try:
            page.screenshot(path=str(full_path), full_page=True)
            full_rel = relative_path(full_path)
        except Exception:
            full_rel = ""
        captcha_rel = self.capture_captcha_element_screenshot(page, captcha_path)
        try:
            html_path.write_text(page.content()[:120000], encoding="utf-8")
            html_rel = relative_path(html_path)
        except Exception:
            html_rel = ""
        snapshot = {
            "phase": phase,
            "capturedAt": now_iso(),
            "keyword": keyword,
            "url": str(getattr(page, "url", "") or ""),
            "state": state.get("state", "verification_required"),
            "reason": state.get("reason", ""),
            "collectedCount": collected_count,
            "fullScreenshotPath": full_rel,
            "fullScreenshotHash": self.verification_file_hash(full_path) if full_rel else "",
            "captchaScreenshotPath": captcha_rel,
            "captchaScreenshotHash": self.verification_file_hash(captcha_path) if captcha_rel else "",
            "htmlSnippetPath": html_rel,
        }
        if slider_puzzle_result is not None:
            snapshot["sliderPuzzle"] = slider_puzzle_result
        return snapshot

    def snapshot_compare_hash(self, snapshot: dict[str, Any]) -> str:
        return clean_text(snapshot.get("captchaScreenshotHash") or snapshot.get("fullScreenshotHash"))

    def snapshot_captcha_hash(self, snapshot: dict[str, Any]) -> str:
        return clean_text(snapshot.get("captchaScreenshotHash"))

    def snapshot_full_hash(self, snapshot: dict[str, Any]) -> str:
        return clean_text(snapshot.get("fullScreenshotHash"))

    def append_failed_verification_attempt(
        self,
        run_dir: Path,
        *,
        keyword: str,
        attempt_dir_name: str,
        reason: str,
        state: dict[str, str],
        collected_count: int,
        before_snapshot: dict[str, Any],
        after_snapshot: dict[str, Any],
        slider_puzzle_result: dict[str, Any],
    ) -> dict[str, Any]:
        before_captcha_hash = self.snapshot_captcha_hash(before_snapshot)
        after_captcha_hash = self.snapshot_captcha_hash(after_snapshot)
        before_full_hash = self.snapshot_full_hash(before_snapshot)
        after_full_hash = self.snapshot_full_hash(after_snapshot)
        hash_source = "captcha" if before_captcha_hash and after_captcha_hash else "full_page"
        record = {
            "autoAttempt": int(slider_puzzle_result.get("autoAttempt", 0) or 0),
            "keyword": keyword,
            "reason": reason,
            "state": state.get("state", "verification_required"),
            "stateReason": state.get("reason", ""),
            "capturedAt": now_iso(),
            "collectedCount": collected_count,
            "captchaRefreshed": bool(
                before_captcha_hash
                and after_captcha_hash
                and before_captcha_hash != after_captcha_hash
            ),
            "pageChanged": bool(
                before_full_hash
                and after_full_hash
                and before_full_hash != after_full_hash
            ),
            "hashSource": hash_source,
            "releasedForManualConfirmation": bool(slider_puzzle_result.get("releasedForManualConfirmation")),
            "score": slider_puzzle_result.get("score", 0.0),
            "dragPx": slider_puzzle_result.get("dragPx", 0.0),
            "angleDelta": slider_puzzle_result.get("angleDelta", 0.0),
            "dragEffective": bool(slider_puzzle_result.get("dragEffective", True)),
            "handleDeltaPx": slider_puzzle_result.get("handleDeltaPx", 0.0),
            "preReleaseChanged": bool(slider_puzzle_result.get("preReleaseChanged", False)),
            "dragStrategy": slider_puzzle_result.get("dragStrategy", ""),
            "dragProbeEffective": bool(slider_puzzle_result.get("dragProbeEffective", False)),
            "weakDragEffect": bool(slider_puzzle_result.get("weakDragEffect", False)),
            "closedLoopRounds": slider_puzzle_result.get("closedLoopRounds", 0),
            "closedLoopImproved": bool(slider_puzzle_result.get("closedLoopImproved", False)),
            "releaseBlockedReason": slider_puzzle_result.get("releaseBlockedReason", ""),
            "sliderProgress": slider_puzzle_result.get("sliderProgress", 0.0),
            "innerRotationDegrees": slider_puzzle_result.get("innerRotationDegrees", 0.0),
            "outerRotationDegrees": slider_puzzle_result.get("outerRotationDegrees", 0.0),
            "relativeRotationDegrees": slider_puzzle_result.get("relativeRotationDegrees", 0.0),
            "fusionAgreementDegrees": slider_puzzle_result.get("fusionAgreementDegrees", 0.0),
            "selectedMethod": slider_puzzle_result.get("selectedMethod", ""),
            "localRefineApplied": bool(slider_puzzle_result.get("localRefineApplied", False)),
            "candidateDiagnostics": slider_puzzle_result.get("candidateDiagnostics", {}),
            "boundaryLineCount": slider_puzzle_result.get("boundaryLineCount", 0),
            "boundaryScore": slider_puzzle_result.get("boundaryScore", 0.0),
            "boundaryConfidenceMargin": slider_puzzle_result.get("boundaryConfidenceMargin", 0.0),
            "boundaryAngleDelta": slider_puzzle_result.get("boundaryAngleDelta", 0.0),
            "boundaryTopAngles": slider_puzzle_result.get("boundaryTopAngles", []),
            "before": before_snapshot,
            "after": after_snapshot,
            "snapshotPath": relative_path(run_dir / "verification" / "captcha_attempts" / slug(keyword) / attempt_dir_name / "snapshot.json"),
        }
        snapshot_path = run_dir / "verification" / "captcha_attempts" / slug(keyword) / attempt_dir_name / "snapshot.json"
        write_json(snapshot_path, record)
        state_path = run_dir / "verification_state.json"
        payload = read_json(state_path, {})
        if not isinstance(payload, dict):
            payload = {}
        failed_attempts = payload.get("failedAttempts") if isinstance(payload.get("failedAttempts"), list) else []
        failed_attempts.append(record)
        payload["failedAttempts"] = failed_attempts
        write_json(state_path, payload)
        return record

    def write_verification_state(
        self,
        page: Any,
        run_dir: Path,
        *,
        keyword: str,
        collected_count: int,
        state: dict[str, str],
        slider_puzzle_result: dict[str, Any] | None = None,
    ) -> None:
        verification_dir = run_dir / "verification"
        verification_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_keyword = slug(keyword)
        screenshot_path = verification_dir / f"{safe_keyword}_{stamp}.png"
        html_path = verification_dir / f"{safe_keyword}_{stamp}.html"
        screenshot_rel = ""
        html_rel = ""
        try:
            page.screenshot(path=str(screenshot_path), full_page=True)
            screenshot_rel = relative_path(screenshot_path)
        except Exception:
            screenshot_rel = ""
        try:
            html_path.write_text(page.content()[:120000], encoding="utf-8")
            html_rel = relative_path(html_path)
        except Exception:
            html_rel = ""
        payload = {
            "schemaVersion": 1,
            "status": state.get("state", "verification_required"),
            "reason": state.get("reason", ""),
            "keyword": keyword,
            "url": str(getattr(page, "url", "") or ""),
            "detectedAt": now_iso(),
            "collectedCount": collected_count,
            "headless": self.headless,
            "screenshotPath": screenshot_rel,
            "htmlSnippetPath": html_rel,
            "message": "Manual action required in the visible Edge window; the discovery job will continue after the page returns to normal.",
        }
        if slider_puzzle_result is not None:
            payload["sliderPuzzle"] = slider_puzzle_result
        previous = read_json(run_dir / "verification_state.json", {})
        if isinstance(previous, dict):
            if isinstance(previous.get("failedAttempts"), list):
                payload["failedAttempts"] = previous["failedAttempts"]
            if isinstance(previous.get("finalFailureSnapshot"), dict):
                payload["finalFailureSnapshot"] = previous["finalFailureSnapshot"]
        write_json(run_dir / "verification_state.json", payload)

    def write_manual_review_failed_state(
        self,
        run_dir: Path,
        page: Any | None = None,
        *,
        keyword: str,
        state: dict[str, str],
        collected_count: int,
        slider_puzzle_result: dict[str, Any] | None = None,
    ) -> None:
        path = run_dir / "verification_state.json"
        payload = read_json(path, {})
        if not isinstance(payload, dict):
            payload = {}
        final_snapshot = {}
        if page is not None:
            final_snapshot = self.capture_verification_snapshot(
                page,
                run_dir,
                keyword=keyword,
                attempt_dir_name=f"final_failure_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                phase="final",
                state=state,
                collected_count=collected_count,
                slider_puzzle_result=slider_puzzle_result,
            )
        payload.update(
            {
                "schemaVersion": 1,
                "status": "manual_review_failed",
                "reason": state.get("reason", "verification_timeout"),
                "keyword": keyword,
                "failedAt": now_iso(),
                "collectedCount": collected_count,
                "headless": self.headless,
                "waitSeconds": self.verification_wait_seconds,
                "manualReview": {
                    "status": "failed",
                    "reason": "timeout_without_feedback",
                },
            }
        )
        if final_snapshot:
            payload["finalFailureSnapshot"] = final_snapshot
        if slider_puzzle_result is not None:
            payload["sliderPuzzle"] = slider_puzzle_result
        write_json(path, payload)

    def wait_for_manual_verification(self, page: Any, run_dir: Path, keyword: str, collected_count: int) -> dict[str, str]:
        state = self.detect_page_state(page)
        if state.get("state") == "ok":
            return state
        if state.get("state") != "verification_required":
            return state
        self.write_verification_state(page, run_dir, keyword=keyword, collected_count=collected_count, state=state)
        slider_puzzle_result: dict[str, Any] = {"attempted": False, "success": False}
        slider_puzzle_attempts: list[dict[str, Any]] = []
        auto_attempt_limit = min(3, max(1, int(self.slider_puzzle_config.get("autoAttempts") or DEFAULT_SLIDER_PUZZLE_AUTO_ATTEMPTS)))
        for auto_attempt in range(1, auto_attempt_limit + 1):
            slider_puzzle_config = dict(self.slider_puzzle_config)
            attempt_dir_name = f"attempt_{auto_attempt:02d}"
            attempt_dir = run_dir / "verification" / "captcha_attempts" / slug(keyword) / attempt_dir_name
            slider_puzzle_config.setdefault("sampleDir", str(attempt_dir / "slider_samples"))
            before_snapshot = self.capture_verification_snapshot(
                page,
                run_dir,
                keyword=keyword,
                attempt_dir_name=attempt_dir_name,
                phase="before",
                state=state,
                collected_count=collected_count,
            )
            attempt_result = solve_tiktok_slider_puzzle(page, slider_puzzle_config)
            attempt_result["autoAttempt"] = auto_attempt
            attempt_result["autoAttemptLimit"] = auto_attempt_limit
            slider_puzzle_attempts.append(attempt_result)
            slider_puzzle_result = dict(attempt_result)
            slider_puzzle_result["autoAttemptHistory"] = slider_puzzle_attempts
            self.write_verification_state(
                page,
                run_dir,
                keyword=keyword,
                collected_count=collected_count,
                state=state,
                slider_puzzle_result=slider_puzzle_result,
            )
            if not attempt_result.get("attempted"):
                break
            if attempt_result.get("releasedForManualConfirmation"):
                page.wait_for_timeout(1000)
            state = self.detect_page_state(page)
            if state.get("state") == "ok":
                write_json(
                    run_dir / "verification_state.json",
                    {
                        "schemaVersion": 1,
                        "status": "resolved",
                        "keyword": keyword,
                        "url": str(getattr(page, "url", "") or ""),
                        "resolvedAt": now_iso(),
                        "collectedCount": collected_count,
                        "sliderPuzzle": slider_puzzle_result,
                    },
                )
                return state
            if state.get("state") != "verification_required":
                return state
            if attempt_result.get("releasedForManualConfirmation") or attempt_result.get("attempted"):
                after_snapshot = self.capture_verification_snapshot(
                    page,
                    run_dir,
                    keyword=keyword,
                    attempt_dir_name=attempt_dir_name,
                    phase="after",
                    state=state,
                    collected_count=collected_count,
                    slider_puzzle_result=slider_puzzle_result,
                )
                failed_reason = (
                    clean_text(attempt_result.get("releaseBlockedReason") or attempt_result.get("error"), max_len=120)
                    or ("manual_confirmation_not_passed" if attempt_result.get("releasedForManualConfirmation") else "auto_attempt_not_released")
                )
                self.append_failed_verification_attempt(
                    run_dir,
                    keyword=keyword,
                    attempt_dir_name=attempt_dir_name,
                    reason=failed_reason,
                    state=state,
                    collected_count=collected_count,
                    before_snapshot=before_snapshot,
                    after_snapshot=after_snapshot,
                    slider_puzzle_result=slider_puzzle_result,
                )
            if not attempt_result.get("releasedForManualConfirmation"):
                if not slider_attempt_retryable_without_release(attempt_result):
                    break
                continue
        if self.headless and not slider_puzzle_result.get("attempted"):
            raise VerificationRequiredError(state.get("state", "verification_required"), state.get("reason", "headless_verification_required"))
        handoff = "slider puzzle module was invoked" if slider_puzzle_result.get("attempted") else "visible Edge window is available"
        print(
            "TikTok keyword discovery needs manual verification; "
            f"{handoff}. keyword={keyword!r}, collected={collected_count}. "
            f"Waiting up to {self.verification_wait_seconds}s..."
        )
        if self.verification_wait_seconds <= 0:
            self.write_manual_review_failed_state(
                run_dir,
                page,
                keyword=keyword,
                state=state,
                collected_count=collected_count,
                slider_puzzle_result=slider_puzzle_result if slider_puzzle_result.get("attempted") else None,
            )
            raise VerificationRequiredError(state.get("state", "verification_required"), state.get("reason", "verification_timeout"), timeout=True)
        deadline = time.monotonic() + self.verification_wait_seconds
        while time.monotonic() <= deadline:
            page.wait_for_timeout(self.verification_poll_seconds * 1000)
            state = self.detect_page_state(page)
            if state.get("state") == "ok":
                payload = {
                    "schemaVersion": 1,
                    "status": "resolved",
                    "keyword": keyword,
                    "url": str(getattr(page, "url", "") or ""),
                    "resolvedAt": now_iso(),
                    "collectedCount": collected_count,
                }
                if slider_puzzle_result.get("attempted"):
                    payload["sliderPuzzle"] = slider_puzzle_result
                write_json(run_dir / "verification_state.json", payload)
                return state
            self.write_verification_state(
                page,
                run_dir,
                keyword=keyword,
                collected_count=collected_count,
                state=state,
                slider_puzzle_result=slider_puzzle_result if slider_puzzle_result.get("attempted") else None,
            )
        self.write_manual_review_failed_state(
            run_dir,
            page,
            keyword=keyword,
            state=state,
            collected_count=collected_count,
            slider_puzzle_result=slider_puzzle_result if slider_puzzle_result.get("attempted") else None,
        )
        raise VerificationRequiredError(state.get("state", "verification_required"), state.get("reason", "verification_timeout"), timeout=True)

    def search_keyword(self, page: Any, keyword: str, limit: int, run_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
        started = time.monotonic()
        response_path = run_dir / "05_search_responses" / f"{slug(keyword)}.jsonl"
        response_recorder = TikTokSearchResponseRecorder(keyword, response_path)
        page.on("response", response_recorder.handle_response)
        links_by_key: dict[str, str] = {}
        cards_by_key: dict[str, dict[str, Any]] = {}
        growth_events: list[dict[str, Any]] = []
        scroll_history: list[dict[str, Any]] = []
        variants = keyword_variants(keyword)
        variants_tried: list[str] = []
        total_scroll_rounds = 0
        final_no_growth_rounds = 0
        stop_reason = "incomplete"
        error = ""

        def pool_key(url: str) -> str:
            return video_id_from_url(url) or url

        def add_link(raw_url: Any) -> bool:
            url = canonical_tiktok_url(str(raw_url or ""))
            if not url:
                return False
            key = pool_key(url)
            if key in links_by_key:
                return False
            links_by_key[key] = url
            return True

        def add_card(raw_card: dict[str, Any], query_variant: str, round_index: int) -> bool:
            url = canonical_tiktok_url(str(raw_card.get("url") or ""))
            if not url:
                return False
            add_link(url)
            key = pool_key(url)
            card = dict(raw_card)
            card["url"] = url
            card.setdefault("videoId", video_id_from_url(url))
            card.setdefault("sourceKeyword", keyword)
            card["queryVariant"] = query_variant
            card["scrollRound"] = round_index
            is_new = key not in cards_by_key
            if is_new:
                card["queryVariants"] = [query_variant]
                card["scrollRounds"] = [round_index]
                cards_by_key[key] = card
                return True
            existing = cards_by_key[key]
            merge_search_card(existing, card)
            existing["queryVariants"] = unique_strings(list(existing.get("queryVariants") or []) + [query_variant])
            existing["scrollRounds"] = sorted({int(value) for value in list(existing.get("scrollRounds") or []) + [round_index]})
            return False

        def capture_current_results(query_variant: str, round_index: int) -> int:
            before_count = len(links_by_key)
            for link in extract_tiktok_links_from_page(page, limit * 3):
                add_link(link)
            for card in extract_tiktok_search_cards_from_page(page, keyword, limit * 3):
                add_card(card, query_variant, round_index)
            return len(links_by_key) - before_count

        def perform_scroll(round_index: int) -> str:
            action = round_index % 3
            if action == 0:
                amount = random.randint(850, 1450)
                page.mouse.wheel(0, amount)
                return f"mouse_wheel:{amount}"
            if action == 1:
                page.keyboard.press("PageDown")
                return "pagedown"
            page.evaluate(
                """() => {
                    const anchors = Array.from(document.querySelectorAll('a[href*="/video/"]'));
                    const last = anchors[anchors.length - 1];
                    if (last) {
                        last.scrollIntoView({ block: 'end', behavior: 'instant' });
                    } else {
                        window.scrollBy(0, 1200);
                    }
                }"""
            )
            return "last_card_scroll_into_view"

        try:
            for variant_index, query_variant in enumerate(variants):
                if len(links_by_key) >= limit:
                    break
                variants_tried.append(query_variant)
                response_recorder.set_context(query_variant, total_scroll_rounds)
                page.goto(f"https://www.tiktok.com/search/video?q={quote(query_variant)}", wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(random_wait_ms(self.scroll_wait_min_ms, self.scroll_wait_max_ms))
                self.wait_for_manual_verification(page, run_dir, keyword, len(links_by_key))
                no_growth_rounds = 0
                for round_index in range(self.max_scrolls + 1):
                    response_recorder.set_context(query_variant, total_scroll_rounds)
                    before_count = len(links_by_key)
                    added_count = capture_current_results(query_variant, total_scroll_rounds)
                    after_count = len(links_by_key)
                    scroll_history.append(
                        {
                            "variant": query_variant,
                            "round": total_scroll_rounds,
                            "beforeCount": before_count,
                            "afterCount": after_count,
                            "addedCount": added_count,
                        }
                    )
                    if added_count > 0:
                        no_growth_rounds = 0
                        growth_events.append(
                            {
                                "variant": query_variant,
                                "round": total_scroll_rounds,
                                "beforeCount": before_count,
                                "afterCount": after_count,
                                "addedCount": added_count,
                            }
                        )
                    else:
                        no_growth_rounds += 1
                    final_no_growth_rounds = no_growth_rounds
                    if len(links_by_key) >= limit:
                        break
                    stop_reason = search_stop_reason(
                        len(links_by_key),
                        limit,
                        no_growth_rounds,
                        self.max_no_growth_rounds,
                        round_index,
                        self.max_scrolls,
                    )
                    if stop_reason in {"target_reached", "no_growth", "max_scrolls"}:
                        break
                    action = perform_scroll(total_scroll_rounds)
                    total_scroll_rounds += 1
                    wait_ms = random_wait_ms(self.scroll_wait_min_ms, self.scroll_wait_max_ms)
                    page.wait_for_timeout(wait_ms)
                    self.wait_for_manual_verification(page, run_dir, keyword, len(links_by_key))
                    scroll_history[-1]["scrollAction"] = action
                    scroll_history[-1]["waitMs"] = wait_ms
                if len(links_by_key) >= limit:
                    stop_reason = "target_reached"
                    break
                if variant_index < len(variants) - 1:
                    stop_reason = "variant_exhausted"
                    continue
            if stop_reason in {"incomplete", "variant_exhausted"}:
                stop_reason = search_stop_reason(
                    len(links_by_key),
                    limit,
                    final_no_growth_rounds,
                    self.max_no_growth_rounds,
                    total_scroll_rounds,
                    self.max_scrolls,
                )
            if links_by_key:
                status = "success"
            else:
                status = "no_links"
                error = "TikTok search returned no video links"
        except VerificationRequiredError as exc:
            stop_reason = "verification_required_timeout" if exc.timeout else "verification_required"
            status = "partial" if links_by_key else "failed"
            error = stop_reason
        except Exception as exc:
            status = "failed"
            error = clean_text(exc, max_len=400)
            stop_reason = "failed"
        try:
            page.remove_listener("response", response_recorder.handle_response)
        except Exception:
            pass
        response_recorder.flush()
        links = list(links_by_key.values())[:limit]
        cards = list(cards_by_key.values())[:limit]
        card_links = {canonical_tiktok_url(card.get("url", "")) for card in cards}
        link_report = {
            "keyword": keyword,
            "status": status,
            "links": links,
            "linkCount": len(links),
            "allocation": limit,
            "scrollRounds": total_scroll_rounds,
            "growthEvents": growth_events,
            "noGrowthRounds": final_no_growth_rounds,
            "stopReason": stop_reason,
            "variantsTried": variants_tried,
            "networkResponseCount": response_recorder.response_count,
            "networkItemCount": response_recorder.item_count,
            "networkCandidateCount": response_recorder.candidate_count,
            "scrollHistory": scroll_history,
            "durationSeconds": round(time.monotonic() - started, 2),
            "error": error,
        }
        card_report = {
            "keyword": keyword,
            "status": "success" if cards else ("partial" if links else status),
            "cards": [card for card in cards if canonical_tiktok_url(card.get("url", "")) in set(links) or canonical_tiktok_url(card.get("url", "")) in card_links],
            "cardCount": len(cards),
            "allocation": limit,
            "scrollRounds": total_scroll_rounds,
            "stopReason": stop_reason,
            "variantsTried": variants_tried,
            "durationSeconds": round(time.monotonic() - started, 2),
            "error": "" if cards else error,
        }
        return link_report, card_report

    def fetch_detail(self, page: Any, url: str, meta: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(self.wait_ms)
            self.assert_page_ok(page)
            dom_fields = extract_detail_dom_fields_from_page(page)
            content = page.content()
            candidate = candidate_from_tiktok_html(content, url, meta, dom_fields=dom_fields)
            return {
                "status": "success",
                "url": url,
                "candidate": candidate,
                "missingFields": candidate_missing_fields(candidate),
                "durationSeconds": round(time.monotonic() - started, 2),
                "htmlSnippet": content[:12000],
            }
        except Exception as exc:
            return {
                "status": "failed",
                "url": url,
                "error": clean_text(exc, max_len=400),
                "durationSeconds": round(time.monotonic() - started, 2),
            }

    def resolve_url_candidate(self, url: str, meta: dict[str, Any], detail_page_factory: Any) -> dict[str, Any]:
        started = time.monotonic()
        source_summary = {
            "networkItemCount": len(meta.get("networkItems") or []),
            "cardCount": len(meta.get("cards") or []),
        }
        search_candidate = candidate_from_search_meta(url, meta)
        missing = candidate_missing_fields(search_candidate)
        if not missing:
            return {
                "status": "success",
                "url": url,
                "candidate": search_candidate,
                "missingFields": [],
                "fallbackAttempted": False,
                "sourceSummary": source_summary,
                "durationSeconds": round(time.monotonic() - started, 2),
            }
        engagement_missing = [field for field in missing if field in {"playCount", "diggCount", "commentCount"}]
        if engagement_missing:
            return {
                "status": "failed",
                "url": url,
                "error": "missing_engagement_stats",
                "missingFields": missing,
                "fallbackAttempted": False,
                "fallbackSkippedReason": "engagement_stats_not_filled_from_detail_page",
                "sourceSummary": source_summary,
                "partialCandidate": search_candidate,
                "durationSeconds": round(time.monotonic() - started, 2),
            }
        detail_report: dict[str, Any] = {}
        fallback_error = ""
        try:
            detail_report = self.fetch_detail(detail_page_factory(), url, meta)
            if detail_report.get("status") == "success" and isinstance(detail_report.get("candidate"), dict):
                merged = merge_candidate(search_candidate, detail_report["candidate"])
                merged_missing = candidate_missing_fields(merged)
                if not merged_missing:
                    return {
                        "status": "success",
                        "url": url,
                        "candidate": merged,
                        "missingFields": [],
                        "fallbackAttempted": True,
                        "fallbackStatus": "success",
                        "sourceSummary": source_summary,
                        "durationSeconds": round(time.monotonic() - started, 2),
                        "htmlSnippet": detail_report.get("htmlSnippet", ""),
                    }
                missing = merged_missing
                search_candidate = merged
            else:
                fallback_error = detail_report.get("error") or detail_report.get("status") or ""
        except Exception as exc:
            fallback_error = clean_text(exc, max_len=400)
        return {
            "status": "failed",
            "url": url,
            "error": "missing_engagement_stats" if any(field in missing for field in ["playCount", "diggCount", "commentCount"]) else "missing_required_fields",
            "missingFields": missing,
            "fallbackAttempted": True,
            "fallbackStatus": detail_report.get("status", "failed") if detail_report else "failed",
            "fallbackError": fallback_error,
            "sourceSummary": source_summary,
            "partialCandidate": search_candidate,
            "durationSeconds": round(time.monotonic() - started, 2),
            "htmlSnippet": detail_report.get("htmlSnippet", "") if detail_report else "",
        }


def load_search_metadata(search_plan: list[dict[str, Any]], run_dir: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    link_dir = run_dir / "05_search_links"
    card_dir = run_dir / "05_search_cards"
    response_dir = run_dir / "05_search_responses"
    metadata_by_url: dict[str, dict[str, Any]] = {}
    rejected: list[dict[str, Any]] = []

    def ensure_meta(url: str, entry: dict[str, Any]) -> dict[str, Any]:
        clean_url = canonical_tiktok_url(url)
        meta = metadata_by_url.setdefault(clean_url, {"url": clean_url, "sourceQueries": [], "planEntries": [], "cards": [], "networkItems": []})
        keyword = clean_text(entry.get("keyword"))
        if keyword and keyword not in meta["sourceQueries"]:
            meta["sourceQueries"].append(keyword)
        if entry and entry not in meta["planEntries"]:
            meta["planEntries"].append(entry)
        return meta

    for entry in search_plan:
        keyword = clean_text(entry.get("keyword"))
        file_slug = slug(keyword)
        link_path = link_dir / f"{file_slug}.json"
        card_path = card_dir / f"{file_slug}.json"
        response_path = response_dir / f"{file_slug}.jsonl"
        if not link_path.exists() and not card_path.exists() and not response_path.exists():
            rejected.append({"stage": "details", "keyword": keyword, "reason": "missing_search_links_artifact"})
            continue
        link_report = read_json(link_path, {}) if link_path.exists() else {}
        for raw_url in link_report.get("links", []) or []:
            url = canonical_tiktok_url(raw_url)
            if url:
                ensure_meta(url, entry)
        card_report = read_json(card_path, {}) if card_path.exists() else {}
        for raw_card in card_report.get("cards", []) or []:
            if not isinstance(raw_card, dict):
                continue
            url = canonical_tiktok_url(raw_card.get("url", ""))
            if not url:
                continue
            card = dict(raw_card)
            card["url"] = url
            card.setdefault("sourceKeyword", keyword)
            card.setdefault("videoId", video_id_from_url(url))
            meta = ensure_meta(url, entry)
            if not any(existing.get("url") == url and existing.get("rank") == card.get("rank") for existing in meta["cards"]):
                meta["cards"].append(card)
        if response_path.exists():
            try:
                lines = response_path.read_text(encoding="utf-8").splitlines()
            except Exception:
                lines = []
            for line in lines:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except Exception:
                    rejected.append({"stage": "details", "keyword": keyword, "reason": "invalid_search_response_jsonl"})
                    continue
                if not isinstance(record, dict):
                    continue
                for raw_item in record.get("items", []) or []:
                    if not isinstance(raw_item, dict):
                        continue
                    url = canonical_tiktok_url(raw_item.get("url", ""))
                    if not url:
                        continue
                    item = dict(raw_item)
                    item.setdefault("sourceKeyword", keyword)
                    item.setdefault("responseUrl", record.get("url"))
                    item.setdefault("queryVariant", record.get("queryVariant"))
                    item.setdefault("scrollRound", record.get("scrollRound"))
                    meta = ensure_meta(url, entry)
                    if not any(existing.get("videoId") == item.get("videoId") and existing.get("responseUrl") == item.get("responseUrl") for existing in meta["networkItems"]):
                        meta["networkItems"].append(item)
    return {url: meta for url, meta in metadata_by_url.items() if url}, rejected


def summarize_search_response_artifacts(run_dir: Path) -> dict[str, int]:
    response_dir = run_dir / "05_search_responses"
    summary = {"responseCount": 0, "itemCount": 0, "candidateCount": 0}
    if not response_dir.exists():
        return summary
    for path in response_dir.glob("*.jsonl"):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except Exception:
                continue
            if not isinstance(record, dict):
                continue
            summary["responseCount"] += 1
            summary["itemCount"] += int(record.get("itemCount") or 0)
            summary["candidateCount"] += int(record.get("candidateCount") or 0)
    return summary


def count_detail_fallbacks(run_dir: Path) -> int:
    detail_dir = run_dir / "06_detail_raw"
    if not detail_dir.exists():
        return 0
    count = 0
    for path in detail_dir.glob("*.json"):
        report = read_json(path, {})
        if isinstance(report, dict) and report.get("fallbackAttempted"):
            count += 1
    return count


def compact_plan_entry(entry: dict[str, Any]) -> dict[str, Any]:
    compact = {
        "keyword": clean_text(entry.get("keyword")),
        "layer": clean_text(entry.get("layer")),
        "allocation": int(entry.get("allocation") or 0),
        "source": clean_text(entry.get("source")),
        "fitType": clean_text(entry.get("fitType")),
        "score": entry.get("score", 0),
    }
    if isinstance(entry.get("scoreDetails"), dict):
        compact["scoreDetails"] = entry["scoreDetails"]
    if isinstance(entry.get("eventContext"), dict):
        compact["eventContext"] = entry["eventContext"]
    if clean_text(entry.get("externalSource")):
        compact["externalSource"] = clean_text(entry.get("externalSource"))
    if clean_text(entry.get("sourceUrl")):
        compact["sourceUrl"] = clean_text(entry.get("sourceUrl"), max_len=600)
    if isinstance(entry.get("rawTrend"), dict):
        compact["rawTrend"] = entry["rawTrend"]
    return {key: value for key, value in compact.items() if value not in ("", None, [], {})}


def layer_metadata_from_plan_entries(entries: list[dict[str, Any]]) -> dict[str, Any]:
    compact_entries = [compact_plan_entry(entry) for entry in entries if isinstance(entry, dict)]
    layers = unique_strings([clean_text(entry.get("layer")) for entry in compact_entries if entry.get("layer")])
    fit_types = unique_strings([clean_text(entry.get("fitType")) for entry in compact_entries if entry.get("fitType")])
    event_contexts = []
    for entry in compact_entries:
        context = entry.get("eventContext")
        if isinstance(context, dict) and context not in event_contexts:
            event_contexts.append(context)
    return {
        "planEntries": compact_entries,
        "keywordLayers": layers,
        "fitTypes": fit_types,
        "eventContexts": event_contexts,
        "primaryLayer": layers[0] if layers else "",
        "primaryFitType": fit_types[0] if fit_types else "",
    }


def iter_json_objects(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        found.append(value)
        for child in value.values():
            found.extend(iter_json_objects(child))
    elif isinstance(value, list):
        for item in value:
            found.extend(iter_json_objects(item))
    return found


def load_embedded_json_objects(content: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for script_id in ["__UNIVERSAL_DATA_FOR_REHYDRATION__", "SIGI_STATE", "__NEXT_DATA__"]:
        match = re.search(
            rf"<script[^>]+id=[\"']{script_id}[\"'][^>]*>(.*?)</script>",
            content or "",
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            continue
        raw = html.unescape(match.group(1))
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        objects.extend(iter_json_objects(payload))
    for match in re.finditer(
        r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        content or "",
        flags=re.IGNORECASE | re.DOTALL,
    ):
        raw = html.unescape(match.group(1)).strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        objects.extend(iter_json_objects(payload))
    return objects


def first_value(source: dict[str, Any], keys: list[str], default: Any = "") -> Any:
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return value
    return default


def nested_first(source: dict[str, Any], paths: list[list[str]], default: Any = "") -> Any:
    for parts in paths:
        current: Any = source
        for part in parts:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(part)
        if current not in (None, ""):
            return current
    return default


def safe_int(value: Any) -> int:
    try:
        if isinstance(value, str):
            value = value.replace(",", "")
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def choose_video_object(objects: list[dict[str, Any]], video_id: str) -> dict[str, Any]:
    scored: list[tuple[int, dict[str, Any]]] = []
    for obj in objects:
        score = 0
        serialized = json.dumps(obj, ensure_ascii=False)[:30000]
        exact_id = clean_text(first_from_dicts([obj], ["id", "awemeId", "aweme_id", "itemId", "item_id", "videoId", "video_id"]))
        if video_id and exact_id == video_id:
            score += 12
        elif video_id and video_id in serialized:
            score += 5
        if any(key in obj for key in ["itemStruct", "awemeInfo", "desc", "description", "stats", "statsV2", "video", "author", "interactionStatistic"]):
            score += 3
        if "videoobject" in clean_text(obj.get("@type")).lower():
            score += 3
        metric_presence = 0
        for key in ["playCount", "play_count", "viewCount", "view_count", "diggCount", "likeCount", "commentCount", "comment_count", "shareCount"]:
            if normalized_metric_value(obj.get(key)) is not None:
                metric_presence += 1
        stats = first_from_dicts([obj], ["statsV2", "stats", "statistics"])
        if isinstance(stats, dict):
            for key in ["playCount", "play_count", "viewCount", "view_count", "diggCount", "likeCount", "commentCount", "comment_count", "shareCount"]:
                if normalized_metric_value(stats.get(key)) is not None:
                    metric_presence += 1
        metric_presence += len(metric_stats_from_interaction_statistics(first_from_dicts([obj], ["interactionStatistic"])))
        if metric_presence:
            score += 2 + metric_presence
        if not (video_id and video_id in serialized) and metric_presence == 0:
            continue
        if score:
            scored.append((score, obj))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1] if scored else {}


def meta_content(content: str, names: list[str]) -> str:
    for name in names:
        pattern = rf"<meta[^>]+(?:name|property)=[\"']{re.escape(name)}[\"'][^>]+content=[\"']([^\"']*)[\"']"
        match = re.search(pattern, content or "", flags=re.IGNORECASE)
        if match:
            return clean_text(html.unescape(match.group(1)))
    return ""


def value_present(value: Any) -> bool:
    return value not in (None, "", [], {})


def first_from_dicts(dicts: list[dict[str, Any]], keys: list[str]) -> Any:
    for source in dicts:
        if not isinstance(source, dict):
            continue
        for key in keys:
            value = source.get(key)
            if value_present(value):
                return value
    return ""


def first_metric_from_dicts(dicts: list[dict[str, Any]], keys: list[str]) -> Any:
    for source in dicts:
        if not isinstance(source, dict):
            continue
        for key in keys:
            metric = normalized_metric_value(source.get(key))
            if metric is not None:
                return metric
    return ""


def normalize_time_pair(value: Any) -> dict[str, Any]:
    if not value_present(value):
        return {}
    if isinstance(value, (int, float)):
        timestamp = int(value)
        if timestamp > 10_000_000_000:
            timestamp = int(timestamp / 1000)
        if 1_400_000_000 <= timestamp <= 2_200_000_000:
            return {
                "createTime": timestamp,
                "createTimeISO": datetime.fromtimestamp(timestamp).isoformat(timespec="seconds"),
            }
        return {}
    text = clean_text(value)
    if not text:
        return {}
    if re.fullmatch(r"\d{10,13}", text):
        return normalize_time_pair(int(text))
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return {"createTimeISO": text}
    return {
        "createTime": int(dt.timestamp()),
        "createTimeISO": dt.isoformat(timespec="seconds"),
    }


def metric_stats_from_interaction_statistics(value: Any) -> dict[str, Any]:
    entries = value if isinstance(value, list) else [value]
    stats: dict[str, Any] = {}
    mapping = {
        "watchaction": "playCount",
        "viewaction": "playCount",
        "likeaction": "diggCount",
        "commentaction": "commentCount",
        "shareaction": "shareCount",
    }
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw_type = clean_text(entry.get("interactionType") or entry.get("@type")).lower()
        key = ""
        for marker, mapped in mapping.items():
            if marker in raw_type:
                key = mapped
                break
        if not key:
            continue
        metric = normalized_metric_value(entry.get("userInteractionCount"))
        if metric is not None:
            stats[key] = metric
    return stats


def hashtag_list_from_values(*values: Any) -> list[str]:
    tags: list[str] = []
    for value in values:
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    tag = clean_text(first_value(item, ["title", "name", "hashtagName"], ""))
                else:
                    tag = clean_text(item)
                if tag:
                    tags.append(tag.lstrip("#"))
        else:
            tags.extend(tag.lstrip("#") for tag in re.findall(r"#([A-Za-z0-9_]+)", str(value or "")))
    return unique_strings(tags)


def candidate_nested_objects(obj: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [obj] if isinstance(obj, dict) else []
    if not isinstance(obj, dict):
        return []
    for key in ["itemStruct", "item", "aweme", "awemeInfo", "aweme_info"]:
        value = obj.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    item_info = obj.get("itemInfo")
    if isinstance(item_info, dict) and isinstance(item_info.get("itemStruct"), dict):
        candidates.append(item_info["itemStruct"])
    return candidates


def compact_video_fields_from_object(obj: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(obj, dict) or not obj:
        return {}
    best: dict[str, Any] = {}
    for candidate in candidate_nested_objects(obj):
        stats = first_from_dicts([candidate], ["statsV2", "stats", "statistics", "statsInfo"])
        stats = stats if isinstance(stats, dict) else {}
        interaction_stats = metric_stats_from_interaction_statistics(first_from_dicts([candidate], ["interactionStatistic"]))
        if interaction_stats:
            stats = {**stats, **interaction_stats}
        video = first_from_dicts([candidate], ["video", "videoMeta"])
        video = video if isinstance(video, dict) else {}
        author = first_from_dicts([candidate], ["author", "authorMeta", "authorInfo"])
        author = author if isinstance(author, dict) else {}
        author_stats = first_from_dicts([candidate], ["authorStats"])
        author_stats = author_stats if isinstance(author_stats, dict) else {}
        text = clean_text(first_from_dicts([candidate], ["desc", "description", "text", "title", "caption", "name"]))
        time_fields = normalize_time_pair(
            first_from_dicts(
                [candidate],
                ["createTime", "create_time", "createTimestamp", "createdAt", "timestamp", "datePublished", "uploadDate"],
            )
        )
        fields = {
            "id": clean_text(first_from_dicts([candidate], ["id", "awemeId", "aweme_id", "itemId", "item_id", "videoId", "video_id"])),
            "text": text,
            "textLanguage": clean_text(first_from_dicts([candidate], ["textLanguage", "language"]) or "unknown"),
            "hashtags": hashtag_list_from_values(first_from_dicts([candidate], ["challenges", "hashtags"]), text),
            "diggCount": first_metric_from_dicts([stats, candidate], ["diggCount", "digg_count", "likeCount", "like_count", "likes", "like_count_str"]),
            "shareCount": first_metric_from_dicts([stats, candidate], ["shareCount", "share_count", "shares", "share_count_str"]),
            "commentCount": first_metric_from_dicts([stats, candidate], ["commentCount", "comment_count", "comments", "comment_count_str"]),
            "playCount": first_metric_from_dicts([stats, candidate], ["playCount", "play_count", "viewCount", "view_count", "views", "plays", "play_count_str"]),
            "duration": first_from_dicts([video, candidate], ["duration"]),
            "coverUrl": clean_text(first_from_dicts([video, candidate], ["cover", "originCover", "dynamicCover", "coverUrl", "thumbnailUrl", "thumbnail", "image"])),
            "authorNickName": clean_text(first_from_dicts([author], ["nickname", "nickName", "name", "uniqueId", "unique_id", "id", "username"])),
            "authorUniqueId": clean_text(first_from_dicts([author], ["uniqueId", "unique_id", "id", "username", "alternateName"])),
            "authorFans": first_metric_from_dicts([author_stats, author], ["followerCount", "fans", "followers"]),
            "createTime": time_fields.get("createTime", ""),
            "createTimeISO": clean_text(time_fields.get("createTimeISO", "")),
        }
        fields = {key: value for key, value in fields.items() if value_present(value)}
        if len(fields) > len(best):
            best = fields
    return best


def _legacy_clean_card_caption_unused(raw_text: str) -> str:
    text = clean_text(raw_text, max_len=800)
    text = re.sub(
        r"([0-9][0-9,]*(?:\.[0-9]+)?\s*[kmb万亿]?)\s*(views?|plays?|likes?|comments?|shares?|播放|观看|点赞|评论|回复|分享|转发)",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s+", " ", text).strip()
    return text[:500]


def clean_card_caption(raw_text: str) -> str:
    text = clean_text(raw_text, max_len=800)
    metric = (
        r"([0-9][0-9,]*(?:\.[0-9]+)?\s*[kmb\u4e07\u4ebf]?)\s*"
        r"(views?|plays?|likes?|comments?|shares?|\u64ad\u653e|\u89c2\u770b|"
        r"\u70b9\u8d5e|\u8bc4\u8bba|\u56de\u590d|\u5206\u4eab|\u8f6c\u53d1)"
    )
    text = re.sub(metric, " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:500]


def set_field(fields: dict[str, Any], sources: dict[str, str], key: str, value: Any, source: str) -> None:
    if key in fields or not value_present(value):
        return
    fields[key] = value
    sources[key] = source


def set_metric_field(fields: dict[str, Any], sources: dict[str, str], key: str, value: Any, source: str) -> None:
    if key in fields:
        return
    metric = normalized_metric_value(value)
    if metric is None:
        return
    fields[key] = metric
    sources[key] = source


def candidate_from_compact_fields(
    url: str,
    meta: dict[str, Any],
    fields: dict[str, Any],
    field_sources: dict[str, str],
    parse_sources: list[str],
) -> dict[str, Any]:
    canonical_url = canonical_tiktok_url(url) or url
    video_id = clean_text(fields.get("id")) or video_id_from_url(canonical_url)
    timestamp_fields = video_time_fields_from_id(video_id)
    for key, value in timestamp_fields.items():
        if not value_present(fields.get(key)):
            fields[key] = value
            field_sources[key] = "video_id_timestamp"
            parse_sources.append("video_id_timestamp")
    text = clean_text(fields.get("text"), max_len=1200)
    hashtags = fields.get("hashtags") if isinstance(fields.get("hashtags"), list) else []
    hashtags = unique_strings([*hashtags, *hashtag_list_from_values(text)])
    source_queries = meta.get("sourceQueries") or []
    layer_meta = layer_metadata_from_plan_entries(meta.get("planEntries") or [])
    author = author_from_url(canonical_url)
    cover_url = clean_text(fields.get("coverUrl"))
    candidate = {
        "id": video_id,
        "text": text,
        "textLanguage": clean_text(fields.get("textLanguage") or "unknown"),
        "hashtags": hashtags,
        "diggCount": safe_int(fields.get("diggCount")),
        "shareCount": safe_int(fields.get("shareCount")),
        "commentCount": safe_int(fields.get("commentCount")),
        "playCount": safe_int(fields.get("playCount")),
        "videoMeta": {
            "duration": safe_int(fields.get("duration")),
            "downloadAddr": "",
            "webVideoUrl": canonical_url,
            "coverUrl": cover_url,
        },
        "webVideoUrl": canonical_url,
        "mediaUrls": [cover_url] if cover_url else [],
        "authorMeta": {
            "nickName": clean_text(fields.get("authorNickName") or fields.get("authorUniqueId") or author),
            "uniqueId": clean_text(fields.get("authorUniqueId") or author),
            "fans": safe_int(fields.get("authorFans")),
        },
        "createTime": fields.get("createTime", ""),
        "createTimeISO": clean_text(fields.get("createTimeISO")),
        "sourcePath": "tiktok_cookie_discovery",
        "sourceQuery": clean_text(source_queries[0] if source_queries else ""),
        "searchQuery": clean_text(source_queries[0] if source_queries else ""),
        "captureSource": "tiktok_keyword_discovery",
        "tiktokKeywordDiscoveryLayer": layer_meta["primaryLayer"],
        "tiktokKeywordDiscoveryFitType": layer_meta["primaryFitType"],
        "tiktokKeywordDiscovery": {
            "sourceQueries": source_queries,
            "productContexts": [ctx for entry in meta.get("planEntries", []) for ctx in entry.get("productContexts", [])],
            "planEntries": layer_meta["planEntries"],
            "keywordLayers": layer_meta["keywordLayers"],
            "fitTypes": layer_meta["fitTypes"],
            "eventContexts": layer_meta["eventContexts"],
            "parseProvenance": {
                "sources": unique_strings(parse_sources),
                "fields": dict(field_sources),
            },
        },
    }
    return candidate


def candidate_from_search_meta(url: str, meta: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    field_sources: dict[str, str] = {}
    parse_sources: list[str] = []
    for network_item in meta.get("networkItems") or []:
        network_fields = network_item.get("fields") if isinstance(network_item.get("fields"), dict) else {}
        for key, value in network_fields.items():
            if key in {"playCount", "diggCount", "commentCount", "shareCount", "authorFans"}:
                set_metric_field(fields, field_sources, key, value, "search_network_json")
            else:
                set_field(fields, field_sources, key, value, "search_network_json")
        for source in network_item.get("parseSources") or ["search_network_json"]:
            parse_sources.append(source)
    cards = sorted(meta.get("cards") or [], key=lambda item: int(item.get("rank") or 999999))
    for card in cards:
        embedded = card.get("embeddedFields") if isinstance(card.get("embeddedFields"), dict) else {}
        for key, value in embedded.items():
            if key in {"playCount", "diggCount", "commentCount", "shareCount"}:
                set_metric_field(fields, field_sources, key, value, "search_embedded_json")
            else:
                set_field(fields, field_sources, key, value, "search_embedded_json")
        raw_stats = card.get("rawStats") if isinstance(card.get("rawStats"), dict) else {}
        html_stats = extract_metric_stats_from_html_attrs(clean_text(card.get("htmlSnippet"), max_len=12000))
        raw_stats = {**raw_stats, **html_stats}
        for key in ["playCount", "diggCount", "commentCount", "shareCount"]:
            set_metric_field(fields, field_sources, key, raw_stats.get(key), "search_card_dom")
        set_field(fields, field_sources, "text", clean_card_caption(embedded.get("text") or card.get("rawText") or card.get("anchorText") or ""), "search_card_dom")
        set_field(fields, field_sources, "authorUniqueId", embedded.get("authorUniqueId"), "search_card_dom")
        covers = card.get("coverCandidates") if isinstance(card.get("coverCandidates"), list) else []
        if covers:
            set_field(fields, field_sources, "coverUrl", covers[0], "search_card_dom")
        for source in card.get("parseSources") or []:
            parse_sources.append(source)
    return candidate_from_compact_fields(url, meta, fields, field_sources, parse_sources or ["search_card_dom"])


def candidate_from_tiktok_html(content: str, url: str, meta: dict[str, Any], dom_fields: dict[str, Any] | None = None) -> dict[str, Any]:
    video_id = video_id_from_url(url)
    objects = load_embedded_json_objects(content)
    obj = choose_video_object(objects, video_id)
    fields = compact_video_fields_from_object(obj)
    field_sources = {key: "detail_html" for key in fields}
    for key, value in (dom_fields or {}).items():
        if key in {"playCount", "diggCount", "commentCount", "shareCount"}:
            set_metric_field(fields, field_sources, key, value, "detail_dom")
        else:
            set_field(fields, field_sources, key, value, "detail_dom")
    html_stats = extract_metric_stats_from_html_attrs(content)
    for key, value in html_stats.items():
        set_metric_field(fields, field_sources, key, value, "detail_html")
    if not fields.get("text"):
        text = meta_content(content, ["description", "og:description", "twitter:description"])
        set_field(fields, field_sources, "text", text, "detail_html")
    if not fields.get("coverUrl"):
        cover_url = meta_content(content, ["og:image", "twitter:image"])
        set_field(fields, field_sources, "coverUrl", cover_url, "detail_html")
    return candidate_from_compact_fields(url, meta, fields, field_sources, ["detail_html"])


def candidate_missing_fields(candidate: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    provenance = (candidate.get("tiktokKeywordDiscovery") or {}).get("parseProvenance") or {}
    field_sources = provenance.get("fields") if isinstance(provenance.get("fields"), dict) else {}
    if not clean_text(candidate.get("id")):
        missing.append("id")
    if not clean_text(candidate.get("webVideoUrl") or (candidate.get("videoMeta") or {}).get("webVideoUrl")):
        missing.append("webVideoUrl")
    if not value_present(candidate.get("createTime")) and not clean_text(candidate.get("createTimeISO")):
        missing.append("createTime")
    for key in ["playCount", "diggCount", "commentCount"]:
        if key not in field_sources and not safe_int(candidate.get(key)):
            missing.append(key)
    return missing


def merge_candidate(primary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    if not primary:
        return fallback
    if not fallback:
        return primary
    merged = dict(primary)
    primary_provenance = ((primary.get("tiktokKeywordDiscovery") or {}).get("parseProvenance") or {})
    fallback_provenance = ((fallback.get("tiktokKeywordDiscovery") or {}).get("parseProvenance") or {})
    primary_fields = dict(primary_provenance.get("fields") or {})
    fallback_fields = dict(fallback_provenance.get("fields") or {})
    for key in ["text", "textLanguage", "diggCount", "shareCount", "commentCount", "playCount", "createTime", "createTimeISO"]:
        metric_missing = key in {"diggCount", "shareCount", "commentCount", "playCount"} and key not in primary_fields and key in fallback_fields
        value_missing = key not in primary_fields and not value_present(merged.get(key))
        if (metric_missing or value_missing) and value_present(fallback.get(key)):
            merged[key] = fallback[key]
            if key in fallback_fields:
                primary_fields[key] = fallback_fields[key]
    primary_video = dict(primary.get("videoMeta") or {})
    fallback_video = fallback.get("videoMeta") or {}
    for key in ["duration", "coverUrl"]:
        if not value_present(primary_video.get(key)) and value_present(fallback_video.get(key)):
            primary_video[key] = fallback_video[key]
            field_name = "coverUrl" if key == "coverUrl" else "duration"
            if field_name in fallback_fields:
                primary_fields[field_name] = fallback_fields[field_name]
    merged["videoMeta"] = primary_video
    if not merged.get("mediaUrls") and primary_video.get("coverUrl"):
        merged["mediaUrls"] = [primary_video["coverUrl"]]
    author = dict(primary.get("authorMeta") or {})
    fallback_author = fallback.get("authorMeta") or {}
    for key in ["nickName", "uniqueId", "fans"]:
        if not value_present(author.get(key)) and value_present(fallback_author.get(key)):
            author[key] = fallback_author[key]
    merged["authorMeta"] = author
    merged_hashtags = unique_strings(list(primary.get("hashtags") or []) + list(fallback.get("hashtags") or []))
    merged["hashtags"] = merged_hashtags
    merged_tkd = dict(primary.get("tiktokKeywordDiscovery") or {})
    merged_sources = unique_strings(list(primary_provenance.get("sources") or []) + list(fallback_provenance.get("sources") or []))
    merged_tkd["parseProvenance"] = {
        "sources": merged_sources,
        "fields": primary_fields,
    }
    merged["tiktokKeywordDiscovery"] = merged_tkd
    return merged


def write_latest(config: dict[str, Any], report: dict[str, Any]) -> None:
    latest = {
        "schemaVersion": 1,
        "runId": report.get("runId", config["runId"]),
        "status": report.get("status", "failed"),
        "generatedAt": report.get("finishedAt") or now_iso(),
        "approvedCount": report.get("approvedCount", 0),
        "rejectedCount": report.get("rejectedCount", 0),
        "paths": {
            "report": relative_path(Path(config["runDir"]) / "report.json"),
            "stageRecords": relative_path(Path(config["runDir"]) / "00_stage_records.json"),
            "approved": relative_path(Path(config["runDir"]) / "10_approved.json"),
            "rejected": relative_path(Path(config["runDir"]) / "09_rejected.json"),
        },
        "error": report.get("error", ""),
    }
    if report.get("keywordLayerSummary"):
        latest["keywordLayerSummary"] = report["keywordLayerSummary"]
    if report.get("feedbackTuningSummary"):
        latest["feedbackTuningSummary"] = report["feedbackTuningSummary"]
    if report.get("targetCandidateTotal") is not None:
        latest["targetCandidateTotal"] = report.get("targetCandidateTotal")
    write_json(Path(config["latestPath"]), latest)


def stage_artifact_paths(run_dir: Path, stage: str) -> dict[str, str]:
    mapping: dict[str, list[Path]] = {
        "stage0": [
            run_dir / "01_feedback_seeds.json",
            run_dir / "02_external_hot_trends.json",
            run_dir / "02_external_preheat_events.json",
            run_dir / "02_product_doc_snapshot.md",
            run_dir / "02_product_doc_snapshot.json",
            run_dir / "03_keyword_candidates.json",
            run_dir / "04_search_plan_stage0.json",
        ],
        "stage1": [
            run_dir / "04_feedback_tuning.json",
            run_dir / "04_search_plan.json",
        ],
        "stage2": [
            run_dir / "05_search_links",
            run_dir / "05_search_cards",
            run_dir / "05_search_responses",
            run_dir / "09_rejected.json",
        ],
        "stage3": [
            run_dir / "06_detail_raw",
            run_dir / "06_detail_html",
            run_dir / "07_candidates.json",
            run_dir / "09_rejected.json",
        ],
        "stage4": [
            run_dir / "08_filtered.json",
            run_dir / "09_rejected.json",
            run_dir / "10_approved.json",
        ],
        "stage5": [
            run_dir / "00_config.json",
            run_dir / "00_stage_records.json",
            run_dir / "report.json",
            Path(run_dir.parent.parent) / "latest.json",
        ],
    }
    result: dict[str, str] = {}
    for path in mapping.get(stage, []):
        result[path.name if path.is_file() or path.suffix else path.name] = relative_path(path)
    return result


def append_stage_record(
    run_dir: Path,
    config: dict[str, Any],
    *,
    stage: str,
    status: str,
    started_at: str,
    counts: dict[str, Any] | None = None,
    error: str = "",
) -> None:
    path = run_dir / "00_stage_records.json"
    payload = read_json(path, {})
    if not isinstance(payload, dict):
        payload = {}
    records = payload.get("records")
    if not isinstance(records, list):
        records = []
    finished_at = now_iso()
    record = {
        "stage": stage,
        "status": status,
        "startedAt": started_at,
        "finishedAt": "" if status == "in_progress" else finished_at,
        "durationSeconds": 0.0
        if status == "in_progress"
        else max(
            0.0,
            round(
                (
                    datetime.fromisoformat(finished_at).timestamp()
                    - datetime.fromisoformat(started_at).timestamp()
                ),
                3,
            ),
        ),
        "counts": counts or {},
        "artifacts": stage_artifact_paths(run_dir, stage),
        "error": clean_text(error, max_len=600),
    }
    updated_existing = False
    if status != "in_progress":
        for index in range(len(records) - 1, -1, -1):
            existing = records[index]
            if isinstance(existing, dict) and existing.get("stage") == stage and existing.get("status") == "in_progress":
                record["startedAt"] = clean_text(existing.get("startedAt")) or started_at
                record["durationSeconds"] = max(
                    0.0,
                    round(
                        (
                            datetime.fromisoformat(finished_at).timestamp()
                            - datetime.fromisoformat(record["startedAt"]).timestamp()
                        ),
                        3,
                    ),
                )
                records[index] = record
                updated_existing = True
                break
    if not updated_existing:
        records.append(record)
    write_json(
        path,
        {
            "schemaVersion": 1,
            "runId": config["runId"],
            "requestedStage": config.get("requestedStage", config["stage"]),
            "canonicalStage": config["stage"],
            "updatedAt": finished_at,
            "records": records,
        },
    )


def ensure_artifact_skeleton(run_dir: Path) -> None:
    for dirname in ["05_search_links", "05_search_cards", "05_search_responses", "06_detail_raw", "06_detail_html"]:
        (run_dir / dirname).mkdir(parents=True, exist_ok=True)
    for filename in [
        "00_stage_records.json",
        "01_feedback_seeds.json",
        "02_external_hot_trends.json",
        "02_external_preheat_events.json",
        "02_product_doc_snapshot.json",
        "03_keyword_candidates.json",
        "04_search_plan_stage0.json",
        "04_feedback_tuning.json",
        "04_search_plan.json",
        "07_candidates.json",
        "08_filtered.json",
        "09_rejected.json",
        "10_approved.json",
    ]:
        path = run_dir / filename
        if not path.exists():
            write_json(
                path,
                {}
                if filename
                in {"00_stage_records.json", "02_product_doc_snapshot.json", "02_external_hot_trends.json", "02_external_preheat_events.json", "04_feedback_tuning.json"}
                else [],
            )
    doc_path = run_dir / "02_product_doc_snapshot.md"
    if not doc_path.exists():
        doc_path.write_text("", encoding="utf-8")


def has_successful_stage_record(run_dir: Path, stage_name: str) -> bool:
    payload = read_json(run_dir / "00_stage_records.json", {})
    records = payload.get("records") if isinstance(payload, dict) else []
    if not isinstance(records, list):
        return False
    return any(
        isinstance(record, dict)
        and clean_text(record.get("stage")) == stage_name
        and clean_text(record.get("status")) == "success"
        for record in records
    )


def stage_keywords(config: dict[str, Any], args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    run_dir = Path(config["runDir"])
    seeds_path = run_dir / "01_feedback_seeds.json"
    doc_md_path = run_dir / "02_product_doc_snapshot.md"
    doc_json_path = run_dir / "02_product_doc_snapshot.json"
    candidates_path = run_dir / "03_keyword_candidates.json"
    stage0_plan_path = run_dir / "04_search_plan_stage0.json"
    plan_path = run_dir / "04_search_plan.json"
    if config["resume"] and all(path.exists() for path in [seeds_path, doc_json_path, candidates_path]) and (stage0_plan_path.exists() or plan_path.exists()):
        return (
            read_json(seeds_path, []),
            read_json(candidates_path, []),
            read_json(stage0_plan_path, read_json(plan_path, [])),
        )
    seeds = load_feedback_seeds(config, args)
    write_json(seeds_path, seeds)
    product_doc_path = Path(config["productDocPath"])
    doc_text = product_doc_path.read_text(encoding="utf-8-sig") if product_doc_path.exists() else ""
    doc_md_path.parent.mkdir(parents=True, exist_ok=True)
    doc_md_path.write_text(doc_text, encoding="utf-8")
    doc = product_doc_signals(product_doc_path)
    write_json(doc_json_path, doc)
    candidates = [
        generate_seed_keyword_candidates(seed, doc, int(config["termsPerSeed"]))
        for seed in seeds
    ]
    write_json(candidates_path, candidates)
    layered = config.get("layeredKeywords") if isinstance(config.get("layeredKeywords"), dict) else {}
    if layered.get("enabled"):
        layer_config = load_keyword_layer_config(Path(layered.get("configPath") or DEFAULT_LAYER_CONFIG))
        today = date.fromisoformat(str(config.get("targetDate") or date.today().isoformat()))
        try:
            lookback = int((layer_config.get("evergreen") or {}).get("lookback_days", 30) or 30)
            feedback_rows = collect_recent_feedback(days=lookback) if not args.seeds_file else seeds
        except Exception as exc:
            print(f"[WARN] TikTok layered keyword feedback read failed; using seed fallback: {exc}")
            feedback_rows = seeds
        external_hot_records, external_preheat_events = collect_external_keyword_sources(
            layer_config,
            root=Path(config["root"]),
            run_dir=run_dir,
            today=today,
            enabled=bool(config.get("externalSourcesEnabled", True)),
        )
        plan = build_layered_search_plan(
            layer_config,
            feedback_rows=feedback_rows,
            today=today,
            root=Path(config["root"]),
            external_hot_records=external_hot_records,
            external_preheat_events=external_preheat_events,
        )
    else:
        plan = build_search_plan(
            main_scrape_queries(),
            candidates,
            max_terms=int(config["maxTerms"]),
            allocation=int(config["allocation"]),
        )
    write_json(stage0_plan_path, plan)
    write_json(plan_path, plan)
    return seeds, candidates, plan


def load_external_artifacts_for_tuning(run_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    hot_payload = read_json(run_dir / "02_external_hot_trends.json", {})
    preheat_payload = read_json(run_dir / "02_external_preheat_events.json", {})
    hot_records = hot_payload.get("records") if isinstance(hot_payload, dict) else []
    preheat_events = preheat_payload.get("events") if isinstance(preheat_payload, dict) else []
    return (
        [item for item in hot_records if isinstance(item, dict)] if isinstance(hot_records, list) else [],
        [item for item in preheat_events if isinstance(item, dict)] if isinstance(preheat_events, list) else [],
    )


def stage_feedback_tuning(
    config: dict[str, Any],
    args: argparse.Namespace,
    initial_plan: list[dict[str, Any]] | None = None,
    feedback_rows: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    run_dir = Path(config["runDir"])
    stage0_plan_path = run_dir / "04_search_plan_stage0.json"
    plan_path = run_dir / "04_search_plan.json"
    tuning_path = run_dir / "04_feedback_tuning.json"
    if config["resume"] and tuning_path.exists() and plan_path.exists() and initial_plan is None:
        return read_json(plan_path, []), read_json(tuning_path, {})
    initial = initial_plan if initial_plan is not None else read_json(stage0_plan_path, read_json(plan_path, []))
    layered = config.get("layeredKeywords") if isinstance(config.get("layeredKeywords"), dict) else {}
    if not layered.get("enabled"):
        report = {
            "schemaVersion": 1,
            "enabled": False,
            "generatedAt": now_iso(),
            "reason": "layered_keywords_disabled",
            "windowDays": 0,
            "matchedFeedbackCount": 0,
            "unmatchedFeedbackCount": 0,
            "replacements": [],
            "allocationChanges": [],
        }
        write_json(plan_path, initial)
        write_json(tuning_path, report)
        return initial, report
    layer_config = load_keyword_layer_config(Path(layered.get("configPath") or DEFAULT_LAYER_CONFIG))
    tuning_cfg = feedback_tuning_config(layer_config)
    if tuning_cfg.get("enabled") is False:
        report = {
            "schemaVersion": 1,
            "enabled": False,
            "generatedAt": now_iso(),
            "reason": "feedback_tuning_disabled",
            "windowDays": int(tuning_cfg.get("lookback_days", 7) or 7),
            "matchedFeedbackCount": 0,
            "unmatchedFeedbackCount": 0,
            "replacements": [],
            "allocationChanges": [],
        }
        write_json(plan_path, initial)
        write_json(tuning_path, report)
        return initial, report
    lookback = max(1, int(tuning_cfg.get("lookback_days", 7) or 7))
    if feedback_rows is None:
        try:
            feedback_rows = collect_recent_feedback(days=lookback)
        except Exception as exc:
            feedback_rows = []
            print(f"[WARN] TikTok Discovery stage1 feedback read failed; keeping stage0 plan: {exc}")
    external_hot_records, external_preheat_events = load_external_artifacts_for_tuning(run_dir)
    today = date.fromisoformat(str(config.get("targetDate") or date.today().isoformat()))
    candidate_pool = build_layered_candidate_pool(
        layer_config,
        feedback_rows=feedback_rows,
        today=today,
        root=Path(config["root"]),
        external_hot_records=external_hot_records,
        external_preheat_events=external_preheat_events,
    )
    final_plan, report = apply_discovery_feedback_tuning(
        initial,
        layer_config,
        feedback_rows,
        root=Path(config["root"]),
        today=today,
        candidate_pool=candidate_pool,
    )
    write_json(tuning_path, report)
    write_json(plan_path, final_plan)
    return final_plan, report


def load_existing_search_plan(config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    run_dir = Path(config["runDir"])
    plan = sanitize_search_plan_entries(read_json(run_dir / "04_search_plan.json", []))
    if not isinstance(plan, list) or not plan:
        raise RuntimeError("TikTok Discovery final search plan is missing; run stage0/stage1 first or omit --resume.")
    seeds = read_json(run_dir / "01_feedback_seeds.json", [])
    candidates = read_json(run_dir / "03_keyword_candidates.json", [])
    return (
        seeds if isinstance(seeds, list) else [],
        candidates if isinstance(candidates, list) else [],
        plan,
    )


def run_discovery(config: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    run_dir = Path(config["runDir"])
    run_dir.mkdir(parents=True, exist_ok=True)
    started_at = now_iso()
    report: dict[str, Any] = {
        "schemaVersion": 1,
        "runId": config["runId"],
        "startedAt": started_at,
        "finishedAt": "",
        "status": "failed",
        "stage": config["stage"],
        "requestedStage": config.get("requestedStage", config["stage"]),
        "approvedCount": 0,
        "rejectedCount": 0,
        "searchTermCount": 0,
        "candidateCount": 0,
        "searchNetworkJsonCount": 0,
        "networkStructuredCandidateCount": 0,
        "detailFallbackCount": 0,
        "targetCandidateTotal": 0,
        "keywordLayerSummary": {},
        "feedbackTuningSummary": {},
        "error": "",
        "browserChannel": config["browserChannel"],
        "browserExecutable": relative_path(Path(config["browserExecutable"])) if config.get("browserExecutable") else "",
        "headless": config["headless"],
        "detailHeadless": config["detailHeadless"],
        "stage4Profile": config.get("stage4Profile", "main"),
        "paths": {},
    }
    write_json(run_dir / "00_config.json", public_config(config))
    ensure_artifact_skeleton(run_dir)
    rejected: list[dict[str, Any]] = []
    active_stage: dict[str, str] = {"stage": "", "startedAt": ""}

    def begin_stage(stage_name: str) -> None:
        active_stage["stage"] = stage_name
        active_stage["startedAt"] = now_iso()
        append_stage_record(
            run_dir,
            config,
            stage=stage_name,
            status="in_progress",
            started_at=active_stage["startedAt"],
        )

    def end_stage(stage_name: str, *, status: str = "success", counts: dict[str, Any] | None = None, error: str = "") -> None:
        started = active_stage["startedAt"] if active_stage.get("stage") == stage_name else now_iso()
        append_stage_record(
            run_dir,
            config,
            stage=stage_name,
            status=status,
            started_at=started,
            counts=counts,
            error=error,
        )
        if active_stage.get("stage") == stage_name:
            active_stage["stage"] = ""
            active_stage["startedAt"] = ""

    try:
        stage = config["stage"]
        plan_path = run_dir / "04_search_plan.json"
        should_prepare_keywords = stage in {"all", "stage0", "stage1"} or (not config["resume"] and not plan_path.exists())
        if should_prepare_keywords:
            begin_stage("stage0")
            seeds, keyword_candidates, stage0_plan = stage_keywords(config, args)
            search_plan = stage0_plan
            report["searchTermCount"] = len(search_plan)
            layer_summary = keyword_layer_summary(search_plan)
            report["targetCandidateTotal"] = layer_summary["targetCandidateTotal"]
            report["keywordLayerSummary"] = layer_summary["layers"]
            end_stage(
                "stage0",
                counts={
                    "feedbackSeedCount": len(seeds),
                    "keywordCandidateGroups": len(keyword_candidates),
                    "searchTermCount": len(search_plan),
                    "targetCandidateTotal": layer_summary["targetCandidateTotal"],
                },
            )
            if stage == "stage0":
                report["status"] = "success"
                return report
            begin_stage("stage1")
            search_plan, tuning_report = stage_feedback_tuning(config, args, stage0_plan)
            end_stage(
                "stage1",
                counts={
                    "searchTermCount": len(search_plan),
                    "matchedFeedbackCount": tuning_report.get("matchedFeedbackCount", 0),
                    "unmatchedFeedbackCount": tuning_report.get("unmatchedFeedbackCount", 0),
                    "replacementCount": len(tuning_report.get("replacements") or []),
                    "allocationChangeCount": len(tuning_report.get("allocationChanges") or []),
                },
            )
            report["feedbackTuningSummary"] = {
                "enabled": bool(tuning_report.get("enabled")),
                "windowDays": tuning_report.get("windowDays", 0),
                "matchedFeedbackCount": tuning_report.get("matchedFeedbackCount", 0),
                "unmatchedFeedbackCount": tuning_report.get("unmatchedFeedbackCount", 0),
                "replacementCount": len(tuning_report.get("replacements") or []),
                "allocationChangeCount": len(tuning_report.get("allocationChanges") or []),
            }
            if stage == "stage1":
                report["searchTermCount"] = len(search_plan)
                layer_summary = keyword_layer_summary(search_plan)
                report["targetCandidateTotal"] = layer_summary["targetCandidateTotal"]
                report["keywordLayerSummary"] = layer_summary["layers"]
                report["status"] = "success"
                return report
        else:
            seeds, keyword_candidates, search_plan = load_existing_search_plan(config)
            tuning_report = read_json(run_dir / "04_feedback_tuning.json", {})
            if isinstance(tuning_report, dict) and tuning_report:
                report["feedbackTuningSummary"] = {
                    "enabled": bool(tuning_report.get("enabled")),
                    "windowDays": tuning_report.get("windowDays", 0),
                    "matchedFeedbackCount": tuning_report.get("matchedFeedbackCount", 0),
                    "unmatchedFeedbackCount": tuning_report.get("unmatchedFeedbackCount", 0),
                    "replacementCount": len(tuning_report.get("replacements") or []),
                    "allocationChangeCount": len(tuning_report.get("allocationChanges") or []),
                }
        report["searchTermCount"] = len(search_plan)
        layer_summary = keyword_layer_summary(search_plan)
        report["targetCandidateTotal"] = layer_summary["targetCandidateTotal"]
        report["keywordLayerSummary"] = layer_summary["layers"]

        candidates_path = run_dir / "07_candidates.json"
        client: TikTokCookieSearchClient | None = None

        def get_client() -> TikTokCookieSearchClient:
            nonlocal client
            if client is None:
                client = TikTokCookieSearchClient(
                    Path(config["cookieFile"]),
                    headless=bool(config["headless"]),
                    detail_headless=bool(config["detailHeadless"]),
                    browser_channel=str(config["browserChannel"]),
                    browser_executable=config.get("browserExecutable"),
                    max_scrolls=int(config["maxScrolls"]),
                    wait_ms=int(config["waitMs"]),
                    scroll_wait_min_ms=int(config["scrollWaitMinMs"]),
                    scroll_wait_max_ms=int(config["scrollWaitMaxMs"]),
                    max_no_growth_rounds=int(config["maxNoGrowthRounds"]),
                    verification_poll_seconds=int(config["verificationPollSeconds"]),
                    verification_wait_seconds=int(config["verificationWaitSeconds"]),
                    slider_puzzle_config=dict(config.get("sliderPuzzle") or {}),
                )
            return client

        can_reuse_candidates = bool(config["resume"] and candidates_path.exists() and stage in {"stage4", "stage5"})
        if stage in {"all", "stage2", "stage4", "stage5"} and not can_reuse_candidates:
            begin_stage("stage2")
            rejected.extend(get_client().collect_search(search_plan, run_dir, bool(config["resume"])))
            search_network_summary = summarize_search_response_artifacts(run_dir)
            end_stage(
                "stage2",
                counts={
                    "searchTermCount": len(search_plan),
                    "rejectedCount": len(rejected),
                    "searchNetworkJsonCount": search_network_summary["responseCount"],
                    "networkStructuredCandidateCount": search_network_summary["candidateCount"],
                },
            )

        if stage == "stage2":
            candidates = []
            report["candidateCount"] = 0
            write_json(run_dir / "09_rejected.json", rejected)
            report["rejectedCount"] = len(rejected)
            report["status"] = "success"
            return report

        if can_reuse_candidates:
            candidates = read_json(candidates_path, [])
        elif stage in {"all", "stage3", "stage4", "stage5"}:
            begin_stage("stage3")
            candidates, detail_rejected = get_client().resolve_candidates(search_plan, run_dir, bool(config["resume"]))
            rejected.extend(detail_rejected)
            write_json(candidates_path, candidates)
            end_stage(
                "stage3",
                counts={
                    "candidateCount": len(candidates),
                    "detailRejectedCount": len(detail_rejected),
                    "detailFallbackCount": count_detail_fallbacks(run_dir),
                    "rejectedCount": len(rejected),
                },
            )
        else:
            candidates = []
        report["candidateCount"] = len(candidates)
        if stage == "stage3":
            write_json(run_dir / "09_rejected.json", rejected)
            report["rejectedCount"] = len(rejected)
            report["status"] = "success"
            return report

        approved_path = run_dir / "10_approved.json"
        filtered_path = run_dir / "08_filtered.json"
        begin_stage("stage4")
        if config["resume"] and approved_path.exists() and stage == "stage5" and has_successful_stage_record(run_dir, "stage4"):
            approved = read_json(approved_path, [])
        else:
            approved = process_scraper_output(
                approved_path,
                input_data=candidates_path,
                data_snapshot_path=filtered_path,
                route_profile=config.get("stage4Profile", "main"),
            )
        approved_urls = {clean_text(item.get("hotspotUrl") or item.get("webVideoUrl") or item.get("url")) for item in approved}
        for item in candidates:
            url = clean_text(item.get("webVideoUrl") or item.get("hotspotUrl") or item.get("url"))
            if url and url not in approved_urls:
                rejected.append({"stage": "filter", "url": url, "reason": "not approved by TikTok filter chain"})
        write_json(run_dir / "09_rejected.json", rejected)
        report["approvedCount"] = len(approved)
        report["rejectedCount"] = len(rejected)
        filtered = read_json(filtered_path, [])
        ua_similarity_payload = read_json(run_dir / "08_ua_batch_similarity_filter.json", {})
        ua_similarity_summary = (
            ua_similarity_payload.get("summary", {})
            if isinstance(ua_similarity_payload, dict)
            else {}
        )
        ua_video_review_payload = read_json(run_dir / "08_ua_video_review.json", {})
        ua_video_review_summary = (
            ua_video_review_payload.get("summary", {})
            if isinstance(ua_video_review_payload, dict)
            else {}
        )
        report["uaBatchSimilarityFilterSummary"] = ua_similarity_summary
        report["uaVideoReviewSummary"] = ua_video_review_summary
        stage4_counts = {
            "candidateCount": len(candidates),
            "filteredCount": len(filtered) if isinstance(filtered, list) else 0,
            "approvedCount": len(approved),
            "rejectedCount": len(rejected),
        }
        if ua_similarity_summary:
            stage4_counts["uaBatchSimilarityFilter"] = ua_similarity_summary
        if ua_video_review_summary:
            stage4_counts["uaVideoReview"] = ua_video_review_summary
        end_stage(
            "stage4",
            counts=stage4_counts,
        )
        report["status"] = "success"
        return report
    except Exception as exc:
        report["error"] = clean_text(exc, max_len=600)
        report["status"] = "failed"
        if active_stage.get("stage"):
            end_stage(active_stage["stage"], status="failed", error=report["error"])
        try:
            write_json(run_dir / "09_rejected.json", rejected)
        except Exception:
            pass
        return report
    finally:
        report["finishedAt"] = now_iso()
        search_network_summary = summarize_search_response_artifacts(run_dir)
        report["searchNetworkJsonCount"] = search_network_summary["responseCount"]
        report["networkStructuredCandidateCount"] = search_network_summary["candidateCount"]
        report["detailFallbackCount"] = count_detail_fallbacks(run_dir)
        report["paths"] = {
            "config": relative_path(run_dir / "00_config.json"),
            "stageRecords": relative_path(run_dir / "00_stage_records.json"),
            "feedbackSeeds": relative_path(run_dir / "01_feedback_seeds.json"),
            "productDocSnapshot": relative_path(run_dir / "02_product_doc_snapshot.md"),
            "externalHotTrends": relative_path(run_dir / "02_external_hot_trends.json"),
            "externalPreheatEvents": relative_path(run_dir / "02_external_preheat_events.json"),
            "keywordCandidates": relative_path(run_dir / "03_keyword_candidates.json"),
            "searchPlanStage0": relative_path(run_dir / "04_search_plan_stage0.json"),
            "feedbackTuning": relative_path(run_dir / "04_feedback_tuning.json"),
            "searchPlan": relative_path(run_dir / "04_search_plan.json"),
            "searchLinksDir": relative_path(run_dir / "05_search_links"),
            "searchCardsDir": relative_path(run_dir / "05_search_cards"),
            "searchResponsesDir": relative_path(run_dir / "05_search_responses"),
            "detailRawDir": relative_path(run_dir / "06_detail_raw"),
            "candidates": relative_path(run_dir / "07_candidates.json"),
            "filtered": relative_path(run_dir / "08_filtered.json"),
            "uaBatchSimilarityFilter": relative_path(run_dir / "08_ua_batch_similarity_filter.json"),
            "uaBatchSimilarityFilterRejected": relative_path(run_dir / "08_ua_batch_similarity_filter_rejected.json"),
            "uaVideoReview": relative_path(run_dir / "08_ua_video_review.json"),
            "uaVideoReviewRejected": relative_path(run_dir / "08_ua_video_review_rejected.json"),
            "rejected": relative_path(run_dir / "09_rejected.json"),
            "approved": relative_path(run_dir / "10_approved.json"),
        }
        if config["stage"] in {"all", "stage5"}:
            append_stage_record(
                run_dir,
                config,
                stage="stage5",
                status=report.get("status", "failed"),
                started_at=report["finishedAt"],
                counts={
                    "approvedCount": report.get("approvedCount", 0),
                    "rejectedCount": report.get("rejectedCount", 0),
                    "candidateCount": report.get("candidateCount", 0),
                    "searchTermCount": report.get("searchTermCount", 0),
                },
                error=report.get("error", ""),
            )
        write_json(run_dir / "report.json", report)
        write_latest(config, report)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run isolated TikTok cookie keyword discovery")
    parser.add_argument("--run-id")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--stage", choices=["all", *CANONICAL_STAGES, *STAGE_ALIASES.keys()], default="all")
    parser.add_argument("--root")
    parser.add_argument("--cookie-file")
    parser.add_argument("--product-doc")
    parser.add_argument("--layer-config")
    parser.add_argument("--target-date")
    parser.add_argument("--layered-keywords", dest="layered_keywords", action="store_true", default=None)
    parser.add_argument("--no-layered-keywords", dest="layered_keywords", action="store_false")
    parser.add_argument("--external-sources", dest="external_sources", action="store_true", default=None)
    parser.add_argument("--no-external-sources", dest="external_sources", action="store_false")
    parser.add_argument("--stage4-profile", choices=["main", "ua", "product"], default=None)
    parser.add_argument("--route-profile", choices=["main", "ua", "product"], default=None, help=argparse.SUPPRESS)
    parser.add_argument("--seeds-file")
    parser.add_argument("--max-terms", type=int)
    parser.add_argument("--terms-per-seed", type=int)
    parser.add_argument("--allocation", type=int)
    parser.add_argument("--lookback-days", type=int)
    parser.add_argument("--browser-channel")
    parser.add_argument("--browser-executable")
    parser.add_argument("--max-scrolls", type=int)
    parser.add_argument("--wait-ms", type=int)
    parser.add_argument("--scroll-wait-min-ms", type=int)
    parser.add_argument("--scroll-wait-max-ms", type=int)
    parser.add_argument("--max-no-growth-rounds", type=int)
    parser.add_argument("--verification-poll-seconds", type=int)
    parser.add_argument("--verification-wait-seconds", type=int)
    parser.add_argument("--slider-puzzle-enabled", dest="slider_puzzle_enabled", action="store_true", default=None)
    parser.add_argument("--no-slider-puzzle", dest="slider_puzzle_enabled", action="store_false")
    parser.add_argument("--slider-puzzle-container-selector")
    parser.add_argument("--slider-puzzle-track-selector")
    parser.add_argument("--slider-puzzle-handle-selector")
    parser.add_argument("--slider-puzzle-inner-selector")
    parser.add_argument("--slider-puzzle-success-selector")
    parser.add_argument("--slider-puzzle-max-attempts", type=int)
    parser.add_argument("--slider-puzzle-auto-attempts", type=int)
    parser.add_argument("--slider-puzzle-tolerance-score", type=float)
    parser.add_argument("--slider-puzzle-rotation-degrees", type=float)
    parser.add_argument("--headless", dest="headless", action="store_true", default=None)
    parser.add_argument("--visible-browser", dest="headless", action="store_false")
    parser.add_argument("--detail-headless", dest="detail_headless", action="store_true", default=None)
    parser.add_argument("--visible-detail-browser", dest="detail_headless", action="store_false")
    parser.add_argument("--no-lock", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    env = {**load_env(), **os.environ}
    config = build_config(args, env)
    with DiscoveryLock(LOCK_FILE, enabled=not bool(config["noLock"])):
        report = run_discovery(config, args)
    if report.get("status") == "failed":
        print(f"TikTok keyword discovery failed: {report.get('error')}")
        return 1
    print(
        "TikTok keyword discovery finished: "
        f"terms={report.get('searchTermCount')} candidates={report.get('candidateCount')} "
        f"approved={report.get('approvedCount')} rejected={report.get('rejectedCount')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
