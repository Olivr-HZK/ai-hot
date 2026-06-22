from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import requests

from ai_intro import validate_intro
from env_utils import env_bool, env_float, load_env
from ins_scoring import clean_text, media_urls, safe_int


DEFAULT_MODEL = "qwen/qwen3.6-plus"

INS_INTRO_SYSTEM_PROMPT = """
你是社媒热点分析师，服务于 AI 创意产品、增长和 UA 投放团队。
你会同时阅读 Instagram 帖子的文字信息和图片内容，生成一段自然中文热点简介。

输出要求：
- 只输出一段中文，80-160 字，不要标题，不要列表，不要写“主体/场景/事件/传播点”标签。
- 必须自然覆盖四类信息：主体是谁或什么、画面/使用场景是什么、帖子里发生了什么、为什么有传播或广告复用价值。
- 不要复述点赞、评论、播放等数字。
- 不要把没有证据的普通图片强行说成 AI 生成；可以表达为“可作为某类 AI 图片/视频产品的广告素材参考”。
- 对真人、家庭、情侣、宠物、妆发、穿搭、旅行、节日、婚礼、毕业、before-after 等非 AI 热门素材，重点说明其可复用为 UA 创意的视觉钩子。
- 不要写营销口号，不要夸张承诺，不要输出英文分析。
""".strip()


def intro_config(rules: dict[str, Any]) -> dict[str, Any]:
    env = load_env()
    configured = rules.get("intro_analysis") if isinstance(rules.get("intro_analysis"), dict) else {}
    return {
        "enabled": env_bool("INS_INTRO_ANALYSIS_ENABLED", bool(configured.get("enabled", True)), env),
        "model": (
            os.environ.get("INS_INTRO_ANALYSIS_MODEL")
            or env.get("INS_INTRO_ANALYSIS_MODEL")
            or configured.get("model")
            or DEFAULT_MODEL
        ),
        "require_model": env_bool(
            "INS_INTRO_ANALYSIS_REQUIRE_MODEL",
            bool(configured.get("require_model", True)),
            env,
        ),
        "timeout_seconds": env_float(
            "INS_INTRO_ANALYSIS_TIMEOUT_SECONDS",
            float(configured.get("timeout_seconds", 45) or 45),
            env,
        ),
        "max_images": max(1, int(configured.get("max_images", 3) or 3)),
    }


def author_name(item: dict[str, Any]) -> str:
    author = item.get("authorMeta") if isinstance(item.get("authorMeta"), dict) else {}
    return clean_text(author.get("nickName") or author.get("uniqueId") or author.get("name") or "未知")


def hashtags_text(item: dict[str, Any]) -> str:
    tags = [clean_text(tag).lstrip("#") for tag in item.get("hashtags") or []]
    tags = [tag for tag in tags if tag]
    return ", ".join(tags[:20])


def build_text_context(item: dict[str, Any]) -> str:
    review = item.get("uaMaterialReview") if isinstance(item.get("uaMaterialReview"), dict) else {}
    high_heat = item.get("insHighHeat") if isinstance(item.get("insHighHeat"), dict) else {}
    product_fit = item.get("insProductFit") if isinstance(item.get("insProductFit"), dict) else {}
    return "\n".join(
        [
            "平台：Instagram",
            f"帖子链接：{clean_text(item.get('hotspotUrl') or item.get('webVideoUrl'))}",
            f"作者：{author_name(item)}",
            f"媒体类型：{clean_text(item.get('mediaType') or 'post')}",
            f"正文/标题：{clean_text(item.get('text') or item.get('desc') or item.get('title'), max_len=1800)}",
            f"图片/视频摘要：{clean_text(item.get('summary'), max_len=700)}",
            f"话题标签：{hashtags_text(item)}",
            f"互动数据：点赞 {safe_int(item.get('diggCount') or item.get('likeCount'))}，评论 {safe_int(item.get('commentCount'))}",
            f"高热依据：{clean_text(high_heat.get('baselineType') or high_heat.get('reason'), max_len=300)}",
            f"产品匹配：{json.dumps(product_fit, ensure_ascii=False)[:700]}",
            f"UA 素材审核：{json.dumps(review, ensure_ascii=False)[:700]}",
            "",
            "请基于文字和附图生成中文热点简介，严格覆盖主体、场景、事件、传播点四类信息，但不要显式写标签。",
        ]
    )


def build_messages(item: dict[str, Any], rules: dict[str, Any]) -> list[dict[str, Any]]:
    cfg = intro_config(rules)
    content: list[dict[str, Any]] = [{"type": "text", "text": f"{INS_INTRO_SYSTEM_PROMPT}\n\n{build_text_context(item)}"}]
    for url in media_urls(item, limit=int(cfg["max_images"])):
        if re.search(r"\.(mp4|mov|webm|m3u8)(?:\?|$)", url, re.IGNORECASE):
            continue
        content.append({"type": "image_url", "image_url": {"url": url}})
    return [{"role": "user", "content": content}]


def model_intro(item: dict[str, Any], rules: dict[str, Any]) -> str:
    cfg = intro_config(rules)
    env = load_env()
    api_key = os.environ.get("OPENROUTER_API_KEY") or env.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required for INS image intro analysis")
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": str(cfg["model"]),
            "messages": build_messages(item, rules),
            "max_tokens": 320,
        },
        timeout=float(cfg["timeout_seconds"]),
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"].get("content") or ""
    return validate_intro(content)


def deterministic_intro(item: dict[str, Any]) -> str:
    author = author_name(item)
    media = clean_text(item.get("mediaType") or "post") or "post"
    text = clean_text(item.get("text") or item.get("title") or item.get("summary"), max_len=120)
    return (
        f"Instagram 博主 @{author} 发布的 {media} 素材进入高热候选，画面围绕"
        f"{text or '视觉内容'} 展开，适合作为 AI 图片或视频产品的广告创意参考。"
        "其传播点在于画面主题明确、社媒钩子清晰，便于转化为可复用的 UA 素材。"
    )


def generate_intro_with_retry(item: dict[str, Any], rules: dict[str, Any], attempts: int = 3) -> str:
    cfg = intro_config(rules)
    if not cfg["enabled"]:
        return item.get("hotspotIntro") or deterministic_intro(item)
    delays = [8, 20]
    for attempt in range(1, attempts + 1):
        try:
            return model_intro(item, rules)
        except Exception as exc:
            message = str(exc)
            retryable = (
                "429" in message
                or "rate limit" in message.lower()
                or "temporarily" in message.lower()
                or "intro is empty" in message.lower()
                or "not readable chinese" in message.lower()
            )
            if retryable and attempt < attempts:
                delay = delays[min(attempt - 1, len(delays) - 1)]
                print(f"  - INS image intro temporary limit; retrying in {delay}s ({attempt}/{attempts})", flush=True)
                time.sleep(delay)
                continue
            if cfg["require_model"]:
                raise
            print(f"  - INS image intro fallback used: {exc}", flush=True)
            return deterministic_intro(item)
    return deterministic_intro(item)


def apply_ins_ai_intros(items: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for index, item in enumerate(items, 1):
        updated = dict(item)
        updated["hotspotIntro"] = generate_intro_with_retry(updated, rules)
        enriched.append(updated)
        print(f"  - INS image intro generated: {index}/{len(items)}", flush=True)
    return enriched
