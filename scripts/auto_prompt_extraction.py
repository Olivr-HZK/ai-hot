from __future__ import annotations

import json
import os
import re
from typing import Any

import requests

from env_utils import env_bool, env_int, load_env
from source_rehydrate import rehydrate_item


DEFAULT_MODEL = "qwen/qwen3.7-max"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

PROMPT_MARKER_RE = re.compile(
    r"(?:^|[\s:])(?:prompt(?:s)?|image\s+prompt|video\s+prompt|"
    r"\u63d0\u793a\u8bcd|\u5492\u8bed|\u5173\u952e\u8bcd)\s*[:\uff1a\-–]\s*",
    re.IGNORECASE,
)
PROMPT_INLINE_SECTION_RE = re.compile(
    r"(?:^|[\s:])(?:prompt(?:s)?|image\s+prompt|video\s+prompt)\s+"
    r"(?=(?:main\s+character|story\s+sequence|character\s+description|scene\s+description|"
    r"final\s+scene|style|negative\s+prompt|use\s+my|use\s+the|create\s+a|create\s+an|"
    r"photorealistic|ultra[-\s]?realistic|cinematic)\b)",
    re.IGNORECASE,
)
PROMPT_BUAT_RE = re.compile(r"\bprompt\s+buat\b.{16,2400}", re.IGNORECASE | re.DOTALL)
LONG_QUOTED_RE = re.compile(r"[\"'\u201c\u201d\u2018\u2019]([^\"'\u201c\u201d\u2018\u2019]{30,1800})[\"'\u201c\u201d\u2018\u2019]")
REQUEST_ONLY_RE = re.compile(
    r"\b(prompt\s+please|what\s+prompt|share\s+(?:the\s+)?prompt|prompt\??|"
    r"can\s+you\s+share\s+the\s+prompt)\b|"
    r"(\u6c42\u63d0\u793a\u8bcd|\u6709\u63d0\u793a\u8bcd|\u5206\u4eab\u63d0\u793a\u8bcd)",
    re.IGNORECASE,
)
URL_RE = re.compile(r"https?://\S+")
SHORT_URL_RE = re.compile(r"https?://(?:t\.co|bit\.ly|tinyurl\.com|shorturl\.at|lnkd\.in)/\S+", re.IGNORECASE)
SPACE_RE = re.compile(r"\s+")

CANDIDATE_TEXT_KEYS = [
    "title",
    "text",
    "desc",
    "description",
    "caption",
    "transcript",
    "ocrText",
]
CONTEXT_TEXT_KEYS = [
    "summary",
    "hotspotIntro",
    "aiIntro",
    "videoSummary",
    "video_summary",
]
NESTED_TEXT_CONTAINERS = ["raw_source", "rawSource", "source", "metadata"]
COMMENT_KEYS = ["topComments", "comments", "latestComments", "commentList", "comment_list", "replies"]
COMMENT_TEXT_KEYS = ["text", "comment", "content", "desc", "message", "full_text"]


def clean_text(value: Any, *, max_len: int | None = None) -> str:
    text = SPACE_RE.sub(" ", str(value or "")).strip()
    if max_len is not None and len(text) > max_len:
        return text[:max_len].rstrip()
    return text


def meaningful_chars(text: str) -> str:
    return "".join(
        ch
        for ch in text
        if ch.isalpha() or ch.isdigit() or ("\u4e00" <= ch <= "\u9fff")
    )


def is_probably_english(text: str) -> bool:
    chars = meaningful_chars(text)
    if len(chars) < 12:
        return False
    english_letters = sum(1 for ch in chars if "a" <= ch.lower() <= "z")
    cjk_chars = sum(1 for ch in chars if "\u4e00" <= ch <= "\u9fff")
    return english_letters / max(len(chars), 1) >= 0.75 and cjk_chars == 0


def _append_text(blocks: list[dict[str, str]], source: str, value: Any) -> None:
    if isinstance(value, str):
        text = clean_text(value)
        if text:
            blocks.append({"source": source, "text": text})
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _append_text(blocks, f"{source}[{index}]", item)
    elif isinstance(value, dict):
        for key in ("text", "full_text", "name", "title", "desc", "description", "caption", "content"):
            if key in value:
                _append_text(blocks, f"{source}.{key}", value.get(key))


def _comment_text(comment: Any) -> str:
    if isinstance(comment, str):
        return clean_text(comment)
    if isinstance(comment, dict):
        for key in COMMENT_TEXT_KEYS:
            text = clean_text(comment.get(key))
            if text:
                return text
    return ""


