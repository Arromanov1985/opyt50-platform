"""Moderated professional feed; content is never published by submission alone."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import Field, StrictBool, field_validator, model_validator

from .community import (
    CommunityModel, ModerationInput, VersionInput, PAGE_SIZE,
    _active_account, _committed, _is_published, _key, _lock_actors, _now, _public_text,
)

from .community_groups import group_info, group_member, install_group_routes

FeedKind = Literal["experience", "question", "projects", "mentoring"]
FEED_CONSENT_VERSION = "community-feed-2026-11-25"

# Static parameterized statement for the root list and discussions alike.
# Visibility includes the current author profile, account/privacy controls,
# and reciprocal blocks. A hidden root cannot expose its replies.
_VISIBLE_SQL = """
WITH viewer AS (SELECT CAST(? AS INTEGER) AS viewer_id),
visible AS (
    SELECT f.id,f.parent_id,f.kind,f.title,f.body,f.created_at,f.published_at,
           p.public_id,p.public_name,p.headline,p.city,p.skills,f.author_id,g.group_slug,
           o.intent AS opportunity_intent,o.meeting_format AS opportunity_format,
           o.commitment AS opportunity_commitment,
           CASE WHEN EXISTS (SELECT 1 FROM community_saved_entries se
             WHERE se.user_id=v.viewer_id AND se.entry_id=f.id) THEN 1 ELSE 0 END AS saved,
           CASE WHEN EXISTS (SELECT 1 FROM community_feed_follows ff
             WHERE ff.follower_id=v.viewer_id AND ff.target_id=f.author_id) THEN 1 ELSE 0 END AS followed
    FROM community_feed_entries f
    LEFT JOIN community_opportunities o ON o.entry_id=f.id
    LEFT JOIN community_group_posts g ON g.entry_id=COALESCE(f.parent_id,f.id)
    JOIN community_profiles p ON p.user_id=f.author_id
    JOIN users u ON u.id=p.user_id
    LEFT JOIN account_controls ac ON ac.user_id=p.user_id
    CROSS JOIN viewer v
    WHERE f.status='published' AND f.consent_at IS NOT NULL
      AND p.status='published' AND p.consent_at IS NOT NULL
      AND p.consent_content_version=p.content_version
      AND p.reviewed_content_version=p.content_version
      AND u.role='candidate' AND COALESCE(ac.status,'active')='active'
      AND NOT EXISTS (
        SELECT 1 FROM privacy_rights_requests pr
        WHERE pr.user_id=p.user_id AND pr.kind IN ('deletion','stop_processing')
          AND pr.status IN ('received','in_review','completed')
      )
      AND NOT EXISTS (
        SELECT 1 FROM community_connections c
        WHERE c.status='blocked' AND
          ((c.sender_id=v.viewer_id AND c.recipient_id=f.author_id)
           OR (c.recipient_id=v.viewer_id AND c.sender_id=f.author_id))
      )
)
SELECT v.id,v.parent_id,v.kind,v.title,v.body,v.created_at,v.published_at,
       v.public_id,v.public_name,v.headline,v.followed,v.saved,
       v.opportunity_intent,v.opportunity_format,v.opportunity_commitment,v.city AS opportunity_city,v.group_slug,
       (SELECT root.title FROM visible root WHERE root.id=v.parent_id) AS root_title
FROM visible v CROSS JOIN viewer actor
WHERE (?<>0 OR COALESCE(v.parent_id,'')=?)
  AND (?=0 OR v.followed=1)
  AND (?=0 OR (
      v.parent_id IS NOT NULL AND v.author_id<>actor.viewer_id
      AND EXISTS (SELECT 1 FROM visible root WHERE root.id=v.parent_id
                  AND root.parent_id IS NULL AND root.author_id=actor.viewer_id)
  ))
  AND (?<>1 OR NOT EXISTS (
      SELECT 1 FROM community_feed_alert_reads ar
      WHERE ar.user_id=actor.viewer_id AND ar.entry_id=v.id
  ))
  AND (?='' OR v.id=?)
  AND (?='' OR v.kind=?)
  AND (?=0 OR v.author_id<>actor.viewer_id)
  AND (?='' OR v.group_slug=?)
  AND (?=0 OR v.id IN (
      SELECT se.entry_id FROM community_saved_entries se WHERE se.user_id=actor.viewer_id
      ORDER BY se.created_at DESC,se.entry_id LIMIT ? OFFSET ?
  ))
  AND (?=0 OR v.opportunity_intent IS NOT NULL)
  AND (?='' OR v.opportunity_intent=?)
  AND (?='' OR v.opportunity_format=?)
  AND (?='' OR v.opportunity_commitment=?)
  AND (?='' OR unicode_fold(v.city)=?)
  AND (?='' OR instr(unicode_fold(v.title),?)>0 OR instr(unicode_fold(v.body),?)>0
       OR (?=1 AND (instr(unicode_fold(v.headline),?)>0 OR instr(unicode_fold(v.skills),?)>0)))
  AND (v.parent_id IS NULL OR EXISTS (
    SELECT 1 FROM visible root WHERE root.id=v.parent_id AND root.parent_id IS NULL
  ))
