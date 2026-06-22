from __future__ import annotations

import csv
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse


USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")


def extract_username(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("@"):
        text = text[1:]
    if "instagram.com" in text.lower():
        parsed = urlparse(text if "://" in text else f"https://{text}")
        parts = [part for part in parsed.path.split("/") if part]
        if not parts:
            return ""
        first = parts[0].strip()
        if first.lower() in {"p", "reel", "tv", "explore", "stories", "accounts"}:
            return ""
        text = first
    text = text.strip().strip("/")
    if not USERNAME_RE.match(text):
        return ""
    return text.lower()


def normalize_profile_url(value: str) -> str:
    username = extract_username(value)
    return f"https://www.instagram.com/{username}/" if username else ""


def _first_non_empty_cell(row: list[str]) -> str:
    for cell in row:
        value = str(cell or "").strip()
        if value:
            return value
    return ""


def read_creator_pool(path: Path) -> list[str]:
    if not path.exists():
        return []
    urls: list[str] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.reader(file):
            url = normalize_profile_url(_first_non_empty_cell(row))
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


def read_column_count(path: Path) -> int:
    if not path.exists():
        return 1
    max_count = 1
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.reader(file):
            if row:
                max_count = max(max_count, len(row))
    return max_count


def backup_pool(path: Path) -> Path | None:
    if not path.exists():
        return None
    backup_dir = path.parent / "skill_runs" / "instagram" / "creator_pool_backups"
    if path.parent.name == "instagram":
        backup_dir = path.parent / "creator_pool_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{path.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{path.suffix}"
    shutil.copy2(path, backup_path)
    return backup_path


def append_creator_urls(path: Path, urls: Iterable[str], *, make_backup: bool = True) -> list[str]:
    normalized: list[str] = []
    existing = set(read_creator_pool(path))
    for value in urls:
        url = normalize_profile_url(str(value))
        if url and url not in existing and url not in normalized:
            normalized.append(url)
    if not normalized:
        return []
    path.parent.mkdir(parents=True, exist_ok=True)
    if make_backup:
        backup_pool(path)
    column_count = read_column_count(path)
    with path.open("a", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        for url in normalized:
            writer.writerow([url, *[""] * (column_count - 1)])
    return normalized


def usernames_from_urls(urls: Iterable[str]) -> list[str]:
    usernames: list[str] = []
    for url in urls:
        username = extract_username(str(url))
        if username and username not in usernames:
            usernames.append(username)
    return usernames

