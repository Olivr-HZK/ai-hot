from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

import requests

from creator_pool import normalize_profile_url, usernames_from_urls
from env_utils import load_env


class ApifyInstagramError(RuntimeError):
    pass


def _actor_api_id(actor_id: str) -> str:
    return actor_id.strip().replace("/", "~")


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), max(1, size))]


class ApifyInstagramProvider:
    def __init__(self, rules: dict[str, Any]) -> None:
        self.rules = rules
        self.env = load_env()
        self.token = os.environ.get("APIFY_TOKEN") or self.env.get("APIFY_TOKEN", "")
        self.apify = rules.get("apify", {})
        self.timeout = int(self.apify.get("run_timeout_seconds", 240) or 240)

    def available(self) -> bool:
        return bool(self.token)

    def _run_actor(self, actor_id: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.token:
            raise ApifyInstagramError("APIFY_TOKEN is required for Instagram scraping")
        api_id = _actor_api_id(actor_id)
        url = f"https://api.apify.com/v2/acts/{api_id}/run-sync-get-dataset-items"
        response = requests.post(
            url,
            params={"token": self.token, "format": "json", "clean": "true"},
            json=payload,
            timeout=self.timeout + 30,
        )
        if response.status_code >= 400:
            raise ApifyInstagramError(f"Apify actor failed ({response.status_code}): {response.text[:500]}")
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise ApifyInstagramError(f"Apify actor did not return JSON: {response.text[:500]}") from exc
        if not isinstance(data, list):
            raise ApifyInstagramError(f"Apify actor returned unexpected payload: {type(data).__name__}")
        return [item for item in data if isinstance(item, dict)]

    def _render_template(self, template: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
        def render(value: Any) -> Any:
            if isinstance(value, str):
                for key, replacement in values.items():
                    marker = "{" + key + "}"
                    if value == marker:
                        return replacement
                    value = value.replace(marker, str(replacement))
                return value
            if isinstance(value, list):
                return [render(item) for item in value]
            if isinstance(value, dict):
                return {key: render(item) for key, item in value.items()}
            return value

        return {key: render(value) for key, value in template.items()}

    def build_post_input(self, profile_urls: list[str], max_posts: int, cutoff: datetime) -> dict[str, Any]:
        template = self.apify.get("post_input_template") or {}
        if not isinstance(template, dict):
            template = {}
        values = {
            "profile_urls": profile_urls,
            "profile_url": profile_urls[0] if profile_urls else "",
            "usernames": usernames_from_urls(profile_urls),
            "username": usernames_from_urls(profile_urls)[0] if profile_urls else "",
            "max_posts": max_posts,
            "cutoff_iso": cutoff.isoformat(),
            "cutoff_date": cutoff.strftime("%Y-%m-%d"),
        }
        if template:
            return self._render_template(template, values)
        return {"directUrls": profile_urls, "resultsLimit": max_posts, "onlyPostsNewerThan": values["cutoff_date"]}

    def fetch_profile_posts(self, profile_urls: list[str], *, max_posts_per_creator: int, cutoff: datetime) -> list[dict[str, Any]]:
        actor_id = os.environ.get("INS_APIFY_POST_ACTOR_ID") or self.env.get("INS_APIFY_POST_ACTOR_ID") or self.apify.get("post_actor_id")
        if not actor_id:
            raise ApifyInstagramError("Instagram post actor id is missing")
        batch_size = int(self.apify.get("batch_size", 20) or 20)
        all_items: list[dict[str, Any]] = []
        for batch in _chunks(profile_urls, batch_size):
            payload = self.build_post_input(batch, max_posts_per_creator, cutoff)
            all_items.extend(self._run_actor(actor_id, payload))
        return all_items

    def build_search_input(self, query: str, limit: int) -> dict[str, Any]:
        template = self.apify.get("search_input_template") or {}
        if not isinstance(template, dict):
            template = {}
        values = {"query": query, "limit": limit}
        if template:
            return self._render_template(template, values)
        return {"search": query, "searchType": "user", "maxItems": limit}

    def search_creators(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        actor_id = os.environ.get("INS_APIFY_SEARCH_ACTOR_ID") or self.env.get("INS_APIFY_SEARCH_ACTOR_ID") or self.apify.get("search_actor_id")
        if not actor_id:
            raise ApifyInstagramError("Instagram search actor id is missing")
        return self._run_actor(actor_id, self.build_search_input(query, limit))


def search_result_profile_url(item: dict[str, Any]) -> str:
    for key in ["url", "profileUrl", "profile_url", "inputUrl"]:
        url = normalize_profile_url(str(item.get(key) or ""))
        if url:
            return url
    user = item.get("user") if isinstance(item.get("user"), dict) else {}
    owner = item.get("owner") if isinstance(item.get("owner"), dict) else {}
    for value in [item.get("username"), item.get("ownerUsername"), user.get("username"), owner.get("username")]:
        url = normalize_profile_url(str(value or ""))
        if url:
            return url
    return ""

