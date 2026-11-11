"""Release 0.2 routes with durable notification outbox and optional SMTP delivery."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from .db import database
from .email_delivery import delivery_mode, send_email
from .security import make_password_hash, token_hash, verify_password


MIGRATION = """
CREATE TABLE IF NOT EXISTS candidate_favorites (
 candidate_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 vacancy_id INTEGER NOT NULL REFERENCES vacancies(id) ON DELETE CASCADE,
 created_at TEXT NOT NULL DEFAULT (datetime('now')),
 PRIMARY KEY(candidate_id,vacancy_id)
);
CREATE TABLE IF NOT EXISTS job_applications (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 vacancy_id INTEGER NOT NULL REFERENCES vacancies(id) ON DELETE CASCADE,
 candidate_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 status TEXT NOT NULL DEFAULT 'applied'
 CHECK(status IN ('applied','reviewing','interview','rejected','hired','withdrawn')),
 created_at TEXT NOT NULL DEFAULT (datetime('now')),
 updated_at TEXT NOT NULL DEFAULT (datetime('now')),
 UNIQUE(vacancy_id,candidate_id)
);
CREATE INDEX IF NOT EXISTS idx_job_applications_candidate ON job_applications(candidate_id);
CREATE INDEX IF NOT EXISTS idx_job_applications_vacancy ON job_applications(vacancy_id);
CREATE TABLE IF NOT EXISTS application_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 application_id INTEGER NOT NULL REFERENCES job_applications(id) ON DELETE CASCADE,
 event TEXT NOT NULL CHECK(event IN ('applied','withdrawn','reapplied','reviewing','interview','rejected','hired')),
 created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_application_events_application ON application_events(application_id,id);
