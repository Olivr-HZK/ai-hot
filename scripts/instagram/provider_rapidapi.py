from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote

import requests

from creator_pool import extract_username
from env_utils import load_env
from ins_scoring import clean_text


BASE_DIR = Path(__file__).resolve().parents[2]
USAGE_DIR = BASE_DIR / "skill_runs" / "instagram"


class RapidApiInstagramError(RuntimeError):
    pass


def _flatten_posts(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for entry in value for item in _flatten_posts(entry)]
    if not isinstance(value, dict):
        return []
    for key in [
        "posts",
        "items",
        "data",
        "edges",
        "feed",
        "media",
        "medias",
        "result",
        "results",
        "response",
        "user_media",
        "user",
        "graphql",
        "edge_owner_to_timeline_media",
        "edge_felix_video_timeline",
        "timeline_media",
        "feed_posts",
    ]:
        child = value.get(key)
        if isinstance(child, (list, dict)):
            posts = _flatten_posts(child)
            if posts:
                return posts
    if isinstance(value.get("node"), dict):
        return _flatten_posts(value["node"])
    post_markers = {
        "caption",
        "shortcode",
        "shortCode",
        "code",
        "taken_at",
        "timestamp",
        "like_count",
        "likesCount",
        "commentsCount",
        "displayUrl",
        "display_url",
    }
    if any(key in value for key in post_markers):
        return [value]
    return []


def _body_template_values(username: str, max_id: str) -> dict[str, Any]:
    return {"username": username, "maxId": max_id}


def _append_profile_url(values: list[str], value: Any) -> None:
    text = clean_text(value)
    if not text:
        return
    if "instagram.com" in text.lower():
        for url in instagram_profile_urls_from_text(text):
            if url not in values:
                values.append(url)
        return
    username = extract_username(text)
    if username:
        url = f"https://www.instagram.com/{username}/"
        if url not in values:
            values.append(url)


