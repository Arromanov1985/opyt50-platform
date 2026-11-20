"""Privacy-minimal, daily aggregate journal analytics.

The table has exactly four fields: UTC date, a vetted editorial source,
an event type, and a count. No user identifiers, IP addresses, session
tokens, user agents, referrers, UTM strings or personal data are stored.
These are *events*, not unique visitors or attributable conversions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
from typing import Any

from .db import database
from .journal_paths import PATHS
from .growth_product import product_snapshot

PATH_SOURCES = {"path:" + item["slug"]: item for item in PATHS}
VALID_ACTIONS = frozenset({"view", "jobs_click", "profile_click", "community_click"})


def record_event(db_path: str, source: str, action: str) -> None:
    """Atomically add one approved event to a per-day counter.

    No user context, browser metadata or identifiable request fields are read.
    Keep at most 180 UTC days of aggregate counters, even on long-running apps.
    """
    if action not in VALID_ACTIONS:
        raise ValueError("Unsupported aggregate event")
    today = datetime.now(timezone.utc).date()
    cutoff = (today - timedelta(days=179)).isoformat()
    with database(db_path) as db:
        if source in PATH_SOURCES:
            # A route exists only while at least one of its steps is published.
            published = {row["slug"] for row in db.execute(
                "SELECT slug FROM journal_entries WHERE status='published' "
                "AND published_json IS NOT NULL"
            ).fetchall()}
            if not any(slug in published for slug, _ in PATH_SOURCES[source]["steps"]):
                raise ValueError("Unsupported aggregate event")
        elif source != "journal":
            # Published CMS entries, including later additions, are the source
            # of truth. Hidden seed articles must not bypass this check.
            if len(source) > 90 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", source):
                raise ValueError("Unsupported aggregate event")
            valid = db.execute(
                "SELECT 1 FROM journal_entries WHERE slug=? AND status='published' "
                "AND published_json IS NOT NULL",
                (source,),
            ).fetchone()
            if valid is None:
                raise ValueError("Unsupported aggregate event")
        db.execute(
            """INSERT INTO growth_daily_counts(event_date,source,action,total)
               VALUES(?,?,?,1)
               ON CONFLICT(event_date,source,action)
               DO UPDATE SET total=growth_daily_counts.total+1""",
            (today.isoformat(), source, action),
        )
        db.execute("DELETE FROM growth_daily_counts WHERE event_date < ?", (cutoff,))


def _source_rollup(db: Any, counters: list[dict]) -> list[dict]:
    """Include all published sources and preserve historical hidden-source totals."""
    entries = db.execute(
        "SELECT slug,published_json,status FROM journal_entries ORDER BY sort_order,slug"
    ).fetchall()
    published = {row["slug"] for row in entries
                 if row["status"] == "published" and row["published_json"]}
    counted = {item["source"] for item in counters}
    sources = {"journal": {"title": "Журнал — список статей", "kind": "index", "published": True}}
    for source, path in PATH_SOURCES.items():
        visible = any(slug in published for slug, _ in path["steps"])
        if visible or source in counted:
            sources[source] = {"title": path["title"], "kind": "path", "published": visible}
    for row in entries:
        if row["slug"] not in published and row["slug"] not in counted:
            continue
        # Use the last published version, never an unfinished editorial draft.
        article = json.loads(row["published_json"]) if row["published_json"] else {}
        sources[row["slug"]] = {
            "title": article.get("title", "Снятый с публикации материал"),
            "kind": "article", "published": row["slug"] in published,
        }
    for source in sorted(counted - sources.keys()):
        sources[source] = {"title": "Удалённый материал", "kind": "article", "published": False}
    totals = {source: {"source": source, **metadata, **dict.fromkeys(VALID_ACTIONS, 0)}
              for source, metadata in sources.items()}
    for item in counters:
        if item["action"] in VALID_ACTIONS:
            totals[item["source"]][item["action"]] += item["total"]
    for row in totals.values():
        clicks = row["jobs_click"] + row["profile_click"] + row["community_click"]
        row["clicks_per_view_percent"] = round(clicks * 100 / row["view"], 1) if row["view"] else None
    return list(totals.values())


def aggregate_snapshot(db: Any, days: int) -> dict:
    """Admin-only rollup of approved click events and *independent* signups."""
    if not 1 <= days <= 90:
        raise ValueError("Invalid reporting period")
    today = datetime.now(timezone.utc).date()
    since = (today - timedelta(days=days - 1)).isoformat()
    through = today.isoformat()
    counters = [
        {
            "date": row["event_date"],
            "source": row["source"],
            "action": row["action"],
            "total": int(row["total"]),
        }
        for row in db.execute(
            """SELECT event_date,source,action,total FROM growth_daily_counts
               WHERE event_date>=? AND event_date<=?
               ORDER BY event_date DESC, source, action""",
            (since, through),
        ).fetchall()
    ]
    registrations = [
        {
            "date": row["day"],
            "role": row["role"],
            "total": int(row["total"]),
        }
        for row in db.execute(
            """SELECT substr(created_at,1,10) AS day,role,COUNT(*) AS total
               FROM users WHERE role IN ('candidate','employer')
               AND substr(created_at,1,10)>=? AND substr(created_at,1,10)<=?
               GROUP BY substr(created_at,1,10),role ORDER BY day DESC,role""",
            (since, through),
        ).fetchall()
    ]
    summary = {
        "journal_requests": sum(item["total"] for item in counters if item["action"] == "view"),
        "jobs_clicks": sum(item["total"] for item in counters if item["action"] == "jobs_click"),
        "profile_clicks": sum(item["total"] for item in counters if item["action"] == "profile_click"),
        "community_clicks": sum(item["total"] for item in counters if item["action"] == "community_click"),
        "new_candidates": sum(item["total"] for item in registrations if item["role"] == "candidate"),
        "new_employers": sum(item["total"] for item in registrations if item["role"] == "employer"),
    }
    return {
        "days": days,
        "since": since,
        "through": through,
        "summary": summary,
        "by_article": counters,
        "by_source": _source_rollup(db, counters),
        "registrations": registrations,
        "product": product_snapshot(db, since, through),
        "limitations": (
            "Просмотры и переходы — события браузера, не уникальные пользователи. "
            "Регистрации подсчитаны независимо: источник конкретной регистрации "
            "не определяется. Блокировщики и роботы могут искажать показатели."
        ),
    }
