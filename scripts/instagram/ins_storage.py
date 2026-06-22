from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ins_scoring import clean_text, parse_ins_datetime, safe_float, safe_int


BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = BASE_DIR / "skill_runs" / "instagram" / "instagram_hotspots.sqlite"


def resolve_db_path(rules: dict[str, Any]) -> Path:
    raw = str((rules.get("database") or {}).get("path") or "skill_runs/instagram/instagram_hotspots.sqlite").strip()
    path = Path(raw)
    return path if path.is_absolute() else BASE_DIR / path


def connect(rules: dict[str, Any]) -> sqlite3.Connection:
    path = resolve_db_path(rules)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS creators (
            username TEXT PRIMARY KEY,
            profile_url TEXT,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            source TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS posts (
            upsert_key TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            profile_url TEXT,
            hotspot_url TEXT,
            media_type TEXT,
            caption TEXT,
            create_time_iso TEXT,
            publish_ts INTEGER,
            like_count INTEGER NOT NULL DEFAULT 0,
            comment_count INTEGER NOT NULL DEFAULT 0,
            play_count INTEGER NOT NULL DEFAULT 0,
            heat_value REAL NOT NULL DEFAULT 0,
            raw_json TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            crawl_count INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_posts_username_publish
        ON posts(username, publish_ts)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS crawl_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stage TEXT NOT NULL,
            crawled_at TEXT NOT NULL,
            post_count INTEGER NOT NULL,
            creator_count INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS discovery_runs (
            week_key TEXT PRIMARY KEY,
            ran_at TEXT NOT NULL,
            status TEXT NOT NULL,
            report_json TEXT NOT NULL
        )
        """
    )
    conn.commit()


def item_username(item: dict[str, Any]) -> str:
    author = item.get("authorMeta") if isinstance(item.get("authorMeta"), dict) else {}
    return clean_text(author.get("uniqueId") or author.get("nickName") or item.get("_insRapidapiUsername") or item.get("ownerUsername")).lower()


def item_profile_url(item: dict[str, Any]) -> str:
    username = item_username(item)
    return f"https://www.instagram.com/{username}/" if username else ""


def item_publish_ts(item: dict[str, Any]) -> int:
    dt = parse_ins_datetime(item)
    return int(dt.timestamp()) if dt else 0


def item_key(item: dict[str, Any]) -> str:
    return clean_text(item.get("upsertKey") or item.get("hotspotUrl") or item.get("url") or item.get("id") or "")


def save_posts(items: list[dict[str, Any]], rules: dict[str, Any], *, stage: str) -> int:
    if not items:
        return 0
    now = datetime.now().isoformat()
    rows = []
    creators: set[str] = set()
    for item in items:
        username = item_username(item)
        key = item_key(item)
        if not username or not key:
            continue
        creators.add(username)
        rows.append(
            {
                "upsert_key": key,
                "username": username,
                "profile_url": item_profile_url(item),
                "hotspot_url": clean_text(item.get("hotspotUrl") or item.get("url") or item.get("webVideoUrl")),
                "media_type": clean_text(item.get("mediaType")),
                "caption": clean_text(item.get("text") or item.get("title") or item.get("desc"), max_len=2000),
                "create_time_iso": clean_text(item.get("createTimeISO")),
                "publish_ts": item_publish_ts(item),
                "like_count": safe_int(item.get("diggCount") or item.get("likeCount")),
                "comment_count": safe_int(item.get("commentCount")),
                "play_count": safe_int(item.get("playCount")),
                "heat_value": float(item.get("heatValue") or 0),
                "raw_json": json.dumps(item.get("raw_source") or item, ensure_ascii=False),
            }
        )
    if not rows:
        return 0
    with connect(rules) as conn:
        for username in creators:
            conn.execute(
                """
                INSERT INTO creators(username, profile_url, first_seen_at, last_seen_at, source)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    profile_url=excluded.profile_url,
                    last_seen_at=excluded.last_seen_at
                """,
                (username, f"https://www.instagram.com/{username}/", now, now, stage),
            )
        for row in rows:
            conn.execute(
                """
                INSERT INTO posts(
                    upsert_key, username, profile_url, hotspot_url, media_type, caption,
                    create_time_iso, publish_ts, like_count, comment_count, play_count,
                    heat_value, raw_json, first_seen_at, last_seen_at, crawl_count
                )
                VALUES(
                    :upsert_key, :username, :profile_url, :hotspot_url, :media_type, :caption,
                    :create_time_iso, :publish_ts, :like_count, :comment_count, :play_count,
                    :heat_value, :raw_json, :first_seen_at, :last_seen_at, 1
                )
                ON CONFLICT(upsert_key) DO UPDATE SET
                    username=excluded.username,
                    profile_url=excluded.profile_url,
                    hotspot_url=excluded.hotspot_url,
                    media_type=excluded.media_type,
                    caption=excluded.caption,
                    create_time_iso=excluded.create_time_iso,
                    publish_ts=excluded.publish_ts,
                    like_count=excluded.like_count,
                    comment_count=excluded.comment_count,
                    play_count=excluded.play_count,
                    heat_value=excluded.heat_value,
                    raw_json=excluded.raw_json,
                    last_seen_at=excluded.last_seen_at,
                    crawl_count=posts.crawl_count + 1
                """,
                {**row, "first_seen_at": now, "last_seen_at": now},
            )
        conn.execute(
            "INSERT INTO crawl_runs(stage, crawled_at, post_count, creator_count) VALUES(?, ?, ?, ?)",
            (stage, now, len(rows), len(creators)),
        )
        conn.commit()
    return len(rows)


def creator_average(
    conn: sqlite3.Connection,
    username: str,
    *,
    baseline_days: int,
    exclude_key: str,
    baseline_cutoff_iso: str | None = None,
) -> dict[str, Any]:
    cutoff_ts = int((datetime.now() - timedelta(days=baseline_days)).timestamp())
    params: list[Any] = [username, cutoff_ts, exclude_key]
    cutoff_filter = ""
    if baseline_cutoff_iso:
        cutoff_filter = " AND first_seen_at < ?"
        params.append(baseline_cutoff_iso)
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS count, AVG(like_count) AS avg_likes, AVG(comment_count) AS avg_comments
        FROM posts
        WHERE username = ?
          AND publish_ts >= ?
          AND upsert_key != ?
          {cutoff_filter}
        """,
        params,
    ).fetchone()
    count = int(row["count"] or 0) if row else 0
    return {
        "baselinePostCount": count,
        "avgLikes": float(row["avg_likes"] or 0) if row else 0.0,
        "avgComments": float(row["avg_comments"] or 0) if row else 0.0,
    }


def item_publish_day(item: dict[str, Any]) -> str:
    dt = parse_ins_datetime(item)
    return dt.date().isoformat() if dt else datetime.now().date().isoformat()


def high_heat_details(
    item: dict[str, Any],
    rules: dict[str, Any],
    conn: sqlite3.Connection,
    *,
    baseline_cutoff_iso: str | None = None,
) -> dict[str, Any]:
    cfg = rules.get("hot_post", {}) if isinstance(rules.get("hot_post"), dict) else {}
    baseline_days = int(cfg.get("baseline_days", 7) or 7)
    min_ratio = float(cfg.get("min_ratio_to_average", 1.0) or 1.0)
    high_score_k = max(1.0, float(cfg.get("high_score_k", 600.0) or 600.0))
    username = item_username(item)
    key = item_key(item)
    averages = creator_average(
        conn,
        username,
        baseline_days=baseline_days,
        exclude_key=key,
        baseline_cutoff_iso=baseline_cutoff_iso,
    )
    likes = safe_int(item.get("diggCount") or item.get("likeCount"))
    comments = safe_int(item.get("commentCount"))
    raw_heat = likes + 8 * comments
    avg_heat = averages["avgLikes"] + 8 * averages["avgComments"]
    heat_ratio = raw_heat / avg_heat if avg_heat > 0 else 0.0
    raw_ins_heat_score = heat_ratio * 100
    if raw_ins_heat_score <= 100:
        ins_heat_score = raw_ins_heat_score
    else:
        over_score = raw_ins_heat_score - 100
        ins_heat_score = 100 + 50 * over_score / (over_score + high_score_k)
    heat_threshold = avg_heat * min_ratio
    is_hot = bool(
        averages["baselinePostCount"] > 0
        and raw_heat >= heat_threshold
    )
    if averages["baselinePostCount"] <= 0:
        baseline_type = "no_history_daily_cap"
        reason = "no creator history in the baseline window; eligible for daily per-creator cap"
    elif is_hot:
        baseline_type = "history_average"
        reason = f"weighted heat score is {ins_heat_score:.1f}, at or above {min_ratio * 100:.0f} for creator {baseline_days}-day average"
    else:
        baseline_type = "below_history_average"
        reason = f"weighted heat score is {ins_heat_score:.1f}, below {min_ratio * 100:.0f} for creator available-history average"
    return {
        "isHighHeat": is_hot,
        "baselineType": baseline_type,
        "baselineDays": baseline_days,
        "minRatioToAverage": min_ratio,
        "rawHeat": raw_heat,
        "avgHeat": avg_heat,
        "heatRatio": heat_ratio,
        "rawInsHeatScore": raw_ins_heat_score,
        "insHeatScore": ins_heat_score,
        "highScoreK": high_score_k,
        "heatThreshold": heat_threshold,
        "likes": likes,
        "comments": comments,
        "likeThreshold": averages["avgLikes"] * min_ratio,
        "commentThreshold": averages["avgComments"] * min_ratio,
        **averages,
        "reason": reason,
    }


def apply_high_heat_filter(
    items: list[dict[str, Any]],
    rules: dict[str, Any],
    *,
    baseline_cutoff_iso: str | None = None,
) -> list[dict[str, Any]]:
    if not rules.get("hot_post", {}).get("enabled", True):
        return items
    kept: list[dict[str, Any]] = []
    no_history_candidates: dict[tuple[str, str], dict[str, Any]] = {}
    with connect(rules) as conn:
        for item in items:
            updated = dict(item)
            details = high_heat_details(updated, rules, conn, baseline_cutoff_iso=baseline_cutoff_iso)
            updated["insHighHeat"] = details
            if details.get("isHighHeat"):
                kept.append(updated)
                continue
            if details.get("baselineType") != "no_history_daily_cap":
                continue
            username = item_username(updated)
            if not username:
                continue
            group_key = (username, item_publish_day(updated))
            previous = no_history_candidates.get(group_key)
            if previous is None or safe_float(updated.get("heatValue")) > safe_float(previous.get("heatValue")):
                no_history_candidates[group_key] = updated
    for item in no_history_candidates.values():
        updated = dict(item)
        details = dict(updated.get("insHighHeat") or {})
        details["isHighHeat"] = True
        details["baselineType"] = "no_history_daily_cap"
        details["reason"] = "no creator history in the baseline window; selected as the daily top candidate for this creator"
        updated["insHighHeat"] = details
        kept.append(updated)
    return kept


def week_key(now: datetime | None = None) -> str:
    resolved = now or datetime.now()
    year, week, _weekday = resolved.isocalendar()
    return f"{year}-W{week:02d}"


def has_discovery_run_this_week(rules: dict[str, Any], now: datetime | None = None) -> bool:
    key = week_key(now)
    with connect(rules) as conn:
        row = conn.execute(
            "SELECT 1 FROM discovery_runs WHERE week_key = ? AND status = 'completed' LIMIT 1",
            (key,),
        ).fetchone()
    return bool(row)


def record_discovery_run(rules: dict[str, Any], report: dict[str, Any], *, status: str = "completed", now: datetime | None = None) -> None:
    resolved = now or datetime.now()
    with connect(rules) as conn:
        conn.execute(
            """
            INSERT INTO discovery_runs(week_key, ran_at, status, report_json)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(week_key) DO UPDATE SET
                ran_at=excluded.ran_at,
                status=excluded.status,
                report_json=excluded.report_json
            """,
            (week_key(resolved), resolved.isoformat(), status, json.dumps(report, ensure_ascii=False)),
        )
        conn.commit()
