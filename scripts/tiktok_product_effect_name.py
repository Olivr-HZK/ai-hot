from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from env_utils import env_bool, env_float, load_env
from visual_dedupe import image_input_urls


BASE_DIR = Path(__file__).resolve().parents[1]
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENROUTER_MODEL = "qwen/qwen3.6-flash"

EFFECT_NAME_RE = re.compile(r"^[A-Za-z]{2,16} [A-Za-z]{2,16}$")
FORBIDDEN_EFFECT_WORDS = {"dance"}
GENERIC_EFFECT_NAMES = {
    "dance trend",
    "dance video",
    "dance effect",
    "viral dance",
    "viral video",
    "cool effect",
    "music dance",
    "video effect",
    "tiktok dance",
    "trending dance",
}

FALLBACK_PATTERNS: list[tuple[list[str], str]] = [
    (["macarena"], "Macarena Move"),
    (["copines"], "Copines Move"),
    (["samba"], "Samba Groove"),
    (["brazil", "brasil"], "Brazil Groove"),
    (["shuffle"], "Shuffle Step"),
    (["hip hop", "hiphop"], "Hip Hop"),
    (["kpop", "k-pop", "korean"], "Kpop Move"),
    (["japan", "japanese"], "Japan Move"),
    (["afro", "afrobeats"], "Afro Groove"),
    (["amapiano"], "Amapiano Beat"),
    (["floor"], "Floor Move"),
    (["fixed camera"], "Fixed Shot"),
    (["solo"], "Solo Move"),
    (["choreo", "choreography"], "Choreo Move"),
    (["hand"], "Hand Move"),
    (["foot"], "Foot Step"),
]

GENERIC_MUSIC_TOKENS = {
    "original",
    "sound",
    "music",
    "official",
    "remix",
    "feat",
    "ft",
    "prod",
    "the",
    "and",
    "dance",
}


