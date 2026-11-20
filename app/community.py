"""Opt-in professional profiles and consent-based, private conversations.

Community identity is authored separately from the hiring profile. Public
serializers never read the account's name, phone, email, or resume. Publishing
requires both consent for the current content and a moderator's approval.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator


CONSENT_VERSION = "professional-profile-2026-11-19"
PAGE_SIZE = 20
Goal = Literal["work", "projects", "mentoring", "exchange"]
ProfileStatus = Literal["draft", "pending", "published", "rejected", "hidden"]
ConnectionStatus = Literal["pending", "accepted", "declined", "cancelled", "blocked"]

# TEXT keys and explicit timestamps work in both runtime database adapters.
COMMUNITY_DDL = (
    """CREATE TABLE IF NOT EXISTS community_actor_locks (
        user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        lock_value INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS community_profiles (
        user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        public_id TEXT NOT NULL UNIQUE,
        public_name TEXT NOT NULL DEFAULT '',
        headline TEXT NOT NULL DEFAULT '',
        city TEXT NOT NULL DEFAULT '',
        skills TEXT NOT NULL DEFAULT '',
        about TEXT NOT NULL DEFAULT '',
        goal TEXT NOT NULL DEFAULT 'exchange'
          CHECK(goal IN ('work','projects','mentoring','exchange')),
        status TEXT NOT NULL DEFAULT 'draft'
          CHECK(status IN ('draft','pending','published','rejected','hidden')),
        version INTEGER NOT NULL DEFAULT 1 CHECK(version>=1),
        content_version INTEGER NOT NULL DEFAULT 1 CHECK(content_version>=1),
        consent_at TEXT,
        consent_version TEXT,
        consent_content_version INTEGER,
        reviewed_content_version INTEGER,
        moderation_reason TEXT NOT NULL DEFAULT '',
        reviewed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        reviewed_at TEXT,
        published_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS community_profile_events (
        id TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        event TEXT NOT NULL,
        profile_version INTEGER NOT NULL,
        content_version INTEGER NOT NULL,
        consent_version TEXT,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS community_connections (
        id TEXT PRIMARY KEY,
        sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        recipient_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        pair_low INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        pair_high INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        purpose TEXT NOT NULL CHECK(purpose IN ('work','projects','mentoring','exchange')),
        note TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending'
          CHECK(status IN ('pending','accepted','declined','cancelled','blocked')),
        blocked_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(pair_low,pair_high),
        CHECK(pair_low<pair_high),
        CHECK(sender_id<>recipient_id)
    )""",
    """CREATE TABLE IF NOT EXISTS community_messages (
        id TEXT PRIMARY KEY,
        connection_id TEXT NOT NULL REFERENCES community_connections(id) ON DELETE CASCADE,
        sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        client_key TEXT NOT NULL,
        body TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(connection_id,sender_id,client_key)
    )""",
    """CREATE TABLE IF NOT EXISTS community_reports (
        id TEXT PRIMARY KEY,
        reporter_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        public_id TEXT REFERENCES community_profiles(public_id) ON DELETE CASCADE,
        connection_id TEXT REFERENCES community_connections(id) ON DELETE CASCADE,
        target_key TEXT NOT NULL,
        reason TEXT NOT NULL CHECK(reason IN ('spam','fraud','harassment','personal_data','other')),
        details TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new','resolved','dismissed')),
        reviewed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        reviewed_at TEXT,
        created_at TEXT NOT NULL,
        UNIQUE(reporter_id,target_key),
        CHECK((public_id IS NULL AND connection_id IS NOT NULL) OR
              (public_id IS NOT NULL AND connection_id IS NULL))
    )""",
    "CREATE INDEX IF NOT EXISTS idx_community_profiles_public ON community_profiles(status,published_at,public_id)",
    "CREATE INDEX IF NOT EXISTS idx_community_profile_events_owner ON community_profile_events(user_id,created_at)",
    "CREATE INDEX IF NOT EXISTS idx_community_connections_sender ON community_connections(sender_id,updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_community_connections_recipient ON community_connections(recipient_id,updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_community_messages_thread ON community_messages(connection_id,created_at,id)",
    "CREATE INDEX IF NOT EXISTS idx_community_reports_status ON community_reports(status,created_at)",
)

PUBLIC_FIELDS = ("public_id", "public_name", "headline", "city", "skills", "about", "goal")
CONTENT_FIELDS = ("public_name", "headline", "city", "skills", "about", "goal")
PUBLIC_VISIBILITY = """p.status='published' AND p.consent_at IS NOT NULL
    AND p.consent_content_version=p.content_version
    AND p.reviewed_content_version=p.content_version
    AND u.role='candidate' AND COALESCE(ac.status,'active')='active'
    AND NOT EXISTS (
        SELECT 1 FROM privacy_rights_requests pr
        WHERE pr.user_id=p.user_id
          AND pr.kind IN ('deletion','stop_processing')
          AND pr.status IN ('received','in_review','completed')
    )"""
PUBLIC_JOIN = """FROM community_profiles p JOIN users u ON u.id=p.user_id
    LEFT JOIN account_controls ac ON ac.user_id=p.user_id"""
CONTACT_PATTERN = re.compile(
    r"(?:[\w.+-]+\s*@\s*[\w.-]+|@[\w.-]{2,}|https?\s*:|www\.|"
    r"[a-z][a-z0-9+.-]{1,20}://|(?:mailto|tel|sms|tg|viber|whatsapp):|"
    r"\b[\w-]+\.(?:ru|рф|com|org|net|io|me|su)\b)", re.IGNORECASE,
)
PHONE_CANDIDATE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _key() -> str:
    return uuid4().hex


def _public_text(value: str) -> str:
    value = value.strip()
    # A year range or date is legitimate professional content, not a phone.
    # This is an accidental-contact guard; moderation and explicit author
    # review remain necessary for unusual/obfuscated personal information.
    has_phone = any(sum(char.isdigit() for char in match.group()) >= 10
                    for match in PHONE_CANDIDATE.finditer(value))
    if CONTACT_PATTERN.search(value) or has_phone:
        raise ValueError("Уберите телефон, email, ссылки и адреса мессенджеров из публичного текста")
    if any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise ValueError("Текст содержит недопустимые символы")
    return value


class CommunityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProfileInput(CommunityModel):
    expected_version: int = Field(ge=0)
    public_name: str = Field(default="", max_length=60)
    headline: str = Field(default="", max_length=120)
    city: str = Field(default="", max_length=80)
    skills: str = Field(default="", max_length=400)
    about: str = Field(default="", max_length=2000)
    goal: Goal = "exchange"

    _safe = field_validator("public_name", "headline", "city", "skills", "about")(_public_text)


class VersionInput(CommunityModel):
    expected_version: int = Field(ge=0)


class PublishInput(VersionInput):
    publish_consent: StrictBool = False


class ModerationInput(VersionInput):
    decision: Literal["approve", "reject", "hide"]
    reason: str = Field(default="", max_length=500)


class ConnectionInput(CommunityModel):
    public_id: str = Field(min_length=1, max_length=64)
    purpose: Goal
    note: str = Field(default="", max_length=500)

    _safe = field_validator("note")(_public_text)


class ConnectionResponseInput(CommunityModel):
    decision: Literal["accept", "decline"]


class MessageInput(CommunityModel):
    body: str = Field(min_length=1, max_length=2000)
    client_key: UUID


class ReportInput(CommunityModel):
    public_id: str | None = Field(default=None, min_length=1, max_length=64)
    connection_id: str | None = Field(default=None, min_length=1, max_length=64)
    reason: Literal["spam", "fraud", "harassment", "personal_data", "other"]
    details: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def one_target(self):
        if (self.public_id is None) == (self.connection_id is None):
            raise ValueError("Выберите один профиль или одну переписку")
        return self


class ReportReviewInput(CommunityModel):
    status: Literal["resolved", "dismissed"]


def _profile(db, user_id: int):
    return db.execute("SELECT * FROM community_profiles WHERE user_id=?", (user_id,)).fetchone()


def _own_profile(row) -> dict:
    if row is None:
        return dict(public_id=None, public_name="", headline="", city="", skills="", about="",
                    goal="exchange", version=0, status="draft", consent_at=None,
                    consent_version=None, moderation_reason="", published_at=None)
    fields = PUBLIC_FIELDS + ("version", "status", "consent_at", "consent_version",
                             "moderation_reason", "published_at")
    return {field: row[field] for field in fields}


def _public_profile(row) -> dict:
    return {field: row[field] for field in PUBLIC_FIELDS}


def public_person(db, public_id: str) -> dict:
    """Single source for public JSON and HTML visibility and field allowlisting."""
    row = db.execute(
        "SELECT p.* " + PUBLIC_JOIN + " WHERE p.public_id=? AND " + PUBLIC_VISIBILITY,
        (public_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Профиль недоступен")
    return _public_profile(row)


def _is_published(db, user_id: int) -> bool:
    return db.execute(
        "SELECT p.user_id " + PUBLIC_JOIN + " WHERE p.user_id=? AND " + PUBLIC_VISIBILITY,
        (user_id,),
    ).fetchone() is not None


def _lock_actors(db, *user_ids: int) -> None:
    """Serialize module mutations, including send/block and submit/withdraw.

    The small additive lock table provides the same ordering on PostgreSQL
    (row locks) and SQLite (write transaction). Always acquire in numeric order.
    No account/hiring profile fields are written by this module.
    """
    for user_id in sorted(set(user_ids)):
        db.execute(
            "INSERT INTO community_actor_locks(user_id) VALUES(?) ON CONFLICT(user_id) DO NOTHING",
            (user_id,),
        )
        db.execute("UPDATE community_actor_locks SET lock_value=lock_value WHERE user_id=?", (user_id,))


def _check_version(row, expected: int) -> None:
    actual = int(row["version"]) if row is not None else 0
    if actual != expected:
        raise HTTPException(409, "Профиль изменился в другой вкладке. Обновите страницу перед сохранением")


def _profile_event(db, row, actor_id: int, event: str) -> None:
    db.execute(
        """INSERT INTO community_profile_events(
           id,user_id,actor_id,event,profile_version,content_version,consent_version,created_at
           ) VALUES(?,?,?,?,?,?,?,?)""",
        (_key(), row["user_id"], actor_id, event, row["version"], row["content_version"],
         row["consent_version"], _now()),
    )


def _active_account(db, user_id: int) -> bool:
    return db.execute(
        """SELECT u.id FROM users u LEFT JOIN account_controls ac ON ac.user_id=u.id
           WHERE u.id=? AND COALESCE(ac.status,'active')='active'
             AND NOT EXISTS (
               SELECT 1 FROM privacy_rights_requests pr
               WHERE pr.user_id=u.id AND pr.kind IN ('deletion','stop_processing')
                 AND pr.status IN ('received','in_review','completed')
             )""", (user_id,),
    ).fetchone() is not None


def _connection(db, connection_id: str, user_id: int):
    row = db.execute(
        """SELECT * FROM community_connections
           WHERE id=? AND (sender_id=? OR recipient_id=?)""",
        (connection_id, user_id, user_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Знакомство недоступно")
    return row


def _locked_connection(db, connection_id: str, user_id: int):
    row = _connection(db, connection_id, user_id)
    _lock_actors(db, int(row["sender_id"]), int(row["recipient_id"]))
    return _connection(db, connection_id, user_id)


def _counterpart(db, user_id: int) -> dict:
    row = db.execute(
        """SELECT u.role,e.company_name FROM users u
           LEFT JOIN employer_profiles e ON e.user_id=u.id WHERE u.id=?""", (user_id,),
    ).fetchone()
    role = row["role"] if row is not None else "candidate"
    result = {"public_name": "Участник СТАЖНО", "headline": "", "public_id": None, "role": role}
    if not _active_account(db, user_id):
        result["public_name"] = "Участник недоступен"
    elif role == "employer":
        result["public_name"] = str(row["company_name"] or "Компания на СТАЖНО")
    elif _is_published(db, user_id):
        profile = _profile(db, user_id)
        result.update({field: profile[field] for field in ("public_name", "headline", "public_id")})
    return result


def _connection_dto(db, row, user_id: int) -> dict:
    incoming = int(row["recipient_id"]) == user_id
    counterpart_id = int(row["sender_id"] if incoming else row["recipient_id"])
    active = _active_account(db, counterpart_id)
    result = {field: row[field] for field in ("id", "status", "purpose", "note", "created_at", "updated_at")}
    result.update(
        direction="incoming" if incoming else "outgoing",
        counterpart=_counterpart(db, counterpart_id),
        can_respond=bool(incoming and row["status"] == "pending" and active),
        can_cancel=bool(not incoming and row["status"] == "pending"),
        can_block=row["status"] != "blocked",
        can_message=bool(row["status"] == "accepted" and active),
    )
    return result


def _message_dto(row, user_id: int) -> dict:
    return {"id": row["id"], "body": row["body"], "mine": int(row["sender_id"]) == user_id,
            "created_at": row["created_at"]}


def _report_dto(row) -> dict:
    return {field: row[field] for field in (
        "id", "public_id", "connection_id", "reason", "details", "status", "created_at",
    )}


def _page_info(page: int, total: int) -> dict:
    return {"page": page, "page_size": PAGE_SIZE, "total": total, "has_more": page * PAGE_SIZE < total}


def _committed(db, payload: dict) -> dict:
    """Confirm durability before FastAPI can send a successful mutation response.

    Callers build the DTO (including its reads) while holding actor locks. The
    yield dependency also performs cleanup, but request-scope cleanup can run
    after the HTTP response; it cannot be the first commit of a successful save.
    """
    db.commit()
    return payload


def install_community_routes(app) -> None:
    # Deferred import preserves the application's existing initialization order.
    from .main import active_user, allowed, consume_security_rate_limit, get_connection
    from .release02 import record_security_event

    def community_user(request: Request, user: dict = Depends(active_user)) -> dict:
        # Identity still comes exclusively from the authenticated session. The
        # optional header is a stale-tab guard: a cookie changed in another tab
        # must not move a private draft or message into a different account.
        expected_actor = request.headers.get("X-Community-Actor")
        if expected_actor is not None and expected_actor != str(user["id"]):
            raise HTTPException(
                409,
                "Аккаунт изменился в другой вкладке. Обновите страницу перед продолжением. "
                "Введённый текст пока остаётся здесь.",
            )
        return user

    def throttle(db, user_id: int, scope: str, limit: int, window: int) -> None:
        permitted, retry_after = consume_security_rate_limit(db, scope, str(user_id), limit, window)
        if not permitted:
            # Preserve the counter but never commit a business mutation here.
            db.commit()
            raise HTTPException(429, "Слишком много действий. Попробуйте позже",
                                headers={"Retry-After": str(retry_after)})

    @app.get("/api/community/profile")
    def own_profile(user: dict = Depends(community_user), db=Depends(get_connection)):
        allowed(user, "candidate")
        return {"profile": _own_profile(_profile(db, user["id"]))}

    @app.put("/api/community/profile")
    def save_profile(data: ProfileInput, user: dict = Depends(community_user), db=Depends(get_connection)):
        allowed(user, "candidate")
        _lock_actors(db, user["id"])
        current = _profile(db, user["id"])
        _check_version(current, data.expected_version)
        fields = data.model_dump(include=set(CONTENT_FIELDS))
        if current is not None and all(current[field] == fields[field] for field in CONTENT_FIELDS):
            return _committed(db, {"profile": _own_profile(current)})
        throttle(db, user["id"], "community-profile-save", 60, 3600)
        now = _now()
        if current is None:
            db.execute(
                """INSERT INTO community_profiles(user_id,public_id,public_name,headline,city,
                   skills,about,goal,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (user["id"], _key(), *(fields[field] for field in CONTENT_FIELDS), now, now),
            )
        else:
            db.execute(
                """UPDATE community_profiles SET public_name=?,headline=?,city=?,skills=?,about=?,goal=?,
                   version=version+1,content_version=content_version+1,status='draft',
                   consent_at=NULL,consent_version=NULL,consent_content_version=NULL,
                   reviewed_content_version=NULL,reviewed_by=NULL,reviewed_at=NULL,
                   published_at=NULL,moderation_reason='',updated_at=? WHERE user_id=? AND version=?""",
                (*(fields[field] for field in CONTENT_FIELDS), now, user["id"], data.expected_version),
            )
        updated = _profile(db, user["id"])
        _profile_event(db, updated, user["id"], "saved")
        return _committed(db, {"profile": _own_profile(updated)})

    @app.post("/api/community/profile/submit")
    def submit_profile(data: PublishInput, user: dict = Depends(community_user), db=Depends(get_connection)):
        allowed(user, "candidate")
        if not data.publish_consent:
            raise HTTPException(400, "Подтвердите отдельное согласие на публичное размещение выбранных сведений")
        _lock_actors(db, user["id"])
        row = _profile(db, user["id"])
        _check_version(row, data.expected_version)
        if row is None:
            raise HTTPException(400, "Сначала сохраните профессиональный профиль")
        if len(row["public_name"]) < 2 or len(row["headline"]) < 3 or len(row["about"]) < 20:
            raise HTTPException(422, "Укажите публичное имя, профессию и описание опыта от 20 символов")
        if row["status"] in {"pending", "published"}:
            return _committed(db, {"profile": _own_profile(row)})
        throttle(db, user["id"], "community-profile-submit", 10, 3600)
        now = _now()
        db.execute(
            """UPDATE community_profiles SET status='pending',version=version+1,
               consent_at=?,consent_version=?,consent_content_version=content_version,
               reviewed_content_version=NULL,reviewed_by=NULL,reviewed_at=NULL,
               published_at=NULL,moderation_reason='',updated_at=? WHERE user_id=? AND version=?""",
            (now, CONSENT_VERSION, now, user["id"], data.expected_version),
        )
        updated = _profile(db, user["id"])
        _profile_event(db, updated, user["id"], "submitted_with_consent")
        return _committed(db, {"profile": _own_profile(updated)})

    @app.delete("/api/community/profile/publication")
    def withdraw_profile(data: VersionInput, user: dict = Depends(community_user), db=Depends(get_connection)):
        allowed(user, "candidate")
        _lock_actors(db, user["id"])
        row = _profile(db, user["id"])
        _check_version(row, data.expected_version)
        if row is None:
            return _committed(db, {"profile": _own_profile(None)})
        db.execute(
            """UPDATE community_profiles SET status='hidden',version=version+1,consent_at=NULL,
               consent_version=NULL,consent_content_version=NULL,reviewed_content_version=NULL,
               published_at=NULL,updated_at=? WHERE user_id=? AND version=?""",
            (_now(), user["id"], data.expected_version),
        )
        updated = _profile(db, user["id"])
        _profile_event(db, updated, user["id"], "consent_withdrawn")
        return _committed(db, {"profile": _own_profile(updated)})

    @app.get("/api/community/people")
    def people(q: str = Query(default="", max_length=100), city: str = Query(default="", max_length=80),
               goal: Goal | None = None, page: int = Query(default=1, ge=1, le=10000),
               db=Depends(get_connection)):
        where = " WHERE " + PUBLIC_VISIBILITY
        args = []
        if q.strip():
            where += """ AND (instr(unicode_fold(p.public_name),?)>0
                OR instr(unicode_fold(p.headline),?)>0 OR instr(unicode_fold(p.skills),?)>0)"""
            args.extend([q.strip().casefold()] * 3)
        if city.strip():
            where += " AND unicode_fold(p.city)=?"
            args.append(city.strip().casefold())
        if goal:
            where += " AND p.goal=?"
            args.append(goal)
        total = db.execute("SELECT COUNT(*) " + PUBLIC_JOIN + where, args).fetchone()[0]
        rows = db.execute(
            "SELECT p.* " + PUBLIC_JOIN + where + " ORDER BY p.published_at DESC,p.public_id LIMIT ? OFFSET ?",
            (*args, PAGE_SIZE, (page - 1) * PAGE_SIZE),
        ).fetchall()
        return JSONResponse(
            {"people": [_public_profile(row) for row in rows], **_page_info(page, total)},
            headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"},
        )

    @app.get("/api/community/people/{public_id}")
    def person(public_id: str, db=Depends(get_connection)):
        return JSONResponse(
            {"person": public_person(db, public_id)},
            headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"},
        )

    @app.get("/api/admin/community/profiles")
    def moderation_profiles(status: Literal["pending", "published", "rejected", "hidden"] = "pending",
                            page: int = Query(default=1, ge=1, le=10000),
                            user: dict = Depends(community_user), db=Depends(get_connection)):
        allowed(user, "admin")
        # A moderator sees only a content revision its author actually submitted,
        # including after withdrawal. Saving a new draft never exposes that draft.
        total = db.execute(
            """SELECT COUNT(*) FROM community_profiles p WHERE p.status=? AND EXISTS (
                 SELECT 1 FROM community_profile_events e WHERE e.user_id=p.user_id
                 AND e.content_version=p.content_version AND e.event='submitted_with_consent')""", (status,),
        ).fetchone()[0]
        rows = db.execute(
            """SELECT p.* FROM community_profiles p WHERE p.status=? AND EXISTS (
                 SELECT 1 FROM community_profile_events e WHERE e.user_id=p.user_id
                 AND e.content_version=p.content_version AND e.event='submitted_with_consent')
               ORDER BY p.updated_at,p.public_id LIMIT ? OFFSET ?""",
            (status, PAGE_SIZE, (page - 1) * PAGE_SIZE),
        ).fetchall()
        return {"profiles": [_own_profile(row) for row in rows], **_page_info(page, total)}

    @app.patch("/api/admin/community/profiles/{public_id}")
    def moderate_profile(public_id: str, data: ModerationInput,
                         user: dict = Depends(community_user), db=Depends(get_connection)):
        allowed(user, "admin")
        owner = db.execute("SELECT user_id FROM community_profiles WHERE public_id=?", (public_id,)).fetchone()
        if owner is None:
            raise HTTPException(404, "Профиль недоступен")
        _lock_actors(db, int(owner["user_id"]))
        row = _profile(db, int(owner["user_id"]))
        _check_version(row, data.expected_version)
        if row["status"] not in {"pending", "published"}:
            raise HTTPException(409, "Эта редакция не опубликована и не ожидает проверки")
        if data.decision == "approve":
            if (row["status"] != "pending" or not row["consent_at"]
                    or row["consent_content_version"] != row["content_version"]
                    or not _active_account(db, int(owner["user_id"]))):
                raise HTTPException(409, "Нельзя опубликовать профиль без актуального согласия и активной заявки")
            now = _now()
            db.execute(
                """UPDATE community_profiles SET status='published',version=version+1,
                   reviewed_content_version=content_version,reviewed_by=?,reviewed_at=?,
                   published_at=?,moderation_reason='',updated_at=? WHERE user_id=? AND version=?""",
                (user["id"], now, now, now, owner["user_id"], data.expected_version),
            )
        else:
            if not data.reason.strip():
                raise HTTPException(422, "Укажите причину решения для автора профиля")
            if data.decision == "reject" and row["status"] != "pending":
                raise HTTPException(409, "Эта редакция профиля уже не ожидает проверки")
            now = _now()
            db.execute(
                """UPDATE community_profiles SET status=?,version=version+1,
                   consent_at=NULL,consent_version=NULL,consent_content_version=NULL,
                   reviewed_content_version=NULL,reviewed_by=?,reviewed_at=?,published_at=NULL,
                   moderation_reason=?,updated_at=? WHERE user_id=? AND version=?""",
                ("rejected" if data.decision == "reject" else "hidden", user["id"], now,
                 data.reason.strip(), now, owner["user_id"], data.expected_version),
            )
        updated = _profile(db, int(owner["user_id"]))
        _profile_event(db, updated, user["id"], "moderator_" + data.decision)
        record_security_event(db, user["id"], "community_profile_moderated",
                              "decision=" + data.decision + " profile=" + public_id)
        return _committed(db, {"profile": _own_profile(updated)})

    @app.post("/api/community/connections")
    def create_connection(data: ConnectionInput, user: dict = Depends(community_user), db=Depends(get_connection)):
        if user["role"] not in {"candidate", "employer"}:
            raise HTTPException(403, "Знакомства доступны участникам и работодателям")
        recipient = db.execute("SELECT user_id FROM community_profiles WHERE public_id=?", (data.public_id,)).fetchone()
        if recipient is None:
            raise HTTPException(404, "Профиль недоступен")
        recipient_id = int(recipient["user_id"])
        if recipient_id == user["id"]:
            raise HTTPException(400, "Нельзя отправить запрос самому себе")
        _lock_actors(db, user["id"], recipient_id)
        public_person(db, data.public_id)
        low, high = sorted((user["id"], recipient_id))
        existing = db.execute(
            "SELECT * FROM community_connections WHERE pair_low=? AND pair_high=?", (low, high),
        ).fetchone()
        if existing is not None:
            if existing["status"] in {"pending", "accepted"}:
                return _committed(db, {"connection": _connection_dto(db, existing, user["id"])})
            raise HTTPException(409, "Знакомство с этим участником уже завершено. Повторный запрос недоступен")
        if user["role"] == "candidate" and not _is_published(db, user["id"]):
            raise HTTPException(403, "Сначала опубликуйте свой профессиональный профиль после проверки")
        if user["role"] == "employer" and db.execute(
            "SELECT user_id FROM employer_profiles WHERE user_id=?", (user["id"],),
        ).fetchone() is None:
            raise HTTPException(403, "Сначала заполните профиль компании")
        throttle(db, user["id"], "community-connections", 10, 86400)
        connection_id, now = _key(), _now()
        db.execute(
            """INSERT INTO community_connections(id,sender_id,recipient_id,pair_low,pair_high,
               purpose,note,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,'pending',?,?)""",
            (connection_id, user["id"], recipient_id, low, high, data.purpose, data.note, now, now),
        )
        return _committed(db, {"connection": _connection_dto(db, _connection(db, connection_id, user["id"]), user["id"])})

    @app.get("/api/community/connections")
    def connections(status: ConnectionStatus | None = None, page: int = Query(default=1, ge=1, le=10000),
                    user: dict = Depends(community_user), db=Depends(get_connection)):
        args = (user["id"], user["id"], status or "", status or "")
        total = db.execute(
            """SELECT COUNT(*) FROM community_connections
               WHERE (sender_id=? OR recipient_id=?) AND (?='' OR status=?)""", args,
        ).fetchone()[0]
        rows = db.execute(
            """SELECT * FROM community_connections
               WHERE (sender_id=? OR recipient_id=?) AND (?='' OR status=?)
               ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?""",
            (*args, PAGE_SIZE, (page - 1) * PAGE_SIZE),
        ).fetchall()
        return {"connections": [_connection_dto(db, row, user["id"]) for row in rows], **_page_info(page, total)}

    @app.get("/api/community/connections/{connection_id}")
    def get_connection_details(connection_id: str, user: dict = Depends(community_user), db=Depends(get_connection)):
        return {"connection": _connection_dto(db, _connection(db, connection_id, user["id"]), user["id"])}

    @app.post("/api/community/connections/{connection_id}/respond")
    def respond_connection(connection_id: str, data: ConnectionResponseInput,
                           user: dict = Depends(community_user), db=Depends(get_connection)):
        row = _locked_connection(db, connection_id, user["id"])
        if row["recipient_id"] != user["id"]:
            raise HTTPException(403, "Ответить может только получатель запроса")
        target = "accepted" if data.decision == "accept" else "declined"
        if row["status"] == target:
            return _committed(db, {"connection": _connection_dto(db, row, user["id"])})
        if row["status"] != "pending":
            raise HTTPException(409, "Запрос уже изменился. Обновите список знакомств")
        if data.decision == "accept" and not _active_account(db, int(row["sender_id"])):
            raise HTTPException(409, "Участник сейчас недоступен")
        db.execute("UPDATE community_connections SET status=?,updated_at=? WHERE id=? AND status='pending'",
                   (target, _now(), connection_id))
        return _committed(db, {"connection": _connection_dto(db, _connection(db, connection_id, user["id"]), user["id"])})

    @app.post("/api/community/connections/{connection_id}/cancel")
    def cancel_connection(connection_id: str, user: dict = Depends(community_user), db=Depends(get_connection)):
        row = _locked_connection(db, connection_id, user["id"])
        if row["sender_id"] != user["id"]:
            raise HTTPException(403, "Отменить запрос может только отправитель")
        if row["status"] == "cancelled":
            return _committed(db, {"connection": _connection_dto(db, row, user["id"])})
        if row["status"] != "pending":
            raise HTTPException(409, "Можно отменить только ожидающий ответа запрос")
        db.execute("UPDATE community_connections SET status='cancelled',updated_at=? WHERE id=? AND status='pending'",
                   (_now(), connection_id))
        return _committed(db, {"connection": _connection_dto(db, _connection(db, connection_id, user["id"]), user["id"])})

    @app.post("/api/community/connections/{connection_id}/block")
    def block_connection(connection_id: str, user: dict = Depends(community_user), db=Depends(get_connection)):
        row = _locked_connection(db, connection_id, user["id"])
        if row["status"] != "blocked":
            db.execute("UPDATE community_connections SET status='blocked',blocked_by=?,updated_at=? WHERE id=?",
                       (user["id"], _now(), connection_id))
        return _committed(db, {"connection": _connection_dto(db, _connection(db, connection_id, user["id"]), user["id"])})

    def readable_thread(db, connection_id: str, user_id: int):
        row = _connection(db, connection_id, user_id)
        if row["status"] not in {"accepted", "blocked"}:
            raise HTTPException(403, "Переписка открывается после принятия запроса")
        return row

    @app.get("/api/community/connections/{connection_id}/messages")
    def messages(connection_id: str, before: str | None = Query(default=None, max_length=64),
                 user: dict = Depends(community_user), db=Depends(get_connection)):
        readable_thread(db, connection_id, user["id"])
        before_time, before_id = "", ""
        if before:
            cursor = db.execute("SELECT created_at,id FROM community_messages WHERE connection_id=? AND id=?",
                                (connection_id, before)).fetchone()
            if cursor is None:
                raise HTTPException(400, "Недопустимый указатель истории переписки")
            before_time, before_id = cursor["created_at"], cursor["id"]
        rows = db.execute(
            """SELECT * FROM community_messages WHERE connection_id=?
               AND (?='' OR created_at<? OR (created_at=? AND id<?))
               ORDER BY created_at DESC,id DESC LIMIT 51""",
            (connection_id, before_time, before_time, before_time, before_id),
        ).fetchall()
        has_more = len(rows) > 50
        rows = rows[:50]
        return {"messages": [_message_dto(row, user["id"]) for row in reversed(rows)],
                "has_more": has_more, "next_before": rows[-1]["id"] if has_more else None}

    @app.post("/api/community/connections/{connection_id}/messages")
    def send_message(connection_id: str, data: MessageInput,
                     user: dict = Depends(community_user), db=Depends(get_connection)):
        row = _locked_connection(db, connection_id, user["id"])
        if row["status"] != "accepted":
            raise HTTPException(403, "Переписка недоступна: запрос не принят или общение прекращено")
        other_id = row["recipient_id"] if row["sender_id"] == user["id"] else row["sender_id"]
        if not _active_account(db, int(other_id)):
            raise HTTPException(403, "Участник сейчас недоступен")
        previous = db.execute(
            "SELECT * FROM community_messages WHERE connection_id=? AND sender_id=? AND client_key=?",
            (connection_id, user["id"], str(data.client_key)),
        ).fetchone()
        if previous is not None:
            if previous["body"] != data.body:
                raise HTTPException(409, "Этот идентификатор уже использован для другого сообщения")
            return _committed(db, {"message": _message_dto(previous, user["id"])})
        throttle(db, user["id"], "community-messages", 30, 60)
        message_id, now = _key(), _now()
        db.execute(
            "INSERT INTO community_messages(id,connection_id,sender_id,client_key,body,created_at) VALUES(?,?,?,?,?,?)",
            (message_id, connection_id, user["id"], str(data.client_key), data.body, now),
        )
        db.execute("UPDATE community_connections SET updated_at=? WHERE id=?", (now, connection_id))
        message = db.execute("SELECT * FROM community_messages WHERE id=?", (message_id,)).fetchone()
        return _committed(db, {"message": _message_dto(message, user["id"])})

    @app.post("/api/community/reports")
    def report(data: ReportInput, user: dict = Depends(community_user), db=Depends(get_connection)):
        if user["role"] not in {"candidate", "employer"}:
            raise HTTPException(403, "Жалобы доступны участникам и работодателям")
        _lock_actors(db, user["id"])
        if data.public_id:
            public_person(db, data.public_id)
            target_key = "profile:" + data.public_id
        else:
            _connection(db, data.connection_id, user["id"])
            target_key = "connection:" + data.connection_id
        existing = db.execute("SELECT id,status FROM community_reports WHERE reporter_id=? AND target_key=?",
                              (user["id"], target_key)).fetchone()
        if existing is not None:
            return _committed(db, {"report": {"id": existing["id"], "status": existing["status"]}})
        throttle(db, user["id"], "community-reports", 10, 86400)
        report_id = _key()
        db.execute(
            """INSERT INTO community_reports(id,reporter_id,public_id,connection_id,target_key,reason,
               details,created_at) VALUES(?,?,?,?,?,?,?,?)""",
            (report_id, user["id"], data.public_id, data.connection_id, target_key, data.reason, data.details, _now()),
        )
        return _committed(db, {"report": {"id": report_id, "status": "new"}})

    @app.get("/api/admin/community/reports")
    def reports(status: Literal["new", "resolved", "dismissed"] = "new",
                page: int = Query(default=1, ge=1, le=10000),
                user: dict = Depends(community_user), db=Depends(get_connection)):
        allowed(user, "admin")
        total = db.execute("SELECT COUNT(*) FROM community_reports WHERE status=?", (status,)).fetchone()[0]
        rows = db.execute("SELECT * FROM community_reports WHERE status=? ORDER BY created_at,id LIMIT ? OFFSET ?",
                          (status, PAGE_SIZE, (page - 1) * PAGE_SIZE)).fetchall()
        return {"reports": [_report_dto(row) for row in rows], **_page_info(page, total)}

    @app.patch("/api/admin/community/reports/{report_id}")
    def review_report(report_id: str, data: ReportReviewInput,
                      user: dict = Depends(community_user), db=Depends(get_connection)):
        allowed(user, "admin")
        result = db.execute("UPDATE community_reports SET status=?,reviewed_by=?,reviewed_at=? WHERE id=?",
                            (data.status, user["id"], _now(), report_id))
        if result.rowcount != 1:
            raise HTTPException(404, "Жалоба не найдена")
        record_security_event(db, user["id"], "community_report_reviewed", "report=" + report_id + " status=" + data.status)
        return _committed(db, {"report": _report_dto(db.execute("SELECT * FROM community_reports WHERE id=?", (report_id,)).fetchone())})
