from __future__ import annotations

import os
import re
import time
from typing import Any

from env_utils import env_float, load_env
from scoring import safe_int


INTRO_SYSTEM_PROMPT = (
    "\u4f60\u662f\u793e\u5a92\u70ed\u70b9\u5206\u6790\u5e08\uff0c\u670d\u52a1\u4e8e AI "
    "\u521b\u610f\u4ea7\u54c1\u548c\u589e\u957f\u56e2\u961f\u3002"
    "\u8bf7\u7528\u4e2d\u6587\u5206\u6790\u793e\u5a92\u5e16\u5b50\u4e2d\u7684 AI "
    "\u73a9\u6cd5\u6216\u8d8b\u52bf\u4ef7\u503c\u3002"
    "\u5206\u6790\u5fc5\u987b\u8986\u76d6\u4e3b\u4f53\u3001\u573a\u666f\u3001\u4e8b\u4ef6\u3001"
    "\u4f20\u64ad\u70b9\u56db\u7c7b\u4fe1\u606f\uff0c\u4f46\u8f93\u51fa\u4e3a\u4e00\u6bb5"
    "\u81ea\u7136\u4e2d\u6587\uff0c\u4e0d\u8981\u5199\u6807\u7b7e\u3002"
    "\u4e0d\u8981\u628a\u666e\u901a\u660e\u661f\u8def\u900f\u3001\u786c\u4ef6\u8d44\u8baf\u3001"
    "\u6cdb\u79d1\u6280\u65b0\u95fb\u5f3a\u884c\u5305\u88c5\u6210 AI \u521b\u4f5c\u673a\u4f1a\uff1b"
    "\u7f3a\u5c11 AI \u521b\u4f5c\u3001AI \u5de5\u5177\u6216 AI \u6548\u679c\u8bc1\u636e\u65f6\uff0c"
    "\u5fc5\u987b\u660e\u786e\u8868\u8fbe\u4e3a\u4f4e\u76f8\u5173\u3002"
    "\u4e0d\u8981\u590d\u8ff0\u64ad\u653e\u3001\u70b9\u8d5e\u3001\u8bc4\u8bba\u7b49\u6570\u5b57\uff0c"
    "\u4e0d\u8981\u5199\u6807\u9898\u5f0f\u6458\u8981\uff0c\u4e0d\u8981\u5199\u8425\u9500\u53e3\u53f7\u3002"
)

INTRO_EXAMPLE_USER = (
    "\u5e73\u53f0\uff1aTikTok\n"
    "\u5e16\u5b50\u94fe\u63a5\uff1ahttps://www.tiktok.com/@boogiebug0/video/7634699603614371103\n"
    "\u5e16\u5b50\u6587\u672c\uff1aKling AI APP \u4e2d\u4e0a\u4f20\u4e00\u5f20"
    "\u5355\u4eba\u7684\u65e5\u5e38\u56fe\uff0c\u751f\u6210\u9ed1\u767d\u827a\u672f"
    "\u5199\u771f\u6548\u679c\u3002"
)

INTRO_EXAMPLE_ASSISTANT = (
    "\u535a\u4e3b\u4ecb\u7ecd\u4e86\u4e00\u79cd AI \u56fe\u7247\u73a9\u6cd5\uff0c"
    "\u5728 Kling AI APP \u4e2d\uff0c\u4e0a\u4f20\u4e00\u5f20\u5355\u4eba\u7684"
    "\u65e5\u5e38\u56fe\uff0c\u751f\u6210\u9ed1\u767d\u827a\u672f\u5199\u771f\u7684"
    "\u6548\u679c\u3002\u8be5\u73a9\u6cd5\u5177\u6709\u65f6\u5c1a\u611f\uff0c\u8ba9"
    "\u666e\u901a\u4eba\u4f4e\u6210\u672c\u83b7\u5f97\u65f6\u5c1a\u5927\u7247\u5199\u771f\uff0c"
    "\u9002\u5408\u4e0e\u670b\u53cb\u3001\u5bb6\u4eba\u3001\u793e\u5a92\u5206\u4eab\u3002"
)


