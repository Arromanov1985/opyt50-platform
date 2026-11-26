"""Opt-in community authored journal articles, independently moderated.

Only the exact submitted text is published. Editors can approve, return or
hide it, but cannot silently rewrite a participant's signed-off text.
"""
from __future__ import annotations

import json
from typing import Literal
from uuid import UUID

from fastapi import Depends, HTTPException, Query
from pydantic import Field, field_validator

from .community import (
    CommunityModel, ModerationInput, PAGE_SIZE, PublishInput, VersionInput,
    _active_account, _check_version, _committed, _is_published, _key, _lock_actors,
    _now, _profile, _public_text,
)
from .community_feed import _private
from .journal_guide import TOPICS
from .journal_cms import parse_sections

CONSENT = "community-author-article-2026-11-26"
LIMIT = 10
KINDS = {"article": "Экспертные статьи", "case": "Профессиональные кейсы", "learning": "Учебные материалы"}
Topic = Literal["career", "management", "sales", "engineering", "technology",
                "finance", "operations", "education", "safety"]
FIELDS = ("id", "kind", "title", "description", "body_text", "status", "version",
          "consent_at", "consent_version", "moderation_reason", "created_at", "updated_at", "published_at")


class AuthorContent(CommunityModel):
    kind: Literal["article", "case", "learning"]
    title: str = Field(min_length=8, max_length=180)
    description: str = Field(min_length=25, max_length=350)
    body_text: str = Field(min_length=200, max_length=12000)
    topics: list[Topic] = Field(default_factory=list, max_length=9)

    _safe = field_validator("title", "description", "body_text")(_public_text)

    @field_validator("topics")
    @classmethod
    def ordered_topics(cls, values):
        return [key for key in TOPICS if key in values]


class AuthorCreate(AuthorContent):
    client_key: UUID


class AuthorEdit(AuthorContent):
    expected_version: int = Field(ge=1)


def _content(data):
    parse_sections(data.body_text)
    return (data.kind, data.title, data.description, data.body_text,
            json.dumps(data.topics, ensure_ascii=False, separators=(",", ":")))


def _owned(db, owner, key):
    row = db.execute("SELECT * FROM community_author_articles WHERE user_id=? AND id=?",
                     (owner, key)).fetchone()
    if row is None:
        raise HTTPException(404, "Материал недоступен")
    return row


def _visible_rows(db):
    # Fixed query with the same identity, consent and privacy gates as
    # community public profiles; the exact author profile version is bound.
    return db.execute(
        """SELECT a.id,a.kind,a.title,a.description,a.body_text,a.topics_json,a.published_at,
                  p.public_id,p.public_name
           FROM community_author_articles a
           JOIN community_profiles p ON p.user_id=a.user_id
           JOIN users u ON u.id=p.user_id
           LEFT JOIN account_controls ac ON ac.user_id=p.user_id
           WHERE a.status='published' AND a.consent_at IS NOT NULL
             AND a.consent_version=? AND a.profile_content_version=p.content_version
             AND p.status='published' AND p.consent_at IS NOT NULL
             AND p.consent_content_version=p.content_version
             AND p.reviewed_content_version=p.content_version
             AND u.role='candidate' AND COALESCE(ac.status,'active')='active'
             AND NOT EXISTS (
                 SELECT 1 FROM privacy_rights_requests pr WHERE pr.user_id=p.user_id
                   AND pr.kind IN ('deletion','stop_processing')
                   AND pr.status IN ('received','in_review','completed'))
           ORDER BY a.published_at,a.id""", (CONSENT,),
    ).fetchall()


