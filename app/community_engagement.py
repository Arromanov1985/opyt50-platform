"""Private following, comment attention and moderation reports for the feed."""
from __future__ import annotations

from typing import Literal

from fastapi import Depends, HTTPException, Query
from pydantic import Field

from .community import CommunityModel, PAGE_SIZE, _committed, _key, _lock_actors, _now
from .community_feed import _entry, _private, _visible


class FollowInput(CommunityModel):
    public_id: str = Field(min_length=1, max_length=100)


class FeedReportInput(CommunityModel):
    reason: Literal["spam", "fraud", "harassment", "personal_data", "other"]
    details: str = Field(default="", max_length=1000)


class FeedReportDecision(CommunityModel):
    decision: Literal["resolve", "dismiss", "hide"]
    reason: str = Field(default="", max_length=500)


# List unavailable subscriptions without disclosing the hidden profile's name.
# This also lets the subscriber remove a subscription after a block or withdrawal.
_FOLLOWS_SQL = """
WITH viewer AS (SELECT CAST(? AS INTEGER) AS viewer_id),
following AS (
    SELECT f.created_at,p.public_id,p.public_name,p.headline,
        CASE WHEN p.status='published' AND p.consent_at IS NOT NULL
          AND p.consent_content_version=p.content_version
          AND p.reviewed_content_version=p.content_version
          AND u.role='candidate' AND COALESCE(ac.status,'active')='active'
          AND NOT EXISTS (
            SELECT 1 FROM privacy_rights_requests pr WHERE pr.user_id=p.user_id
              AND pr.kind IN ('deletion','stop_processing')
              AND pr.status IN ('received','in_review','completed')
          )
          AND NOT EXISTS (
            SELECT 1 FROM community_connections c WHERE c.status='blocked'
              AND ((c.sender_id=v.viewer_id AND c.recipient_id=p.user_id)
                OR (c.recipient_id=v.viewer_id AND c.sender_id=p.user_id))
          )
        THEN 1 ELSE 0 END AS available
    FROM community_feed_follows f
    JOIN community_profiles p ON p.user_id=f.target_id
    JOIN users u ON u.id=p.user_id
    LEFT JOIN account_controls ac ON ac.user_id=p.user_id
    CROSS JOIN viewer v
    WHERE f.follower_id=v.viewer_id
)
SELECT public_id,created_at,available,
       CASE WHEN available=1 THEN public_name ELSE NULL END AS public_name,
       CASE WHEN available=1 THEN headline ELSE NULL END AS headline
FROM following ORDER BY created_at DESC,public_id LIMIT ? OFFSET ?
"""


def _follow_target(db, viewer: int, public_id: str):
    return db.execute(
        """SELECT p.user_id FROM community_profiles p
           JOIN users u ON u.id=p.user_id
           LEFT JOIN account_controls ac ON ac.user_id=p.user_id
           WHERE p.public_id=? AND p.status='published' AND p.consent_at IS NOT NULL
             AND p.consent_content_version=p.content_version
             AND p.reviewed_content_version=p.content_version
             AND u.role='candidate' AND COALESCE(ac.status,'active')='active'
             AND NOT EXISTS (
               SELECT 1 FROM privacy_rights_requests pr WHERE pr.user_id=p.user_id
                 AND pr.kind IN ('deletion','stop_processing')
                 AND pr.status IN ('received','in_review','completed')
             )
             AND NOT EXISTS (
               SELECT 1 FROM community_connections c WHERE c.status='blocked'
                 AND ((c.sender_id=? AND c.recipient_id=p.user_id)
                   OR (c.recipient_id=? AND c.sender_id=p.user_id))
             )""", (public_id, viewer, viewer),
    ).fetchone()


def _visible_entry(db, viewer, row):
    return bool(_visible(db, viewer, parent=row["parent_id"] or "",
                         entry_id=row["id"])["entries"])


def _lock_entry(db, viewer, entry_id):
    row = _entry(db, entry_id)
    parent = _entry(db, row["parent_id"]) if row["parent_id"] else row
    _lock_actors(db, viewer, int(row["author_id"]), int(parent["author_id"]))
    return _entry(db, entry_id)