def clean_text(value: Any, max_len: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if max_len is not None and len(text) > max_len:
        return text[: max_len - 3].rstrip() + "..."
    return text


def normalize_hashtag(tag: Any) -> str:
    if isinstance(tag, dict):
        return clean_text(tag.get("name") or tag.get("title") or tag.get("hashtag") or tag.get("hashtagName"))
    return clean_text(tag)


def title_case_effect_name(value: str) -> str:
    return " ".join(part[:1].upper() + part[1:].lower() for part in value.split())


def strip_response_text(content: Any) -> str:
    text = clean_text(content)
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s*```$", "", text).strip()
    text = text.strip("\"'")
    text = re.sub(r"^(?:effect\s*name|name)\s*[:=-]\s*", "", text, flags=re.IGNORECASE).strip()
    return text


def validate_effect_name(value: Any) -> str:
    text = strip_response_text(value)
    if not text:
        raise ValueError("effect name is empty")
    if not EFFECT_NAME_RE.fullmatch(text):
        raise ValueError(f"effect name must be exactly two ASCII words: {text}")
    normalized = title_case_effect_name(text)
    words = {word.lower() for word in normalized.split()}
    if words & FORBIDDEN_EFFECT_WORDS:
        raise ValueError(f"effect name must not contain forbidden words: {normalized}")
    if normalized.lower() in GENERIC_EFFECT_NAMES:
        raise ValueError(f"effect name is too generic: {normalized}")
    return normalized


def parse_json_object(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    text = strip_response_text(content)
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def item_url(item: dict[str, Any]) -> str:
    video_meta = item.get("videoMeta") if isinstance(item.get("videoMeta"), dict) else {}
    return clean_text(item.get("hotspotUrl") or item.get("webVideoUrl") or video_meta.get("webVideoUrl") or item.get("url"))


def author_name(item: dict[str, Any]) -> str:
    author = item.get("authorMeta") if isinstance(item.get("authorMeta"), dict) else {}
    return clean_text(author.get("nickName") or author.get("name") or author.get("uniqueId") or item.get("author"))


def item_text(item: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ["title", "text", "desc", "summary", "video_summary", "sourceQuery", "searchQuery"]:
        if item.get(key):
            parts.append(str(item.get(key)))
    hashtags = item.get("hashtags")
    if isinstance(hashtags, list):
        parts.extend(normalize_hashtag(tag) for tag in hashtags)
    comments = item.get("topComments")
    if isinstance(comments, list):
        parts.extend(str(comment) for comment in comments[:5])
    return clean_text(" ".join(part for part in parts if part), max_len=2200)


def compact_music_meta(item: dict[str, Any]) -> dict[str, Any]:
    candidates: list[Any] = [item.get("musicMeta")]
    raw_source = item.get("raw_source") if isinstance(item.get("raw_source"), dict) else {}
    candidates.extend([raw_source.get("musicMeta"), raw_source.get("music"), raw_source.get("sound")])
    for value in candidates:
        if not isinstance(value, dict):
            continue
        compact: dict[str, Any] = {}
        for key in ["musicName", "musicAuthor", "title", "authorName", "artist", "track", "album"]:
            text = clean_text(value.get(key), max_len=140)
            if text:
                compact[key] = text
        if compact:
            return compact
    return {}


def compact_ytdlp_info(info: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in [
        "title",
        "description",
        "track",
        "artist",
        "album",
        "creator",
        "uploader",
        "uploader_id",
        "channel",
        "duration",
        "webpage_url",
        "thumbnail",
    ]:
        value = info.get(key)
        if isinstance(value, str):
            value = clean_text(value, max_len=700 if key == "description" else 180)
        if value not in (None, "", []):
            compact[key] = value
    for key in ["tags", "categories"]:
        values = info.get(key)
        if isinstance(values, list):
            compact[key] = [clean_text(value, max_len=60) for value in values[:16] if clean_text(value)]
    return compact


def extract_ytdlp_metadata(url: str, timeout_seconds: float = 20.0) -> dict[str, Any]:
    if not url:
        return {}
    try:
        import yt_dlp  # type: ignore
    except ImportError:
        return {"error": "yt-dlp is not installed"}
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "extract_flat": False,
        "ignore_no_formats_error": True,
        "socket_timeout": max(1, int(timeout_seconds)),
        "retries": 0,
    }
    cookie_path = BASE_DIR / "www.tiktok.com_cookies.txt"
    if cookie_path.exists():
        options["cookiefile"] = str(cookie_path)
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        return {"error": clean_text(str(exc), max_len=180)}
    return compact_ytdlp_info(info if isinstance(info, dict) else {})


def is_image_evidence_url(url: str) -> bool:
    text = clean_text(url)
    if not text.startswith(("http://", "https://")):
        return False
    lowered = text.lower().split("?", 1)[0]
    if lowered.endswith((".mp4", ".m3u8", ".mov", ".webm")):
        return False
    if "tiktok.com/@" in lowered and "/video/" in lowered:
        return False
    return True


def evidence_image_urls(item: dict[str, Any], ytdlp_info: dict[str, Any] | None = None, limit: int = 3) -> list[str]:
    urls: list[str] = []
    for url in image_input_urls(item, limit=8):
        if is_image_evidence_url(url) and url not in urls:
            urls.append(url)
        if len(urls) >= limit:
            return urls
    ytdlp_info = ytdlp_info if isinstance(ytdlp_info, dict) else {}
    thumbnail = clean_text(ytdlp_info.get("thumbnail"))
    if thumbnail and is_image_evidence_url(thumbnail) and thumbnail not in urls:
        urls.append(thumbnail)
    return urls[:limit]


def build_effect_name_evidence(item: dict[str, Any], ytdlp_info: dict[str, Any], image_urls: list[str]) -> dict[str, Any]:
    hashtags = [normalize_hashtag(tag) for tag in item.get("hashtags") or []]
    hashtags = [tag for tag in hashtags if tag]
    return {
        "url": item_url(item),
        "author": author_name(item),
        "text": item_text(item),
        "sourceQuery": clean_text(item.get("sourceQuery") or item.get("searchQuery")),
        "hashtags": hashtags[:20],
        "musicMeta": compact_music_meta(item),
        "ytDlp": ytdlp_info,
        "imageUrls": image_urls,
    }


def build_messages(evidence: dict[str, Any], image_urls: list[str]) -> list[dict[str, Any]]:
    system = (
        "You name TikTok dance/product effects for a video cover. "
        "Infer the music, dance name, dance style, or most concrete visual movement from evidence. "
        "Return strict JSON only."
    )
    user_text = (
        "Generate one cover-friendly effect name.\n"
        "Rules:\n"
        "- effectName must be exactly two simple English words.\n"
        "- Use Title Case ASCII letters only, no punctuation, no emojis, no Chinese.\n"
        "- Do not use the word Dance.\n"
        "- Prefer specific music, movement, style, or visual descriptors such as Samba Groove or Shuffle Step.\n"
        "- Avoid generic names like Dance Trend, Viral Video, Cool Effect, TikTok Dance.\n"
        "- If uncertain, use the clearest dance style or movement from sourceQuery, hashtags, and visuals.\n"
        "Return JSON keys: effectName, source, reason.\n\n"
        f"Evidence:\n{json.dumps(evidence, ensure_ascii=False)}"
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
    for url in image_urls[:3]:
        content.append({"type": "image_url", "image_url": {"url": url}})
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": content},
    ]


def resolve_effect_name_client() -> tuple[Any, str]:
    env = load_env(override=False)
    merged_env = {**env, **os.environ}
    timeout = env_float("TIKTOK_PRODUCT_EFFECT_NAME_TIMEOUT_SECONDS", 45.0, merged_env)
    model = os.environ.get("TIKTOK_PRODUCT_EFFECT_NAME_MODEL") or env.get("TIKTOK_PRODUCT_EFFECT_NAME_MODEL")
    api_key = os.environ.get("OPENAI_API_KEY") or env.get("OPENAI_API_KEY")
    base_url = None
    if api_key:
        model = model or os.environ.get("INTRO_ANALYSIS_MODEL") or env.get("INTRO_ANALYSIS_MODEL")
        model = model or os.environ.get("OPENAI_FEEDBACK_MODEL") or env.get("OPENAI_FEEDBACK_MODEL") or "gpt-5.4"
    else:
        api_key = os.environ.get("OPENROUTER_API_KEY") or env.get("OPENROUTER_API_KEY")
        model = model or os.environ.get("OPENROUTER_MODEL") or env.get("OPENROUTER_MODEL") or DEFAULT_OPENROUTER_MODEL
        base_url = OPENROUTER_BASE_URL
    if not api_key or not model:
        raise RuntimeError("No OPENAI_API_KEY/OPENROUTER_API_KEY and effect-name model configured")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("openai package is required for TikTok Product effect-name generation") from exc
    kwargs: dict[str, Any] = {"api_key": api_key, "timeout": timeout, "max_retries": 0}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs), model


def response_text(response: Any) -> str:
    try:
        return response.choices[0].message.content or ""
    except (AttributeError, IndexError, TypeError):
        return ""


def generate_effect_name(item: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    env = load_env(override=False)
    merged_env = {**env, **os.environ}
    ytdlp_enabled = env_bool("TIKTOK_PRODUCT_EFFECT_NAME_YTDLP_ENABLED", True, merged_env)
    ytdlp_timeout = env_float("TIKTOK_PRODUCT_EFFECT_NAME_YTDLP_TIMEOUT_SECONDS", 20.0, merged_env)
    ytdlp_info = extract_ytdlp_metadata(item_url(item), timeout_seconds=ytdlp_timeout) if ytdlp_enabled else {}
    image_urls = evidence_image_urls(item, ytdlp_info)
    evidence = build_effect_name_evidence(item, ytdlp_info, image_urls)
    client, model = resolve_effect_name_client()
    response = client.chat.completions.create(
        model=model,
        messages=build_messages(evidence, image_urls),
        response_format={"type": "json_object"},
        max_tokens=220,
    )
    content = response_text(response)
    parsed = parse_json_object(content)
    raw_name = parsed.get("effectName") or parsed.get("name") or content
    name = validate_effect_name(raw_name)
    return name, {
        "method": "ai",
        "model": model,
        "rawName": clean_text(raw_name, max_len=80),
        "source": clean_text(parsed.get("source"), max_len=160),
        "reason": clean_text(parsed.get("reason"), max_len=260),
        "evidence": {
            "imageUrlsUsed": image_urls,
            "hasYtDlp": bool(ytdlp_info and not ytdlp_info.get("error")),
            "ytDlpError": ytdlp_info.get("error") if isinstance(ytdlp_info, dict) else "",
        },
    }


def generate_effect_name_with_retry(item: dict[str, Any], attempts: int = 3) -> tuple[str, dict[str, Any]]:
    delays = [15, 30]
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            return generate_effect_name(item)
        except Exception as exc:
            last_error = str(exc)
            retryable = any(marker in last_error.lower() for marker in ["429", "rate limit", "temporarily", "timeout"])
            if not retryable or attempt >= attempts:
                raise
            delay = delays[min(attempt - 1, len(delays) - 1)]
            print(f"  - TikTok Product effect-name temporary limit; retrying in {delay}s ({attempt}/{attempts})", flush=True)
            time.sleep(delay)
    raise RuntimeError(last_error or "TikTok Product effect-name generation failed")


def fallback_haystack(item: dict[str, Any]) -> str:
    parts = [item_text(item)]
    music = compact_music_meta(item)
    parts.extend(str(value) for value in music.values())
    discovery = item.get("tiktokKeywordDiscovery") if isinstance(item.get("tiktokKeywordDiscovery"), dict) else {}
    for key in ["sourceQueries", "keywords"]:
        values = discovery.get(key)
        if isinstance(values, list):
            parts.extend(str(value) for value in values)
    return clean_text(" ".join(part for part in parts if part)).lower()


def music_fallback_token(item: dict[str, Any]) -> str:
    music = compact_music_meta(item)
    for key in ["musicName", "title", "track", "musicAuthor", "authorName", "artist"]:
        value = clean_text(music.get(key))
        if not value:
            continue
        for token in re.findall(r"[A-Za-z]{2,16}", value):
            if token.lower() not in GENERIC_MUSIC_TOKENS:
                return title_case_effect_name(token)
    return ""


def fallback_effect_name(item: dict[str, Any]) -> str:
    haystack = fallback_haystack(item)
    for needles, name in FALLBACK_PATTERNS:
        if any(needle in haystack for needle in needles):
            return validate_effect_name(name)
    music_token = music_fallback_token(item)
    if music_token:
        return validate_effect_name(f"{music_token} Groove")
    if "dance" in haystack or "dancetrend" in haystack:
        return validate_effect_name("Rhythm Move")
    return validate_effect_name("Motion Style")


def apply_tiktok_product_effect_names(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    env = load_env(override=False)
    merged_env = {**env, **os.environ}
    enabled = env_bool("TIKTOK_PRODUCT_EFFECT_NAME_ENABLED", True, merged_env)
    enriched: list[dict[str, Any]] = []
    total = len(items)
    for index, item in enumerate(items, 1):
        updated = dict(item)
        source: dict[str, Any]
        try:
            name = validate_effect_name(updated.get("tiktokProductEffectName"))
            source = {"method": "existing", "reason": "existing valid tiktokProductEffectName"}
        except ValueError:
            if enabled:
                try:
                    name, source = generate_effect_name_with_retry(updated)
                except Exception as exc:
                    name = fallback_effect_name(updated)
                    source = {"method": "fallback", "reason": clean_text(f"AI effect-name failed: {exc}", max_len=260)}
            else:
                name = fallback_effect_name(updated)
                source = {"method": "fallback", "reason": "TIKTOK_PRODUCT_EFFECT_NAME_ENABLED is false"}
        updated["tiktokProductEffectName"] = name
        updated["hotspotIntro"] = name
        updated["tiktokProductEffectNameSource"] = source
        enriched.append(updated)
        print(f"  - TikTok Product effect name generated: {index}/{total} {name}", flush=True)
    return enriched
