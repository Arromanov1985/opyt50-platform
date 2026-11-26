"""Recommendations are personal statements, not verified qualifications or scores.

Both participants must have an accepted professional connection, published
profiles and independent publication consent. Review happens only afterwards.
"""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import Depends, HTTPException, Query
from pydantic import Field, StrictBool, field_validator

from .community import (
    CommunityModel, ModerationInput, PAGE_SIZE,
    VersionInput, _active_account, _check_version, _committed, _connection,
    _is_published, _key, _lock_actors, _now, _public_text, public_person,
)
from .community_feed import _private

CONSENT = "colleague-recommendation-2026-11-26"
PARTICIPANT_FIELDS = ("id", "connection_id", "skill", "context", "body", "status", "version",
                      "author_consent_at", "recipient_consent_at", "moderation_reason",
                      "created_at", "updated_at", "published_at")
PUBLIC_FIELDS = ("id", "skill", "context", "body", "author_public_id", "author_public_name")
# Static SQL; the public-profile visibility conditions are deliberately kept
# explicit here so the analyzer can verify that all user values are bound.
PARTICIPANT_QUERY = """
WITH visible_profiles AS (
    SELECT p.user_id,p.public_id,p.public_name
    FROM community_profiles p JOIN users u ON u.id=p.user_id
    LEFT JOIN account_controls ac ON ac.user_id=p.user_id
    WHERE p.status='published' AND p.consent_at IS NOT NULL
      AND p.consent_content_version=p.content_version
      AND p.reviewed_content_version=p.content_version
      AND u.role='candidate' AND COALESCE(ac.status,'active')='active'
      AND NOT EXISTS (
        SELECT 1 FROM privacy_rights_requests pr WHERE pr.user_id=p.user_id
          AND pr.kind IN ('deletion','stop_processing')
          AND pr.status IN ('received','in_review','completed')
      )
)
SELECT r.*,a.public_id AS author_public_id,a.public_name AS author_public_name,
       b.public_id AS recipient_public_id,b.public_name AS recipient_public_name
FROM community_recommendations r
LEFT JOIN visible_profiles a ON a.user_id=r.author_id
LEFT JOIN visible_profiles b ON b.user_id=r.recipient_id
JOIN community_connections c ON c.id=r.connection_id
"""


class RecommendationInput(CommunityModel):
    connection_id: str = Field(min_length=1, max_length=64)
    client_key: UUID
    skill: str = Field(min_length=3, max_length=100)
    context: str = Field(min_length=10, max_length=200)
    body: str = Field(min_length=20, max_length=1000)
    publish_consent: StrictBool = False

    _safe = field_validator("skill", "context", "body")(_public_text)


class RecipientDecision(VersionInput):
    decision: Literal["accept", "decline"]
    publish_consent: StrictBool = False


def _pair_ready(db, row):
    connection = db.execute("SELECT * FROM community_connections WHERE id=?",
                            (row["connection_id"],)).fetchone()
    return (connection is not None and connection["status"] == "accepted"
            and {connection["sender_id"], connection["recipient_id"]} == {row["author_id"], row["recipient_id"]}
            and _is_published(db, int(row["author_id"]))
            and _is_published(db, int(row["recipient_id"])))


def _row(db, key):
    row = db.execute(PARTICIPANT_QUERY + " WHERE r.id=?", (key,)).fetchone()
    if row is None:
        raise HTTPException(404, "Рекомендация недоступна")
    return row


def _participant(db, key, owner):
    row = _row(db, key)
    if owner not in (row["author_id"], row["recipient_id"]):
        raise HTTPException(404, "Рекомендация недоступна")
    return row


def _locked(db, key, owner=None):
    row = _row(db, key) if owner is None else _participant(db, key, owner)
    _lock_actors(db, int(row["author_id"]), int(row["recipient_id"]))
    return _row(db, key) if owner is None else _participant(db, key, owner)


def _dto(row, owner=None):
    result = {key: row[key] for key in PARTICIPANT_FIELDS}
    if owner is not None:
        outgoing = owner == row["author_id"]
        result["direction"] = "outgoing" if outgoing else "incoming"
        result["counterpart_public_id"] = row["recipient_public_id" if outgoing else "author_public_id"]
        result["counterpart_public_name"] = row["recipient_public_name" if outgoing else "author_public_name"]
    else:
        for key in ("author_public_id", "author_public_name", "recipient_public_id", "recipient_public_name"):
            result[key] = row[key]
    return result