ORDER BY v.published_at DESC,v.id DESC LIMIT ? OFFSET ?
"""


OpportunityKind = Literal["projects", "mentoring"]
OpportunityIntent = Literal["offer", "seek", "organize", "join"]
OpportunityFormat = Literal["online", "offline", "hybrid"]
OpportunityCommitment = Literal["one_off", "regular", "flexible"]
OPPORTUNITY_INTENTS = {"mentoring": {"offer", "seek"}, "projects": {"organize", "join"}}


class OpportunityInput(CommunityModel):
    intent: OpportunityIntent
    meeting_format: OpportunityFormat
    commitment: OpportunityCommitment


class FeedInput(CommunityModel):
    client_key: UUID
    parent_id: str | None = Field(default=None, min_length=1, max_length=64)
    kind: Literal["experience", "question", "projects", "mentoring", "comment"]
    title: str = Field(default="", max_length=140)
    body: str = Field(min_length=1, max_length=2400)
    publish_consent: StrictBool = False
    opportunity: OpportunityInput | None = None
    group_slug: str | None = Field(default=None, min_length=1, max_length=40)

    _safe = field_validator("title", "body")(_public_text)

    @model_validator(mode="after")
    def shape(self):
        if self.parent_id:
            if self.kind != "comment" or self.title or len(self.body) > 1000:
                raise ValueError("Комментарий должен содержать только текст до 1000 символов")
        elif self.kind == "comment" or not self.title:
            raise ValueError("Для публикации укажите тему и заголовок")
        if self.group_slug and (self.parent_id or self.opportunity):
            raise ValueError("Группа определяется исходной публикацией; тематические предложения создаются отдельно")
        if self.opportunity and (self.parent_id or self.opportunity.intent not in OPPORTUNITY_INTENTS.get(self.kind, set())):
            raise ValueError("Выберите подходящую цель предложения")
        if not self.body:
            raise ValueError("Введите текст")
        return self


def _own_dto(row) -> dict:
    fields = ("id", "parent_id", "kind", "title", "body", "status", "version",
              "moderation_reason", "created_at", "published_at")
    result = {field: row[field] for field in fields}
    item = dict(row)
    if item.get("group_slug"):
        result["group_slug"] = item["group_slug"]
    opportunity = _opportunity_dto(item)
    if opportunity:
        result["opportunity"] = opportunity
    return result


def _opportunity_dto(item: dict) -> dict | None:
    if not item.get("opportunity_intent"):
        return None
    return {
        "intent": item["opportunity_intent"],
        "meeting_format": item["opportunity_format"],
        "commitment": item["opportunity_commitment"],
    }


def _entry(db, entry_id: str):
    row = db.execute(
        """SELECT f.*,o.intent AS opportunity_intent,o.meeting_format AS opportunity_format,
                  o.commitment AS opportunity_commitment,g.group_slug
           FROM community_feed_entries f LEFT JOIN community_opportunities o ON o.entry_id=f.id
           LEFT JOIN community_group_posts g ON g.entry_id=COALESCE(f.parent_id,f.id)
           WHERE f.id=?""", (entry_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Публикация недоступна")
    return row


def _visible(db, viewer: int, parent: str = "", entry_id: str = "",
             kind: str = "", q: str = "", page: int = 1,
             following: bool = False, alerts: int = 0,
             opportunity_only: bool = False, intent: str = "", meeting_format: str = "",
             commitment: str = "", city: str = "", saved_page: int = 0,
             exclude_self: bool = False, match_profile: bool = False, group_slug: str = "") -> dict:
    rows = db.execute(_VISIBLE_SQL, (
        viewer, alerts, parent, int(following), alerts, alerts,
        entry_id, entry_id, kind, kind, int(exclude_self), group_slug, group_slug, int(bool(saved_page)),
        PAGE_SIZE, max(0, saved_page - 1) * PAGE_SIZE, int(opportunity_only),
        intent, intent, meeting_format, meeting_format, commitment, commitment, city, city,
        q, q, q, int(opportunity_only or match_profile), q, q,
        PAGE_SIZE + 1, (page - 1) * PAGE_SIZE,
    )).fetchall()
    entries, followed, saved = [], set(), []
    for row in rows[:PAGE_SIZE]:
        item = dict(row)
        if item.pop("saved"):
            saved.append(item["id"])
        if item.pop("followed"):
            followed.add(item["public_id"])
        opportunity = _opportunity_dto(item)
        opportunity_city = item.pop("opportunity_city")
        if not item.get("group_slug"):
            item.pop("group_slug", None)
        for field in ("opportunity_intent", "opportunity_format", "opportunity_commitment"):
            item.pop(field)
        if opportunity:
            item["opportunity"] = {**opportunity, "city": opportunity_city}
        root_title = item.pop("root_title")
        if alerts:
            item["root_title"] = root_title
        entries.append(item)
    return {"entries": entries, "following_public_ids": sorted(followed), "saved_entry_ids": saved,
            "page": page, "has_more": len(rows) > PAGE_SIZE}


def _visible_root(db, viewer: int, entry_id: str) -> dict:
    result = _visible(db, viewer, entry_id=entry_id)["entries"]
    if not result:
        raise HTTPException(404, "Публикация недоступна")
    return result[0]


def _page(rows, page: int) -> dict:
    return {"entries": [_own_dto(row) for row in rows[:PAGE_SIZE]],
            "page": page, "has_more": len(rows) > PAGE_SIZE}


def _private(payload):
    return JSONResponse(payload, headers={
        "Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow",
    })


def install_feed_routes(app, community_user, throttle, get_connection, allowed, record_security_event):
    def reader(user, db):
        if user["role"] not in {"candidate", "employer"} or not _active_account(db, user["id"]):
            raise HTTPException(403, "Лента доступна активным участникам и работодателям")

    def can_publish(user, db):
        return user["role"] == "candidate" and _is_published(db, user["id"])

    @app.get("/api/community/feed")
    def feed(kind: FeedKind | None = None, q: str = Query(default="", max_length=100),
             page: int = Query(default=1, ge=1, le=10000), following: bool = False,
             group_slug: str = Query(default="", max_length=40),
             user: dict = Depends(community_user), db=Depends(get_connection)):
        reader(user, db)
        if group_slug:
            group_info(group_slug)
        result = _visible(db, user["id"], kind=kind or "", q=q.strip().casefold(),
                          page=page, following=following, group_slug=group_slug)
        own = db.execute("SELECT public_id FROM community_profiles WHERE user_id=?",
                         (user["id"],)).fetchone()
        result["own_public_id"] = own["public_id"] if own else None
        return _private(result)

    @app.get("/api/community/opportunities")
    def opportunities(kind: OpportunityKind,
                      intent: OpportunityIntent | None = None,
                      meeting_format: OpportunityFormat | None = None,
                      commitment: OpportunityCommitment | None = None,
                      city: str = Query(default="", max_length=80),
                      q: str = Query(default="", max_length=100),
                      page: int = Query(default=1, ge=1, le=10000),
                      user: dict = Depends(community_user), db=Depends(get_connection)):
        reader(user, db)
        if intent and intent not in OPPORTUNITY_INTENTS[kind]:
            raise HTTPException(422, "Цель не соответствует разделу")
        result = _visible(db, user["id"], kind=kind, q=q.strip().casefold(),
                          page=page, opportunity_only=True, intent=intent or "",
                          meeting_format=meeting_format or "", commitment=commitment or "",
                          city=city.strip().casefold())
        own = db.execute("SELECT public_id FROM community_profiles WHERE user_id=?",
                         (user["id"],)).fetchone()
        result["own_public_id"] = own["public_id"] if own else None
        result["can_publish"] = can_publish(user, db)
        return _private(result)

    @app.get("/api/community/feed/mine")
    def mine(page: int = Query(default=1, ge=1, le=10000),
             opportunity_kind: OpportunityKind | None = None,
             group_slug: str = Query(default="", max_length=40),
             user: dict = Depends(community_user), db=Depends(get_connection)):
        if user["role"] != "candidate":
            raise HTTPException(403, "Раздел доступен участникам с профессиональным профилем")
        if group_slug:
            group_info(group_slug)
        rows = db.execute(
            """SELECT f.*,o.intent AS opportunity_intent,o.meeting_format AS opportunity_format,
                      o.commitment AS opportunity_commitment,g.group_slug
               FROM community_feed_entries f LEFT JOIN community_opportunities o ON o.entry_id=f.id
               LEFT JOIN community_group_posts g ON g.entry_id=COALESCE(f.parent_id,f.id)
               WHERE f.author_id=? AND (?='' OR (o.entry_id IS NOT NULL AND f.kind=?))
                 AND (?='' OR g.group_slug=?)
               ORDER BY f.created_at DESC,f.id DESC LIMIT ? OFFSET ?""",
            (user["id"], opportunity_kind or "", opportunity_kind or "", group_slug, group_slug,
             PAGE_SIZE + 1, (page - 1) * PAGE_SIZE),
        ).fetchall()
        return _private({**_page(rows, page), "can_publish": can_publish(user, db)})

    @app.get("/api/community/feed/{entry_id}/comments")
    def comments(entry_id: str, page: int = Query(default=1, ge=1, le=10000),
                 user: dict = Depends(community_user), db=Depends(get_connection)):
        reader(user, db)
        root = _visible_root(db, user["id"], entry_id)
        return _private({"post": root,
                         "can_comment": can_publish(user, db) and (
                             not root.get("group_slug") or group_member(db, user["id"], root["group_slug"])),
                         **_visible(db, user["id"], parent=entry_id, page=page)})

    @app.post("/api/community/feed")
    def submit(data: FeedInput, user: dict = Depends(community_user), db=Depends(get_connection)):
        owner = user["id"]
        reader(user, db)
        if not data.publish_consent:
            raise HTTPException(422, "Подтвердите согласие на показ текста другим участникам после проверки")
        if not can_publish(user, db):
            raise HTTPException(403, "Сначала опубликуйте профессиональный профиль")
        parent_owner = owner
        if data.parent_id:
            _visible_root(db, owner, data.parent_id)
            parent = _entry(db, data.parent_id)
            parent_owner = int(parent["author_id"])
        _lock_actors(db, owner, parent_owner)
        if not can_publish(user, db):
            raise HTTPException(403, "Сначала опубликуйте профессиональный профиль")
        group_slug = data.group_slug
        if data.parent_id:
            _visible_root(db, owner, data.parent_id)
            group_slug = _entry(db, data.parent_id)["group_slug"]
        if group_slug:
            group_info(group_slug)
            if not group_member(db, owner, group_slug):
                raise HTTPException(403, "Сначала вступите в тематическую группу")
        previous = db.execute(
            """SELECT f.*,o.intent AS opportunity_intent,o.meeting_format AS opportunity_format,
                      o.commitment AS opportunity_commitment,g.group_slug
               FROM community_feed_entries f LEFT JOIN community_opportunities o ON o.entry_id=f.id
               LEFT JOIN community_group_posts g ON g.entry_id=COALESCE(f.parent_id,f.id)
               WHERE f.author_id=? AND f.client_key=?""",
            (owner, str(data.client_key)),
        ).fetchone()
        if previous is not None:
            expected_opportunity = data.opportunity.model_dump() if data.opportunity else None
            if (any(previous[field] != getattr(data, field) for field in ("parent_id", "kind", "title", "body"))
                    or previous["group_slug"] != group_slug
                    or _opportunity_dto(dict(previous)) != expected_opportunity):
                raise HTTPException(409, "Идентификатор уже использован для другого текста")
            return _committed(db, {"entry": _own_dto(previous)})
        throttle(db, owner, "community-feed-submit", 12, 3600)
        entry_id, now = _key(), _now()
        db.execute(
            """INSERT INTO community_feed_entries(
               id,author_id,parent_id,client_key,kind,title,body,consent_at,consent_version,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (entry_id, owner, data.parent_id, str(data.client_key), data.kind, data.title,
             data.body, now, FEED_CONSENT_VERSION, now, now),
        )
        if data.group_slug:
            db.execute("INSERT INTO community_group_posts(entry_id,group_slug) VALUES(?,?)",
                       (entry_id, data.group_slug))
        if data.opportunity:
            db.execute(
                """INSERT INTO community_opportunities(entry_id,intent,meeting_format,commitment)
                   VALUES(?,?,?,?)""",
                (entry_id, data.opportunity.intent, data.opportunity.meeting_format, data.opportunity.commitment),
            )
        return _committed(db, {"entry": _own_dto(_entry(db, entry_id))})

    @app.delete("/api/community/feed/{entry_id}")
    def withdraw(entry_id: str, data: VersionInput,
                 user: dict = Depends(community_user), db=Depends(get_connection)):
        owner = user["id"]
        _lock_actors(db, owner)
        row = db.execute(
            "SELECT * FROM community_feed_entries WHERE id=? AND author_id=?", (entry_id, owner),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Публикация недоступна")
        if row["version"] != data.expected_version or row["status"] == "hidden":
            raise HTTPException(409, "Статус изменился. Обновите список")
        db.execute(
            """UPDATE community_feed_entries SET status='hidden',version=version+1,
               consent_at=NULL,consent_version=NULL,published_at=NULL,updated_at=?
               WHERE id=? AND author_id=? AND version=?""",
            (_now(), entry_id, owner, data.expected_version),
        )
        return _committed(db, {"entry": _own_dto(_entry(db, entry_id))})

    @app.get("/api/admin/community/feed")
    def review_queue(status: Literal["pending", "published", "rejected", "hidden"] = "pending",
                     page: int = Query(default=1, ge=1, le=10000),
                     user: dict = Depends(community_user), db=Depends(get_connection)):
        allowed(user, "admin")
        rows = db.execute(
            """SELECT f.*,p.public_id,p.public_name,p.headline,
                      root.title AS parent_title,root.body AS parent_body,
                      o.intent AS opportunity_intent,o.meeting_format AS opportunity_format,
                      o.commitment AS opportunity_commitment,g.group_slug
               FROM community_feed_entries f
               LEFT JOIN community_opportunities o ON o.entry_id=f.id
               LEFT JOIN community_group_posts g ON g.entry_id=COALESCE(f.parent_id,f.id)
               LEFT JOIN community_profiles p ON p.user_id=f.author_id
               LEFT JOIN community_feed_entries root ON root.id=f.parent_id
               WHERE f.status=? ORDER BY f.created_at,f.id LIMIT ? OFFSET ?""",
            (status, PAGE_SIZE + 1, (page - 1) * PAGE_SIZE),
        ).fetchall()
        entries = [
            {**_own_dto(row), **{key: row[key] for key in
             ("public_id", "public_name", "headline", "parent_title", "parent_body")}}
            for row in rows[:PAGE_SIZE]
        ]
        return _private({"entries": entries, "page": page, "has_more": len(rows) > PAGE_SIZE})

    @app.patch("/api/admin/community/feed/{entry_id}")
    def moderate(entry_id: str, data: ModerationInput,
                 user: dict = Depends(community_user), db=Depends(get_connection)):
        allowed(user, "admin")
        row = _entry(db, entry_id)
        parent_owner = int(row["author_id"])
        if row["parent_id"]:
            parent_owner = int(_entry(db, row["parent_id"])["author_id"])
        _lock_actors(db, int(row["author_id"]), parent_owner)
        row = _entry(db, entry_id)
        if row["version"] != data.expected_version:
            raise HTTPException(409, "Статус изменился. Обновите список")
        if data.decision == "approve":
            if row["status"] != "pending" or not row["consent_at"] or not _is_published(db, row["author_id"]):
                raise HTTPException(409, "Нельзя одобрить этот текст без согласия и действующего профиля")
            if row["parent_id"]:
                _visible_root(db, int(row["author_id"]), row["parent_id"])
            status, published, reason = "published", _now(), ""
        else:
            if not data.reason.strip():
                raise HTTPException(422, "Укажите причину для автора")
            if (data.decision == "reject" and row["status"] != "pending") or (
                data.decision == "hide" and row["status"] not in {"pending", "published"}
            ):
                raise HTTPException(409, "Недопустимое изменение статуса")
            status = "rejected" if data.decision == "reject" else "hidden"
            published, reason = None, data.reason.strip()
        now = _now()
        db.execute(
            """UPDATE community_feed_entries SET status=?,published_at=?,moderation_reason=?,
               reviewed_by=?,reviewed_at=?,updated_at=?,version=version+1
               WHERE id=? AND version=?""",
            (status, published, reason, user["id"], now, now, entry_id, data.expected_version),
        )
        record_security_event(db, user["id"], "community_feed_reviewed",
                              "entry=" + entry_id + " status=" + status)
        return _committed(db, {"entry": _own_dto(_entry(db, entry_id))})

    from .community_engagement import install_engagement_routes
    install_engagement_routes(app, community_user, throttle, get_connection, allowed,
                              record_security_event, reader)

    from .community_discovery import install_discovery_routes
    install_discovery_routes(app, community_user, throttle, get_connection, reader, can_publish)

    install_group_routes(app, community_user, throttle, get_connection, reader, allowed)