def published_author_articles(db):
    items = []
    for row in _visible_rows(db):
        items.append({
            "slug": "author-" + row["id"],
            "title": row["title"], "description": row["description"],
            "category": KINDS[row["kind"]],
            "content_type": "learning" if row["kind"] == "learning" else "article",
            "read": str(max(2, (len(row["body_text"].split()) + 159) // 160)) + " мин.",
            "sections": parse_sections(row["body_text"]),
            "topics": json.loads(row["topics_json"]),
            "published_at": row["published_at"],
            "author_public_id": row["public_id"], "author_public_name": row["public_name"],
        })
    return items


def _dto(row, visible=False):
    result = {key: row[key] for key in FIELDS}
    result["topics"] = json.loads(row["topics_json"])
    result["public_path"] = "/journal/author-" + row["id"] if visible else None
    return result


def _revoke(db, owner, key=""):
    db.execute(
        """UPDATE community_author_articles SET status='hidden',version=version+1,
           consent_at=NULL,consent_version=NULL,profile_content_version=NULL,
           published_at=NULL,updated_at=?
           WHERE user_id=? AND (?='' OR id=?) AND status IN ('pending','published','rejected')""",
        (_now(), owner, key, key),
    )


def revoke_author_articles(db, owner):
    _revoke(db, owner)


def install_author_routes(app, community_user, throttle, get_connection, allowed, record_security_event):
    def candidate(user, db):
        allowed(user, "candidate")
        if not _active_account(db, user["id"]):
            raise HTTPException(403, "Новые материалы недоступны при ограничении обработки данных")

    @app.get("/api/community/author-articles")
    def mine(user: dict = Depends(community_user), db=Depends(get_connection)):
        allowed(user, "candidate")
        owner = user["id"]
        profile = _profile(db, owner)
        published = _is_published(db, owner)
        rows = db.execute("SELECT * FROM community_author_articles WHERE user_id=? ORDER BY updated_at DESC,id DESC",
                          (owner,)).fetchall()
        return _private({
            "entries": [_dto(row, published and row["status"] == "published"
                             and row["consent_version"] == CONSENT and row["consent_at"] is not None
                             and row["profile_content_version"] == profile["content_version"])
                        for row in rows],
            "can_submit": published, "has_profile": profile is not None,
            "restricted": not _active_account(db, owner), "limit": LIMIT,
            "topics": TOPICS,
        })

    @app.post("/api/community/author-articles")
    def create(data: AuthorCreate, user: dict = Depends(community_user), db=Depends(get_connection)):
        owner = user["id"]
        _lock_actors(db, owner)
        candidate(user, db)
        if _profile(db, owner) is None:
            raise HTTPException(409, "Сначала сохраните профессиональный профиль")
        content = _content(data)
        old = db.execute("SELECT * FROM community_author_articles WHERE user_id=? AND client_key=?",
                         (owner, str(data.client_key))).fetchone()
        if old is not None:
            if tuple(old[key] for key in ("kind","title","description","body_text","topics_json")) != content:
                raise HTTPException(409, "Запрос уже сохранён с другим содержанием")
            return _committed(db, {"entry": _dto(old)})
        count = db.execute("SELECT COUNT(*) FROM community_author_articles WHERE user_id=?", (owner,)).fetchone()[0]
        if count >= LIMIT:
            raise HTTPException(409, "Достигнут лимит материалов. Измените существующую запись")
        throttle(db, owner, "community-author-create", 10, 86400)
        key, now = _key(), _now()
        db.execute(
            """INSERT INTO community_author_articles
               (id,user_id,client_key,kind,title,description,body_text,topics_json,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (key, owner, str(data.client_key), *content, now, now),
        )
        return _committed(db, {"entry": _dto(_owned(db, owner, key))})

    @app.put("/api/community/author-articles/{key}")
    def edit(key: str, data: AuthorEdit, user: dict = Depends(community_user), db=Depends(get_connection)):
        owner = user["id"]
        _lock_actors(db, owner)
        candidate(user, db)
        row = _owned(db, owner, key)
        _check_version(row, data.expected_version)
        content = _content(data)
        if tuple(row[field] for field in ("kind","title","description","body_text","topics_json")) == content:
            return _committed(db, {"entry": _dto(row)})
        throttle(db, owner, "community-author-edit", 30, 3600)
        db.execute(
            """UPDATE community_author_articles SET kind=?,title=?,description=?,body_text=?,topics_json=?,
               status='draft',version=version+1,consent_at=NULL,consent_version=NULL,profile_content_version=NULL,
               reviewed_by=NULL,reviewed_at=NULL,published_at=NULL,moderation_reason='',updated_at=?
               WHERE id=? AND user_id=? AND version=?""",
            (*content, _now(), key, owner, data.expected_version),
        )
        return _committed(db, {"entry": _dto(_owned(db, owner, key))})

    @app.post("/api/community/author-articles/{key}/submit")
    def submit(key: str, data: PublishInput, user: dict = Depends(community_user), db=Depends(get_connection)):
        owner = user["id"]
        _lock_actors(db, owner)
        candidate(user, db)
        row = _owned(db, owner, key)
        _check_version(row, data.expected_version)
        if not data.publish_consent:
            raise HTTPException(400, "Подтвердите публикацию текста и публичного имени")
        if not _is_published(db, owner):
            raise HTTPException(409, "Для отправки материала нужен опубликованный профиль")
        if row["status"] not in ("draft","hidden","rejected"):
            raise HTTPException(409, "Материал уже опубликован или ожидает проверки")
        throttle(db, owner, "community-author-submit", 5, 86400)
        now = _now()
        db.execute(
            """UPDATE community_author_articles SET status='pending',version=version+1,
               consent_at=?,consent_version=?,profile_content_version=?,moderation_reason='',
               reviewed_by=NULL,reviewed_at=NULL,published_at=NULL,updated_at=?
               WHERE id=? AND user_id=? AND version=?""",
            (now, CONSENT, _profile(db, owner)["content_version"], now, key, owner, data.expected_version),
        )
        return _committed(db, {"entry": _dto(_owned(db, owner, key))})

    @app.delete("/api/community/author-articles/{key}/publication")
    def withdraw(key: str, data: VersionInput, user: dict = Depends(community_user), db=Depends(get_connection)):
        allowed(user, "candidate")
        owner = user["id"]
        _lock_actors(db, owner)
        row = _owned(db, owner, key)
        _check_version(row, data.expected_version)
        _revoke(db, owner, key)
        return _committed(db, {"entry": _dto(_owned(db, owner, key))})

    @app.get("/api/admin/community/author-articles")
    def queue(status: Literal["pending","published"] = "pending",
              page: int = Query(default=1, ge=1, le=10000),
              user: dict = Depends(community_user), db=Depends(get_connection)):
        allowed(user, "admin")
        rows = db.execute(
            """SELECT a.*,p.public_id,p.public_name FROM community_author_articles a
               JOIN community_profiles p ON p.user_id=a.user_id JOIN users u ON u.id=p.user_id
               LEFT JOIN account_controls ac ON ac.user_id=p.user_id
               WHERE a.status=? AND a.consent_at IS NOT NULL AND a.consent_version=?
                 AND a.profile_content_version=p.content_version AND p.status='published'
                 AND p.consent_at IS NOT NULL AND p.consent_content_version=p.content_version
                 AND p.reviewed_content_version=p.content_version
                 AND u.role='candidate' AND COALESCE(ac.status,'active')='active'
                 AND NOT EXISTS (SELECT 1 FROM privacy_rights_requests pr WHERE pr.user_id=p.user_id
                   AND pr.kind IN ('deletion','stop_processing') AND pr.status IN ('received','in_review','completed'))
               ORDER BY a.updated_at,a.id LIMIT ? OFFSET ?""",
            (status, CONSENT, PAGE_SIZE + 1, (page - 1) * PAGE_SIZE),
        ).fetchall()
        return _private({"entries": [{**_dto(row, row["status"] == "published"),
                                       "author_public_id": row["public_id"], "author_public_name": row["public_name"]}
                                      for row in rows[:PAGE_SIZE]],
                         "page": page, "has_more": len(rows) > PAGE_SIZE})

    @app.patch("/api/admin/community/author-articles/{key}")
    def moderate(key: str, data: ModerationInput, user: dict = Depends(community_user), db=Depends(get_connection)):
        allowed(user, "admin")
        found = db.execute("SELECT user_id FROM community_author_articles WHERE id=?", (key,)).fetchone()
        if found is None:
            raise HTTPException(404, "Материал недоступен")
        owner = int(found["user_id"])
        _lock_actors(db, owner)
        row = _owned(db, owner, key)
        _check_version(row, data.expected_version)
        if row["status"] not in ("pending","published") or not row["consent_at"] or row["consent_version"] != CONSENT:
            raise HTTPException(409, "Нет действующего согласия на публикацию")
        now = _now()
        if data.decision == "approve":
            if (row["status"] != "pending" or not _is_published(db, owner)
                    or row["profile_content_version"] != _profile(db, owner)["content_version"]):
                raise HTTPException(409, "Материал или профиль больше не доступны для публикации")
            status, reason, published = "published", "", now
        else:
            if data.decision == "reject" and row["status"] != "pending":
                raise HTTPException(409, "Материал уже проверен")
            if not data.reason.strip():
                raise HTTPException(422, "Укажите причину решения")
            status, reason, published = ("rejected" if data.decision == "reject" else "hidden"), data.reason.strip(), None
        db.execute(
            """UPDATE community_author_articles SET status=?,version=version+1,moderation_reason=?,
               reviewed_by=?,reviewed_at=?,published_at=?,updated_at=?,
               consent_at=CASE WHEN ?='published' THEN consent_at ELSE NULL END,
               consent_version=CASE WHEN ?='published' THEN consent_version ELSE NULL END,
               profile_content_version=CASE WHEN ?='published' THEN profile_content_version ELSE NULL END
               WHERE id=? AND version=?""",
            (status, reason, user["id"], now, published, now, status, status, status, key, data.expected_version),
        )
        record_security_event(db, user["id"], "community_author_reviewed", "article=" + key + " decision=" + data.decision)
        return _committed(db, {"entry": _dto(_owned(db, owner, key), status == "published")})
