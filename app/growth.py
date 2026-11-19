"""Privacy-minimal, daily aggregate journal analytics.

The table has exactly four fields: UTC date, a vetted editorial source,
an event type, and a count. No user identifiers, IP addresses, session
tokens, user agents, referrers, UTM strings or personal data are stored.
These are *events*, not unique visitors or attributable conversions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any

from .db import database
from .journal import BY_SLUG

VALID_SOURCES = frozenset({"journal", *BY_SLUG})
from .journal_paths import PATHS

PATH_SOURCES = frozenset("path-" + item["slug"] for item in PATHS)
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
        # A newly published editor article is valid even if absent from the
        # original six/ten-file release catalog. Reject arbitrary identifiers.
        if source not in VALID_SOURCES and source not in PATH_SOURCES:
            if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", source):
                raise ValueError("Unsupported aggregate event")
            valid = db.execute(
                "SELECT 1 FROM journal_entries WHERE slug=? AND status='published'",
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


def aggregate_snapshot(db: Any, days: int) -> dict:
    """Admin-only rollup of approved click events and *independent* signups."""
    if not 1 <= days <= 90:
        raise ValueError("Invalid reporting period")
    today = datetime.now(timezone.utc).date()
    since = (today - timedelta(days=days - 1)).isoformat()
    counters = [
        {
            "date": row["event_date"],
            "source": row["source"],
            "action": row["action"],
            "total": int(row["total"]),
        }
        for row in db.execute(
            """SELECT event_date,source,action,total FROM growth_daily_counts
               WHERE event_date>=? ORDER BY event_date DESC, source, action""",
            (since,),
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
               AND substr(created_at,1,10)>=?
               GROUP BY substr(created_at,1,10),role ORDER BY day DESC,role""",
            (since,),
        ).fetchall()
    ]
    summary = {
        "journal_requests": sum(item["total"] for item in counters if item["action"] == "view"),
        "jobs_clicks": sum(item["total"] for item in counters if item["action"] == "jobs_click"),
        "profile_clicks": sum(item["total"] for item in counters if item["action"] == "profile_click"),
        "new_candidates": sum(item["total"] for item in registrations if item["role"] == "candidate"),
        "new_employers": sum(item["total"] for item in registrations if item["role"] == "employer"),
    }
    return {
        "days": days,
        "since": since,
        "through": today.isoformat(),
        "summary": summary,
        "by_article": counters,
        "registrations": registrations,
        "limitations": (
            "Просмотры и переходы — события браузера, не уникальные пользователи. "
            "Регистрации подсчитаны независимо: источник конкретной регистрации "
            "не определяется. Блокировщики и роботы могут искажать показатели."
        ),
    }