def _search_result_profile_urls(value: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(value, list):
        for item in value:
            for url in _search_result_profile_urls(item):
                if url not in urls:
                    urls.append(url)
        return urls
    if not isinstance(value, dict):
        _append_profile_url(urls, value)
        return urls
    for key in [
        "url",
        "profileUrl",
        "profile_url",
        "instagramUrl",
        "instagram_url",
        "link",
        "permalink",
        "username",
        "userName",
        "handle",
        "screenName",
    ]:
        _append_profile_url(urls, value.get(key))
    for key in [
        "users",
        "accounts",
        "profiles",
        "items",
        "results",
        "data",
        "records",
        "docs",
        "entities",
        "response",
        "user",
        "account",
        "profile",
        "socialProfiles",
        "socials",
    ]:
        child = value.get(key)
        if isinstance(child, (list, dict)):
            for url in _search_result_profile_urls(child):
                if url not in urls:
                    urls.append(url)
    return urls


class RapidApiInstagramProvider:
    def __init__(self, rules: dict[str, Any]) -> None:
        self.rules = rules
        self.env = load_env()
        rapidapi = rules.get("rapidapi", {}) if isinstance(rules.get("rapidapi"), dict) else {}
        self.host = (
            os.environ.get("INS_RAPIDAPI_HOST")
            or self.env.get("INS_RAPIDAPI_HOST")
            or rapidapi.get("host")
            or "instagram120.p.rapidapi.com"
        )
        self.posts_path = (
            os.environ.get("INS_RAPIDAPI_POSTS_PATH")
            or self.env.get("INS_RAPIDAPI_POSTS_PATH")
            or rapidapi.get("posts_path")
            or "/api/instagram/posts"
        )
        self.base_url = (
            os.environ.get("INS_RAPIDAPI_BASE_URL")
            or self.env.get("INS_RAPIDAPI_BASE_URL")
            or rapidapi.get("base_url")
            or f"https://{self.host}"
        ).rstrip("/")
        self.timeout = int(os.environ.get("INS_RAPIDAPI_TIMEOUT_SECONDS") or self.env.get("INS_RAPIDAPI_TIMEOUT_SECONDS") or rapidapi.get("timeout_seconds", 45) or 45)
        self.key = (
            os.environ.get("INS_RAPIDAPI_KEY")
            or self.env.get("INS_RAPIDAPI_KEY")
            or os.environ.get("RAPIDAPI_INSTAGRAM_KEY")
            or self.env.get("RAPIDAPI_INSTAGRAM_KEY")
            or ""
        )
        self.usage = {
            "provider": "rapidapi",
            "host": self.host,
            "startedAt": datetime.now().isoformat(),
            "requests": 0,
            "success": 0,
            "failed": 0,
            "profiles": [],
            "errors": [],
        }

    def available(self) -> bool:
        return bool(self.key)

    def _headers(self) -> dict[str, str]:
        if not self.key:
            raise RapidApiInstagramError("INS_RAPIDAPI_KEY is required for Instagram RapidAPI scraping")
        return {
            "X-RapidAPI-Key": self.key,
            "X-RapidAPI-Host": self.host,
            "Content-Type": "application/json",
        }

    def _post(self, path: str, body: dict[str, Any]) -> Any:
        self.usage["requests"] += 1
        url = f"{self.base_url}{path if path.startswith('/') else '/' + path}"
        response = requests.post(url, headers=self._headers(), json=body, timeout=self.timeout)
        if response.status_code >= 400:
            self.usage["failed"] += 1
            message = clean_text(response.text, max_len=500)
            self.usage["errors"].append({"status": response.status_code, "body": body, "message": message})
            raise RapidApiInstagramError(f"Instagram RapidAPI failed ({response.status_code}): {message}")
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            self.usage["failed"] += 1
            message = clean_text(response.text, max_len=500)
            self.usage["errors"].append({"status": response.status_code, "body": body, "message": message})
            raise RapidApiInstagramError(f"Instagram RapidAPI did not return JSON: {message}") from exc
        self.usage["success"] += 1
        return payload

    def fetch_username_posts(self, username: str, *, max_id: str = "") -> list[dict[str, Any]]:
        username = extract_username(username)
        if not username:
            return []
        body = _body_template_values(username, max_id)
        payload = self._post(self.posts_path, body)
        posts = _flatten_posts(payload)
        normalized_posts: list[dict[str, Any]] = []
        for item in posts:
            updated = dict(item)
            updated.setdefault("ownerUsername", username)
            updated.setdefault("_insRapidapiUsername", username)
            updated.setdefault("_insRapidapiPath", self.posts_path)
            normalized_posts.append(updated)
        self.usage["profiles"].append({"username": username, "postCount": len(normalized_posts)})
        return normalized_posts

    def fetch_profile_posts(
        self,
        profile_urls: list[str],
        checkpoint_callback: Callable[[list[dict[str, Any]], dict[str, Any]], None] | None = None,
    ) -> list[dict[str, Any]]:
        all_posts: list[dict[str, Any]] = []
        seen_usernames: set[str] = set()
        completed_usernames: list[str] = []
        failed_profiles: list[dict[str, Any]] = []
        for value in profile_urls:
            username = extract_username(value)
            if not username or username in seen_usernames:
                continue
            seen_usernames.add(username)
            try:
                all_posts.extend(self.fetch_username_posts(username))
                completed_usernames.append(username)
                if checkpoint_callback:
                    checkpoint_callback(
                        all_posts,
                        {
                            "status": "partial",
                            "completed": completed_usernames,
                            "failed": failed_profiles,
                            "error": "",
                        },
                    )
            except Exception as exc:
                error = {"username": username, "message": clean_text(exc, max_len=300)}
                failed_profiles.append(error)
                self.usage["errors"].append(error)
                print(f"  - INS RapidAPI posts skipped for {username}: {exc}", flush=True)
                if checkpoint_callback and all_posts:
                    checkpoint_callback(
                        all_posts,
                        {
                            "status": "partial",
                            "completed": completed_usernames,
                            "failed": failed_profiles,
                            "error": clean_text(exc, max_len=300),
                        },
                    )
        return all_posts

    def write_usage(self, stage: str, extra: dict[str, Any] | None = None) -> Path:
        USAGE_DIR.mkdir(parents=True, exist_ok=True)
        path = USAGE_DIR / f"rapidapi_usage_{datetime.now().strftime('%Y%m%d')}.json"
        run = {**self.usage, "stage": stage, "finishedAt": datetime.now().isoformat(), **(extra or {})}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except json.JSONDecodeError:
                data = {}
        else:
            data = {}
        runs = data.get("runs") if isinstance(data.get("runs"), list) else []
        runs.append(run)
        data["date"] = datetime.now().strftime("%Y-%m-%d")
        data["runs"] = runs
        data["totals"] = {
            "requests": sum(int(item.get("requests", 0) or 0) for item in runs if isinstance(item, dict)),
            "success": sum(int(item.get("success", 0) or 0) for item in runs if isinstance(item, dict)),
            "failed": sum(int(item.get("failed", 0) or 0) for item in runs if isinstance(item, dict)),
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path


class RapidApiCreatorSearchProvider:
    def __init__(self, rules: dict[str, Any]) -> None:
        self.rules = rules
        self.env = load_env()
        search = rules.get("creator_search", {}) if isinstance(rules.get("creator_search"), dict) else {}
        self.provider = (
            os.environ.get("INS_CREATOR_SEARCH_PROVIDER")
            or self.env.get("INS_CREATOR_SEARCH_PROVIDER")
            or search.get("provider")
            or "rapidapi"
        )
        self.host = (
            os.environ.get("INS_RAPIDAPI_SEARCH_HOST")
            or self.env.get("INS_RAPIDAPI_SEARCH_HOST")
            or search.get("host")
            or "instagram-statistics-api.p.rapidapi.com"
        )
        self.path = (
            os.environ.get("INS_RAPIDAPI_SEARCH_PATH")
            or self.env.get("INS_RAPIDAPI_SEARCH_PATH")
            or search.get("path")
            or "/search"
        )
        self.method = (
            os.environ.get("INS_RAPIDAPI_SEARCH_METHOD")
            or self.env.get("INS_RAPIDAPI_SEARCH_METHOD")
            or search.get("method")
            or "GET"
        ).upper()
        self.base_url = (
            os.environ.get("INS_RAPIDAPI_SEARCH_BASE_URL")
            or self.env.get("INS_RAPIDAPI_SEARCH_BASE_URL")
            or search.get("base_url")
            or f"https://{self.host}"
        ).rstrip("/")
        self.timeout = int(
            os.environ.get("INS_RAPIDAPI_SEARCH_TIMEOUT_SECONDS")
            or self.env.get("INS_RAPIDAPI_SEARCH_TIMEOUT_SECONDS")
            or search.get("timeout_seconds", 30)
            or 30
        )
        self.per_page = int(
            os.environ.get("INS_RAPIDAPI_SEARCH_PER_PAGE")
            or self.env.get("INS_RAPIDAPI_SEARCH_PER_PAGE")
            or search.get("per_page", 10)
            or 10
        )
        self.query_param = clean_text(
            os.environ.get("INS_RAPIDAPI_SEARCH_QUERY_PARAM")
            or self.env.get("INS_RAPIDAPI_SEARCH_QUERY_PARAM")
            or search.get("query_param")
        )
        candidates = search.get("query_param_candidates")
        if isinstance(candidates, list):
            self.query_param_candidates = [clean_text(value) for value in candidates if clean_text(value)]
        else:
            self.query_param_candidates = ["q", "query", "keyword", "search", "username"]
        self.key = (
            os.environ.get("INS_RAPIDAPI_KEY")
            or self.env.get("INS_RAPIDAPI_KEY")
            or os.environ.get("RAPIDAPI_INSTAGRAM_KEY")
            or self.env.get("RAPIDAPI_INSTAGRAM_KEY")
            or ""
        )
        self.default_params = {
            "page": 1,
            "perPage": self.per_page,
            "sort": "-score",
            "socialTypes": "INST",
            "trackTotal": "true",
        }
        if isinstance(search.get("default_params"), dict):
            self.default_params.update(search["default_params"])
        self.usage = {
            "provider": self.provider,
            "host": self.host,
            "startedAt": datetime.now().isoformat(),
            "requests": 0,
            "success": 0,
            "failed": 0,
            "queries": [],
            "errors": [],
        }

    def available(self) -> bool:
        return self.provider == "rapidapi" and bool(self.key)

    def _headers(self) -> dict[str, str]:
        if not self.key:
            raise RapidApiInstagramError("INS_RAPIDAPI_KEY is required for Instagram RapidAPI creator search")
        return {
            "X-RapidAPI-Key": self.key,
            "X-RapidAPI-Host": self.host,
            "Content-Type": "application/json",
        }

    def _params(self, query: str, limit: int, query_param: str | None = None) -> dict[str, Any]:
        params = dict(self.default_params)
        params["perPage"] = min(max(1, int(params.get("perPage") or self.per_page)), max(1, limit))
        selected_query_param = self.query_param if query_param is None else query_param
        if selected_query_param:
            params[selected_query_param] = query
        return params

    def _request(self, query: str, limit: int, query_param: str | None = None) -> Any:
        self.usage["requests"] += 1
        url = f"{self.base_url}{self.path if self.path.startswith('/') else '/' + self.path}"
        params = self._params(query, limit, query_param=query_param)
        response = (
            requests.get(url, headers=self._headers(), params=params, timeout=self.timeout)
            if self.method == "GET"
            else requests.post(url, headers=self._headers(), json=params, timeout=self.timeout)
        )
        if response.status_code >= 400:
            self.usage["failed"] += 1
            message = clean_text(response.text, max_len=500)
            self.usage["errors"].append({"query": query, "status": response.status_code, "message": message})
            raise RapidApiInstagramError(f"Instagram RapidAPI creator search failed ({response.status_code}): {message}")
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            self.usage["failed"] += 1
            message = clean_text(response.text, max_len=500)
            self.usage["errors"].append({"query": query, "status": response.status_code, "message": message})
            raise RapidApiInstagramError(f"Instagram RapidAPI creator search did not return JSON: {message}") from exc
        self.usage["success"] += 1
        return payload

    def search_creators(self, query: str, *, limit: int) -> list[str]:
        query = clean_text(query)
        if not query:
            return []
        candidates = [self.query_param] if self.query_param else [*self.query_param_candidates, ""]
        seen_params: set[str] = set()
        diagnostics: list[dict[str, Any]] = []
        last_error: Exception | None = None
        for query_param in candidates:
            if query_param in seen_params:
                continue
            seen_params.add(query_param)
            try:
                payload = self._request(query, limit, query_param=query_param)
            except Exception as exc:
                last_error = exc
                diagnostics.append({"queryParam": query_param, "error": clean_text(exc, max_len=300)})
                continue
            urls = _search_result_profile_urls(payload)[:limit]
            diagnostics.append({"queryParam": query_param, "resultCount": len(urls)})
            if urls:
                if not self.query_param and query_param:
                    self.query_param = query_param
                self.usage["queries"].append(
                    {"query": query, "queryParam": query_param, "resultCount": len(urls), "diagnostics": diagnostics}
                )
                return urls
        if last_error and not diagnostics:
            raise last_error
        self.usage["queries"].append({"query": query, "resultCount": 0, "diagnostics": diagnostics})
        return []

    def write_usage(self, stage: str, extra: dict[str, Any] | None = None) -> Path:
        USAGE_DIR.mkdir(parents=True, exist_ok=True)
        path = USAGE_DIR / f"rapidapi_usage_{datetime.now().strftime('%Y%m%d')}.json"
        run = {**self.usage, "stage": stage, "finishedAt": datetime.now().isoformat(), **(extra or {})}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except json.JSONDecodeError:
                data = {}
        else:
            data = {}
        runs = data.get("runs") if isinstance(data.get("runs"), list) else []
        runs.append(run)
        data["date"] = datetime.now().strftime("%Y-%m-%d")
        data["runs"] = runs
        data["totals"] = {
            "requests": sum(int(item.get("requests", 0) or 0) for item in runs if isinstance(item, dict)),
            "success": sum(int(item.get("success", 0) or 0) for item in runs if isinstance(item, dict)),
            "failed": sum(int(item.get("failed", 0) or 0) for item in runs if isinstance(item, dict)),
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path


def instagram_profile_urls_from_text(text: str) -> list[str]:
    decoded = unquote(text or "")
    values: list[str] = []
    for match in re.finditer(r"https?://(?:www\.)?instagram\.com/([A-Za-z0-9._]+)/?", decoded):
        username = extract_username(match.group(0))
        if username:
            url = f"https://www.instagram.com/{username}/"
            if url not in values:
                values.append(url)
    return values