def collect_text_blocks(
    item: dict[str, Any],
    *,
    max_comments: int,
    max_chars: int,
    include_context: bool = False,
) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    keys = CONTEXT_TEXT_KEYS if include_context else CANDIDATE_TEXT_KEYS
    for key in keys:
        _append_text(blocks, key, item.get(key))
    for container_key in NESTED_TEXT_CONTAINERS:
        nested = item.get(container_key)
        if not isinstance(nested, dict):
            continue
        for key in keys:
            _append_text(blocks, f"{container_key}.{key}", nested.get(key))
    if include_context:
        return _limit_blocks(blocks, max_chars)
    for key in ("hashtags", "tags"):
        value = item.get(key)
        if isinstance(value, list):
            tags = [clean_text(tag.get("name") if isinstance(tag, dict) else tag) for tag in value]
            tags = [tag for tag in tags if tag]
            if tags:
                blocks.append({"source": key, "text": " ".join(tags)})
    for index, block in enumerate(item.get("sourceRehydrateTextBlocks") or []):
        if isinstance(block, dict):
            _append_text(blocks, str(block.get("source") or f"sourceRehydrate[{index}]"), block.get("text"))
    comment_count = 0
    comment_sources: list[tuple[str, Any]] = []
    for key in COMMENT_KEYS:
        comment_sources.append((key, item.get(key)))
    comment_sources.append(("sourceRehydrateComments", item.get("sourceRehydrateComments")))
    for key, value in comment_sources:
        if not isinstance(value, list):
            continue
        for comment in value:
            if comment_count >= max_comments:
                break
            text = _comment_text(comment)
            if text:
                blocks.append({"source": key, "text": text})
                comment_count += 1
        if comment_count >= max_comments:
            break
    return _limit_blocks(blocks, max_chars)


def _limit_blocks(blocks: list[dict[str, str]], max_chars: int) -> list[dict[str, str]]:
    limited: list[dict[str, str]] = []
    total = 0
    for block in blocks:
        text = clean_text(block.get("text"))
        if not text:
            continue
        remaining = max_chars - total
        if remaining <= 0:
            break
        if len(text) > remaining:
            text = text[:remaining].rstrip()
        limited.append({"source": block.get("source", ""), "text": text})
        total += len(text)
    return limited


def clean_prompt_candidate(text: str) -> str:
    text = str(text or "")
    text = re.sub(r"^\s*[:\uff1a\-–]+", "", text)
    text = re.sub(r"(?:\s+#\w+){4,}\s*$", "", text)
    text = URL_RE.sub("", text)
    return clean_text(text, max_len=4000)


