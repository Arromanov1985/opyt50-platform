"""СТАЖНО: self-service hiring with confirmed candidate introductions.

No paid services, real payments, or automated age-based screening in this release.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import secrets
import re
import sqlite3
import time

import pyotp
from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.exceptions import (
    InvalidAuthenticationResponse,
    InvalidRegistrationResponse,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field, field_validator, model_validator

from .db import database, init_db
from .matching import lead_price, match_candidate, taxonomy_payload
from .security import (
    ADMIN_SESSION_IDLE_SECONDS, ADMIN_SESSION_SECONDS, COOKIE_NAME,
    SESSION_SECONDS, SESSION_TOUCH_SECONDS, USER_SESSION_IDLE_SECONDS,
    issue_session, make_password_hash, password_needs_rehash, token_hash, verify_password,
)

BASE = Path(__file__).resolve().parent
DEFAULT_DB = os.getenv("OPYT50_DB_PATH", str(BASE.parent / "data" / "opyt50.db"))
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
CONTACT_EMAIL_PATTERN = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+", re.IGNORECASE)
CONTACT_PHONE_PATTERN = re.compile(
    r"(?<!\d)(?:\+7|8)[\s\-]*(?:\(?\d{3}\)?)[\s\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)"
)
SCHEDULES = {"Любой", "Полный день", "Сменный", "Гибкий", "Удалённо"}
EMPLOYMENTS = {"Любая", "Полная", "Частичная", "Проектная"}


class Registration(BaseModel):
    role: Literal["candidate", "employer"]
    name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=15, max_length=128)
    phone: str = Field(default="", max_length=30)
    company_name: str = Field(default="", max_length=120)

    @field_validator("email")
    @classmethod
    def clean_email(cls, value: str) -> str:
        value = value.strip().casefold()
        if not EMAIL_PATTERN.fullmatch(value):
            raise ValueError("Укажите корректный email")
        return value

    @model_validator(mode="after")
    def check_company(self):
        if self.role == "employer" and not self.company_name.strip():
            raise ValueError("Введите название компании")
        return self


class Login(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class AdminMfaVerify(BaseModel):
    challenge_id: str = Field(min_length=20, max_length=160)
    code: str = Field(pattern=r"^\d{6,8}$")


class AdminWebAuthnRegistrationVerify(BaseModel):
    challenge_id: str = Field(min_length=20, max_length=160)
    credential: dict[str, Any]
    label: str = Field(default="Passkey администратора", min_length=2, max_length=80)


class AdminWebAuthnAuthenticationVerify(BaseModel):
    challenge_id: str = Field(min_length=20, max_length=160)
    credential: dict[str, Any]


class AdminWebAuthnFallback(BaseModel):
    challenge_id: str = Field(min_length=20, max_length=160)


class CandidateProfile(BaseModel):
    profession: str = Field(min_length=2, max_length=120)
    city: str = Field(min_length=2, max_length=100)
    skills: str = Field(default="", max_length=300)
    salary_min: int = Field(ge=0, le=10_000_000)
    schedule: str = "Любой"
    employment: str = "Любая"
    about: str = Field(default="", max_length=700)
    is_active: bool = True
    phone: str = Field(default="", max_length=30)

    @model_validator(mode="after")
    def check_options(self):
        if self.schedule not in SCHEDULES or self.employment not in EMPLOYMENTS:
            raise ValueError("Недопустимый график или формат занятости")
        return self


class VacancyIn(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    city: str = Field(min_length=2, max_length=100)
    salary_min: int = Field(ge=0, le=10_000_000)
    salary_max: int = Field(ge=0, le=10_000_000)
    schedule: str = "Любой"
    employment: str = "Любая"
    skills: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=1200)

    @model_validator(mode="after")
    def check_fields(self):
        if self.salary_max < self.salary_min:
            raise ValueError("Максимальная зарплата должна быть не меньше минимальной")
        if self.schedule not in SCHEDULES or self.employment not in EMPLOYMENTS:
            raise ValueError("Недопустимый график или формат занятости")
        public_text = "\n".join((self.skills, self.description))
        if CONTACT_EMAIL_PATTERN.search(public_text) or CONTACT_PHONE_PATTERN.search(public_text):
            raise ValueError(
                "Не указывайте телефон или email в вакансии. Контакты открываются только через защищённое знакомство"
            )
        return self


class VacancyEdit(VacancyIn):
    """Full replacement of vacancy content, never a new vacancy or a status change."""

    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def require_meaningful_text(self):
        if len(self.title.strip()) < 3 or len(self.city.strip()) < 2:
            raise ValueError("Укажите должность и город, не состоящие из пробелов")
        return self


VACANCY_CONTENT_FIELDS = (
    "title", "city", "salary_min", "salary_max", "schedule",
    "employment", "skills", "description",
)
VACANCY_REVISION_FIELDS = ("id", "employer_id", *VACANCY_CONTENT_FIELDS, "status")


def vacancy_revision(row: sqlite3.Row | dict) -> str:
    """Version token for optimistic edits; no migration or extra database column."""
    current = {key: row[key] for key in VACANCY_REVISION_FIELDS}
    data = json.dumps(current, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class InvitationIn(BaseModel):
    vacancy_id: int = Field(gt=0)
    candidate_id: int = Field(gt=0)


class InvitationReply(BaseModel):
    decision: Literal["accepted", "declined"]
    share_consent: bool = False


class VacancyStatus(BaseModel):
    status: Literal["open", "closed"]


def utc_expiry(seconds: int = SESSION_SECONDS) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def production_runtime() -> bool:
    explicit = os.getenv("OPYT50_ENV", "").strip().casefold()
    public_url = os.getenv("OPYT50_PUBLIC_URL", "").strip().casefold()
    return explicit in {"prod", "production"} or public_url.startswith("https://") or bool(os.getenv("DATABASE_URL", "").strip())


def admin_mfa_mode() -> str:
    mode = os.getenv("OPYT50_ADMIN_MFA_MODE", "off").strip().casefold()
    return mode if mode in {"off", "email", "totp", "hybrid"} else "off"


def security_profile() -> str:
    profile = os.getenv("OPYT50_SECURITY_PROFILE", "standard").strip().casefold()
    return profile if profile in {"standard", "high"} else "standard"


def secure_cookie_enabled() -> bool:
    explicit = os.getenv("OPYT50_COOKIE_SECURE")
    if explicit is not None:
        return explicit == "1"
    return production_runtime()


def session_cookie_name() -> str:
    return "__Host-stazhno_session" if secure_cookie_enabled() else COOKIE_NAME


def _bytes_to_base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _webauthn_context(request: Request) -> tuple[str, str]:
    configured = os.getenv("OPYT50_PUBLIC_URL", "").strip()
    parsed = urlsplit(configured or str(request.base_url))
    if not parsed.scheme or not parsed.netloc or not parsed.hostname:
        raise HTTPException(500, "Не настроен публичный адрес для passkey")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return origin, parsed.hostname


def _store_admin_webauthn_challenge(
    db: sqlite3.Connection,
    user_id: int,
    kind: str,
    challenge: bytes,
    rp_id: str,
    origin: str,
) -> str:
    challenge_key = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    db.execute(
        """INSERT INTO admin_webauthn_challenges(
               challenge_key,user_id,kind,challenge_b64,rp_id,origin,
               expires_at,attempts,used_at,created_at
           ) VALUES(?,?,?,?,?,?,?,0,NULL,?)""",
        (
            challenge_key,
            user_id,
            kind,
            _bytes_to_base64url(challenge),
            rp_id,
            origin,
            (now + timedelta(minutes=5)).isoformat(),
            now.isoformat(),
        ),
    )
    db.execute(
        "DELETE FROM admin_webauthn_challenges WHERE expires_at<?",
        ((now - timedelta(days=1)).isoformat(),),
    )
    return challenge_key


def issue_admin_webauthn_authentication(
    db: sqlite3.Connection,
    user_id: int,
    request: Request,
) -> tuple[str, dict[str, Any]] | None:
    rows = db.execute(
        """SELECT credential_id
           FROM admin_webauthn_credentials
           WHERE user_id=?
           ORDER BY created_at""",
        (user_id,),
    ).fetchall()
    if not rows:
        return None
    origin, rp_id = _webauthn_context(request)
    options = generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(str(row["credential_id"])))
            for row in rows
        ],
        user_verification=UserVerificationRequirement.REQUIRED,
        timeout=120_000,
    )
    challenge_key = _store_admin_webauthn_challenge(
        db, user_id, "authentication", options.challenge, rp_id, origin
    )
    return challenge_key, json.loads(options_to_json(options))


DUMMY_PASSWORD_HASH = make_password_hash("dummy-authentication-verifier-not-a-user-password")


def _rate_limit_key(scope: str, subject: str, bucket_start: int) -> str:
    payload = f"{scope}\0{subject}\0{bucket_start}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _rate_limit_subject(*parts: str) -> str:
    payload = "\0".join(str(part or "") for part in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _rate_limit_state(
    db: sqlite3.Connection,
    scope: str,
    subject: str,
    window_seconds: int,
) -> tuple[str, int, int]:
    now_epoch = int(time.time())
    bucket_start = now_epoch - (now_epoch % window_seconds)
    return _rate_limit_key(scope, subject, bucket_start), bucket_start, now_epoch


def consume_security_rate_limit(
    db: sqlite3.Connection,
    scope: str,
    subject: str,
    limit: int,
    window_seconds: int,
) -> tuple[bool, int]:
    key, bucket_start, now_epoch = _rate_limit_state(db, scope, subject, window_seconds)
    now_iso = datetime.now(timezone.utc).isoformat()
    db.execute(
        """INSERT INTO security_rate_limits(rate_key,bucket_start,count,updated_at)
           VALUES(?,?,1,?)
           ON CONFLICT(rate_key) DO UPDATE SET
             count=security_rate_limits.count+1,
             updated_at=excluded.updated_at""",
        (key, bucket_start, now_iso),
    )
    row = db.execute(
        "SELECT count FROM security_rate_limits WHERE rate_key=?",
        (key,),
    ).fetchone()
    # Small fixed-window table; prune stale buckets opportunistically.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    db.execute("DELETE FROM security_rate_limits WHERE updated_at<?", (cutoff,))
    retry_after = max(1, bucket_start + window_seconds - now_epoch)
    return int(row["count"]) <= limit, retry_after


def security_rate_limit_count(
    db: sqlite3.Connection,
    scope: str,
    subject: str,
    window_seconds: int,
) -> int:
    key, _, _ = _rate_limit_state(db, scope, subject, window_seconds)
    row = db.execute(
        "SELECT count FROM security_rate_limits WHERE rate_key=?",
        (key,),
    ).fetchone()
    return int(row["count"]) if row else 0


def clear_security_rate_limit(
    db: sqlite3.Connection,
    scope: str,
    subject: str,
    window_seconds: int,
) -> None:
    key, _, _ = _rate_limit_state(db, scope, subject, window_seconds)
    db.execute("DELETE FROM security_rate_limits WHERE rate_key=?", (key,))


def validate_production_security() -> None:
    # Fail closed only after the operator explicitly marks the deployment as
    # production. DATABASE_URL/HTTPS alone are not sufficient evidence that
    # all newly introduced security environment variables have been configured.
    if os.getenv("OPYT50_ENV", "").strip().casefold() not in {"prod", "production"}:
        return
    errors = []
    public_url = os.getenv("OPYT50_PUBLIC_URL", "").strip()
    if not public_url.startswith("https://"):
        errors.append("OPYT50_PUBLIC_URL must use https://")
    if not secure_cookie_enabled():
        errors.append("secure session cookies must be enabled")
    if os.getenv("OPYT50_ENABLE_DOCS", "0") == "1":
        errors.append("API docs must be disabled")
    if os.getenv("OPYT50_PREVIEW_SEED_DEMO", "0") == "1":
        errors.append("demo seeding must be disabled")
    if os.getenv("DATABASE_URL", "").strip():
        sslmode = os.getenv("OPYT50_DB_SSLMODE", "").strip().casefold()
        if sslmode not in {"require", "verify-ca", "verify-full"}:
            errors.append("PostgreSQL TLS must use require, verify-ca or verify-full")
    if os.getenv("OPYT50_SMTP_HOST", "").strip():
        smtp_tls = (
            os.getenv("OPYT50_SMTP_SSL", "0") == "1"
            or os.getenv("OPYT50_SMTP_STARTTLS", "1") == "1"
        )
        if not smtp_tls:
            errors.append("SMTP must use TLS")
    mfa_mode = admin_mfa_mode()
    profile = security_profile()
    if profile == "high":
        if mfa_mode not in {"totp", "hybrid"}:
            errors.append("high security profile requires TOTP or hybrid passkey administrator MFA")
        hosts = [
            host.strip()
            for host in os.getenv("OPYT50_ALLOWED_HOSTS", "").split(",")
            if host.strip()
        ]
        if not hosts:
            errors.append("high security profile requires a Host allowlist")
        if not os.getenv("DATABASE_URL", "").strip():
            errors.append("high security profile requires shared PostgreSQL")
        elif os.getenv("OPYT50_DB_SSLMODE", "").strip().casefold() != "verify-full":
            errors.append("high security profile requires PostgreSQL TLS verify-full")
    if mfa_mode == "off":
        errors.append("administrator MFA must be enabled in production")
    elif mfa_mode == "email":
        if not os.getenv("OPYT50_SMTP_HOST", "").strip() or not os.getenv("OPYT50_MAIL_FROM", "").strip():
            errors.append("admin email MFA requires configured SMTP delivery")
    elif mfa_mode in {"totp", "hybrid"}:
        secret = os.getenv("OPYT50_ADMIN_TOTP_SECRET", "").strip()
        if len(secret) < 32:
            errors.append("admin TOTP secret is missing or shorter than 160 bits")
        else:
            try:
                pyotp.TOTP(secret, digits=6, interval=30).at(0)
            except Exception:
                errors.append("admin TOTP secret is not valid base32")
    if errors:
        raise RuntimeError("Unsafe production configuration: " + "; ".join(errors))


def get_connection(request: Request):
    with database(request.app.state.db_path) as connection:
        yield connection


def active_user(request: Request, db: sqlite3.Connection = Depends(get_connection)) -> dict:
    token = request.cookies.get(session_cookie_name())
    if not token and session_cookie_name() != COOKIE_NAME:
        # Transitional fallback: old production sessions remain usable until
        # their normal expiry, while every fresh login receives a __Host- cookie.
        token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "Нужно войти в аккаунт")

    digest = token_hash(token)
    now = datetime.now(timezone.utc)
    row = db.execute(
        """SELECT u.id,u.email,u.name,u.phone,u.role,s.token_hash,s.expires_at,
                  a.authenticated_at,a.last_seen_at
           FROM sessions s
           JOIN users u ON u.id=s.user_id
           LEFT JOIN session_activity a ON a.token_hash=s.token_hash
           WHERE s.token_hash=? AND s.expires_at>?""",
        (digest, now.isoformat()),
    ).fetchone()
    if row is None:
        raise HTTPException(401, "Сессия завершена. Войдите снова")

    # Existing sessions created before the activity table rollout are migrated
    # lazily on first successful authenticated request.
    if not row["last_seen_at"]:
        db.execute(
            """INSERT INTO session_activity(token_hash,authenticated_at,last_seen_at)
               VALUES(?,?,?)
               ON CONFLICT(token_hash) DO NOTHING""",
            (digest, now.isoformat(), now.isoformat()),
        )
        last_seen = now
    else:
        try:
            last_seen = datetime.fromisoformat(row["last_seen_at"])
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            # Corrupt activity metadata must fail closed for the session.
            db.execute("DELETE FROM sessions WHERE token_hash=?", (digest,))
            db.commit()
            raise HTTPException(401, "Сессия завершена. Войдите снова") from None

    idle_limit = (
        ADMIN_SESSION_IDLE_SECONDS if row["role"] == "admin"
        else USER_SESSION_IDLE_SECONDS
    )
    if (now - last_seen).total_seconds() > idle_limit:
        db.execute("DELETE FROM sessions WHERE token_hash=?", (digest,))
        try:
            from .release02 import record_security_event
            record_security_event(
                db, row["id"], "session_idle_expired",
                "role=" + str(row["role"]),
            )
        except Exception:
            # Authentication must still fail closed even if audit storage has
            # an unexpected issue.
            pass
        db.commit()
        raise HTTPException(401, "Сессия завершена из-за бездействия. Войдите снова")

    # Avoid a write on every API call while still keeping idle enforcement
    # accurate to roughly one minute.
    if (now - last_seen).total_seconds() >= SESSION_TOUCH_SECONDS:
        db.execute(
            "UPDATE session_activity SET last_seen_at=? WHERE token_hash=?",
            (now.isoformat(), digest),
        )

    # User controls exist after the 0.2 migration; deny disabled accounts on every authenticated request.
    control = db.execute("SELECT status FROM account_controls WHERE user_id=?", (row["id"],)).fetchone()
    if control is not None and control["status"] == "disabled":
        raise HTTPException(403, "Аккаунт временно заблокирован")
    user = {key: row[key] for key in ("id", "email", "name", "phone", "role")}
    # Internal-only identifier for server-side session controls. user_response()
    # deliberately serializes an explicit safe subset and never exposes this.
    user["_session_token_hash"] = digest
    return user

def allowed(user: dict, role: str) -> None:
    if user["role"] != role:
        raise HTTPException(403, "Нет доступа к этому разделу")


def candidate_view(db: sqlite3.Connection, user_id: int) -> dict | None:
    row = db.execute("SELECT * FROM candidate_profiles WHERE user_id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def employer_view(db: sqlite3.Connection, user_id: int) -> dict | None:
    row = db.execute("SELECT * FROM employer_profiles WHERE user_id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def user_response(user: dict, db: sqlite3.Connection) -> dict:
    data = {k: user[k] for k in ("id", "name", "email", "role", "phone")}
    if user["role"] == "candidate":
        data["profile"] = candidate_view(db, user["id"])
    if user["role"] == "employer":
        data["company"] = employer_view(db, user["id"])
    return data


def add_session(db: sqlite3.Connection, response: Response, user_id: int) -> None:
    role_row = db.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
    role = role_row["role"] if role_row is not None else ""
    lifetime = ADMIN_SESSION_SECONDS if role == "admin" else SESSION_SECONDS
    if role == "admin":
        db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    token, digest = issue_session()
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        "INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)",
        (digest, user_id, utc_expiry(lifetime)),
    )
    db.execute(
        "INSERT INTO session_activity(token_hash,authenticated_at,last_seen_at) VALUES(?,?,?)",
        (digest, now, now),
    )
    # FastAPI yield dependencies may finalize after the response is sent.
    # Commit before issuing the session cookie, so the next /api/me sees it.
    db.commit()
    response.set_cookie(
        session_cookie_name(),
        token,
        httponly=True,
        secure=secure_cookie_enabled(),
        samesite="strict",
        max_age=lifetime,
        path="/",
    )

def create_app(db_path: str | None = None) -> FastAPI:
    db_location = db_path or DEFAULT_DB

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        validate_production_security()
        init_db(app.state.db_path)
        from .release02 import init_release02
        init_release02(app.state.db_path)
        yield

    docs_enabled = os.getenv("OPYT50_ENABLE_DOCS", "0" if production_runtime() else "1") == "1"
    app = FastAPI(
        title="СТАЖНО",
        version="0.21.0-dev",
        lifespan=lifespan,
        docs_url="/api/docs" if docs_enabled else None,
        redoc_url="/api/redoc" if docs_enabled else None,
        openapi_url="/api/openapi.json" if docs_enabled else None,
    )
    app.state.db_path = db_location
    # Authentication throttles are persisted in the shared database so they
    # survive process restarts and work consistently across multiple instances.
    allowed_hosts = [
        host.strip()
        for host in os.getenv("OPYT50_ALLOWED_HOSTS", "").split(",")
        if host.strip()
    ]
    if allowed_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
    app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")

    @app.middleware("http")
    async def secure_requests(request: Request, call_next):
        # Optional preview-only HTTP Basic gate. Configure a strong password in
        # the hosting environment; leave it unset for normal local development.
        # Keep health checks available to the hosting platform.
        preview_password = os.getenv("OPYT50_PREVIEW_PASSWORD", "")
        if preview_password and request.url.path != "/api/health":
            login = os.getenv("OPYT50_PREVIEW_USERNAME", "review")
            auth_header = request.headers.get("authorization", "")
            scheme, space, encoded = auth_header.partition(" ")
            authenticated = False
            if scheme.lower() == "basic" and space:
                try:
                    decoded = base64.b64decode(encoded.encode("ascii"), validate=True)
                    supplied_user, colon, supplied_password = decoded.partition(b":")
                    authenticated = bool(colon) and (
                        secrets.compare_digest(supplied_user, login.encode("utf-8"))
                        and secrets.compare_digest(supplied_password, preview_password.encode("utf-8"))
                    )
                except (UnicodeEncodeError, ValueError, binascii.Error):
                    pass
            if not authenticated:
                return Response(
                    content="Тестовый стенд защищён паролем",
                    status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="STAZHNO Preview"', "Cache-Control": "no-store"},
                )
        if request.url.path.startswith("/api/"):
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > 262_144:
                        return Response(status_code=413, content="Слишком большой запрос")
                except ValueError:
                    return Response(status_code=400, content="Некорректный Content-Length")
        # Mutations are same-origin only. The custom header blocks ordinary
        # cross-site forms; Fetch Metadata and Origin add defense in depth.
        if request.url.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if request.headers.get("sec-fetch-site", "").casefold() == "cross-site":
                return Response(status_code=403, content="Cross-site request is not allowed")
            origin = request.headers.get("origin", "").rstrip("/")
            public_url = os.getenv("OPYT50_PUBLIC_URL", "").strip()
            if origin and public_url:
                parsed = urlsplit(public_url)
                expected_origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
                if origin.casefold() != expected_origin.casefold():
                    return Response(status_code=403, content="Request origin is not allowed")
            if request.headers.get("x-requested-with") != "OPYT50":
                return Response(status_code=403, content="Request header is required")
        if request.method == "POST":
            rate_limits = {
                "/api/register": (30, 600),
                "/api/login": (30, 600),
                "/api/account/password/request": (10, 600),
                "/api/account/password/reset": (20, 600),
                "/api/account/email/request": (10, 600),
                "/api/account/email/confirm": (20, 600),
                "/api/admin/mfa/verify": (12, 600),
            }
            limit = rate_limits.get(request.url.path)
            if limit:
                max_attempts, window_seconds = limit
                source = request.client.host if request.client else "unknown"
                subject = _rate_limit_subject(source, request.url.path)
                with database(request.app.state.db_path) as rate_db:
                    permitted, retry_after = consume_security_rate_limit(
                        rate_db,
                        "route",
                        subject,
                        max_attempts,
                        window_seconds,
                    )
                if not permitted:
                    return Response(
                        status_code=429,
                        content="Слишком много попыток. Повторите позже",
                        headers={"Retry-After": str(retry_after)},
                    )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "0"
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
        response.headers["X-DNS-Prefetch-Control"] = "off"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=(), payment=(), usb=()"
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
        csp = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; "
            "form-action 'self'"
        )
        if production_runtime():
            csp += "; upgrade-insecure-requests"
        response.headers["Content-Security-Policy"] = csp
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        return response

    @app.get("/", include_in_schema=False)
    def index():
        response = FileResponse(BASE / "static" / "index.html")
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    @app.get("/api/health")
    def health():
        if production_runtime():
            return {"status": "ok"}
        return {"status": "ok", "version": "0.21.0-dev", "payments": "demo_only"}

    @app.get("/api/taxonomy")
    def taxonomy(db: sqlite3.Connection = Depends(get_connection)):
        data = taxonomy_payload()
        rows = db.execute(
            """SELECT kind,display_value FROM taxonomy_observations
               WHERE status='approved'
               ORDER BY display_value ASC"""
        ).fetchall()
        profession_keys = {item["value"].strip().casefold() for item in data["professions"]}
        skill_keys = {item["value"].strip().casefold() for item in data["skills"]}
        for row in rows:
            value = str(row["display_value"] or "").strip()
            if not value:
                continue
            key = value.casefold()
            if row["kind"] == "profession":
                if key not in profession_keys:
                    data["professions"].append({"value": value, "family": "", "family_key": "", "source": "approved_observation"})
                    profession_keys.add(key)
            else:
                if key not in skill_keys:
                    data["skills"].append({"value": value, "canonical": value.casefold(), "aliases": [value], "source": "approved_observation"})
                    skill_keys.add(key)
        data["professions"].sort(key=lambda item: item["value"].casefold())
        data["skills"].sort(key=lambda item: item["value"].casefold())
        return data

    @app.post("/api/register", status_code=201)
    def register(data: Registration, response: Response, db: sqlite3.Connection = Depends(get_connection)):
        try:
            cursor = db.execute(
                "INSERT INTO users(email,password_hash,role,name,phone) VALUES(?,?,?,?,?)",
                (data.email, make_password_hash(data.password), data.role, data.name.strip(), data.phone.strip()),
            )
            user_id = cursor.lastrowid
            if data.role == "candidate":
                db.execute("INSERT INTO candidate_profiles(user_id) VALUES(?)", (user_id,))
            else:
                db.execute(
                    "INSERT INTO employer_profiles(user_id,company_name) VALUES(?,?)",
                    (user_id, data.company_name.strip()),
                )
            add_session(db, response, user_id)
            from .release02 import enqueue_notice
            enqueue_notice(db, user_id, "welcome", "Добро пожаловать в СТАЖНО", "Ваш аккаунт создан. Добро пожаловать в СТАЖНО.")
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Этот email уже зарегистрирован") from None
        return {"user": user_response(dict(db.execute("SELECT id,email,role,name,phone FROM users WHERE id=?", (user_id,)).fetchone()), db)}

    @app.post("/api/login")
    def login(data: Login, request: Request, response: Response, db: sqlite3.Connection = Depends(get_connection)):
        from .release02 import issue_admin_mfa_challenge, issue_admin_totp_challenge, record_security_event

        email = data.email.strip().casefold()
        source = request.client.host if request.client else "unknown"
        identity = hashlib.sha256(email.encode("utf-8")).hexdigest()
        failure_subject = _rate_limit_subject(source, identity)
        if security_rate_limit_count(db, "login-failure", failure_subject, 900) >= 10:
            raise HTTPException(
                429,
                "Слишком много неверных попыток входа. Повторите позже",
                headers={"Retry-After": "900"},
            )

        row = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        stored_hash = row["password_hash"] if row is not None else DUMMY_PASSWORD_HASH
        password_ok = verify_password(data.password, stored_hash)
        if row is None or not password_ok:
            _, retry_after = consume_security_rate_limit(
                db, "login-failure", failure_subject, 10, 900
            )
            if row is not None:
                record_security_event(db, row["id"], "login_password_failed")
            db.commit()
            raise HTTPException(
                401,
                "Неверный email или пароль",
                headers={"Retry-After": str(retry_after)},
            )
        clear_security_rate_limit(db, "login-failure", failure_subject, 900)
        block = db.execute("SELECT status FROM account_controls WHERE user_id=?", (row["id"],)).fetchone()
        if block is not None and block["status"] == "disabled":
            record_security_event(db, row["id"], "login_blocked_disabled_account")
            db.commit()
            raise HTTPException(403, "Аккаунт временно заблокирован")
        if password_needs_rehash(row["password_hash"]):
            db.execute(
                "UPDATE users SET password_hash=? WHERE id=?",
                (make_password_hash(data.password), row["id"]),
            )

        if row["role"] == "admin":
            mode = admin_mfa_mode()
            if mode == "email":
                challenge_id, debug_code = issue_admin_mfa_challenge(db, row["id"])
                record_security_event(db, row["id"], "login_password_verified_mfa_required", "method=email")
                db.commit()
                from .email_delivery import delivery_mode
                result = {
                    "mfa_required": True,
                    "mfa_method": "email",
                    "code_length": 8,
                    "challenge_id": challenge_id,
                    "expires_in": 300,
                    "delivery": delivery_mode(),
                }
                if not production_runtime():
                    result["debug_code"] = debug_code
                return result
            if mode == "hybrid":
                webauthn_challenge = issue_admin_webauthn_authentication(
                    db, row["id"], request
                )
                if webauthn_challenge is not None:
                    challenge_id, public_key = webauthn_challenge
                    record_security_event(
                        db, row["id"], "login_password_verified_mfa_required",
                        "method=webauthn",
                    )
                    db.commit()
                    return {
                        "mfa_required": True,
                        "mfa_method": "webauthn",
                        "challenge_id": challenge_id,
                        "public_key": public_key,
                        "expires_in": 300,
                        "totp_fallback": True,
                    }
                mode = "totp"
            if mode == "totp":
                challenge_id = issue_admin_totp_challenge(db, row["id"])
                record_security_event(db, row["id"], "login_password_verified_mfa_required", "method=totp")
                db.commit()
                return {
                    "mfa_required": True,
                    "mfa_method": "totp",
                    "code_length": 6,
                    "challenge_id": challenge_id,
                    "expires_in": 300,
                }

        old_token = (
            request.cookies.get(session_cookie_name())
            or request.cookies.get(COOKIE_NAME)
        )
        if old_token:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(old_token),))
        record_security_event(db, row["id"], "login_success")
        add_session(db, response, row["id"])
        return {"user": user_response(dict(row), db)}

    @app.post("/api/admin/mfa/verify")
    def verify_admin_mfa(
        data: AdminMfaVerify,
        response: Response,
        db: sqlite3.Connection = Depends(get_connection),
    ):
        from .release02 import record_security_event

        challenge = db.execute(
            """SELECT c.challenge_key,c.user_id,c.code_hash,c.expires_at,c.attempts,c.used_at,
                      u.email,u.name,u.phone,u.role
               FROM admin_mfa_challenges c
               JOIN users u ON u.id=c.user_id
               WHERE c.challenge_key=?""",
            (data.challenge_id,),
        ).fetchone()
        now = datetime.now(timezone.utc)
        invalid = (
            challenge is None
            or challenge["used_at"] is not None
            or challenge["role"] != "admin"
        )
        if invalid:
            raise HTTPException(400, "Код недействителен или срок истёк")
        try:
            expired = datetime.fromisoformat(challenge["expires_at"]) <= now
        except (TypeError, ValueError):
            expired = True
        if expired:
            db.execute(
                "UPDATE admin_mfa_challenges SET used_at=? WHERE challenge_key=?",
                (now.isoformat(), data.challenge_id),
            )
            record_security_event(db, challenge["user_id"], "admin_mfa_expired")
            db.commit()
            raise HTTPException(400, "Код недействителен или срок истёк")
        if int(challenge["attempts"] or 0) >= 5:
            raise HTTPException(429, "Слишком много неверных попыток. Войдите заново")

        attempts = int(challenge["attempts"] or 0) + 1
        if challenge["code_hash"] == "totp-v1":
            secret = os.getenv("OPYT50_ADMIN_TOTP_SECRET", "").strip()
            code_ok = bool(secret) and pyotp.TOTP(secret, digits=6, interval=30).verify(
                data.code,
                valid_window=1,
            )
        else:
            code_ok = verify_password(data.code, challenge["code_hash"])
        if not code_ok:
            used_at = now.isoformat() if attempts >= 5 else None
            db.execute(
                """UPDATE admin_mfa_challenges SET attempts=?,used_at=?
                   WHERE challenge_key=?""",
                (attempts, used_at, data.challenge_id),
            )
            record_security_event(
                db,
                challenge["user_id"],
                "admin_mfa_failed",
                f"attempt={attempts}",
            )
            db.commit()
            if attempts >= 5:
                raise HTTPException(429, "Слишком много неверных попыток. Войдите заново")
            raise HTTPException(401, "Неверный код подтверждения")

        control = db.execute(
            "SELECT status FROM account_controls WHERE user_id=?",
            (challenge["user_id"],),
        ).fetchone()
        if control is not None and control["status"] == "disabled":
            raise HTTPException(403, "Аккаунт временно заблокирован")

        db.execute(
            "UPDATE admin_mfa_challenges SET attempts=?,used_at=? WHERE challenge_key=?",
            (attempts, now.isoformat(), data.challenge_id),
        )
        db.execute("DELETE FROM sessions WHERE user_id=?", (challenge["user_id"],))
        record_security_event(db, challenge["user_id"], "admin_mfa_success")
        user = {
            "id": challenge["user_id"],
            "email": challenge["email"],
            "name": challenge["name"],
            "phone": challenge["phone"],
            "role": challenge["role"],
        }
        add_session(db, response, challenge["user_id"])
        return {"user": user_response(user, db)}

    @app.post("/api/admin/passkeys/register/options")
    def admin_passkey_registration_options(
        request: Request,
        user: dict = Depends(active_user),
        db: sqlite3.Connection = Depends(get_connection),
    ):
        allowed(user, "admin")
        origin, rp_id = _webauthn_context(request)
        existing = db.execute(
            "SELECT credential_id FROM admin_webauthn_credentials WHERE user_id=?",
            (user["id"],),
        ).fetchall()
        user_handle = hashlib.sha256(
            f"stazhno-admin:{user['id']}".encode("utf-8")
        ).digest()
        options = generate_registration_options(
            rp_id=rp_id,
            rp_name="СТАЖНО",
            user_id=user_handle,
            user_name=user["email"],
            user_display_name=user["name"],
            exclude_credentials=[
                PublicKeyCredentialDescriptor(
                    id=base64url_to_bytes(str(row["credential_id"]))
                )
                for row in existing
            ],
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            timeout=120_000,
        )
        challenge_id = _store_admin_webauthn_challenge(
            db, user["id"], "registration", options.challenge, rp_id, origin
        )
        db.commit()
        return {
            "challenge_id": challenge_id,
            "public_key": json.loads(options_to_json(options)),
        }

    @app.post("/api/admin/passkeys/register/verify")
    def admin_passkey_registration_verify(
        data: AdminWebAuthnRegistrationVerify,
        user: dict = Depends(active_user),
        db: sqlite3.Connection = Depends(get_connection),
    ):
        allowed(user, "admin")
        from .release02 import record_security_event

        challenge = db.execute(
            """SELECT * FROM admin_webauthn_challenges
               WHERE challenge_key=? AND user_id=? AND kind='registration'""",
            (data.challenge_id, user["id"]),
        ).fetchone()
        now = datetime.now(timezone.utc)
        if challenge is None or challenge["used_at"] is not None:
            raise HTTPException(400, "Запрос регистрации passkey недействителен")
        try:
            expired = datetime.fromisoformat(challenge["expires_at"]) <= now
        except (TypeError, ValueError):
            expired = True
        if expired:
            db.execute(
                "UPDATE admin_webauthn_challenges SET used_at=? WHERE challenge_key=?",
                (now.isoformat(), data.challenge_id),
            )
            db.commit()
            raise HTTPException(400, "Срок регистрации passkey истёк")
        try:
            verified = verify_registration_response(
                credential=data.credential,
                expected_challenge=base64url_to_bytes(challenge["challenge_b64"]),
                expected_rp_id=challenge["rp_id"],
                expected_origin=challenge["origin"],
                require_user_verification=True,
            )
        except InvalidRegistrationResponse:
            attempts = int(challenge["attempts"] or 0) + 1
            db.execute(
                """UPDATE admin_webauthn_challenges
                   SET attempts=?,used_at=?
                   WHERE challenge_key=?""",
                (
                    attempts,
                    now.isoformat() if attempts >= 5 else None,
                    data.challenge_id,
                ),
            )
            record_security_event(
                db, user["id"], "admin_passkey_registration_failed",
                f"attempt={attempts}",
            )
            db.commit()
            raise HTTPException(400, "Не удалось проверить passkey") from None

        credential_id = _bytes_to_base64url(verified.credential_id)
        public_key = _bytes_to_base64url(verified.credential_public_key)
        device_type = getattr(
            verified.credential_device_type, "value",
            str(verified.credential_device_type),
        )
        transports = data.credential.get("response", {}).get("transports", [])
        if not isinstance(transports, list):
            transports = []
        try:
            db.execute(
                """INSERT INTO admin_webauthn_credentials(
                       credential_id,user_id,public_key,sign_count,label,transports,
                       credential_device_type,backed_up,created_at,last_used_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,NULL)""",
                (
                    credential_id,
                    user["id"],
                    public_key,
                    int(verified.sign_count),
                    data.label.strip(),
                    json.dumps(transports, ensure_ascii=False),
                    device_type,
                    1 if verified.credential_backed_up else 0,
                    now.isoformat(),
                ),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Этот passkey уже зарегистрирован") from None
        db.execute(
            "UPDATE admin_webauthn_challenges SET used_at=? WHERE challenge_key=?",
            (now.isoformat(), data.challenge_id),
        )
        record_security_event(
            db, user["id"], "admin_passkey_registered",
            "credential=" + hashlib.sha256(credential_id.encode("utf-8")).hexdigest()[:16],
        )
        db.commit()
        return {"ok": True}

    @app.delete("/api/admin/passkeys/{passkey_id}")
    def delete_admin_passkey(
        passkey_id: str,
        user: dict = Depends(active_user),
        db: sqlite3.Connection = Depends(get_connection),
    ):
        allowed(user, "admin")
        from .release02 import record_security_event

        if not re.fullmatch(r"[0-9a-f]{24}", passkey_id):
            raise HTTPException(404, "Passkey не найден")
        rows = db.execute(
            "SELECT credential_id FROM admin_webauthn_credentials WHERE user_id=?",
            (user["id"],),
        ).fetchall()
        target = None
        for row in rows:
            credential_id = str(row["credential_id"])
            public_id = hashlib.sha256(
                ("webauthn-public-id:" + credential_id).encode("utf-8")
            ).hexdigest()[:24]
            if secrets.compare_digest(public_id, passkey_id):
                target = credential_id
                break
        if target is None:
            raise HTTPException(404, "Passkey не найден")
        db.execute(
            "DELETE FROM admin_webauthn_credentials WHERE user_id=? AND credential_id=?",
            (user["id"], target),
        )
        record_security_event(db, user["id"], "admin_passkey_deleted")
        db.commit()
        return {"ok": True}

    @app.post("/api/admin/mfa/webauthn/verify")
    def verify_admin_webauthn_mfa(
        data: AdminWebAuthnAuthenticationVerify,
        response: Response,
        db: sqlite3.Connection = Depends(get_connection),
    ):
        from .release02 import record_security_event

        challenge = db.execute(
            """SELECT c.*,u.email,u.name,u.phone,u.role
               FROM admin_webauthn_challenges c
               JOIN users u ON u.id=c.user_id
               WHERE c.challenge_key=? AND c.kind='authentication'""",
            (data.challenge_id,),
        ).fetchone()
        now = datetime.now(timezone.utc)
        if (
            challenge is None
            or challenge["used_at"] is not None
            or challenge["role"] != "admin"
        ):
            raise HTTPException(400, "Passkey-запрос недействителен или уже использован")
        try:
            expired = datetime.fromisoformat(challenge["expires_at"]) <= now
        except (TypeError, ValueError):
            expired = True
        if expired:
            db.execute(
                "UPDATE admin_webauthn_challenges SET used_at=? WHERE challenge_key=?",
                (now.isoformat(), data.challenge_id),
            )
            record_security_event(db, challenge["user_id"], "admin_passkey_expired")
            db.commit()
            raise HTTPException(400, "Срок подтверждения passkey истёк")
        if int(challenge["attempts"] or 0) >= 5:
            raise HTTPException(429, "Слишком много неверных попыток. Войдите заново")

        credential_id = str(data.credential.get("id") or "")
        stored = db.execute(
            """SELECT credential_id,public_key,sign_count
               FROM admin_webauthn_credentials
               WHERE user_id=? AND credential_id=?""",
            (challenge["user_id"], credential_id),
        ).fetchone()
        if stored is None:
            raise HTTPException(401, "Этот passkey не зарегистрирован")
        try:
            verified = verify_authentication_response(
                credential=data.credential,
                expected_challenge=base64url_to_bytes(challenge["challenge_b64"]),
                expected_rp_id=challenge["rp_id"],
                expected_origin=challenge["origin"],
                credential_public_key=base64url_to_bytes(stored["public_key"]),
                credential_current_sign_count=int(stored["sign_count"] or 0),
                require_user_verification=True,
            )
        except InvalidAuthenticationResponse:
            attempts = int(challenge["attempts"] or 0) + 1
            db.execute(
                """UPDATE admin_webauthn_challenges
                   SET attempts=?,used_at=?
                   WHERE challenge_key=?""",
                (
                    attempts,
                    now.isoformat() if attempts >= 5 else None,
                    data.challenge_id,
                ),
            )
            record_security_event(
                db, challenge["user_id"], "admin_passkey_failed",
                f"attempt={attempts}",
            )
            db.commit()
            if attempts >= 5:
                raise HTTPException(429, "Слишком много неверных попыток. Войдите заново")
            raise HTTPException(401, "Passkey не подтверждён") from None

        control = db.execute(
            "SELECT status FROM account_controls WHERE user_id=?",
            (challenge["user_id"],),
        ).fetchone()
        if control is not None and control["status"] == "disabled":
            raise HTTPException(403, "Аккаунт временно заблокирован")
        db.execute(
            """UPDATE admin_webauthn_credentials
               SET sign_count=?,last_used_at=?
               WHERE user_id=? AND credential_id=?""",
            (
                int(verified.new_sign_count),
                now.isoformat(),
                challenge["user_id"],
                credential_id,
            ),
        )
        db.execute(
            "UPDATE admin_webauthn_challenges SET used_at=? WHERE challenge_key=?",
            (now.isoformat(), data.challenge_id),
        )
        record_security_event(db, challenge["user_id"], "admin_passkey_success")
        user = {
            "id": challenge["user_id"],
            "email": challenge["email"],
            "name": challenge["name"],
            "phone": challenge["phone"],
            "role": challenge["role"],
        }
        add_session(db, response, challenge["user_id"])
        return {"user": user_response(user, db)}

    @app.post("/api/admin/mfa/webauthn/fallback-totp")
    def admin_webauthn_fallback_totp(
        data: AdminWebAuthnFallback,
        db: sqlite3.Connection = Depends(get_connection),
    ):
        if admin_mfa_mode() != "hybrid":
            raise HTTPException(403, "Резервный TOTP не включён")
        from .release02 import issue_admin_totp_challenge, record_security_event

        challenge = db.execute(
            """SELECT challenge_key,user_id,expires_at,used_at
               FROM admin_webauthn_challenges
               WHERE challenge_key=? AND kind='authentication'""",
            (data.challenge_id,),
        ).fetchone()
        now = datetime.now(timezone.utc)
        if challenge is None or challenge["used_at"] is not None:
            raise HTTPException(400, "Passkey-запрос недействителен")
        try:
            expired = datetime.fromisoformat(challenge["expires_at"]) <= now
        except (TypeError, ValueError):
            expired = True
        if expired:
            raise HTTPException(400, "Срок подтверждения истёк")
        db.execute(
            "UPDATE admin_webauthn_challenges SET used_at=? WHERE challenge_key=?",
            (now.isoformat(), data.challenge_id),
        )
        challenge_id = issue_admin_totp_challenge(db, challenge["user_id"])
        record_security_event(
            db, challenge["user_id"], "admin_passkey_fallback_totp"
        )
        db.commit()
        return {
            "mfa_required": True,
            "mfa_method": "totp",
            "code_length": 6,
            "challenge_id": challenge_id,
            "expires_in": 300,
        }

    @app.post("/api/logout")
    def logout(request: Request, response: Response, db: sqlite3.Connection = Depends(get_connection)):
        token = (
            request.cookies.get(session_cookie_name())
            or request.cookies.get(COOKIE_NAME)
        )
        if token:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),))
            db.commit()  # Prevent next /api/me from seeing a deleted session.
        response.delete_cookie(
            session_cookie_name(),
            path="/",
            secure=secure_cookie_enabled(),
            httponly=True,
            samesite="strict",
        )
        if session_cookie_name() != COOKIE_NAME:
            response.delete_cookie(
                COOKIE_NAME,
                path="/",
                secure=True,
                httponly=True,
                samesite="lax",
            )
        return {"ok": True}

    @app.get("/api/me")
    def me(user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        return {"user": user_response(user, db)}

    @app.get("/api/admin/security-status")
    def admin_security_status(user: dict = Depends(active_user)):
        allowed(user, "admin")
        return {
            "security_profile": security_profile(),
            "admin_mfa_mode": admin_mfa_mode(),
            "admin_mfa_enabled": admin_mfa_mode() != "off",
            "admin_mfa_strength": "app-based TOTP" if admin_mfa_mode() == "totp" else ("email OTP" if admin_mfa_mode() == "email" else "off"),
            "admin_session_minutes": ADMIN_SESSION_SECONDS // 60,
            "admin_idle_minutes": ADMIN_SESSION_IDLE_SECONDS // 60,
            "user_idle_hours": USER_SESSION_IDLE_SECONDS // 3600,
            "password_hash": "argon2id",
            "secure_cookie": secure_cookie_enabled(),
            "production_runtime": production_runtime(),
            "api_docs_enabled": docs_enabled,
        }

    @app.put("/api/candidate/profile")
    def save_profile(
        data: CandidateProfile, user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)
    ):
        allowed(user, "candidate")
        db.execute(
            """UPDATE candidate_profiles SET profession=?,city=?,skills=?,salary_min=?,schedule=?,
               employment=?,about=?,is_active=?,updated_at=datetime('now') WHERE user_id=?""",
            (
                data.profession.strip(), data.city.strip(), data.skills.strip(), data.salary_min,
                data.schedule, data.employment, data.about.strip(), int(data.is_active), user["id"],
            ),
        )
        db.execute("UPDATE users SET phone=? WHERE id=?", (data.phone.strip(), user["id"]))
        # Commit before the HTTP response: a new dashboard request may arrive immediately.
        db.commit()
        return {"ok": True, "profile": candidate_view(db, user["id"])}

    @app.get("/api/jobs")
    def jobs(q: str = "", city: str = "", salary_min: int = 0, schedule: str = "",
             employment: str = "", sort: str = "recent",
             db: sqlite3.Connection = Depends(get_connection)):
        """Public job search with transparent filters and deterministic sorting."""
        if salary_min < 0 or salary_min > 10_000_000 or len(q) > 120 or len(city) > 100:
            raise HTTPException(422, "Проверьте параметры поиска")
        if schedule and schedule not in SCHEDULES:
            raise HTTPException(422, "Недопустимый график")
        if employment and employment not in EMPLOYMENTS:
            raise HTTPException(422, "Недопустимая занятость")
        if sort not in {"recent", "salary_desc", "salary_asc"}:
            raise HTTPException(422, "Недопустимая сортировка")
        sql = """SELECT v.*,e.company_name,e.verified AS employer_verified,
                        CASE WHEN length(e.inn)>0 THEN 1 ELSE 0 END AS employer_inn_provided,
                        COALESCE(ac.email_verified,0) AS employer_email_verified,
                        eu.created_at AS employer_created_at
                 FROM vacancies v
                 JOIN employer_profiles e ON e.user_id=v.employer_id
                 JOIN users eu ON eu.id=e.user_id
                 LEFT JOIN account_controls ac ON ac.user_id=e.user_id
                 LEFT JOIN vacancy_moderation vm ON vm.vacancy_id=v.id
                 WHERE v.status='open'
                   AND COALESCE(ac.status,'active')='active'
                   AND COALESCE(vm.status,'approved')='approved'"""
        params: list = []
        if q.strip():
            # instr on Unicode-casefolded text ensures correct Cyrillic search.
            sql += """ AND (instr(unicode_fold(v.title), ?) > 0
                         OR instr(unicode_fold(v.skills), ?) > 0
                         OR instr(unicode_fold(v.description), ?) > 0)"""
            needle = q.strip().casefold()
            params.extend([needle, needle, needle])
        if city.strip():
            sql += " AND (unicode_fold(v.city)=? OR unicode_fold(v.city)='удалённо' OR unicode_fold(v.city)='любой город')"
            params.append(city.strip().casefold())
        if salary_min:
            sql += " AND v.salary_max >= ?"
            params.append(salary_min)
        if schedule and schedule != "Любой":
            sql += " AND (v.schedule=? OR v.schedule='Любой')"
            params.append(schedule)
        if employment and employment != "Любая":
            sql += " AND (v.employment=? OR v.employment='Любая')"
            params.append(employment)
        if sort == "salary_desc":
            sql += " ORDER BY v.salary_max DESC, v.salary_min DESC, v.id DESC"
        elif sort == "salary_asc":
            sql += " ORDER BY v.salary_min ASC, v.salary_max ASC, v.id DESC"
        else:
            sql += " ORDER BY v.id DESC"
        sql += " LIMIT 100"
        return {"jobs": [dict(row) for row in db.execute(sql, params).fetchall()]}

    @app.get("/api/candidate/jobs")
    def matching_jobs(user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "candidate")
        profile = candidate_view(db, user["id"])
        # Attach only the current candidate's application status. This keeps
        # the recommendation card authoritative across sessions and reloads;
        # no other candidate's application details are exposed.
        jobs_rows = db.execute(
            """SELECT v.*,e.company_name,e.verified AS employer_verified,
                      CASE WHEN length(e.inn)>0 THEN 1 ELSE 0 END AS employer_inn_provided,
                      COALESCE(ac.email_verified,0) AS employer_email_verified,
                      eu.created_at AS employer_created_at,
                      a.id AS application_id, a.status AS application_status,
                      i.id AS invitation_id,i.status AS invitation_status,
                      i.contact_shared AS contact_shared
               FROM vacancies v
               JOIN employer_profiles e ON e.user_id=v.employer_id
               JOIN users eu ON eu.id=e.user_id
               LEFT JOIN account_controls ac ON ac.user_id=e.user_id
               LEFT JOIN vacancy_moderation vm ON vm.vacancy_id=v.id
               LEFT JOIN job_applications a
                    ON a.vacancy_id=v.id AND a.candidate_id=?
               LEFT JOIN invitations i
                    ON i.vacancy_id=v.id AND i.candidate_id=?
               WHERE v.status='open'
                 AND COALESCE(ac.status,'active')='active'
                 AND COALESCE(vm.status,'approved')='approved'
               LIMIT 500""",
            (user["id"],user["id"]),
        ).fetchall()
        matches = []
        from .release02 import introduction_stage
        for row in jobs_rows:
            result = match_candidate(dict(row), profile)
            if result:
                matches.append({**dict(row), **result,
                                "introduction_stage": introduction_stage(row["invitation_status"], row["contact_shared"])})
        return {"jobs": sorted(matches, key=lambda x: (-x["score"], -x["id"]))[:50]}

    @app.get("/api/candidate/alternative-jobs")
    def alternative_jobs(user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        """Other public vacancies with transparent differences, not personalized matches."""
        allowed(user, "candidate")
        profile = candidate_view(db, user["id"])
        if not profile["profession"] or not profile["city"] or not profile["is_active"]:
            return {"jobs": []}
        from .matching import evaluate_candidate
        rows = db.execute(
            """SELECT v.id,v.title,v.city,v.salary_min,v.salary_max,v.schedule,
                      v.employment,v.skills,v.description,v.status,v.created_at,
                      e.company_name,e.verified AS employer_verified,
                      CASE WHEN length(e.inn)>0 THEN 1 ELSE 0 END AS employer_inn_provided,
                      COALESCE(ac.email_verified,0) AS employer_email_verified,
                      eu.created_at AS employer_created_at
               FROM vacancies v
               JOIN employer_profiles e ON e.user_id=v.employer_id
               JOIN users eu ON eu.id=e.user_id
               LEFT JOIN account_controls ac ON ac.user_id=e.user_id
               LEFT JOIN vacancy_moderation vm ON vm.vacancy_id=v.id
               WHERE v.status='open'
                 AND COALESCE(ac.status,'active')='active'
                 AND COALESCE(vm.status,'approved')='approved'
               ORDER BY v.id DESC LIMIT 500"""
        ).fetchall()
        alternatives = []
        for row in rows:
            vacancy = dict(row)
            evaluation = evaluate_candidate(vacancy, profile)
            if evaluation["eligible"]:
                continue
            reasons = evaluation["mismatch_reasons"]
            if reasons:
                alternatives.append({
                    **vacancy,
                    "mismatch_reasons": reasons,
                    "near_score": evaluation["score"],
                    "strengths": evaluation["strengths"],
                    "cautions": evaluation["cautions"],
                    "score_breakdown": evaluation["score_breakdown"],
                })
        alternatives.sort(
            key=lambda v: (-v["near_score"], len(v["mismatch_reasons"]), -v["id"])
        )
        return {"jobs": alternatives[:10]}

    @app.post("/api/employer/vacancies", status_code=201)
    def create_vacancy(data: VacancyIn, user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "employer")
        cursor = db.execute(
            """INSERT INTO vacancies(employer_id,title,city,salary_min,salary_max,schedule,employment,skills,description)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                user["id"], data.title.strip(), data.city.strip(), data.salary_min, data.salary_max,
                data.schedule, data.employment, data.skills.strip(), data.description.strip(),
            ),
        )
        from .release02 import utc_now_text
        db.execute(
            "INSERT INTO vacancy_moderation(vacancy_id,status,reason,updated_at) VALUES(?,?,?,?)",
            (cursor.lastrowid, "approved", "", utc_now_text()),
        )
        # Commit before the HTTP response: a new dashboard request may arrive immediately.
        db.commit()
        return {"id": cursor.lastrowid, "ok": True, "moderation_status": "approved"}

    @app.get("/api/employer/vacancies")
    def employer_jobs(user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "employer")
        rows = db.execute(
            """SELECT v.*,COALESCE(vm.status,'approved') AS moderation_status,
                      COALESCE(vm.reason,'') AS moderation_reason
               FROM vacancies v
               LEFT JOIN vacancy_moderation vm ON vm.vacancy_id=v.id
               WHERE v.employer_id=? ORDER BY v.id DESC""",
            (user["id"],),
        ).fetchall()
        return {"jobs": [{**dict(row), "revision": vacancy_revision(row)} for row in rows]}

    @app.patch("/api/employer/vacancies/{job_id}")
    def edit_vacancy(
        job_id: int,
        data: VacancyEdit,
        user: dict = Depends(active_user),
        db: sqlite3.Connection = Depends(get_connection),
    ):
        """Edit content of an owned vacancy in place, preserving ID and relationships.

        An optimistic version and a compare-and-swap UPDATE reject stale browser
        tabs; application/invitation status, consent, history and the job status
        are intentionally never touched.
        """
        allowed(user, "employer")
        original = db.execute(
            "SELECT * FROM vacancies WHERE id=? AND employer_id=?",
            (job_id, user["id"]),
        ).fetchone()
        if original is None:
            raise HTTPException(404, "Вакансия не найдена")
        if vacancy_revision(original) != data.expected_revision:
            raise HTTPException(409, "Вакансия уже изменена. Обновите список и проверьте условия ещё раз.")

        values = {field: getattr(data, field) for field in VACANCY_CONTENT_FIELDS}
        values["title"] = values["title"].strip()
        values["city"] = values["city"].strip()
        values["skills"] = values["skills"].strip()
        values["description"] = values["description"].strip()

        cursor = db.execute(
            """UPDATE vacancies
               SET title=?,city=?,salary_min=?,salary_max=?,schedule=?,employment=?,skills=?,description=?
               WHERE id=? AND employer_id=?
                 AND title=? AND city=? AND salary_min=? AND salary_max=?
                 AND schedule=? AND employment=? AND skills=? AND description=?
                 AND status=?""",
            tuple(values[field] for field in VACANCY_CONTENT_FIELDS)
            + (job_id, user["id"])
            + tuple(original[field] for field in VACANCY_CONTENT_FIELDS)
            + (original["status"],),
        )
        if cursor.rowcount != 1:
            raise HTTPException(409, "Вакансия изменилась во время редактирования. Обновите данные.")

        # Create exactly one update event per substantive edit. Recipients are
        # snapshotted at this moment: later applicants cannot see earlier edits.
        # No external email or payment service is invoked.
        changed = {
            field: {"before": original[field], "after": values[field]}
            for field in VACANCY_CONTENT_FIELDS
            if original[field] != values[field]
        }
        if changed:
            from .release02 import utc_now_text
            db.execute(
                """UPDATE vacancy_moderation
                   SET status=CASE WHEN status='rejected' THEN 'pending' ELSE status END,
                       reason=CASE WHEN status='rejected'
                                   THEN 'Вакансия изменена работодателем и отправлена на повторную проверку'
                                   ELSE reason END,
                       reviewed_by=CASE WHEN status='rejected' THEN NULL ELSE reviewed_by END,
                       reviewed_at=CASE WHEN status='rejected' THEN NULL ELSE reviewed_at END,
                       updated_at=?
                   WHERE vacancy_id=?""",
                (utc_now_text(), job_id),
            )
            event = db.execute(
                "INSERT INTO vacancy_updates(vacancy_id,employer_id,changes_json) VALUES(?,?,?)",
                (job_id, user["id"], json.dumps(changed, ensure_ascii=False)),
            )
            db.execute(
                """INSERT INTO vacancy_update_recipients(update_id,candidate_id)
                   SELECT ?,recipient.candidate_id FROM (
                       SELECT candidate_id FROM job_applications
                       WHERE vacancy_id=? AND status <> 'withdrawn'
                       UNION
                       SELECT candidate_id FROM invitations
                       WHERE vacancy_id=? AND status IN ('sent','accepted')
                   ) AS recipient""",
                (event.lastrowid, job_id, job_id),
            )
        db.commit()
        updated = db.execute(
            "SELECT * FROM vacancies WHERE id=? AND employer_id=?",
            (job_id, user["id"]),
        ).fetchone()
        return {"ok": True, "job": {**dict(updated), "revision": vacancy_revision(updated)}}

    @app.get("/api/candidate/vacancy-updates")
    def candidate_vacancy_updates(
        user: dict = Depends(active_user),
        db: sqlite3.Connection = Depends(get_connection),
    ):
        """Private in-account notices about actual edits to relevant vacancies."""
        allowed(user, "candidate")
        rows = db.execute(
            """SELECT u.id,u.vacancy_id,u.created_at,u.changes_json,
                      v.title,v.status AS vacancy_status,e.company_name,
                      r.read_at
               FROM vacancy_update_recipients r
               JOIN vacancy_updates u ON u.id=r.update_id
               JOIN vacancies v ON v.id=u.vacancy_id
               JOIN employer_profiles e ON e.user_id=u.employer_id
               WHERE r.candidate_id=?
               ORDER BY u.id DESC LIMIT 100""",
            (user["id"],),
        ).fetchall()
        unread_count = db.execute(
            """SELECT COUNT(*) FROM vacancy_update_recipients
               WHERE candidate_id=? AND read_at IS NULL""", (user["id"],),
        ).fetchone()[0]
        return {
            "unread_count": unread_count,
            "updates": [
                {**{field: row[field] for field in (
                    "id", "vacancy_id", "created_at", "title",
                    "vacancy_status", "company_name", "read_at"
                )}, "changes": json.loads(row["changes_json"])}
                for row in rows
            ],
        }

    @app.post("/api/candidate/vacancy-updates/{update_id}/read")
    def candidate_read_vacancy_update(
        update_id: int,
        user: dict = Depends(active_user),
        db: sqlite3.Connection = Depends(get_connection),
    ):
        """Idempotent read receipt for the logged-in recipient only."""
        allowed(user, "candidate")
        cursor = db.execute(
            """UPDATE vacancy_update_recipients SET read_at=COALESCE(read_at,datetime('now'))
               WHERE update_id=? AND candidate_id=?""", (update_id, user["id"]),
        )
        if cursor.rowcount == 0:
            raise HTTPException(404, "Уведомление не найдено")
        db.commit()
        return {"ok": True}

    @app.patch("/api/employer/vacancies/{job_id}/status")
    def set_vacancy_status(
        job_id: int, data: VacancyStatus, user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)
    ):
        allowed(user, "employer")
        changed = db.execute("UPDATE vacancies SET status=? WHERE id=? AND employer_id=?", (data.status, job_id, user["id"]))
        if changed.rowcount == 0:
            raise HTTPException(404, "Вакансия не найдена")
        # Commit before the HTTP response: a new dashboard request may arrive immediately.
        db.commit()
        return {"ok": True}

    @app.get("/api/employer/vacancies/{job_id}/matches")
    def job_matches(job_id: int, user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "employer")
        vacancy = db.execute(
            """SELECT v.*,COALESCE(vm.status,'approved') AS moderation_status
               FROM vacancies v
               LEFT JOIN vacancy_moderation vm ON vm.vacancy_id=v.id
               WHERE v.id=? AND v.employer_id=?""",
            (job_id, user["id"]),
        ).fetchone()
        if vacancy is None:
            raise HTTPException(404, "Вакансия не найдена")
        if vacancy["moderation_status"] != "approved":
            raise HTTPException(409, "Вакансия временно недоступна для подбора до завершения модерации")
        rows = db.execute(
            """SELECT c.*,u.id AS candidate_id,
                      i.id AS invitation_id,i.status AS invitation_status,
                      i.contact_shared AS contact_shared
               FROM candidate_profiles c
               JOIN users u ON u.id=c.user_id
               LEFT JOIN invitations i ON i.candidate_id=u.id AND i.vacancy_id=?
               WHERE c.is_active=1 AND u.role='candidate'""",
            (job_id,),
        ).fetchall()
        matches = []
        for row in rows:
            score = match_candidate(dict(vacancy), dict(row))
            if score:
                # Privacy: no name, phone, email or freeform about before candidate consent + contact opening.
                public = {k: row[k] for k in (
                    "candidate_id", "profession", "city", "skills",
                    "salary_min", "schedule", "employment",
                    "invitation_id", "invitation_status", "contact_shared",
                )}
                matches.append(public | score)
        return {"matches": sorted(matches, key=lambda x: (-x["score"], x["candidate_id"]))[:50]}

    @app.post("/api/employer/invitations", status_code=201)
    def invite(data: InvitationIn, user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "employer")
        vacancy = db.execute(
            """SELECT v.*,COALESCE(vm.status,'approved') AS moderation_status
               FROM vacancies v
               LEFT JOIN vacancy_moderation vm ON vm.vacancy_id=v.id
               WHERE v.id=? AND v.employer_id=? AND v.status='open'""",
            (data.vacancy_id, user["id"]),
        ).fetchone()
        if vacancy is None:
            raise HTTPException(404, "Нет активной вакансии с таким ID")
        if vacancy["moderation_status"] != "approved":
            raise HTTPException(409, "Вакансия ожидает проверки и пока не может использоваться для приглашений")
        candidate = db.execute(
            """SELECT c.* FROM candidate_profiles c JOIN users u ON u.id=c.user_id
               WHERE c.user_id=? AND u.role='candidate'""", (data.candidate_id,)
        ).fetchone()
        if candidate is None or match_candidate(dict(vacancy), dict(candidate)) is None:
            raise HTTPException(422, "Кандидат не соответствует условиям вакансии")
        try:
            cursor = db.execute(
                "INSERT INTO invitations(vacancy_id,candidate_id,employer_id,price_rub) VALUES(?,?,?,?)",
                (data.vacancy_id, data.candidate_id, user["id"], lead_price(vacancy["title"])),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Этому кандидату уже направлено приглашение") from None
        from .release02 import enqueue_notice
        enqueue_notice(db, data.candidate_id, "invitation", "Приглашение от компании — СТАЖНО",
                       f"Вы получили приглашение на вакансию «{vacancy['title']}». Откройте личный кабинет.")
        # Commit before the HTTP response: a new dashboard request may arrive immediately.
        db.commit()
        return {"id": cursor.lastrowid, "ok": True}

    @app.get("/api/candidate/invitations")
    def candidate_invitations(user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "candidate")
        rows = db.execute(
            """SELECT i.id,i.status,i.share_consent,i.contact_shared,i.created_at,
               i.responded_at,v.title,v.city,v.salary_min,v.salary_max,
               v.schedule,v.employment,v.description,e.company_name,
               e.verified AS employer_verified,
               CASE WHEN length(e.inn)>0 THEN 1 ELSE 0 END AS employer_inn_provided,
               COALESCE(ac.email_verified,0) AS employer_email_verified,
               eu.created_at AS employer_created_at,
               a.id AS application_id
               FROM invitations i JOIN vacancies v ON i.vacancy_id=v.id
               JOIN employer_profiles e ON e.user_id=i.employer_id
               JOIN users eu ON eu.id=e.user_id
               LEFT JOIN account_controls ac ON ac.user_id=e.user_id
               LEFT JOIN job_applications a
                    ON a.vacancy_id=i.vacancy_id AND a.candidate_id=i.candidate_id
               WHERE i.candidate_id=? ORDER BY i.id DESC""", (user["id"],)
        ).fetchall()
        from .release02 import introduction_stage, interaction_timeline
        return {"invitations": [
            {**dict(row),
             "introduction_stage": introduction_stage(row["status"], row["contact_shared"]),
             "timeline": interaction_timeline(db, row["application_id"], row["id"])}
            for row in rows
        ]}

    @app.post("/api/candidate/invitations/{invitation_id}/respond")
    def respond(
        invitation_id: int, data: InvitationReply, user: dict = Depends(active_user),
        db: sqlite3.Connection = Depends(get_connection),
    ):
        allowed(user, "candidate")
        if data.decision == "accepted" and not data.share_consent:
            raise HTTPException(422, "Нужно подтвердить согласие на передачу контакта этой компании")
        invitation = db.execute(
            "SELECT id,status FROM invitations WHERE id=? AND candidate_id=?", (invitation_id, user["id"])
        ).fetchone()
        if not invitation:
            raise HTTPException(404, "Приглашение не найдено")
        if invitation["status"] != "sent":
            raise HTTPException(409, "На это приглашение уже ответили")
        db.execute(
            """UPDATE invitations SET status=?,share_consent=?,responded_at=datetime('now')
               WHERE id=? AND candidate_id=?""",
            (data.decision, int(data.decision == "accepted" and data.share_consent), invitation_id, user["id"]),
        )
        from .release02 import enqueue_notice
        employer = db.execute("SELECT employer_id FROM invitations WHERE id=?", (invitation_id,)).fetchone()
        enqueue_notice(db, employer["employer_id"], "invitation_response", "Ответ кандидата — СТАЖНО",
                       f"Кандидат ответил на приглашение: {data.decision}. Откройте кабинет.")
        # Commit before the HTTP response: a new dashboard request may arrive immediately.
        db.commit()
        return {"ok": True}

    @app.get("/api/employer/invitations")
    def employer_invitations(user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "employer")
        rows = db.execute(
            """SELECT i.*,v.title AS vacancy_title,u.name AS candidate_name,
               u.email AS candidate_email,u.phone AS candidate_phone,
               c.profession AS candidate_profession,a.id AS application_id
               FROM invitations i JOIN vacancies v ON v.id=i.vacancy_id
               JOIN users u ON u.id=i.candidate_id
               JOIN candidate_profiles c ON c.user_id=i.candidate_id
               LEFT JOIN job_applications a
                    ON a.vacancy_id=i.vacancy_id AND a.candidate_id=i.candidate_id
               WHERE i.employer_id=? ORDER BY i.id DESC""", (user["id"],)
        ).fetchall()
        from .release02 import introduction_stage, interaction_timeline
        result = []
        for row in rows:
            item = {key: row[key] for key in (
                "id", "vacancy_id", "candidate_id", "status", "price_rub",
                "contact_shared", "vacancy_title", "candidate_profession", "created_at",
            )}
            item["introduction_stage"] = introduction_stage(row["status"], row["contact_shared"])
            item["timeline"] = interaction_timeline(db, row["application_id"], row["id"])
            if row["contact_shared"] and row["share_consent"]:
                item["contact"] = {
                    "name": row["candidate_name"],
                    "email": row["candidate_email"],
                    "phone": row["candidate_phone"],
                }
            result.append(item)
        return {"invitations": result}

    @app.post("/api/employer/invitations/{invitation_id}/demo-pay")
    def demo_pay(invitation_id: int, user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        """SIMULATION ONLY: records a fake transaction. Does not collect money or card details."""
        allowed(user, "employer")
        row = db.execute(
            "SELECT * FROM invitations WHERE id=? AND employer_id=?", (invitation_id, user["id"])
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Приглашение не найдено")
        if row["status"] != "accepted" or not row["share_consent"]:
            raise HTTPException(409, "Кандидат ещё не согласился на знакомство")
        db.execute(
            "INSERT OR IGNORE INTO demo_transactions(invitation_id,amount_rub) VALUES(?,?)",
            (invitation_id, row["price_rub"]),
        )
        first_unlock = db.execute("SELECT changes()").fetchone()[0] == 1
        db.execute("UPDATE invitations SET contact_shared=1 WHERE id=?", (invitation_id,))
        if first_unlock:
            from .release02 import enqueue_notice
            enqueue_notice(db, row["candidate_id"], "contact_opened",
                           "Знакомство состоялось — СТАЖНО",
                           "Работодатель завершил демонстрационное знакомство. Контакт открыт в тестовом режиме.")
        contact = db.execute("SELECT name,email,phone FROM users WHERE id=?", (row["candidate_id"],)).fetchone()
        # Commit before the HTTP response: a new dashboard request may arrive immediately.
        db.commit()
        return {"ok": True, "mode": "demo_only", "amount_rub": row["price_rub"], "contact": dict(contact)}

    @app.get("/api/admin/stats")
    def stats(user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "admin")
        def count(query: str) -> int:
            return db.execute(query).fetchone()[0]
        return {
            "candidates": count("SELECT COUNT(*) FROM users WHERE role='candidate'"),
            "employers": count("SELECT COUNT(*) FROM users WHERE role='employer'"),
            "open_vacancies": count("SELECT COUNT(*) FROM vacancies WHERE status='open'"),
            "applications_total": count("SELECT COUNT(*) FROM job_applications"),
            "applications_active": count("SELECT COUNT(*) FROM job_applications WHERE status IN ('applied','reviewing','interview')"),
            "applications_withdrawn": count("SELECT COUNT(*) FROM job_applications WHERE status='withdrawn'"),
            "invitations": count("SELECT COUNT(*) FROM invitations"),
            "confirmed": count("SELECT COUNT(*) FROM invitations WHERE status='accepted'"),
            "demo_transactions": count("SELECT COUNT(*) FROM demo_transactions"),
            "demo_turnover_rub": count("SELECT COALESCE(SUM(amount_rub),0) FROM demo_transactions"),
        }

    from .release02 import install_routes
    install_routes(app)
    return app


app = create_app()