def clean_text(value: Any, max_len: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if max_len is not None and len(text) > max_len:
        return text[: max_len - 3].rstrip() + "..."
    return text


def normalize_hashtag(tag: Any) -> str:
    if isinstance(tag, str):
        return tag.strip()
    if isinstance(tag, dict):
        return clean_text(tag.get("name") or tag.get("title") or tag.get("hashtagName"))
    return clean_text(tag)


def platform_name(item: dict[str, Any]) -> str:
    platform = clean_text(item.get("hotspotPlatform") or item.get("sourcePlatform") or item.get("platform") or "tiktok").lower()
    return {"tiktok": "TikTok", "tt": "TikTok", "x": "X", "reddit": "Reddit", "ins": "Instagram"}.get(platform, platform or "TikTok")


def author_name(item: dict[str, Any]) -> str:
    author = item.get("authorMeta") or {}
    if isinstance(author, dict):
        return clean_text(author.get("nickName") or author.get("name") or author.get("uniqueId"))
    return ""


def build_intro_prompt(item: dict[str, Any]) -> str:
    hashtags = [normalize_hashtag(tag) for tag in item.get("hashtags") or []]
    hashtags = [tag for tag in hashtags if tag]
    parts = [
        f"\u5e73\u53f0\uff1a{platform_name(item)}",
        f"\u5e16\u5b50\u94fe\u63a5\uff1a{clean_text(item.get('hotspotUrl') or item.get('webVideoUrl'))}",
        f"\u4f5c\u8005\uff1a{author_name(item) or '\u672a\u77e5'}",
        f"\u6807\u9898/\u6b63\u6587\uff1a{clean_text(item.get('text') or item.get('desc') or item.get('title'), max_len=4200)}",
        f"\u5df2\u6709\u6458\u8981\uff1a{clean_text(item.get('video_summary') or item.get('summary'), max_len=1000)}",
        f"\u8bdd\u9898\u6807\u7b7e\uff1a{', '.join(hashtags[:20])}",
        f"\u64ad\u653e/\u70b9\u8d5e/\u8bc4\u8bba\uff1a{safe_int(item.get('playCount'))}/{safe_int(item.get('diggCount') or item.get('likeCount'))}/{safe_int(item.get('commentCount'))}",
        f"\u70ed\u95e8\u8bc4\u8bba\uff1a{clean_text(' / '.join(str(comment) for comment in (item.get('topComments') or [])[:5]), max_len=1000)}",
        "",
        "\u8bf7\u8f93\u51fa\u4e00\u6bb5\u4e2d\u6587\u70ed\u70b9\u7b80\u4ecb\uff0c80-160\u5b57\u3002"
        "\u5fc5\u987b\u8bf4\u660e\uff1a\u8c01/\u4ec0\u4e48\u5185\u5bb9\u662f\u4e3b\u4f53\uff0c"
        "\u53d1\u751f\u5728\u54ea\u4e2a\u5de5\u5177\u6216\u4f7f\u7528\u573a\u666f\uff0c"
        "\u7528\u6237\u505a\u4e86\u4ec0\u4e48\uff0c\u4e3a\u4ec0\u4e48\u6709\u4f20\u64ad"
        "\u6216\u590d\u7528\u4ef7\u503c\u3002",
    ]
    return "\n".join(parts)


def strip_intro_text(content: str) -> str:
    text = clean_text(content)
    text = re.sub(r"^```(?:\w+)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip().strip("\"'")
    prefixes = ["\u70ed\u70b9\u7b80\u4ecb\uff1a", "\u5206\u6790\uff1a", "\u7b80\u4ecb\uff1a"]
    for prefix in prefixes:
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
    return text


def cjk_count(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def validate_intro(text: str) -> str:
    intro = strip_intro_text(text)
    if not intro:
        raise RuntimeError("AI intro is empty")
    if cjk_count(intro) < 12:
        raise RuntimeError(f"AI intro is not readable Chinese: {intro}")
    if intro.startswith("\u793e\u5a92\u70ed\u70b9+") or "+\u64ad\u653e" in intro:
        raise RuntimeError(f"AI intro still uses the old template format: {intro}")
    if re.search(r"(\u4e3b\u4f53|\u573a\u666f|\u4e8b\u4ef6|\u4f20\u64ad\u70b9)\s*[:\uff1a]", intro):
        raise RuntimeError(f"AI intro contains explicit framework labels: {intro}")
    if len(intro) > 260:
        intro = intro[:257].rstrip() + "..."
    return intro


def resolve_intro_client() -> tuple[Any, str]:
    env = load_env()
    timeout = env_float("INTRO_ANALYSIS_TIMEOUT_SECONDS", 45.0, env)
    api_key = os.environ.get("OPENAI_API_KEY") or env.get("OPENAI_API_KEY")
    base_url = None
    model = os.environ.get("INTRO_ANALYSIS_MODEL") or env.get("INTRO_ANALYSIS_MODEL")
    if api_key:
        model = model or os.environ.get("OPENAI_FEEDBACK_MODEL") or env.get("OPENAI_FEEDBACK_MODEL") or "gpt-5.4"
    else:
        api_key = os.environ.get("OPENROUTER_API_KEY") or env.get("OPENROUTER_API_KEY")
        model = model or os.environ.get("OPENROUTER_MODEL") or env.get("OPENROUTER_MODEL")
        base_url = "https://openrouter.ai/api/v1"
    if not api_key or not model:
        raise RuntimeError("No OPENAI_API_KEY/OPENROUTER_API_KEY and intro model configured")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("openai package is required for AI intro generation") from exc
    kwargs: dict[str, Any] = {"api_key": api_key, "timeout": timeout, "max_retries": 0}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs), model


def generate_intro(item: dict[str, Any]) -> str:
    client, model = resolve_intro_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": INTRO_SYSTEM_PROMPT},
            {"role": "user", "content": INTRO_EXAMPLE_USER},
            {"role": "assistant", "content": INTRO_EXAMPLE_ASSISTANT},
            {"role": "user", "content": build_intro_prompt(item)},
        ],
        max_tokens=260,
    )
    try:
        content = response.choices[0].message.content or ""
    except (AttributeError, IndexError, TypeError):
        content = ""
    return validate_intro(content)


def generate_intro_with_retry(item: dict[str, Any], attempts: int = 4) -> str:
    delays = [30, 60, 120]
    for attempt in range(1, attempts + 1):
        try:
            return generate_intro(item)
        except Exception as exc:
            message = str(exc)
            retryable = "429" in message or "rate-limit" in message.lower() or "rate limit" in message.lower() or "temporarily" in message.lower()
            if not retryable or attempt >= attempts:
                raise
            delay = delays[min(attempt - 1, len(delays) - 1)]
            print(f"  - AI intro temporary limit; retrying in {delay}s ({attempt}/{attempts})", flush=True)
            time.sleep(delay)


def apply_ai_intros(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for index, item in enumerate(items, 1):
        updated = dict(item)
        updated["hotspotIntro"] = generate_intro_with_retry(updated)
        enriched.append(updated)
        print(f"  - AI intro generated: {index}/{len(items)}", flush=True)
    return enriched
