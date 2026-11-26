"""Optional professional portfolio entries, moderated separately from profiles."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import Depends, HTTPException, Query
from pydantic import Field, field_validator

from .community import (
    CommunityModel, ModerationInput, PAGE_SIZE, PublishInput, VersionInput,
    _active_account, _check_version, _committed, _is_published, _key, _lock_actors,
    _now, _profile, _public_text, public_person,
)
from .community_feed import _private

PORTFOLIO_CONSENT = "professional-portfolio-2026-11-26"
PORTFOLIO_LIMIT = 30
PUBLIC_FIELDS = ("id", "kind", "title", "period", "contribution", "result")
CONTENT_FIELDS = PUBLIC_FIELDS[1:]
OWN_FIELDS = PUBLIC_FIELDS + ("version", "status", "consent_at", "consent_version",
                             "moderation_reason", "created_at", "updated_at", "published_at")


class PortfolioContent(CommunityModel):
    kind: Literal["project", "achievement", "experience"]
    title: str = Field(min_length=3, max_length=120)
    period: str = Field(default="", max_length=60)
    contribution: str = Field(min_length=10, max_length=1200)
    result: str = Field(min_length=3, max_length=1000)

    _safe = field_validator("title", "period", "contribution", "result")(_public_text)


class PortfolioCreate(PortfolioContent):
    client_key: UUID


class PortfolioEdit(PortfolioContent):
    expected_version: int = Field(ge=1)


def _dto(row):
    return {key: row[key] for key in OWN_FIELDS}


def _owned(db, owner, entry_id):
    row = db.execute(
        "SELECT * FROM community_portfolio_entries WHERE user_id=? AND id=?", (owner, entry_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Запись портфолио недоступна")
    return row


def public_portfolio(db, public_id: str) -> list[dict]:
    # Repeat the parent visibility predicates in the actual content query:
    # even a concurrently withdrawn parent must not reveal a portfolio.
    rows = db.execute(
        """SELECT e.id,e.kind,e.title,e.period,e.contribution,e.result
           FROM community_portfolio_entries e
           JOIN community_profiles p ON p.user_id=e.user_id
           JOIN users u ON u.id=p.user_id
           LEFT JOIN account_controls ac ON ac.user_id=p.user_id
           WHERE p.public_id=? AND p.status='published' AND p.consent_at IS NOT NULL
             AND p.consent_content_version=p.content_version AND p.reviewed_content_version=p.content_version
             AND u.role='candidate' AND COALESCE(ac.status,'active')='active'
             AND NOT EXISTS (
                 SELECT 1 FROM privacy_rights_requests pr WHERE pr.user_id=p.user_id
                   AND pr.kind IN ('deletion','stop_processing')
                   AND pr.status IN ('received','in_review','completed')
             )
             AND e.status='published' AND e.consent_at IS NOT NULL
           ORDER BY e.published_at DESC,e.id DESC LIMIT ?""",
        (public_id, PORTFOLIO_LIMIT),
    ).fetchall()
    return [{field: row[field] for field in PUBLIC_FIELDS} for row in rows]


def install_portfolio_routes(app, community_user, throttle, get_connection, allowed, record_security_event):
    def candidate(user, db):
        allowed(user, "candidate")
        if not _active_account(db, user["id"]):
            raise HTTPException(403, "Портфолио недоступно при ограничении обработки данных")

    @app.get("/api/community/portfolio")
    def mine(user: dict = Depends(community_user), db=Depends(get_connection)):
        candidate(user, db)
        rows = db.execute(
            """SELECT * FROM community_portfolio_entries WHERE user_id=?
               ORDER BY updated_at DESC,id DESC LIMIT ?""", (user["id"], PORTFOLIO_LIMIT),
        ).fetchall()
        profile = _profile(db, user["id"])
        return _private({"entries": [_dto(row) for row in rows], "has_profile": profile is not None,
                         "can_publish": _is_published(db, user["id"]), "limit": PORTFOLIO_LIMIT,
                         "public_id": profile["public_id"] if profile else None})

    @app.get("/api/community/people/{public_id}/portfolio")
    def portfolio(public_id: str, db=Depends(get_connection)):
        public_person(db, public_id)
        return _private({"entries": public_portfolio(db, public_id)})

    @app.post("/api/community/portfolio")
    def create(data: PortfolioCreate, user: dict = Depends(community_user), db=Depends(get_connection)):
        owner = user["id"]
        _lock_actors(db, owner)
        candidate(user, db)
        if _profile(db, owner) is None:
            raise HTTPException(409, "Сначала сохраните профессиональный профиль")
        old = db.execute(
            "SELECT * FROM community_portfolio_entries WHERE user_id=? AND client_key=?",
            (owner, str(data.client_key)),
        ).fetchone()
        if old is not None:
            if any(old[field] != getattr(data, field) for field in CONTENT_FIELDS):
                raise HTTPException(409, "Эта запись уже сохранена. Обновите список")
            return _committed(db, {"entry": _dto(old)})
        count = db.execute("SELECT COUNT(*) FROM community_portfolio_entries WHERE user_id=?",
                           (owner,)).fetchone()[0]
        if count >= PORTFOLIO_LIMIT:
            raise HTTPException(409, "Достигнут лимит портфолио. Измените существующие записи")
        throttle(db, owner, "community-portfolio-create", 30, 3600)
        key, now = _key(), _now()
        db.execute(
            """INSERT INTO community_portfolio_entries(id,user_id,client_key,kind,title,period,
               contribution,result,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (key, owner, str(data.client_key), *(getattr(data, field) for field in CONTENT_FIELDS), now, now),
        )
        return _committed(db, {"entry": _dto(_owned(db, owner, key))})

    @app.put("/api/community/portfolio/{entry_id}")
    def edit(entry_id: str, data: PortfolioEdit, user: dict = Depends(community_user),
             db=Depends(get_connection)):
        owner = user["id"]
        _lock_actors(db, owner)
        candidate(user, db)
        row = _owned(db, owner, entry_id)
        _check_version(row, data.expected_version)
        if all(row[field] == getattr(data, field) for field in CONTENT_FIELDS):
            return _committed(db, {"entry": _dto(row)})
        throttle(db, owner, "community-portfolio-edit", 60, 3600)
        db.execute(
            """UPDATE community_portfolio_entries SET kind=?,title=?,period=?,contribution=?,result=?,
               status='draft',version=version+1,consent_at=NULL,consent_version=NULL,
               reviewed_by=NULL,reviewed_at=NULL,published_at=NULL,moderation_reason='',updated_at=?
               WHERE user_id=? AND id=? AND version=?""",
            (*(getattr(data, field) for field in CONTENT_FIELDS), _now(), owner, entry_id, data.expected_version),
        )
        return _committed(db, {"entry": _dto(_owned(db, owner, entry_id))})

    @app.post("/api/community/portfolio/{entry_id}/submit")
    def submit(entry_id: str, data: PublishInput, user: dict = Depends(community_user),
               db=Depends(get_connection)):
        owner = user["id"]
        _lock_actors(db, owner)
        candidate(user, db)
        row = _owned(db, owner, entry_id)
        _check_version(row, data.expected_version)
        if not data.publish_consent:
            raise HTTPException(400, "Подтвердите согласие на публичное размещение этой записи")
        if not _is_published(db, owner):
            raise HTTPException(409, "Сначала опубликуйте профессиональный профиль")
        if row["status"] in {"pending", "published"}:
            return _committed(db, {"entry": _dto(row)})
        throttle(db, owner, "community-portfolio-submit", 20, 3600)
        now = _now()
        db.execute(
            """UPDATE community_portfolio_entries SET status='pending',version=version+1,
               consent_at=?,consent_version=?,reviewed_by=NULL,reviewed_at=NULL,published_at=NULL,
               moderation_reason='',updated_at=? WHERE user_id=? AND id=? AND version=?""",
            (now, PORTFOLIO_CONSENT, now, owner, entry_id, data.expected_version),
        )
        return _committed(db, {"entry": _dto(_owned(db, owner, entry_id))})

    @app.delete("/api/community/portfolio/{entry_id}/publication")
    def withdraw(entry_id: str, data: VersionInput, user: dict = Depends(community_user),
                 db=Depends(get_connection)):
        owner = user["id"]
        allowed(user, "candidate")
        _lock_actors(db, owner)
        row = _owned(db, owner, entry_id)
        _check_version(row, data.expected_version)
        db.execute(
            """UPDATE community_portfolio_entries SET status='hidden',version=version+1,
               consent_at=NULL,consent_version=NULL,published_at=NULL,updated_at=?
               WHERE user_id=? AND id=? AND version=?""",
            (_now(), owner, entry_id, data.expected_version),
        )
        return _committed(db, {"entry": _dto(_owned(db, owner, entry_id))})

    @app.get("/api/admin/community/portfolio")
    def queue(status: Literal["pending", "published"] = "pending",
              page: int = Query(default=1, ge=1, le=10000),
              user: dict = Depends(community_user), db=Depends(get_connection)):
        allowed(user, "admin")
        rows = db.execute(
            """SELECT e.*,p.public_id,p.status AS profile_status,
                      CASE WHEN p.status='published' AND p.consent_at IS NOT NULL
                        AND p.consent_content_version=p.content_version
                        AND p.reviewed_content_version=p.content_version THEN p.public_name ELSE NULL END AS public_name,
                      CASE WHEN p.status='published' AND p.consent_at IS NOT NULL
                        AND p.consent_content_version=p.content_version
                        AND p.reviewed_content_version=p.content_version THEN p.headline ELSE NULL END AS headline
               FROM community_portfolio_entries e JOIN community_profiles p ON p.user_id=e.user_id
               WHERE e.status=? AND e.consent_at IS NOT NULL
               ORDER BY e.updated_at,e.id LIMIT ? OFFSET ?""",
            (status, PAGE_SIZE + 1, (page - 1) * PAGE_SIZE),
        ).fetchall()
        return _private({"entries": [{**_dto(row), **{key: row[key] for key in
                                      ("public_id", "public_name", "headline", "profile_status")}}
                                     for row in rows[:PAGE_SIZE]],
                         "page": page, "has_more": len(rows) > PAGE_SIZE})

    @app.patch("/api/admin/community/portfolio/{entry_id}")
    def moderate(entry_id: str, data: ModerationInput, user: dict = Depends(community_user),
                 db=Depends(get_connection)):
        allowed(user, "admin")
        found = db.execute("SELECT user_id FROM community_portfolio_entries WHERE id=?", (entry_id,)).fetchone()
        if found is None:
            raise HTTPException(404, "Запись недоступна")
        owner = int(found["user_id"])
        _lock_actors(db, owner)
        row = _owned(db, owner, entry_id)
        _check_version(row, data.expected_version)
        if row["status"] not in {"pending", "published"} or not row["consent_at"]:
            raise HTTPException(409, "Эта версия не доступна для модерации")
        now = _now()
        if data.decision == "approve":
            if row["status"] != "pending" or not _is_published(db, owner):
                raise HTTPException(409, "Нельзя одобрить запись без опубликованного профиля")
            status, reason, published = "published", "", now
        else:
            if data.decision == "reject" and row["status"] != "pending":
                raise HTTPException(409, "Запись уже не ожидает проверки")
            if not data.reason.strip():
                raise HTTPException(422, "Укажите причину для автора")
            status, reason, published = ("rejected" if data.decision == "reject" else "hidden"), data.reason.strip(), None
        db.execute(
            """UPDATE community_portfolio_entries SET status=?,version=version+1,moderation_reason=?,
               reviewed_by=?,reviewed_at=?,published_at=?,updated_at=?,
               consent_at=CASE WHEN ?='published' THEN consent_at ELSE NULL END,
               consent_version=CASE WHEN ?='published' THEN consent_version ELSE NULL END
               WHERE id=? AND user_id=? AND version=?""",
            (status, reason, user["id"], now, published, now, status, status, entry_id, owner, data.expected_version),
        )
        record_security_event(db, user["id"], "community_portfolio_reviewed",
                              "entry=" + entry_id + " decision=" + data.decision)
        return _committed(db, {"entry": _dto(_owned(db, owner, entry_id))})