def _report_dto(row):
    return {key: row[key] for key in ("id", "entry_id", "reason", "details", "status",
                                      "created_at", "reviewed_at")}


def install_engagement_routes(app, community_user, throttle, get_connection,
                              allowed, record_security_event, reader):
    @app.get("/api/community/feed/follows")
    def follows(page: int = Query(default=1, ge=1, le=10000),
                user: dict = Depends(community_user), db=Depends(get_connection)):
        reader(user, db)
        rows = db.execute(_FOLLOWS_SQL, (
            user["id"], PAGE_SIZE + 1, (page - 1) * PAGE_SIZE,
        )).fetchall()
        return _private({"follows": [dict(row) for row in rows[:PAGE_SIZE]],
                         "page": page, "has_more": len(rows) > PAGE_SIZE})

    @app.post("/api/community/feed/follows")
    def follow(data: FollowInput, user: dict = Depends(community_user),
               db=Depends(get_connection)):
        reader(user, db)
        owner = user["id"]
        target = _follow_target(db, owner, data.public_id)
        if target is None:
            raise HTTPException(404, "Участник недоступен")
        target_id = int(target["user_id"])
        if target_id == owner:
            raise HTTPException(422, "Нельзя подписаться на себя")
        _lock_actors(db, owner, target_id)
        reader(user, db)
        if _follow_target(db, owner, data.public_id) is None:
            raise HTTPException(404, "Участник недоступен")
        previous = db.execute(
            "SELECT 1 FROM community_feed_follows WHERE follower_id=? AND target_id=?",
            (owner, target_id),
        ).fetchone()
        if previous is None:
            throttle(db, owner, "community-feed-follow", 60, 3600)
            db.execute(
                """INSERT INTO community_feed_follows(follower_id,target_id,created_at)
                   VALUES(?,?,?) ON CONFLICT(follower_id,target_id) DO NOTHING""",
                (owner, target_id, _now()),
            )
        return _committed(db, {"public_id": data.public_id, "following": True})

    @app.delete("/api/community/feed/follows/{public_id}")
    def unfollow(public_id: str, user: dict = Depends(community_user),
                 db=Depends(get_connection)):
        reader(user, db)
        owner = user["id"]
        _lock_actors(db, owner)
        # Removal is idempotent and does not reveal whether the target exists.
        db.execute(
            """DELETE FROM community_feed_follows WHERE follower_id=? AND target_id IN
               (SELECT user_id FROM community_profiles WHERE public_id=?)""",
            (owner, public_id),
        )
        return _committed(db, {"public_id": public_id, "following": False})

    @app.get("/api/community/feed/alerts")
    def alerts(page: int = Query(default=1, ge=1, le=10000),
               user: dict = Depends(community_user), db=Depends(get_connection)):
        reader(user, db)
        result = _visible(db, user["id"], page=page, alerts=1)
        return _private({"entries": result["entries"], "page": page,
                         "has_more": result["has_more"]})

    @app.post("/api/community/feed/alerts/{entry_id}/read")
    def mark_alert_read(entry_id: str, user: dict = Depends(community_user),
                        db=Depends(get_connection)):
        reader(user, db)
        owner = user["id"]
        if not _visible(db, owner, entry_id=entry_id, alerts=2)["entries"]:
            raise HTTPException(404, "Уведомление недоступно")
        _lock_entry(db, owner, entry_id)
        reader(user, db)
        if not _visible(db, owner, entry_id=entry_id, alerts=2)["entries"]:
            raise HTTPException(404, "Уведомление недоступно")
        db.execute(
            """INSERT INTO community_feed_alert_reads(user_id,entry_id,read_at)
               VALUES(?,?,?) ON CONFLICT(user_id,entry_id) DO NOTHING""",
            (owner, entry_id, _now()),
        )
        return _committed(db, {"entry_id": entry_id, "read": True})

    @app.post("/api/community/feed/{entry_id}/reports")
    def report(entry_id: str, data: FeedReportInput, user: dict = Depends(community_user),
               db=Depends(get_connection)):
        reader(user, db)
        owner = user["id"]
        row = _entry(db, entry_id)
        if not _visible_entry(db, owner, row):
            raise HTTPException(404, "Публикация недоступна")
        row = _lock_entry(db, owner, entry_id)
        reader(user, db)
        if not _visible_entry(db, owner, row):
            raise HTTPException(404, "Публикация недоступна")
        if int(row["author_id"]) == owner:
            raise HTTPException(422, "Собственный текст можно скрыть в личном архиве")
        previous = db.execute(
            """SELECT id,status FROM community_feed_reports
               WHERE reporter_id=? AND entry_id=?""",
            (owner, entry_id),
        ).fetchone()
        if previous is not None:
            return _committed(db, {"report": dict(previous)})
        throttle(db, owner, "community-feed-report", 10, 86400)
        report_id = _key()
        db.execute(
            """INSERT INTO community_feed_reports(id,reporter_id,entry_id,reason,details,created_at)
               VALUES(?,?,?,?,?,?)""",
            (report_id, owner, entry_id, data.reason, data.details, _now()),
        )
        return _committed(db, {"report": {"id": report_id, "status": "new"}})

    @app.get("/api/admin/community/feed/reports")
    def reports(status: Literal["new", "resolved", "dismissed"] = "new",
                page: int = Query(default=1, ge=1, le=10000),
                user: dict = Depends(community_user), db=Depends(get_connection)):
        allowed(user, "admin")
        rows = db.execute(
            """SELECT r.*,f.kind,f.title,f.body,f.status AS entry_status,
                      root.title AS parent_title
               FROM community_feed_reports r
               JOIN community_feed_entries f ON f.id=r.entry_id
               LEFT JOIN community_feed_entries root ON root.id=f.parent_id
               WHERE r.status=? ORDER BY r.created_at,r.id LIMIT ? OFFSET ?""",
            (status, PAGE_SIZE + 1, (page - 1) * PAGE_SIZE),
        ).fetchall()
        return _private({
            "reports": [
                {**_report_dto(row), "entry": {
                    key: row[key] for key in ("kind", "title", "body", "entry_status", "parent_title")
                }} for row in rows[:PAGE_SIZE]
            ], "page": page, "has_more": len(rows) > PAGE_SIZE,
        })

    @app.patch("/api/admin/community/feed/reports/{report_id}")
    def review_report(report_id: str, data: FeedReportDecision,
                      user: dict = Depends(community_user), db=Depends(get_connection)):
        allowed(user, "admin")
        report_row = db.execute("SELECT * FROM community_feed_reports WHERE id=?",
                                (report_id,)).fetchone()
        if report_row is None:
            raise HTTPException(404, "Жалоба недоступна")
        row = _lock_entry(db, int(report_row["reporter_id"]), report_row["entry_id"])
        current = db.execute("SELECT * FROM community_feed_reports WHERE id=?",
                             (report_id,)).fetchone()
        if current is None or current["status"] != "new":
            raise HTTPException(409, "Жалоба уже рассмотрена")
        now = _now()
        if data.decision == "hide":
            if not data.reason.strip():
                raise HTTPException(422, "Укажите причину для автора текста")
            if row["status"] in {"published", "pending"}:
                db.execute(
                    """UPDATE community_feed_entries SET status='hidden',published_at=NULL,
                       moderation_reason=?,reviewed_by=?,reviewed_at=?,updated_at=?,version=version+1
                       WHERE id=? AND version=?""",
                    (data.reason.strip(), user["id"], now, now, row["id"], row["version"]),
                )
        status = "dismissed" if data.decision == "dismiss" else "resolved"
        db.execute(
            """UPDATE community_feed_reports SET status=?,reviewed_by=?,reviewed_at=?
               WHERE id=? AND status='new'""",
            (status, user["id"], now, report_id),
        )
        record_security_event(db, user["id"], "community_feed_report_reviewed",
                              "report=" + report_id + " decision=" + data.decision)
        return _committed(db, {"report": _report_dto(db.execute(
            "SELECT * FROM community_feed_reports WHERE id=?", (report_id,),
        ).fetchone())})