def _revoke(db, *, key=None, owner=None, connection_id=None):
    # One static statement, with bound selectors. A revoked pair cannot be
    # repeatedly solicited. All callers already hold the relevant actor lock.
    db.execute(
        """UPDATE community_recommendations SET status='hidden',version=version+1,
           author_consent_at=NULL,recipient_consent_at=NULL,consent_version=NULL,
           published_at=NULL,updated_at=? WHERE status IN ('offered','pending','published','rejected')
             AND ((?<>'' AND id=?) OR (?<>0 AND ? IN (author_id,recipient_id))
               OR (?<>'' AND connection_id=?))""",
        (_now(), key or "", key or "", owner or 0, owner or 0,
         connection_id or "", connection_id or ""),
    )


def revoke_profile_recommendations(db, owner):
    _revoke(db, owner=owner)


def revoke_connection_recommendations(db, connection_id):
    _revoke(db, connection_id=connection_id)


def public_recommendations(db, public_id):
    rows = db.execute(
        PARTICIPANT_QUERY + """
        WHERE b.public_id=? AND a.user_id IS NOT NULL AND c.status='accepted'
          AND ((c.sender_id=r.author_id AND c.recipient_id=r.recipient_id)
            OR (c.recipient_id=r.author_id AND c.sender_id=r.recipient_id))
          AND r.status='published' AND r.author_consent_at IS NOT NULL
          AND r.recipient_consent_at IS NOT NULL
        ORDER BY r.published_at DESC,r.id DESC LIMIT ?""", (public_id, 50),
    ).fetchall()
    return [{field: row[field] for field in PUBLIC_FIELDS} for row in rows]