def raw_candidate_after_marker(text: str, match: re.Match[str]) -> str:
    candidate = text[match.end() : match.end() + 4000]
    candidate = re.split(
        r"\n\s*\n|(?:\s{2,})(?:comments?|caption|hashtags?)\s*[:\uff1a]",
        candidate,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return candidate


def is_request_only(text: str) -> bool:
    cleaned = clean_text(text).lower()
    if not cleaned:
        return True
    if PROMPT_MARKER_RE.search(cleaned):
        return False
    if len(cleaned) <= 90 and REQUEST_ONLY_RE.search(cleaned):
        return True
    return False


def is_link_only_or_truncated(raw: str, cleaned: str) -> bool:
    raw_text = clean_text(raw)
    cleaned_text = clean_text(cleaned)
    if not cleaned_text:
        return True
    if URL_RE.fullmatch(raw_text) or (SHORT_URL_RE.search(raw_text) and len(meaningful_chars(cleaned_text)) < 120):
        return True
    if SHORT_URL_RE.search(raw_text) and cleaned_text.rstrip().endswith((":","\uff1a")):
        return True
    if SHORT_URL_RE.search(raw_text) and re.search(r"\b(reference|prompt|identity|image)\s*[:\uff1a]?$", cleaned_text, re.I):
        return True
    if len(meaningful_chars(cleaned_text)) < 24:
        return True
    return False


def add_candidate(
    candidates: list[dict[str, Any]],
    seen: set[str],
    *,
    source: str,
    raw: str,
    marker: str,
) -> None:
    cleaned = clean_prompt_candidate(raw)
    if is_request_only(cleaned):
        return
    if is_link_only_or_truncated(raw, cleaned):
        candidates.append(
            {
                "source": source,
                "text": "",
                "rawText": clean_text(raw, max_len=800),
                "marker": marker,
                "rejectedByRule": "prompt_truncated_or_link_only",
            }
        )
        return
    key = cleaned.lower()
    if key in seen:
        return
    seen.add(key)
    candidates.append({"source": source, "text": cleaned, "rawText": clean_text(raw, max_len=1200), "marker": marker})


def extract_rule_candidates(blocks: list[dict[str, str]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for block in blocks:
        text = block.get("text", "")
        source = block.get("source", "")
        for match in PROMPT_MARKER_RE.finditer(text):
            add_candidate(candidates, seen, source=source, raw=raw_candidate_after_marker(text, match), marker=match.group(0).strip())
        for match in PROMPT_INLINE_SECTION_RE.finditer(text):
            add_candidate(candidates, seen, source=source, raw=raw_candidate_after_marker(text, match), marker=match.group(0).strip())
        for match in PROMPT_BUAT_RE.finditer(text):
            add_candidate(candidates, seen, source=source, raw=match.group(0), marker="Prompt Buat")
        if "prompt" in text.lower() or "\u63d0\u793a\u8bcd" in text:
            for match in LONG_QUOTED_RE.finditer(text):
                add_candidate(candidates, seen, source=source, raw=match.group(1), marker="quoted")
    return candidates[:10]


def parse_json_object(content: str) -> dict[str, Any]:
    text = clean_text(content)
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("model response is not a JSON object")
    return parsed


def model_config(env: dict[str, str]) -> dict[str, Any]:
    model = (
        os.environ.get("AUTO_PROMPT_MODEL")
        or env.get("AUTO_PROMPT_MODEL")
        or os.environ.get("OPENROUTER_MODEL")
        or env.get("OPENROUTER_MODEL")
        or DEFAULT_MODEL
    )
    return {
        "enabled": env_bool("AUTO_PROMPT_EXTRACTION_ENABLED", True, env),
        "model": model,
        "require_model": env_bool("AUTO_PROMPT_REQUIRE_MODEL", True, env),
        "max_comments": env_int("AUTO_PROMPT_MAX_COMMENTS", 10, env),
        "max_text_chars": env_int("AUTO_PROMPT_MAX_TEXT_CHARS", 6000, env),
        "source_rehydrate": env_bool("AUTO_PROMPT_SOURCE_REHYDRATE_ENABLED", True, env),
    }


def rejected_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [candidate for candidate in candidates if candidate.get("rejectedByRule")]


def valid_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [candidate for candidate in candidates if clean_text(candidate.get("text")) and not candidate.get("rejectedByRule")]


def normalize_model_result(parsed: dict[str, Any], *, model: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    valid = valid_candidates(candidates)
    has_prompt = bool(parsed.get("hasPrompt"))
    try:
        selected_index = int(parsed.get("selectedCandidateIndex", 0))
    except (TypeError, ValueError):
        selected_index = 0
    if selected_index < 0 or selected_index >= len(valid):
        selected_index = 0
    selected = valid[selected_index] if valid else {}
    action = clean_text(parsed.get("action") or "reject").lower()
    reason = clean_text(parsed.get("reason"), max_len=500)
    prompt_text = ""
    source = clean_text(selected.get("source"))
    if has_prompt and valid:
        candidate_text = clean_text(selected.get("text"), max_len=4000)
        if action == "accept_exact" and is_probably_english(candidate_text):
            prompt_text = candidate_text
        elif action == "translate":
            translated = clean_text(parsed.get("translatedPromptEnglish") or parsed.get("promptEnglish"), max_len=4000)
            if is_probably_english(translated):
                prompt_text = translated
        elif action == "accept_exact" and not is_probably_english(candidate_text):
            reason = reason or "candidate is not English and model did not translate it"
    result = {
        "hasPrompt": bool(prompt_text),
        "promptEnglish": prompt_text,
        "source": source,
        "reason": reason,
        "model": model,
        "selectedCandidateIndex": selected_index if prompt_text else None,
        "action": action,
        "candidateCount": len(valid),
        "candidates": candidates,
        "rejectedCandidates": rejected_candidates(candidates),
    }
    if has_prompt and not prompt_text:
        result["error"] = "model did not return an allowed exact English candidate or English translation"
    return result


def review_candidates_with_model(
    item: dict[str, Any],
    candidate_blocks: list[dict[str, str]],
    context_blocks: list[dict[str, str]],
    candidates: list[dict[str, Any]],
    *,
    cfg: dict[str, Any],
    env: dict[str, str],
) -> dict[str, Any]:
    model = str(cfg["model"])
    valid = valid_candidates(candidates)
    api_key = os.environ.get("OPENROUTER_API_KEY") or env.get("OPENROUTER_API_KEY", "")
    if not valid:
        return {
            "hasPrompt": False,
            "promptEnglish": "",
            "source": "",
            "reason": "no complete explicit prompt candidate found",
            "model": model,
            "candidateCount": 0,
            "candidates": candidates,
            "rejectedCandidates": rejected_candidates(candidates),
            "error": "prompt_truncated_or_link_only" if rejected_candidates(candidates) else "",
        }
    if not api_key:
        if cfg.get("require_model", True):
            return {
                "hasPrompt": False,
                "promptEnglish": "",
                "source": "",
                "reason": "OPENROUTER_API_KEY is missing; prompt extraction requires model confirmation",
                "model": model,
                "candidateCount": len(valid),
                "candidates": candidates,
                "error": "missing_openrouter_key",
            }
        first = valid[0]
        text = clean_text(first.get("text"))
        return {
            "hasPrompt": bool(text and is_probably_english(text)),
            "promptEnglish": text if is_probably_english(text) else "",
            "source": first.get("source", ""),
            "reason": "model disabled; used exact English rule candidate fallback",
            "model": "rules",
            "candidateCount": len(valid),
            "candidates": candidates,
        }
    payload = {
        "platform": item.get("hotspotPlatform") or item.get("sourcePlatform") or item.get("platform"),
        "url": item.get("hotspotUrl") or item.get("webVideoUrl") or item.get("url"),
        "candidatePrompts": valid,
        "contextOnlyBlocks": context_blocks,
        "candidateSourceBlocks": candidate_blocks,
        "sourceRehydrate": item.get("sourceRehydrate") or {},
    }
    prompt = (
        "You verify whether candidate text is a real reusable prompt shared by a creator. "
        "Use contextOnlyBlocks only to understand the post; never copy or add words from contextOnlyBlocks into the prompt. "
        "Never invent, summarize, expand, or reverse-engineer prompts. "
        "If an English candidate is real and complete, return action=accept_exact and do not rewrite it. "
        "If a non-English candidate is real and complete, return action=translate and translate only that candidate into English. "
        "Reject request-only comments, link-only candidates, truncated candidates, captions, tags, and promotional copy. "
        "Return strict JSON with keys: hasPrompt, selectedCandidateIndex, action, translatedPromptEnglish, reason. "
        "action must be accept_exact, translate, or reject.\n\n"
        f"Material:\n{json.dumps(payload, ensure_ascii=False)}"
    )
    response = requests.post(
        OPENROUTER_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": 900,
        },
        timeout=45,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"].get("content") or "{}"
    parsed = parse_json_object(content)
    return normalize_model_result(parsed, model=model, candidates=candidates)


def extract_auto_prompt(item: dict[str, Any], env: dict[str, str] | None = None) -> dict[str, Any]:
    env = env or load_env()
    cfg = model_config(env)
    updated = dict(item)
    if not cfg["enabled"]:
        updated["autoPromptText"] = ""
        updated["autoPromptExtraction"] = {
            "hasPrompt": False,
            "promptEnglish": "",
            "reason": "auto prompt extraction disabled",
            "model": "",
        }
        return updated
    if cfg["source_rehydrate"]:
        updated = rehydrate_item(updated, env)
    candidate_blocks = collect_text_blocks(
        updated,
        max_comments=max(int(cfg["max_comments"]), 0),
        max_chars=max(int(cfg["max_text_chars"]), 1000),
        include_context=False,
    )
    context_blocks = collect_text_blocks(
        updated,
        max_comments=0,
        max_chars=2000,
        include_context=True,
    )
    candidates = extract_rule_candidates(candidate_blocks)
    if not candidates:
        updated["autoPromptText"] = ""
        updated["autoPromptExtraction"] = {
            "hasPrompt": False,
            "promptEnglish": "",
            "source": "",
            "reason": "no explicit prompt candidate found in source text or comments",
            "model": str(cfg["model"]),
            "candidateCount": 0,
            "candidates": [],
            "sourceRehydrate": updated.get("sourceRehydrate") or {},
        }
        return updated
    try:
        extraction = review_candidates_with_model(updated, candidate_blocks, context_blocks, candidates, cfg=cfg, env=env)
    except Exception as exc:
        extraction = {
            "hasPrompt": False,
            "promptEnglish": "",
            "source": "",
            "reason": "prompt model review failed",
            "model": str(cfg["model"]),
            "candidateCount": len(valid_candidates(candidates)),
            "candidates": candidates,
            "rejectedCandidates": rejected_candidates(candidates),
            "sourceRehydrate": updated.get("sourceRehydrate") or {},
            "error": clean_text(exc, max_len=500),
        }
    extraction["sourceRehydrate"] = updated.get("sourceRehydrate") or {}
    updated["autoPromptExtraction"] = extraction
    updated["autoPromptText"] = extraction.get("promptEnglish") if extraction.get("hasPrompt") else ""
    return updated


def apply_auto_prompt_extraction(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    env = load_env()
    updated_items = [extract_auto_prompt(item, env) for item in items]
    extracted = sum(1 for item in updated_items if clean_text(item.get("autoPromptText")))
    print(f"Auto prompt extraction: {extracted}/{len(updated_items)} prompts found", flush=True)
    return updated_items
