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
VALID_ACTIONS = frozenset({
    "view", "jobs_click", "profile_click", "community_click",
    "company_click", "vacancy_click", "apply_click",
})
PUBLIC_SOURCE_RE = re.compile(r"^(vacancy|company):([1-9][0-9]{0,9})$")


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
            public_match = PUBLIC_SOURCE_RE.fullmatch(source)
            if public_match:
                kind, raw_id = public_match.groups()
                resource_id = int(raw_id)
                if kind == "vacancy":
                    valid = db.execute(
                        """SELECT 1 FROM vacancies v
                           JOIN users u ON u.id=v.employer_id AND u.role='employer'
                           LEFT JOIN account_controls c ON c.user_id=v.employer_id
                           LEFT JOIN vacancy_moderation vm ON vm.vacancy_id=v.id
                           WHERE v.id=? AND v.status='open'
                             AND COALESCE(c.status,'active')='active'
                             AND COALESCE(vm.status,'approved')='approved'
                             AND NOT EXISTS (
                               SELECT 1 FROM privacy_rights_requests pr
                               WHERE pr.user_id=v.employer_id
                                 AND pr.kind IN ('deletion','stop_processing')
                                 AND pr.status IN ('received','in_review','completed')
                             )""",
                        (resource_id,),
                    ).fetchone()
                else:
                    # Company pages stay public as an empty state even when the
                    # last approved vacancy closes. Match public_company() rather
                    # than tying company visibility to vacancy availability.
                    valid = db.execute(
                        """SELECT 1 FROM employer_profiles e
                           JOIN users u ON u.id=e.user_id AND u.role='employer'
                           LEFT JOIN account_controls c ON c.user_id=e.user_id
                           WHERE e.user_id=? AND COALESCE(c.status,'active')='active'
                             AND NOT EXISTS (
                               SELECT 1 FROM privacy_rights_requests pr
                               WHERE pr.user_id=e.user_id
                                 AND pr.kind IN ('deletion','stop_processing')
                                 AND pr.status IN ('received','in_review','completed')
                             )""",
                        (resource_id,),
                    ).fetchone()
                if valid is None:
                    raise ValueError("Unsupported aggregate event")
            else:
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
        public_match = PUBLIC_SOURCE_RE.fullmatch(source)
        if not public_match:
            sources[source] = {"title": "Удалённый материал", "kind": "article", "published": False}
            continue
        kind, raw_id = public_match.groups()
        resource_id = int(raw_id)
        if kind == "vacancy":
            row = db.execute(
                """SELECT v.title,e.company_name,
                          CASE WHEN v.status='open'
                            AND COALESCE(c.status,'active')='active'
                            AND COALESCE(vm.status,'approved')='approved'
                            AND NOT EXISTS (
                              SELECT 1 FROM privacy_rights_requests pr
                              WHERE pr.user_id=v.employer_id
                                AND pr.kind IN ('deletion','stop_processing')
                                AND pr.status IN ('received','in_review','completed')
                            ) THEN 1 ELSE 0 END AS is_public
                   FROM vacancies v
                   LEFT JOIN employer_profiles e ON e.user_id=v.employer_id
                   LEFT JOIN account_controls c ON c.user_id=v.employer_id
                   LEFT JOIN vacancy_moderation vm ON vm.vacancy_id=v.id
                   WHERE v.id=?""",
                (resource_id,),
            ).fetchone()
            sources[source] = {
                "title": (
                    f"Вакансия: {row['title']} — {row['company_name'] or 'работодатель'}"
                    if row else f"Удалённая вакансия #{resource_id}"
                ),
                "kind": "vacancy",
                "published": bool(row and row["is_public"]),
            }
        else:
            row = db.execute(
                """SELECT e.company_name,
                          CASE WHEN COALESCE(c.status,'active')='active'
                            AND NOT EXISTS (
                              SELECT 1 FROM privacy_rights_requests pr
                              WHERE pr.user_id=e.user_id
                                AND pr.kind IN ('deletion','stop_processing')
                                AND pr.status IN ('received','in_review','completed')
                            ) THEN 1 ELSE 0 END AS is_public
                   FROM employer_profiles e
                   JOIN users u ON u.id=e.user_id AND u.role='employer'
                   LEFT JOIN account_controls c ON c.user_id=e.user_id
                   WHERE e.user_id=?""",
                (resource_id,),
            ).fetchone()
            sources[source] = {
                "title": f"Компания: {row['company_name']}" if row else f"Удалённая компания #{resource_id}",
                "kind": "company",
                "published": bool(row and row["is_public"]),
            }
    totals = {source: {"source": source, **metadata, **dict.fromkeys(VALID_ACTIONS, 0)}
              for source, metadata in sources.items()}
    for item in counters:
        if item["action"] in VALID_ACTIONS:
            totals[item["source"]][item["action"]] += item["total"]
    for row in totals.values():
        clicks = sum(row[action] for action in VALID_ACTIONS if action != "view")
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
        "journal_requests": sum(
            item["total"] for item in counters
            if item["action"] == "view" and not PUBLIC_SOURCE_RE.fullmatch(item["source"])
        ),
        "public_vacancy_views": sum(
            item["total"] for item in counters
            if item["action"] == "view" and item["source"].startswith("vacancy:")
        ),
        "public_company_views": sum(
            item["total"] for item in counters
            if item["action"] == "view" and item["source"].startswith("company:")
        ),
        "jobs_clicks": sum(
            item["total"] for item in counters
            if item["action"] == "jobs_click" and not PUBLIC_SOURCE_RE.fullmatch(item["source"])
        ),
        "profile_clicks": sum(item["total"] for item in counters if item["action"] == "profile_click"),
        "community_clicks": sum(item["total"] for item in counters if item["action"] == "community_click"),
        "company_clicks": sum(item["total"] for item in counters if item["action"] == "company_click"),
        "vacancy_clicks": sum(item["total"] for item in counters if item["action"] == "vacancy_click"),
        "apply_clicks": sum(item["total"] for item in counters if item["action"] == "apply_click"),
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