def install_reputation_routes(app, community_user, throttle, get_connection, allowed, record_security_event):
    def candidate(user, db):
        allowed(user, "candidate")
        if not _active_account(db, user["id"]):
            raise HTTPException(403, "Рекомендации недоступны при ограничении обработки данных")

    @app.get("/api/community/reputation")
    def mine(direction: Literal["incoming", "outgoing"] = "incoming",
             page: int = Query(default=1, ge=1, le=10000),
             user: dict = Depends(community_user), db=Depends(get_connection)):
        allowed(user, "candidate")
        owner = user["id"]
        rows = db.execute(
            PARTICIPANT_QUERY + """
            WHERE ((?='incoming' AND r.recipient_id=?) OR (?='outgoing' AND r.author_id=?))
            ORDER BY r.updated_at DESC,r.id DESC LIMIT ? OFFSET ?""",
            (direction, owner, direction, owner, PAGE_SIZE + 1, (page - 1) * PAGE_SIZE),
        ).fetchall()
        return _private({"entries": [_dto(row, owner) for row in rows[:PAGE_SIZE]],
                         "page": page, "has_more": len(rows) > PAGE_SIZE,
                         "can_offer": _is_published(db, owner),
                         "restricted": not _active_account(db, owner)})

    @app.get("/api/community/people/{public_id}/reputation")
    def public_list(public_id: str, db=Depends(get_connection)):
        public_person(db, public_id)
        return _private({"entries": public_recommendations(db, public_id)})

    @app.post("/api/community/reputation")
    def create(data: RecommendationInput, user: dict = Depends(community_user), db=Depends(get_connection)):
        owner = user["id"]
        candidate(user, db)
        if not data.publish_consent:
            raise HTTPException(400, "Подтвердите согласие на публикацию своего имени и рекомендации")
        connection = _connection(db, data.connection_id, owner)
        target = int(connection["recipient_id"] if connection["sender_id"] == owner else connection["sender_id"])
        _lock_actors(db, owner, target)
        if not _pair_ready(db, {"connection_id": data.connection_id, "author_id": owner, "recipient_id": target}):
            raise HTTPException(409, "Нужно принятое знакомство между двумя опубликованными профилями участников")
        old = db.execute("SELECT * FROM community_recommendations WHERE author_id=? AND client_key=?",
                         (owner, str(data.client_key))).fetchone()
        if old is not None:
            if (old["connection_id"] != data.connection_id or
                    any(old[key] != getattr(data, key) for key in ("skill", "context", "body"))):
                raise HTTPException(409, "Этот запрос уже использован")
            return _committed(db, {"entry": _dto(_row(db, old["id"]), owner)})
        pair = db.execute("SELECT * FROM community_recommendations WHERE author_id=? AND recipient_id=?",
                          (owner, target)).fetchone()
        if pair is not None and pair["status"] != "rejected":
            raise HTTPException(409, "Рекомендация этому коллеге уже была отправлена")
        throttle(db, owner, "community-recommendation-create", 5, 86400)
        now = _now()
        if pair is None:
            key = _key()
            db.execute(
                """INSERT INTO community_recommendations(id,connection_id,author_id,recipient_id,
                   client_key,skill,context,body,status,author_consent_at,consent_version,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,'offered',?,?,?,?)""",
                (key, data.connection_id, owner, target, str(data.client_key), data.skill,
                 data.context, data.body, now, CONSENT, now, now),
            )
        else:
            key = pair["id"]
            db.execute(
                """UPDATE community_recommendations SET client_key=?,skill=?,context=?,body=?,status='offered',
                   version=version+1,author_consent_at=?,recipient_consent_at=NULL,consent_version=?,
                   reviewed_by=NULL,reviewed_at=NULL,published_at=NULL,moderation_reason='',updated_at=?
                   WHERE id=? AND status='rejected'""",
                (str(data.client_key), data.skill, data.context, data.body, now, CONSENT, now, key),
            )
        return _committed(db, {"entry": _dto(_row(db, key), owner)})

    @app.post("/api/community/reputation/{key}/respond")
    def respond(key: str, data: RecipientDecision, user: dict = Depends(community_user),
                db=Depends(get_connection)):
        candidate(user, db)
        owner = user["id"]
        row = _locked(db, key, owner)
        if owner != row["recipient_id"]:
            raise HTTPException(403, "Решение принимает получатель рекомендации")
        _check_version(row, data.expected_version)
        if row["status"] != "offered" or not row["author_consent_at"]:
            raise HTTPException(409, "Рекомендация больше не ожидает ответа")
        if data.decision == "decline":
            _revoke(db, key=key)
        else:
            if not data.publish_consent:
                raise HTTPException(400, "Подтвердите согласие на публикацию рекомендации в своём профиле")
            if not _pair_ready(db, row):
                raise HTTPException(409, "Знакомство или профиль больше недоступны")
            now = _now()
            db.execute(
                """UPDATE community_recommendations SET status='pending',version=version+1,
                   recipient_consent_at=?,updated_at=? WHERE id=? AND version=?""",
                (now, now, key, data.expected_version),
            )
        return _committed(db, {"entry": _dto(_row(db, key), owner)})

    @app.delete("/api/community/reputation/{key}/publication")
    def withdraw(key: str, data: VersionInput, user: dict = Depends(community_user),
                 db=Depends(get_connection)):
        allowed(user, "candidate")
        owner = user["id"]
        row = _locked(db, key, owner)
        _check_version(row, data.expected_version)
        _revoke(db, key=key)
        return _committed(db, {"entry": _dto(_row(db, key), owner)})

    @app.get("/api/admin/community/reputation")
    def queue(status: Literal["pending", "published"] = "pending",
              page: int = Query(default=1, ge=1, le=10000),
              user: dict = Depends(community_user), db=Depends(get_connection)):
        allowed(user, "admin")
        rows = db.execute(
            PARTICIPANT_QUERY + """
            WHERE r.status=? AND r.author_consent_at IS NOT NULL AND r.recipient_consent_at IS NOT NULL
              AND a.user_id IS NOT NULL AND b.user_id IS NOT NULL AND c.status='accepted'
            ORDER BY r.updated_at,r.id LIMIT ? OFFSET ?""",
            (status, PAGE_SIZE + 1, (page - 1) * PAGE_SIZE),
        ).fetchall()
        return _private({"entries": [_dto(row) for row in rows[:PAGE_SIZE]], "page": page,
                         "has_more": len(rows) > PAGE_SIZE})

    @app.patch("/api/admin/community/reputation/{key}")
    def moderate(key: str, data: ModerationInput, user: dict = Depends(community_user),
                 db=Depends(get_connection)):
        allowed(user, "admin")
        row = _locked(db, key)
        _check_version(row, data.expected_version)
        if (row["status"] not in {"pending", "published"} or not row["author_consent_at"]
                or not row["recipient_consent_at"] or not _pair_ready(db, row)):
            raise HTTPException(409, "Нет действующего согласия обеих сторон или доступного знакомства")
        now = _now()
        if data.decision == "approve":
            if row["status"] != "pending":
                raise HTTPException(409, "Рекомендация уже проверена")
            status, reason, published = "published", "", now
        else:
            if data.decision == "reject" and row["status"] != "pending":
                raise HTTPException(409, "Рекомендация уже проверена")
            if not data.reason.strip():
                raise HTTPException(422, "Укажите причину решения")
            status, reason, published = ("rejected" if data.decision == "reject" else "hidden"), data.reason.strip(), None
        db.execute(
            """UPDATE community_recommendations SET status=?,version=version+1,moderation_reason=?,
               reviewed_by=?,reviewed_at=?,published_at=?,updated_at=?,
               author_consent_at=CASE WHEN ?='published' THEN author_consent_at ELSE NULL END,
               recipient_consent_at=CASE WHEN ?='published' THEN recipient_consent_at ELSE NULL END,
               consent_version=CASE WHEN ?='published' THEN consent_version ELSE NULL END
               WHERE id=? AND version=?""",
            (status, reason, user["id"], now, published, now, status, status, status, key, data.expected_version),
        )
        record_security_event(db, user["id"], "community_recommendation_reviewed",
                              "recommendation=" + key + " decision=" + data.decision)
        return _committed(db, {"entry": _dto(_row(db, key))})