CREATE TABLE IF NOT EXISTS account_controls (
 user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','disabled')),
 email_verified INTEGER NOT NULL DEFAULT 0 CHECK(email_verified IN (0,1))
);
CREATE TABLE IF NOT EXISTS email_tokens (
 token_hash TEXT PRIMARY KEY,
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 purpose TEXT NOT NULL CHECK(purpose IN ('verify','reset')),
 expires_at TEXT NOT NULL,
 used_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_email_tokens_user ON email_tokens(user_id,purpose);
CREATE TABLE IF NOT EXISTS email_outbox (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 to_email TEXT NOT NULL,
 event TEXT NOT NULL,
 subject TEXT NOT NULL,
 body TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS admin_audit (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 admin_id INTEGER NOT NULL REFERENCES users(id),
 action TEXT NOT NULL,
 target_id INTEGER NOT NULL,
 created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Vacancy changes and their intended recipients live only in the demo SQLite database.
-- Recipients are determined at edit time; candidates joining later never receive old updates.
CREATE TABLE IF NOT EXISTS vacancy_updates (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 vacancy_id INTEGER NOT NULL REFERENCES vacancies(id) ON DELETE CASCADE,
 employer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 changes_json TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_vacancy_updates_vacancy ON vacancy_updates(vacancy_id,id);
CREATE TABLE IF NOT EXISTS vacancy_update_recipients (
 update_id INTEGER NOT NULL REFERENCES vacancy_updates(id) ON DELETE CASCADE,
 candidate_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 read_at TEXT,
 PRIMARY KEY (update_id,candidate_id)
);
CREATE INDEX IF NOT EXISTS idx_vacancy_update_recipients_candidate ON vacancy_update_recipients(candidate_id,read_at,update_id);
"""

RELEASE09_RUNTIME_DDL = (
    """CREATE TABLE IF NOT EXISTS employer_public_profiles (
        employer_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        about TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS vacancy_moderation (
        vacancy_id INTEGER PRIMARY KEY REFERENCES vacancies(id) ON DELETE CASCADE,
        status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected')),
        reason TEXT NOT NULL DEFAULT '',
        reviewed_by INTEGER REFERENCES users(id),
        reviewed_at TEXT,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS content_reports (
        report_key TEXT PRIMARY KEY,
        reporter_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        vacancy_id INTEGER NOT NULL REFERENCES vacancies(id) ON DELETE CASCADE,
        employer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        target_type TEXT NOT NULL CHECK(target_type IN ('vacancy','employer')),
        reason TEXT NOT NULL CHECK(reason IN ('misleading','discrimination','fraud','contacts','other')),
        details TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL CHECK(status IN ('new','reviewed','dismissed','actioned')),
        created_at TEXT NOT NULL,
        reviewed_at TEXT,
        reviewed_by INTEGER REFERENCES users(id)
    )""",
    """CREATE TABLE IF NOT EXISTS taxonomy_observations (
        term_key TEXT PRIMARY KEY,
        kind TEXT NOT NULL CHECK(kind IN ('profession','skill')),
        normalized_value TEXT NOT NULL,
        display_value TEXT NOT NULL,
        candidate_seen INTEGER NOT NULL DEFAULT 0,
        vacancy_seen INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
        reviewed_by INTEGER REFERENCES users(id),
        reviewed_at TEXT,
        updated_at TEXT NOT NULL,
        UNIQUE(kind,normalized_value)
    )""",
    """CREATE TABLE IF NOT EXISTS admin_mfa_challenges (
        challenge_key TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        code_hash TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        used_at TEXT,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS security_events (
        event_key TEXT PRIMARY KEY,
        user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        event_type TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS session_activity (
        token_hash TEXT PRIMARY KEY REFERENCES sessions(token_hash) ON DELETE CASCADE,
        authenticated_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS account_devices (
        device_key TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        label TEXT NOT NULL,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        login_count INTEGER NOT NULL DEFAULT 1
    )""",
    """CREATE TABLE IF NOT EXISTS session_context (
        token_hash TEXT PRIMARY KEY REFERENCES sessions(token_hash) ON DELETE CASCADE,
        device_key TEXT REFERENCES account_devices(device_key) ON DELETE SET NULL,
        device_label TEXT NOT NULL DEFAULT 'Неизвестное устройство'
    )""",
    """CREATE TABLE IF NOT EXISTS security_rate_limits (
        rate_key TEXT PRIMARY KEY,
        bucket_start INTEGER NOT NULL,
        count INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS admin_webauthn_credentials (
        credential_id TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        public_key TEXT NOT NULL,
        sign_count INTEGER NOT NULL DEFAULT 0,
        label TEXT NOT NULL,
        transports TEXT NOT NULL DEFAULT '',
        credential_device_type TEXT NOT NULL DEFAULT '',
        backed_up INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        last_used_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS admin_webauthn_challenges (
        challenge_key TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        kind TEXT NOT NULL CHECK(kind IN ('registration','authentication')),
        challenge_b64 TEXT NOT NULL,
        rp_id TEXT NOT NULL,
        origin TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        used_at TEXT,
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_vacancy_moderation_status ON vacancy_moderation(status)",
    "CREATE INDEX IF NOT EXISTS idx_content_reports_status ON content_reports(status,created_at)",
    "CREATE INDEX IF NOT EXISTS idx_content_reports_vacancy ON content_reports(vacancy_id,status)",
    "CREATE INDEX IF NOT EXISTS idx_taxonomy_observations_status ON taxonomy_observations(status,kind,updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_admin_mfa_user ON admin_mfa_challenges(user_id,expires_at)",
    "CREATE INDEX IF NOT EXISTS idx_security_events_user ON security_events(user_id,created_at)",
    "CREATE INDEX IF NOT EXISTS idx_security_events_type ON security_events(event_type,created_at)",
    "CREATE INDEX IF NOT EXISTS idx_session_activity_last_seen ON session_activity(last_seen_at)",
    "CREATE INDEX IF NOT EXISTS idx_account_devices_user ON account_devices(user_id,last_seen_at)",
    "CREATE INDEX IF NOT EXISTS idx_session_context_device ON session_context(device_key)",
    "CREATE INDEX IF NOT EXISTS idx_security_rate_limits_updated ON security_rate_limits(updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_admin_webauthn_user ON admin_webauthn_credentials(user_id,created_at)",
    "CREATE INDEX IF NOT EXISTS idx_admin_webauthn_challenge_user ON admin_webauthn_challenges(user_id,expires_at)",
)
MIGRATION += "\n" + "\n".join(statement + ";" for statement in RELEASE09_RUNTIME_DDL)


LEGACY_ADMIN_EMAIL = "admin@demo.example"
PRODUCTION_ADMIN_EMAIL = "admin@stazhno.ru"


def migrate_legacy_admin_email(db: sqlite3.Connection) -> bool:
    """Move the original demo administrator login to the production mailbox.

    The user id is preserved so TOTP/passkeys/audit relations stay attached to
    the same administrator. A conflicting target account aborts startup rather
    than merging two identities implicitly.
    """
    old = db.execute(
        "SELECT id,role FROM users WHERE email=?",
        (LEGACY_ADMIN_EMAIL,),
    ).fetchone()
    if old is None:
        return False
    if old["role"] != "admin":
        raise RuntimeError("legacy administrator email belongs to a non-admin account")

    target = db.execute(
        "SELECT id,role FROM users WHERE email=?",
        (PRODUCTION_ADMIN_EMAIL,),
    ).fetchone()
    if target is not None and int(target["id"]) != int(old["id"]):
        raise RuntimeError("production administrator email is already used by another account")

    user_id = int(old["id"])
    db.execute(
        "UPDATE users SET email=? WHERE id=?",
        (PRODUCTION_ADMIN_EMAIL, user_id),
    )
    # Old reset/verification links must not survive an identity-address change.
    db.execute("DELETE FROM email_tokens WHERE user_id=?", (user_id,))
    # Force a fresh login with the new address; WebAuthn/TOTP credentials remain.
    db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    db.execute("DELETE FROM admin_mfa_challenges WHERE user_id=?", (user_id,))
    db.execute("DELETE FROM admin_webauthn_challenges WHERE user_id=?", (user_id,))
    db.execute(
        "UPDATE account_controls SET email_verified=0 WHERE user_id=?",
        (user_id,),
    )
    record_security_event(
        db,
        user_id,
        "admin_email_migrated",
        "legacy_demo_address_replaced",
    )
    return True


def production_admin_email_migration_enabled() -> bool:
    env = os.getenv("OPYT50_ENV", "").strip().casefold()
    public_url = os.getenv("OPYT50_PUBLIC_URL", "").strip().casefold()
    return (
        env in {"prod", "production"}
        or public_url.startswith("https://stazhno.ru")
        or public_url.startswith("https://www.stazhno.ru")
    )


def init_release02(path: str) -> None:
    with database(path) as db:
        db.executescript(MIGRATION)
        # PostgreSQL runtime intentionally skips SQLite executescript().
        # These 0.9 tables use cross-compatible additive DDL so existing production
        # databases can gain them safely with CREATE TABLE/INDEX IF NOT EXISTS.
        for statement in RELEASE09_RUNTIME_DDL:
            db.execute(statement)
        if production_admin_email_migration_enabled():
            migrate_legacy_admin_email(db)


def enqueue_notice(
    db: sqlite3.Connection,
    user_id: int,
    event: str,
    subject: str,
    message: str,
    *,
    stored_body: str | None = None,
) -> None:
    """Persist a redaction-safe notice and optionally deliver the real message."""
    user = db.execute("SELECT email FROM users WHERE id=?", (user_id,)).fetchone()
    if user is not None:
        persisted = message if stored_body is None else stored_body
        db.execute(
            "INSERT INTO email_outbox(to_email,event,subject,body) VALUES(?,?,?,?)",
            (user["email"], event, subject, persisted),
        )
        send_email(user["email"], subject, message)


class ApplicationIn(BaseModel):
    vacancy_id: int = Field(gt=0)


class ApplicationStatusIn(BaseModel):
    status: Literal["reviewing", "interview", "rejected", "hired"]


class AccountStatusIn(BaseModel):
    status: Literal["active", "disabled"]


class EmployerCompanyIn(BaseModel):
    company_name: str = Field(min_length=2, max_length=120)
    inn: str = Field(default="", max_length=12)
    about: str = Field(default="", max_length=1200)

    @field_validator("inn")
    @classmethod
    def clean_inn(cls, value: str) -> str:
        value = value.strip()
        if value and (not value.isdigit() or len(value) not in (10, 12)):
            raise ValueError("ИНН должен содержать 10 или 12 цифр")
        return value


class EmployerVerificationIn(BaseModel):
    verified: bool


class VacancyAdminStatusIn(BaseModel):
    status: Literal["open", "closed"]


class VacancyModerationIn(BaseModel):
    status: Literal["pending", "approved", "rejected"]
    reason: str = Field(default="", max_length=500)


class ContentReportIn(BaseModel):
    vacancy_id: int = Field(gt=0)
    target_type: Literal["vacancy", "employer"]
    reason: Literal["misleading", "discrimination", "fraud", "contacts", "other"]
    details: str = Field(default="", max_length=800)


class ContentReportStatusIn(BaseModel):
    status: Literal["reviewed", "dismissed", "actioned"]


class TaxonomyObservationStatusIn(BaseModel):
    status: Literal["approved", "rejected"]


class EmailTokenIn(BaseModel):
    token: str = Field(min_length=20, max_length=256)


class PasswordRequestIn(BaseModel):
    email: str = Field(min_length=5, max_length=254)


class PasswordResetIn(EmailTokenIn):
    password: str = Field(min_length=15, max_length=128)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=15, max_length=128)


def issue_email_token(db: sqlite3.Connection, user_id: int, purpose: str) -> None:
    token = secrets.token_urlsafe(40)
    expires = (datetime.now(timezone.utc) + timedelta(minutes=30 if purpose == "reset" else 1440)).isoformat()
    db.execute("DELETE FROM email_tokens WHERE user_id=? AND purpose=?", (user_id, purpose))
    db.execute("INSERT INTO email_tokens(token_hash,user_id,purpose,expires_at) VALUES(?,?,?,?)",
               (token_hash(token), user_id, purpose, expires))
    # Token is never returned by the API or written to application logs.
    route = "reset" if purpose == "reset" else "verify"
    public_url = __import__("os").getenv("OPYT50_PUBLIC_URL", "").strip().rstrip("/")
    path = f"/?account_action={route}&token={token}"
    link = public_url + path if public_url else path
    ttl = "30 минут" if purpose == "reset" else "24 часа"
    action = "восстановления пароля" if purpose == "reset" else "подтверждения email"
    subject = (
        "СТАЖНО — восстановление пароля"
        if purpose == "reset"
        else "СТАЖНО — подтверждение email"
    )
    intro = (
        "Вы запросили восстановление пароля в СТАЖНО."
        if purpose == "reset"
        else "Подтвердите ваш email для работы в СТАЖНО."
    )
    button_hint = (
        "Откройте ссылку ниже и задайте новый пароль:"
        if purpose == "reset"
        else "Откройте ссылку ниже, чтобы подтвердить email:"
    )
    message = (
        f"{intro}\n\n"
        f"{button_hint}\n{link}\n\n"
        f"Ссылка действует {ttl}.\n"
        "Если вы не запрашивали это действие, просто проигнорируйте письмо."
    )
    enqueue_notice(
        db,
        user_id,
        f"account_{purpose}",
        subject,
        message,
        stored_body=(
            f"Ссылка для {action} отправлена пользователю. "
            f"Срок действия: {ttl}. Секретный токен намеренно не сохраняется."
        ),
    )


def redeem_token(db: sqlite3.Connection, raw: str, purpose: str) -> sqlite3.Row:
    row = db.execute("SELECT * FROM email_tokens WHERE token_hash=? AND purpose=? AND used_at IS NULL",
                     (token_hash(raw), purpose)).fetchone()
    if row is None or datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
        raise HTTPException(400, "Ссылка недействительна или срок истёк")
    db.execute("UPDATE email_tokens SET used_at=datetime('now') WHERE token_hash=?", (row["token_hash"],))
    return row


def utc_now_text() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


def record_security_event(
    db: sqlite3.Connection,
    user_id: int | None,
    event_type: str,
    detail: str = "",
) -> None:
    """Store a minimal audit event without passwords, tokens, OTPs, IPs or user agents."""
    event_key = secrets.token_urlsafe(18)
    safe_detail = str(detail or "").replace("\n", " ").strip()[:240]
    db.execute(
        """INSERT INTO security_events(event_key,user_id,event_type,detail,created_at)
           VALUES(?,?,?,?,?)""",
        (event_key, user_id, event_type[:80], safe_detail, utc_now_text()),
    )


def issue_admin_mfa_challenge(
    db: sqlite3.Connection,
    user_id: int,
) -> tuple[str, str]:
    """Create one short-lived, single-use 8-digit challenge for an administrator."""
    code = f"{secrets.randbelow(100_000_000):08d}"
    challenge_key = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    db.execute("DELETE FROM admin_mfa_challenges WHERE user_id=?", (user_id,))
    db.execute(
        """INSERT INTO admin_mfa_challenges(
               challenge_key,user_id,code_hash,expires_at,attempts,created_at
           ) VALUES(?,?,?,?,0,?)""",
        (challenge_key, user_id, make_password_hash(code), expires, utc_now_text()),
    )
    enqueue_notice(
        db,
        user_id,
        "admin_mfa",
        "СТАЖНО — код подтверждения входа",
        (
            f"Код подтверждения входа администратора: {code}\n\n"
            "Код действует 5 минут и только один раз. "
            "Если вы не входили в СТАЖНО, смените пароль и проверьте активные сессии."
        ),
        stored_body=(
            "Одноразовый код подтверждения входа администратора отправлен. "
            "Секретный код намеренно не сохраняется."
        ),
    )
    record_security_event(db, user_id, "admin_mfa_challenge_issued")
    return challenge_key, code


def issue_admin_totp_challenge(
    db: sqlite3.Connection,
    user_id: int,
) -> str:
    """Create a short-lived gate proving the administrator password was verified."""
    challenge_key = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    db.execute("DELETE FROM admin_mfa_challenges WHERE user_id=?", (user_id,))
    db.execute(
        """INSERT INTO admin_mfa_challenges(
               challenge_key,user_id,code_hash,expires_at,attempts,created_at
           ) VALUES(?,?,?,?,0,?)""",
        (challenge_key, user_id, "totp-v1", expires, utc_now_text()),
    )
    record_security_event(db, user_id, "admin_totp_challenge_issued")
    return challenge_key


def refresh_taxonomy_observations(db: sqlite3.Connection) -> None:
    """Aggregate anonymous profession/skill terms from current profiles and vacancies.

    Only term text and aggregate counts are stored. No user/vacancy identifiers
    are persisted in this learning queue.
    """
    from .matching import normalize_phrase, taxonomy_payload

    payload = taxonomy_payload()
    known_professions = {
        normalize_phrase(item["value"]) for item in payload["professions"]
    }
    known_skills = set()
    for item in payload["skills"]:
        known_skills.add(normalize_phrase(item["value"]))
        known_skills.update(normalize_phrase(alias) for alias in item.get("aliases", []))

    profession_counts: dict[str, dict[str, object]] = {}
    skill_counts: dict[str, dict[str, object]] = {}

    def add(bucket: dict, raw: str, source: str) -> None:
        display = str(raw or "").strip()
        normalized = normalize_phrase(display)
        if not normalized:
            return
        row = bucket.setdefault(normalized, {
            "display": display, "candidate": 0, "vacancy": 0,
        })
        # Prefer the most recently observed human spelling, but never attach identity.
        row["display"] = display
        row[source] = int(row[source]) + 1

    for row in db.execute(
        "SELECT profession,skills FROM candidate_profiles WHERE length(trim(profession))>0 OR length(trim(skills))>0"
    ).fetchall():
        if row["profession"]:
            add(profession_counts, row["profession"], "candidate")
        for skill in re.split(r"[,;\n]+", str(row["skills"] or "")):
            if skill.strip():
                add(skill_counts, skill, "candidate")

    for row in db.execute(
        "SELECT title,skills FROM vacancies WHERE length(trim(title))>0 OR length(trim(skills))>0"
    ).fetchall():
        if row["title"]:
            add(profession_counts, row["title"], "vacancy")
        for skill in re.split(r"[,;\n]+", str(row["skills"] or "")):
            if skill.strip():
                add(skill_counts, skill, "vacancy")

    now = utc_now_text()

    def sync(kind: str, counts: dict, known: set[str]) -> None:
        for normalized, item in counts.items():
            if normalized in known:
                continue
            term_key = hashlib.sha256(f"{kind}\0{normalized}".encode("utf-8")).hexdigest()[:24]
            db.execute(
                """INSERT INTO taxonomy_observations(
                       term_key,kind,normalized_value,display_value,candidate_seen,vacancy_seen,updated_at
                   ) VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(term_key) DO UPDATE SET
                     display_value=excluded.display_value,
                     candidate_seen=excluded.candidate_seen,
                     vacancy_seen=excluded.vacancy_seen,
                     updated_at=excluded.updated_at""",
                (
                    term_key, kind, normalized, str(item["display"]),
                    int(item["candidate"]), int(item["vacancy"]), now,
                ),
            )

    sync("profession", profession_counts, known_professions)
    sync("skill", skill_counts, known_skills)


def moderation_status(db: sqlite3.Connection, vacancy_id: int) -> str:
    row = db.execute(
        "SELECT status FROM vacancy_moderation WHERE vacancy_id=?",
        (vacancy_id,),
    ).fetchone()
    return row["status"] if row else "approved"


def employer_trust(db: sqlite3.Connection, employer_id: int) -> dict | None:
    """Non-sensitive employer trust signals used by public vacancy UI."""
    row = db.execute(
        """SELECT e.company_name,e.inn,e.verified,u.created_at,
                  COALESCE(c.email_verified,0) AS email_verified
           FROM employer_profiles e
           JOIN users u ON u.id=e.user_id
           LEFT JOIN account_controls c ON c.user_id=e.user_id
           WHERE e.user_id=?""",
        (employer_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "company_name": row["company_name"],
        "verified": bool(row["verified"]),
        "email_verified": bool(row["email_verified"]),
        "inn_provided": bool(str(row["inn"] or "").strip()),
        "created_at": normalize_event_time(row["created_at"]),
    }


def introduction_stage(status: str | None, contact_shared: int | bool | None) -> str | None:
    """Single, non-sensitive workflow status for all dashboards."""
    if contact_shared:
        return "introduced"
    return {"sent": "awaiting_consent", "accepted": "consented", "declined": "declined"}.get(status)


def normalize_event_time(value) -> str:
    """Stable second-resolution UTC-like text for SQLite and PostgreSQL timelines."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        value = value.astimezone(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")
    else:
        value = str(value).strip().replace("T", " ")
        if value.endswith("Z"):
            value = value[:-1]
        if "+" in value:
            value = value.split("+", 1)[0]
        if "." in value:
            value = value.split(".", 1)[0]
    return value[:19]


def interaction_timeline(
    db: sqlite3.Connection, application_id: int | None, invitation_id: int | None
) -> list[dict[str, str]]:
    """Unified chronological activity without names, addresses or contact values."""
    entries: list[tuple[str, int, dict[str, str]]] = []
    if application_id is not None:
        rows = db.execute(
            """SELECT id,event,created_at FROM application_events
               WHERE application_id=? ORDER BY id ASC""", (application_id,)
        ).fetchall()
        for row in rows:
            entries.append((normalize_event_time(row["created_at"]), row["id"], {
                "event": row["event"], "created_at": normalize_event_time(row["created_at"])
            }))
    if invitation_id is not None:
        invitation = db.execute(
            """SELECT status,contact_shared,created_at,responded_at
               FROM invitations WHERE id=?""", (invitation_id,)
        ).fetchone()
        if invitation:
            entries.append((normalize_event_time(invitation["created_at"]), 1000000, {
                "event": "invitation_sent", "created_at": normalize_event_time(invitation["created_at"])
            }))
            if normalize_event_time(invitation["responded_at"]) and invitation["status"] in ("accepted", "declined"):
                entries.append((normalize_event_time(invitation["responded_at"]), 2000000, {
                    "event": "invitation_accepted" if invitation["status"] == "accepted" else "invitation_declined",
                    "created_at": normalize_event_time(invitation["responded_at"])
                }))
            if invitation["contact_shared"]:
                txn = db.execute(
                    "SELECT created_at FROM demo_transactions WHERE invitation_id=?",
                    (invitation_id,),
                ).fetchone()
                if txn:
                    entries.append((normalize_event_time(txn["created_at"]), 3000000, {
                        "event": "contact_opened", "created_at": normalize_event_time(txn["created_at"])
                    }))
    # SQLite timestamps are second-resolution; an explicit sequence makes
    # events from one request deterministic, without relying on client clocks.
    entries.sort(key=lambda row: (row[0], row[1]))
    return [entry for _, __, entry in entries]


def install_routes(app) -> None:
    # Imported here to avoid a circular module initialization.
    from .main import (
        CONTACT_EMAIL_PATTERN, CONTACT_PHONE_PATTERN,
        active_user, add_session, allowed, candidate_view,
        clear_security_rate_limit, consume_security_rate_limit, get_connection,
    )

    @app.get("/api/employer/company")
    def employer_company(user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "employer")
        profile = db.execute(
            """SELECT e.company_name,e.inn,e.verified,COALESCE(p.about,'') AS about
               FROM employer_profiles e
               LEFT JOIN employer_public_profiles p ON p.employer_id=e.user_id
               WHERE e.user_id=?""",
            (user["id"],),
        ).fetchone()
        if profile is None:
            raise HTTPException(404, "Профиль компании не найден")
        trust = employer_trust(db, user["id"])
        return {
            "company": {
                "company_name": profile["company_name"],
                "inn": profile["inn"],
                "verified": bool(profile["verified"]),
                "about": profile["about"],
            },
            "trust": trust,
        }

    @app.put("/api/employer/company")
    def update_employer_company(
        data: EmployerCompanyIn,
        user: dict = Depends(active_user),
        db: sqlite3.Connection = Depends(get_connection),
    ):
        allowed(user, "employer")
        if CONTACT_EMAIL_PATTERN.search(data.about) or CONTACT_PHONE_PATTERN.search(data.about):
            raise HTTPException(422, "Не указывайте телефон или email в публичном описании компании")
        current = db.execute(
            "SELECT company_name,inn,verified FROM employer_profiles WHERE user_id=?",
            (user["id"],),
        ).fetchone()
        if current is None:
            raise HTTPException(404, "Профиль компании не найден")
        changed_identity = (
            current["company_name"] != data.company_name.strip()
            or str(current["inn"] or "") != data.inn
        )
        verified = 0 if changed_identity else int(bool(current["verified"]))
        db.execute(
            "UPDATE employer_profiles SET company_name=?,inn=?,verified=? WHERE user_id=?",
            (data.company_name.strip(), data.inn, verified, user["id"]),
        )
        db.execute(
            """INSERT INTO employer_public_profiles(employer_id,about,updated_at) VALUES(?,?,?)
               ON CONFLICT(employer_id) DO UPDATE SET about=excluded.about,updated_at=excluded.updated_at""",
            (user["id"], data.about.strip(), utc_now_text()),
        )
        db.commit()
        return {"ok": True, "trust": employer_trust(db, user["id"])}

    @app.get("/api/companies/{employer_id}")
    def public_company(employer_id: int, db: sqlite3.Connection = Depends(get_connection)):
        company = db.execute(
            """SELECT e.company_name,e.verified,u.created_at,COALESCE(c.status,'active') AS account_status,
                      COALESCE(p.about,'') AS about
               FROM employer_profiles e
               JOIN users u ON u.id=e.user_id
               LEFT JOIN account_controls c ON c.user_id=e.user_id
               LEFT JOIN employer_public_profiles p ON p.employer_id=e.user_id
               WHERE e.user_id=? AND u.role='employer'""",
            (employer_id,),
        ).fetchone()
        if company is None or company["account_status"] != "active":
            raise HTTPException(404, "Компания не найдена")
        jobs = db.execute(
            """SELECT v.id,v.employer_id,v.title,v.city,v.salary_min,v.salary_max,
                      v.schedule,v.employment,v.skills,v.description,v.created_at
               FROM vacancies v
               LEFT JOIN vacancy_moderation vm ON vm.vacancy_id=v.id
               WHERE v.employer_id=? AND v.status='open'
                 AND COALESCE(vm.status,'approved')='approved'
               ORDER BY v.id DESC LIMIT 20""",
            (employer_id,),
        ).fetchall()
        trust = employer_trust(db, employer_id)
        return {
            "company": {
                "id": employer_id,
                "company_name": company["company_name"],
                "about": company["about"],
                "created_at": normalize_event_time(company["created_at"]),
                "trust": trust,
                "open_vacancies": len(jobs),
            },
            "jobs": [dict(row) for row in jobs],
        }

    @app.post("/api/reports", status_code=201)
    def create_content_report(
        data: ContentReportIn,
        user: dict = Depends(active_user),
        db: sqlite3.Connection = Depends(get_connection),
    ):
        allowed(user, "candidate")
        vacancy = db.execute(
            """SELECT v.id,v.employer_id,v.status,COALESCE(vm.status,'approved') AS moderation_status
               FROM vacancies v
               LEFT JOIN vacancy_moderation vm ON vm.vacancy_id=v.id
               WHERE v.id=?""",
            (data.vacancy_id,),
        ).fetchone()
        if vacancy is None or vacancy["status"] != "open" or vacancy["moderation_status"] != "approved":
            raise HTTPException(404, "Вакансия недоступна")
        duplicate = db.execute(
            """SELECT report_key FROM content_reports
               WHERE reporter_id=? AND vacancy_id=? AND target_type=?
                 AND status IN ('new','reviewed')""",
            (user["id"], data.vacancy_id, data.target_type),
        ).fetchone()
        if duplicate is not None:
            raise HTTPException(409, "Жалоба уже отправлена и находится на рассмотрении")
        report_key = secrets.token_urlsafe(12)
        db.execute(
            """INSERT INTO content_reports(
                   report_key,reporter_id,vacancy_id,employer_id,target_type,reason,details,status,created_at
               ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                report_key, user["id"], data.vacancy_id, vacancy["employer_id"],
                data.target_type, data.reason, data.details.strip(), "new", utc_now_text(),
            ),
        )
        auto_pending = False
        if data.target_type == "vacancy":
            count = db.execute(
                """SELECT COUNT(DISTINCT reporter_id) FROM content_reports
                   WHERE vacancy_id=? AND target_type='vacancy' AND status IN ('new','reviewed')""",
                (data.vacancy_id,),
            ).fetchone()[0]
            current = moderation_status(db, data.vacancy_id)
            if count >= 2 and current == "approved":
                now = utc_now_text()
                db.execute(
                    """INSERT INTO vacancy_moderation(vacancy_id,status,reason,updated_at)
                       VALUES(?,?,?,?)
                       ON CONFLICT(vacancy_id) DO UPDATE SET
                         status=excluded.status,reason=excluded.reason,
                         reviewed_by=NULL,reviewed_at=NULL,updated_at=excluded.updated_at""",
                    (data.vacancy_id, "pending", "Автоматически скрыта после нескольких жалоб", now),
                )
                auto_pending = True
        db.commit()
        return {"ok": True, "report_key": report_key, "vacancy_pending_review": auto_pending}

    @app.patch("/api/admin/employers/{user_id}/verification")
    def admin_employer_verification(
        user_id: int,
        data: EmployerVerificationIn,
        user: dict = Depends(active_user),
        db: sqlite3.Connection = Depends(get_connection),
    ):
        allowed(user, "admin")
        target = db.execute(
            """SELECT u.role,e.inn,COALESCE(c.email_verified,0) AS email_verified
               FROM users u
               LEFT JOIN employer_profiles e ON e.user_id=u.id
               LEFT JOIN account_controls c ON c.user_id=u.id
               WHERE u.id=?""",
            (user_id,),
        ).fetchone()
        if target is None or target["role"] != "employer" or target["inn"] is None:
            raise HTTPException(404, "Работодатель не найден")
        if data.verified and (not str(target["inn"]).strip() or not target["email_verified"]):
            raise HTTPException(422, "Для проверки компании нужны заполненный ИНН и подтверждённый email")
        db.execute(
            "UPDATE employer_profiles SET verified=? WHERE user_id=?",
            (int(data.verified), user_id),
        )
        db.execute(
            "INSERT INTO admin_audit(admin_id,action,target_id) VALUES(?,?,?)",
            (user["id"], "employer_verified" if data.verified else "employer_unverified", user_id),
        )
        db.commit()
        return {"ok": True, "trust": employer_trust(db, user_id)}

    @app.get("/api/jobs/{job_id}")
    def job_detail(job_id: int, db: sqlite3.Connection = Depends(get_connection)):
        row = db.execute("""SELECT v.*,e.company_name,e.verified AS employer_verified,
                                   CASE WHEN length(e.inn)>0 THEN 1 ELSE 0 END AS employer_inn_provided,
                                   COALESCE(c.email_verified,0) AS employer_email_verified,
                                   u.created_at AS employer_created_at
                            FROM vacancies v
                            JOIN employer_profiles e ON e.user_id=v.employer_id
                            JOIN users u ON u.id=e.user_id
                            LEFT JOIN account_controls c ON c.user_id=e.user_id
                            LEFT JOIN vacancy_moderation vm ON vm.vacancy_id=v.id
                            WHERE v.id=? AND v.status='open'
                              AND COALESCE(c.status,'active')='active'
                              AND COALESCE(vm.status,'approved')='approved'""", (job_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Вакансия не найдена или закрыта")
        return {"job": dict(row)}

    @app.get("/api/candidate/favorites")
    def favorites(user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "candidate")
        rows = db.execute("""SELECT v.*,e.company_name,e.verified AS employer_verified,
                                    CASE WHEN length(e.inn)>0 THEN 1 ELSE 0 END AS employer_inn_provided,
                                    COALESCE(c.email_verified,0) AS employer_email_verified,
                                    u.created_at AS employer_created_at
                             FROM candidate_favorites f
                             JOIN vacancies v ON v.id=f.vacancy_id
                             JOIN employer_profiles e ON e.user_id=v.employer_id
                             JOIN users u ON u.id=e.user_id
                             LEFT JOIN account_controls c ON c.user_id=e.user_id
                             LEFT JOIN vacancy_moderation vm ON vm.vacancy_id=v.id
                             WHERE f.candidate_id=?
                               AND v.status='open'
                               AND COALESCE(c.status,'active')='active'
                               AND COALESCE(vm.status,'approved')='approved'
                             ORDER BY f.created_at DESC,v.id DESC""", (user["id"],)).fetchall()
        return {"jobs": [dict(r) for r in rows]}

    @app.post("/api/candidate/favorites/{job_id}", status_code=201)
    def save_favorite(job_id: int, user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "candidate")
        if db.execute(
            """SELECT 1 FROM vacancies v
               JOIN employer_profiles e ON e.user_id=v.employer_id
               LEFT JOIN account_controls c ON c.user_id=e.user_id
               LEFT JOIN vacancy_moderation vm ON vm.vacancy_id=v.id
               WHERE v.id=? AND v.status='open'
                 AND COALESCE(c.status,'active')='active'
                 AND COALESCE(vm.status,'approved')='approved'""",
            (job_id,),
        ).fetchone() is None:
            raise HTTPException(404, "Вакансия не найдена")
        db.execute("INSERT OR IGNORE INTO candidate_favorites(candidate_id,vacancy_id) VALUES(?,?)",
                   (user["id"], job_id))
        # Commit before the HTTP response: a new dashboard request may arrive immediately.
        db.commit()
        return {"ok": True}

    @app.delete("/api/candidate/favorites/{job_id}")
    def remove_favorite(job_id: int, user: dict = Depends(active_user),
                        db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "candidate")
        db.execute("DELETE FROM candidate_favorites WHERE candidate_id=? AND vacancy_id=?", (user["id"], job_id))
        # Commit before the HTTP response: a new dashboard request may arrive immediately.
        db.commit()
        return {"ok": True}

    @app.post("/api/candidate/applications", status_code=201)
    def apply(data: ApplicationIn, user: dict = Depends(active_user),
              db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "candidate")
        profile = candidate_view(db, user["id"])
        if profile is None or not profile["profession"] or not profile["city"]:
            raise HTTPException(422, "Сначала заполните профессию и город в профиле")
        job = db.execute(
            """SELECT v.id,v.employer_id,v.title,v.status,
                      COALESCE(vm.status,'approved') AS moderation_status,
                      COALESCE(c.status,'active') AS employer_status
               FROM vacancies v
               LEFT JOIN vacancy_moderation vm ON vm.vacancy_id=v.id
               LEFT JOIN account_controls c ON c.user_id=v.employer_id
               WHERE v.id=?""",
            (data.vacancy_id,),
        ).fetchone()
        if (job is None or job["status"] != "open" or
                job["moderation_status"] != "approved" or job["employer_status"] != "active"):
            raise HTTPException(404, "Вакансия закрыта, скрыта или не найдена")
        previous = db.execute(
            "SELECT id,status FROM job_applications WHERE vacancy_id=? AND candidate_id=?",
            (data.vacancy_id, user["id"]),
        ).fetchone()
        if previous is None:
            try:
                cursor = db.execute(
                    "INSERT INTO job_applications(vacancy_id,candidate_id) VALUES(?,?)",
                    (data.vacancy_id, user["id"]),
                )
            except sqlite3.IntegrityError:
                raise HTTPException(409, "Вы уже откликались на эту вакансию") from None
            application_id, event = cursor.lastrowid, "applied"
        elif previous["status"] == "withdrawn":
            # Restore the same application ID: unique pair prevents duplicates.
            # The previous withdrawal is retained in the events timeline.
            db.execute(
                """UPDATE job_applications SET status='applied',updated_at=datetime('now')
                   WHERE id=? AND candidate_id=? AND status='withdrawn'""",
                (previous["id"], user["id"]),
            )
            application_id, event = previous["id"], "reapplied"
        else:
            raise HTTPException(409, "Активный или завершённый отклик на эту вакансию уже существует")
        db.execute(
            "INSERT INTO application_events(application_id,event) VALUES(?,?)",
            (application_id, event),
        )
        enqueue_notice(db, job["employer_id"], "new_application", "Новый отклик — СТАЖНО",
                       f"Получен обезличенный отклик на вакансию «{job['title']}». Откройте кабинет.")
        # Commit before the HTTP response: a new dashboard request may arrive immediately.
        db.commit()
        return {"ok": True, "id": application_id, "status": "applied", "reapplied": event == "reapplied"}

    @app.get("/api/candidate/applications")
    def candidate_applications(user: dict = Depends(active_user),
                               db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "candidate")
        rows = db.execute("""SELECT a.id,a.vacancy_id,a.status,a.created_at,a.updated_at,
                             v.title,v.city,v.salary_min,v.salary_max,v.schedule,v.employment,
                             e.company_name,i.id AS invitation_id,i.status AS invitation_status,
                             i.contact_shared AS contact_shared
                             FROM job_applications a
                             JOIN vacancies v ON v.id=a.vacancy_id
                             JOIN employer_profiles e ON e.user_id=v.employer_id
                             LEFT JOIN invitations i ON i.vacancy_id=a.vacancy_id AND i.candidate_id=a.candidate_id
                             WHERE a.candidate_id=? ORDER BY a.id DESC""", (user["id"],)).fetchall()
        applications = []
        for row in rows:
            data = dict(row)
            data["timeline"] = interaction_timeline(db, row["id"], row["invitation_id"])
            data["introduction_stage"] = introduction_stage(row["invitation_status"], row["contact_shared"])
            applications.append(data)
        return {"applications": applications}

    @app.post("/api/candidate/applications/{application_id}/withdraw")
    def withdraw(application_id: int, user: dict = Depends(active_user),
                 db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "candidate")
        item = db.execute("""SELECT a.*,v.employer_id,v.title FROM job_applications a
                             JOIN vacancies v ON v.id=a.vacancy_id
                             WHERE a.id=? AND a.candidate_id=?""", (application_id, user["id"])).fetchone()
        if item is None:
            raise HTTPException(404, "Отклик не найден")
        if item["status"] not in {"applied", "reviewing", "interview"}:
            raise HTTPException(409, "Этот отклик уже нельзя отозвать")
        invitation = db.execute(
            "SELECT status,contact_shared FROM invitations WHERE vacancy_id=? AND candidate_id=?",
            (item["vacancy_id"], user["id"]),
        ).fetchone()
        if invitation and (invitation["status"] in {"sent", "accepted"} or invitation["contact_shared"]):
            raise HTTPException(409, "Сначала завершите или отклоните запрос на знакомство")
        db.execute("UPDATE job_applications SET status='withdrawn',updated_at=datetime('now') WHERE id=?",
                   (application_id,))
        db.execute("INSERT INTO application_events(application_id,event) VALUES(?,?)",
                   (application_id, "withdrawn"))
        enqueue_notice(db, item["employer_id"], "application_withdrawn", "Отклик отозван — СТАЖНО",
                       f"Отклик на вакансию «{item['title']}» отозван.")
        # Commit before the HTTP response: a new dashboard request may arrive immediately.
        db.commit()
        return {"ok": True}

    @app.get("/api/employer/applications")
    def employer_applications(vacancy_id: int | None = None, user: dict = Depends(active_user),
                              db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "employer")
        params = [user["id"]]
        sql = """SELECT a.id,a.vacancy_id,a.status,a.created_at,a.updated_at,v.title,
                 c.profession,c.city,c.skills,c.salary_min AS expected_salary,
                 i.id AS invitation_id,i.status AS invitation_status,i.contact_shared AS contact_shared
                 FROM job_applications a
                 JOIN vacancies v ON v.id=a.vacancy_id
                 JOIN candidate_profiles c ON c.user_id=a.candidate_id
                 LEFT JOIN invitations i ON i.vacancy_id=a.vacancy_id AND i.candidate_id=a.candidate_id
                 WHERE v.employer_id=?"""
        if vacancy_id is not None:
            sql += " AND a.vacancy_id=?"
            params.append(vacancy_id)
        sql += " ORDER BY a.id DESC LIMIT 300"
        rows = db.execute(sql, params).fetchall()
        applications = []
        for row in rows:
            item = dict(row)
            item["introduction_stage"] = introduction_stage(row["invitation_status"], row["contact_shared"])
            item["timeline"] = interaction_timeline(db, row["id"], row["invitation_id"])
            applications.append(item)
        return {"applications": applications}

    @app.post("/api/employer/applications/{application_id}/interest")
    def interested_in_application(
        application_id: int,
        user: dict = Depends(active_user),
        db: sqlite3.Connection = Depends(get_connection),
    ):
        """One-click employer interest; invitation is reused, contacts stay private.

        A candidate's application is not consent to share their contact information.
        Each unique vacancy/candidate pair gets at most one introduction request.
        """
        allowed(user, "employer")
        item = db.execute(
            """SELECT a.id,a.vacancy_id,a.candidate_id,a.status,
                      v.title,v.status AS vacancy_status,
                      COALESCE(vm.status,'approved') AS moderation_status
               FROM job_applications a
               JOIN vacancies v ON v.id=a.vacancy_id
               LEFT JOIN vacancy_moderation vm ON vm.vacancy_id=v.id
               WHERE a.id=? AND v.employer_id=?""",
            (application_id, user["id"]),
        ).fetchone()
        if item is None:
            raise HTTPException(404, "Отклик не найден")
        if item["vacancy_status"] != "open":
            raise HTTPException(409, "Вакансия закрыта")
        if item["moderation_status"] != "approved":
            raise HTTPException(409, "Вакансия ожидает проверки. Новые знакомства временно недоступны")
        if item["status"] in {"withdrawn", "rejected", "hired"}:
            raise HTTPException(409, "Обработка этого отклика завершена")
        # Never generate a contact-sharing flow for a disabled candidate.
        control = db.execute(
            "SELECT status FROM account_controls WHERE user_id=?", (item["candidate_id"],)
        ).fetchone()
        if control is not None and control["status"] == "disabled":
            raise HTTPException(409, "Профиль кандидата временно недоступен")

        invite = db.execute(
            "SELECT id,status,contact_shared FROM invitations WHERE vacancy_id=? AND candidate_id=?",
            (item["vacancy_id"], item["candidate_id"]),
        ).fetchone()
        if invite is None:
            from .matching import lead_price
            db.execute(
                """INSERT OR IGNORE INTO invitations(vacancy_id,candidate_id,employer_id,price_rub)
                   VALUES(?,?,?,?)""",
                (item["vacancy_id"], item["candidate_id"], user["id"], lead_price(item["title"])),
            )
            invite = db.execute(
                "SELECT id,status,contact_shared FROM invitations WHERE vacancy_id=? AND candidate_id=?",
                (item["vacancy_id"], item["candidate_id"]),
            ).fetchone()
            # Only the request that won the unique constraint sends a message.
            # Reaching this state without an invitation cannot happen with a valid database.
            if invite is None:
                raise HTTPException(409, "Не удалось создать запрос на знакомство")
            # The id is stable; a previously created row must not be re-notified.
            created = db.execute(
                "SELECT changes()"
            ).fetchone()[0] == 1
            if created:
                enqueue_notice(
                    db, item["candidate_id"], "invitation",
                    "Работодатель заинтересован — СТАЖНО",
                    f"По вашему отклику на «{item['title']}» поступил запрос на знакомство. "
                    "Контакты будут переданы только после отдельного согласия.",
                )
        else:
            created = False

        if item["status"] != "interview":
            db.execute(
                """UPDATE job_applications SET status='interview',updated_at=datetime('now')
                   WHERE id=?""",
                (application_id,),
            )
            db.execute(
                "INSERT INTO application_events(application_id,event) VALUES(?,?)",
                (application_id, "interview"),
            )
            enqueue_notice(
                db, item["candidate_id"], "application_status",
                "Статус отклика — СТАЖНО",
                f"Работодатель заинтересовался откликом на «{item['title']}». Откройте кабинет.",
            )
        # Commit before the HTTP response: a new dashboard request may arrive immediately.
        db.commit()
        return {
            "ok": True,
            "application_status": "interview",
            "invitation_id": invite["id"],
            "invitation_status": invite["status"],
            "contact_shared": bool(invite["contact_shared"]),
            "created": created,
        }

    @app.patch("/api/employer/applications/{application_id}/status")
    def update_application(application_id: int, body: ApplicationStatusIn,
                           user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "employer")
        item = db.execute("""SELECT a.*,v.title FROM job_applications a JOIN vacancies v ON v.id=a.vacancy_id
                             WHERE a.id=? AND v.employer_id=?""", (application_id, user["id"])).fetchone()
        if item is None:
            raise HTTPException(404, "Отклик не найден")
        if item["status"] in {"withdrawn", "hired", "rejected"}:
            raise HTTPException(409, "Статус этого отклика уже окончательный")
        invite = db.execute(
            "SELECT status,contact_shared FROM invitations WHERE vacancy_id=? AND candidate_id=?",
            (item["vacancy_id"], item["candidate_id"]),
        ).fetchone()
        if invite and (invite["status"] in ("sent", "accepted") or invite["contact_shared"]):
            # Once an introduction has begun, application review cannot
            # contradict consent. A hire may be recorded after contact unlock.
            if not (body.status == "hired" and invite["contact_shared"]):
                raise HTTPException(409, "Знакомство уже началось. Измените его через раздел приглашений")
        if item["status"] == body.status:
            return {"ok": True, "status": body.status}
        db.execute("UPDATE job_applications SET status=?,updated_at=datetime('now') WHERE id=?",
                   (body.status, application_id))
        db.execute("INSERT INTO application_events(application_id,event) VALUES(?,?)",
                   (application_id, body.status))
        enqueue_notice(db, item["candidate_id"], "application_status", "Статус отклика — СТАЖНО",
                       f"Статус отклика на «{item['title']}» изменён на {body.status}. Откройте кабинет.")
        # Commit before the HTTP response: a new dashboard request may arrive immediately.
        db.commit()
        return {"ok": True, "status": body.status}

    @app.get("/api/account/security")
    def account_security(user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        now_iso = datetime.now(timezone.utc).isoformat()
        current_digest = user.get("_session_token_hash", "")
        session_rows = db.execute(
            """SELECT s.token_hash,s.expires_at,a.authenticated_at,a.last_seen_at,
                      COALESCE(c.device_label,'Неизвестное устройство') AS device_label
               FROM sessions s
               LEFT JOIN session_activity a ON a.token_hash=s.token_hash
               LEFT JOIN session_context c ON c.token_hash=s.token_hash
               WHERE s.user_id=? AND s.expires_at>?
               ORDER BY COALESCE(a.last_seen_at,a.authenticated_at,s.expires_at) DESC""",
            (user["id"], now_iso),
        ).fetchall()
        sessions = []
        for row in session_rows:
            token_hash_value = str(row["token_hash"])
            public_id = hashlib.sha256(
                ("session-public-id:" + token_hash_value).encode("utf-8")
            ).hexdigest()[:24]
            sessions.append({
                "id": public_id,
                "current": hmac.compare_digest(token_hash_value, current_digest),
                "authenticated_at": row["authenticated_at"],
                "last_seen_at": row["last_seen_at"],
                "expires_at": row["expires_at"],
                "device_label": row["device_label"],
            })
        email_row = db.execute(
            "SELECT email_verified FROM account_controls WHERE user_id=?",
            (user["id"],),
        ).fetchone()
        events = db.execute(
            """SELECT event_type,detail,created_at
               FROM security_events
               WHERE user_id=?
               ORDER BY created_at DESC
               LIMIT 20""",
            (user["id"],),
        ).fetchall()
        passkeys = []
        if user["role"] == "admin":
            rows = db.execute(
                """SELECT credential_id,label,credential_device_type,backed_up,created_at,last_used_at
                   FROM admin_webauthn_credentials
                   WHERE user_id=?
                   ORDER BY created_at DESC""",
                (user["id"],),
            ).fetchall()
            for row in rows:
                public_id = hashlib.sha256(
                    ("webauthn-public-id:" + str(row["credential_id"])).encode("utf-8")
                ).hexdigest()[:24]
                passkeys.append({
                    "id": public_id,
                    "label": row["label"],
                    "device_type": row["credential_device_type"],
                    "backed_up": bool(row["backed_up"]),
                    "created_at": row["created_at"],
                    "last_used_at": row["last_used_at"],
                })
        return {
            "active_sessions": len(sessions),
            "sessions": sessions,
            "email_verified": bool(email_row and email_row["email_verified"]),
            "events": [dict(row) for row in events],
            "password_min_length": 15,
            "passkeys": passkeys,
        }

    @app.delete("/api/account/sessions/{session_id}")
    def revoke_session(
        session_id: str,
        user: dict = Depends(active_user),
        db: sqlite3.Connection = Depends(get_connection),
    ):
        if not re.fullmatch(r"[0-9a-f]{24}", session_id):
            raise HTTPException(404, "Сессия не найдена")
        current_digest = user.get("_session_token_hash")
        rows = db.execute(
            "SELECT token_hash FROM sessions WHERE user_id=?",
            (user["id"],),
        ).fetchall()
        target_digest = None
        for row in rows:
            candidate = str(row["token_hash"])
            public_id = hashlib.sha256(
                ("session-public-id:" + candidate).encode("utf-8")
            ).hexdigest()[:24]
            if hmac.compare_digest(public_id, session_id):
                target_digest = candidate
                break
        if target_digest is None:
            raise HTTPException(404, "Сессия не найдена")
        if current_digest and hmac.compare_digest(target_digest, current_digest):
            raise HTTPException(409, "Текущую сессию завершайте кнопкой «Выйти»")
        result = db.execute(
            "DELETE FROM sessions WHERE user_id=? AND token_hash=?",
            (user["id"], target_digest),
        )
        revoked = max(int(result.rowcount or 0), 0)
        if not revoked:
            raise HTTPException(404, "Сессия уже завершена")
        record_security_event(
            db, user["id"], "single_session_revoked", "session_id=" + session_id
        )
        db.commit()
        return {"ok": True, "revoked": 1}

    @app.post("/api/account/sessions/revoke-others")
    def revoke_other_sessions(
        user: dict = Depends(active_user),
        db: sqlite3.Connection = Depends(get_connection),
    ):
        current_digest = user.get("_session_token_hash")
        if not current_digest:
            raise HTTPException(401, "Текущая сессия не определена")
        result = db.execute(
            "DELETE FROM sessions WHERE user_id=? AND token_hash<>?",
            (user["id"], current_digest),
        )
        revoked = max(int(result.rowcount or 0), 0)
        record_security_event(
            db, user["id"], "other_sessions_revoked", f"count={revoked}"
        )
        db.commit()
        return {"ok": True, "revoked": revoked}

    @app.post("/api/account/password/change")
    def change_password(
        data: PasswordChangeIn,
        request: Request,
        response: Response,
        user: dict = Depends(active_user),
        db: sqlite3.Connection = Depends(get_connection),
    ):
        subject = str(user["id"])
        allowed_attempt, retry_after = consume_security_rate_limit(
            db, "password_change", subject, 5, 900
        )
        if not allowed_attempt:
            db.commit()
            raise HTTPException(
                429,
                "Слишком много попыток. Повторите позже",
                headers={"Retry-After": str(retry_after)},
            )
        row = db.execute(
            "SELECT password_hash FROM users WHERE id=?",
            (user["id"],),
        ).fetchone()
        if row is None or not verify_password(data.current_password, row["password_hash"]):
            record_security_event(db, user["id"], "password_change_failed")
            db.commit()
            raise HTTPException(401, "Текущий пароль указан неверно")
        if verify_password(data.new_password, row["password_hash"]):
            db.commit()
            raise HTTPException(422, "Новый пароль должен отличаться от текущего")

        db.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (make_password_hash(data.new_password), user["id"]),
        )
        db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
        clear_security_rate_limit(db, "password_change", subject, 900)
        record_security_event(db, user["id"], "password_changed_all_sessions_revoked")
        enqueue_notice(
            db,
            user["id"],
            "security_password_changed",
            "СТАЖНО — пароль изменён",
            (
                "Пароль вашей учётной записи СТАЖНО был изменён.\n\n"
                "Все ранее активные сессии были завершены.\n\n"
                "Если это были не вы, немедленно восстановите пароль через страницу входа "
                "и проверьте активные сессии в разделе «Безопасность»."
            ),
        )
        # add_session commits the password update/audit event and rotates the
        # browser to a fresh opaque session token.
        add_session(db, response, user["id"], request)
        return {"ok": True}

    @app.get("/api/account/email/status")
    def email_status(user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        row = db.execute("SELECT email_verified FROM account_controls WHERE user_id=?",
                         (user["id"],)).fetchone()
        return {"email_verified": bool(row and row["email_verified"]), "delivery": delivery_mode()}

    @app.post("/api/account/email/request")
    def request_verification(user: dict = Depends(active_user),
                             db: sqlite3.Connection = Depends(get_connection)):
        issue_email_token(db, user["id"], "verify")
        # Commit before the HTTP response: a new dashboard request may arrive immediately.
        db.commit()
        return {"ok": True, "delivery": delivery_mode()}

    @app.post("/api/account/email/confirm")
    def confirm_email(data: EmailTokenIn, db: sqlite3.Connection = Depends(get_connection)):
        row = redeem_token(db, data.token, "verify")
        db.execute("""INSERT INTO account_controls(user_id,email_verified) VALUES(?,1)
                      ON CONFLICT(user_id) DO UPDATE SET email_verified=1""", (row["user_id"],))
        # Commit before the HTTP response: a new dashboard request may arrive immediately.
        db.commit()
        return {"ok": True}

    @app.post("/api/account/password/request")
    def request_reset(data: PasswordRequestIn, db: sqlite3.Connection = Depends(get_connection)):
        row = db.execute("SELECT id FROM users WHERE email=?", (data.email.strip().casefold(),)).fetchone()
        if row:
            issue_email_token(db, row["id"], "reset")
        # Commit before the HTTP response: a new dashboard request may arrive immediately.
        db.commit()
        return {"ok": True, "delivery": delivery_mode()}

    @app.post("/api/account/password/reset")
    def reset_password(data: PasswordResetIn, db: sqlite3.Connection = Depends(get_connection)):
        row = redeem_token(db, data.token, "reset")
        db.execute("UPDATE users SET password_hash=? WHERE id=?",
                   (make_password_hash(data.password), row["user_id"]))
        db.execute(
            """INSERT INTO account_controls(user_id,email_verified) VALUES(?,1)
               ON CONFLICT(user_id) DO UPDATE SET email_verified=1""",
            (row["user_id"],),
        )
        db.execute("DELETE FROM sessions WHERE user_id=?", (row["user_id"],))
        record_security_event(db, row["user_id"], "password_reset_completed")
        record_security_event(db, row["user_id"], "email_verified_via_password_reset")
        enqueue_notice(
            db,
            row["user_id"],
            "security_password_reset",
            "СТАЖНО — пароль восстановлен",
            (
                "Пароль вашей учётной записи СТАЖНО был восстановлен по одноразовой ссылке.\n\n"
                "Все ранее активные сессии завершены.\n\n"
                "Если это были не вы, снова восстановите пароль через страницу входа "
                "и обратитесь к администратору платформы."
            ),
        )
        # Commit before the HTTP response: a new dashboard request may arrive immediately.
        db.commit()
        return {"ok": True}

    @app.get("/api/admin/users")
    def admin_users(user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "admin")
        rows = db.execute("""SELECT u.id,u.name,u.email,u.role,u.created_at,
                             COALESCE(c.status,'active') AS status,
                             COALESCE(c.email_verified,0) AS email_verified,
                             e.company_name,e.inn,COALESCE(e.verified,0) AS employer_verified
                             FROM users u
                             LEFT JOIN account_controls c ON c.user_id=u.id
                             LEFT JOIN employer_profiles e ON e.user_id=u.id
                             ORDER BY u.id DESC LIMIT 300""").fetchall()
        return {"users": [dict(r) for r in rows]}

    @app.patch("/api/admin/users/{user_id}/status")
    def admin_user_status(user_id: int, data: AccountStatusIn, user: dict = Depends(active_user),
                          db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "admin")
        target = db.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
        if target is None:
            raise HTTPException(404, "Пользователь не найден")
        if target["role"] == "admin" or user_id == user["id"]:
            raise HTTPException(403, "Нельзя менять статус администратора")
        db.execute("""INSERT INTO account_controls(user_id,status) VALUES(?,?)
                      ON CONFLICT(user_id) DO UPDATE SET status=excluded.status""", (user_id, data.status))
        if data.status == "disabled":
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        db.execute("INSERT INTO admin_audit(admin_id,action,target_id) VALUES(?,?,?)",
                   (user["id"], "user_" + data.status, user_id))
        # Commit before the HTTP response: a new dashboard request may arrive immediately.
        db.commit()
        return {"ok": True}

    @app.get("/api/admin/vacancies")
    def admin_vacancies(user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "admin")
        rows = db.execute(
            """SELECT v.id,v.employer_id,v.title,v.city,v.status,v.created_at,e.company_name,
                      COALESCE(vm.status,'approved') AS moderation_status,
                      COALESCE(vm.reason,'') AS moderation_reason,
                      COALESCE((
                        SELECT COUNT(*) FROM content_reports r
                        WHERE r.vacancy_id=v.id AND r.status IN ('new','reviewed')
                      ),0) AS active_reports
               FROM vacancies v
               JOIN employer_profiles e ON e.user_id=v.employer_id
               LEFT JOIN vacancy_moderation vm ON vm.vacancy_id=v.id
               ORDER BY CASE COALESCE(vm.status,'approved') WHEN 'pending' THEN 0 WHEN 'rejected' THEN 1 ELSE 2 END,
                        v.id DESC LIMIT 300"""
        ).fetchall()
        return {"jobs": [dict(r) for r in rows]}

    @app.patch("/api/admin/vacancies/{job_id}/status")
    def admin_vacancy_status(job_id: int, data: VacancyAdminStatusIn,
                             user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "admin")
        changed = db.execute("UPDATE vacancies SET status=? WHERE id=?", (data.status, job_id))
        if not changed.rowcount:
            raise HTTPException(404, "Вакансия не найдена")
        db.execute("INSERT INTO admin_audit(admin_id,action,target_id) VALUES(?,?,?)",
                   (user["id"], "vacancy_" + data.status, job_id))
        # Commit before the HTTP response: a new dashboard request may arrive immediately.
        db.commit()
        return {"ok": True}

    @app.patch("/api/admin/vacancies/{job_id}/moderation")
    def admin_vacancy_moderation(
        job_id: int,
        data: VacancyModerationIn,
        user: dict = Depends(active_user),
        db: sqlite3.Connection = Depends(get_connection),
    ):
        allowed(user, "admin")
        if data.status == "rejected" and not data.reason.strip():
            raise HTTPException(422, "Укажите причину отклонения вакансии")
        if db.execute("SELECT 1 FROM vacancies WHERE id=?", (job_id,)).fetchone() is None:
            raise HTTPException(404, "Вакансия не найдена")
        now = utc_now_text()
        db.execute(
            """INSERT INTO vacancy_moderation(vacancy_id,status,reason,reviewed_by,reviewed_at,updated_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(vacancy_id) DO UPDATE SET
                 status=excluded.status,reason=excluded.reason,reviewed_by=excluded.reviewed_by,
                 reviewed_at=excluded.reviewed_at,updated_at=excluded.updated_at""",
            (job_id, data.status, data.reason.strip(), user["id"], now, now),
        )
        db.execute(
            "INSERT INTO admin_audit(admin_id,action,target_id) VALUES(?,?,?)",
            (user["id"], "vacancy_moderation_" + data.status, job_id),
        )
        db.commit()
        return {"ok": True, "status": data.status}

    @app.get("/api/admin/reports")
    def admin_reports(user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "admin")
        rows = db.execute(
            """SELECT r.report_key,r.vacancy_id,r.employer_id,r.target_type,r.reason,r.details,
                      r.status,r.created_at,r.reviewed_at,v.title,e.company_name
               FROM content_reports r
               JOIN vacancies v ON v.id=r.vacancy_id
               JOIN employer_profiles e ON e.user_id=r.employer_id
               ORDER BY CASE r.status WHEN 'new' THEN 0 WHEN 'reviewed' THEN 1 ELSE 2 END,
                        r.created_at DESC LIMIT 300"""
        ).fetchall()
        return {"reports": [dict(row) for row in rows]}

    @app.patch("/api/admin/reports/{report_key}/status")
    def admin_report_status(
        report_key: str,
        data: ContentReportStatusIn,
        user: dict = Depends(active_user),
        db: sqlite3.Connection = Depends(get_connection),
    ):
        allowed(user, "admin")
        report = db.execute(
            "SELECT vacancy_id FROM content_reports WHERE report_key=?",
            (report_key,),
        ).fetchone()
        if report is None:
            raise HTTPException(404, "Жалоба не найдена")
        db.execute(
            """UPDATE content_reports SET status=?,reviewed_at=?,reviewed_by=?
               WHERE report_key=?""",
            (data.status, utc_now_text(), user["id"], report_key),
        )
        db.execute(
            "INSERT INTO admin_audit(admin_id,action,target_id) VALUES(?,?,?)",
            (user["id"], "report_" + data.status, report["vacancy_id"]),
        )
        db.commit()
        return {"ok": True}

    @app.get("/api/admin/taxonomy")
    def admin_taxonomy(user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "admin")
        refresh_taxonomy_observations(db)
        db.commit()
        rows = db.execute(
            """SELECT term_key,kind,display_value,candidate_seen,vacancy_seen,status,updated_at
               FROM taxonomy_observations
               ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END,
                        (candidate_seen + vacancy_seen) DESC, display_value ASC
               LIMIT 500"""
        ).fetchall()
        return {
            "terms": [dict(row) for row in rows],
            "summary": {
                "pending": sum(1 for row in rows if row["status"] == "pending"),
                "approved": sum(1 for row in rows if row["status"] == "approved"),
                "rejected": sum(1 for row in rows if row["status"] == "rejected"),
            },
        }

    @app.patch("/api/admin/taxonomy/{term_key}")
    def admin_taxonomy_status(
        term_key: str,
        data: TaxonomyObservationStatusIn,
        user: dict = Depends(active_user),
        db: sqlite3.Connection = Depends(get_connection),
    ):
        allowed(user, "admin")
        row = db.execute(
            "SELECT term_key FROM taxonomy_observations WHERE term_key=?",
            (term_key,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Термин не найден")
        db.execute(
            """UPDATE taxonomy_observations
               SET status=?,reviewed_by=?,reviewed_at=?,updated_at=?
               WHERE term_key=?""",
            (data.status, user["id"], utc_now_text(), utc_now_text(), term_key),
        )
        db.commit()
        return {"ok": True, "status": data.status}

    @app.get("/api/admin/security-events")
    def admin_security_events(
        user: dict = Depends(active_user),
        db: sqlite3.Connection = Depends(get_connection),
    ):
        allowed(user, "admin")
        rows = db.execute(
            """SELECT s.event_key,s.user_id,s.event_type,s.detail,s.created_at,
                      COALESCE(u.email,'') AS user_email
               FROM security_events s
               LEFT JOIN users u ON u.id=s.user_id
               ORDER BY s.created_at DESC LIMIT 300"""
        ).fetchall()
        return {"events": [dict(row) for row in rows]}

    @app.get("/api/admin/mail-preview")
    def admin_demo_mail(user: dict = Depends(active_user),
                        db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "admin")
        # Never return reset/verification secrets to the public demo admin.
        rows = db.execute("""SELECT id,event,subject,created_at FROM email_outbox
                             ORDER BY id DESC LIMIT 50""").fetchall()
        return {"delivery": delivery_mode(), "messages": [dict(r) for r in rows]}
