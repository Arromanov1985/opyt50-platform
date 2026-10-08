"""OПЫТ 50+ MVP: self-service hiring with confirmed candidate introductions.

No paid services, real payments, or automated age-based screening in this release.
"""

from __future__ import annotations

import base64
import binascii
import os
import secrets
import re
import sqlite3
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator

from .db import database, init_db
from .matching import lead_price, match_candidate
from .security import COOKIE_NAME, SESSION_SECONDS, issue_session, make_password_hash, token_hash, verify_password

BASE = Path(__file__).resolve().parent
DEFAULT_DB = os.getenv("OPYT50_DB_PATH", str(BASE.parent / "data" / "opyt50.db"))
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
SCHEDULES = {"Любой", "Полный день", "Сменный", "Гибкий", "Удалённо"}
EMPLOYMENTS = {"Любая", "Полная", "Частичная", "Проектная"}


class Registration(BaseModel):
    role: Literal["candidate", "employer"]
    name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=10, max_length=128)
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
    email: str
    password: str


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
        return self


class InvitationIn(BaseModel):
    vacancy_id: int = Field(gt=0)
    candidate_id: int = Field(gt=0)


class InvitationReply(BaseModel):
    decision: Literal["accepted", "declined"]
    share_consent: bool = False


class VacancyStatus(BaseModel):
    status: Literal["open", "closed"]


def utc_expiry() -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=SESSION_SECONDS)).isoformat()


def get_connection(request: Request):
    with database(request.app.state.db_path) as connection:
        yield connection


def active_user(request: Request, db: sqlite3.Connection = Depends(get_connection)) -> dict:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "Нужно войти в аккаунт")
    row = db.execute(
        """SELECT u.id,u.email,u.name,u.phone,u.role FROM sessions s
           JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?""",
        (token_hash(token), datetime.now(timezone.utc).isoformat()),
    ).fetchone()
    if row is None:
        raise HTTPException(401, "Сессия завершена. Войдите снова")
    # User controls exist after the 0.2 migration; deny disabled accounts on every authenticated request.
    control = db.execute("SELECT status FROM account_controls WHERE user_id=?", (row["id"],)).fetchone()
    if control is not None and control["status"] == "disabled":
        raise HTTPException(403, "Аккаунт временно заблокирован")
    return dict(row)


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
    token, digest = issue_session()
    db.execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)", (digest, user_id, utc_expiry()))
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=os.getenv("OPYT50_COOKIE_SECURE", "0") == "1",
        samesite="lax",
        max_age=SESSION_SECONDS,
        path="/",
    )


def create_app(db_path: str | None = None) -> FastAPI:
    db_location = db_path or DEFAULT_DB

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(app.state.db_path)
        from .release02 import init_release02
        init_release02(app.state.db_path)
        yield

    app = FastAPI(title="ОПЫТ 50+", version="0.2.0", lifespan=lifespan, docs_url="/api/docs")
    app.state.db_path = db_location
    app.state.auth_attempts = defaultdict(deque)
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
                    headers={"WWW-Authenticate": 'Basic realm="OPYTNO Preview"', "Cache-Control": "no-store"},
                )
        # A custom header forces cross-origin browser requests to preflight; no CORS enabled.
        if request.url.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if request.headers.get("x-requested-with") != "OPYT50":
                return Response(status_code=403, content="Request header is required")
        if request.url.path in {"/api/register", "/api/login"} and request.method == "POST":
            key = (request.client.host if request.client else "unknown", request.url.path)
            queue = request.app.state.auth_attempts[key]
            now = time.monotonic()
            while queue and queue[0] < now - 600:
                queue.popleft()
            if len(queue) >= 30:
                return Response(status_code=429, content="Слишком много попыток. Повторите позже")
            queue.append(now)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(BASE / "static" / "index.html")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "0.2.0", "payments": "demo_only"}

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
            enqueue_notice(db, user_id, "welcome", "Добро пожаловать в ОПЫТНО.РФ", "Ваш аккаунт создан. Письмо записано в тестовую очередь и НЕ отправлено.")
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Этот email уже зарегистрирован") from None
        return {"user": user_response(dict(db.execute("SELECT id,email,role,name,phone FROM users WHERE id=?", (user_id,)).fetchone()), db)}

    @app.post("/api/login")
    def login(data: Login, request: Request, response: Response, db: sqlite3.Connection = Depends(get_connection)):
        row = db.execute("SELECT * FROM users WHERE email=?", (data.email.strip().casefold(),)).fetchone()
        if row is None or not verify_password(data.password, row["password_hash"]):
            raise HTTPException(401, "Неверный email или пароль")
        block = db.execute("SELECT status FROM account_controls WHERE user_id=?", (row["id"],)).fetchone()
        if block is not None and block["status"] == "disabled":
            raise HTTPException(403, "Аккаунт временно заблокирован")
        add_session(db, response, row["id"])
        return {"user": user_response(dict(row), db)}

    @app.post("/api/logout")
    def logout(request: Request, response: Response, db: sqlite3.Connection = Depends(get_connection)):
        token = request.cookies.get(COOKIE_NAME)
        if token:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),))
        response.delete_cookie(COOKIE_NAME, path="/")
        return {"ok": True}

    @app.get("/api/me")
    def me(user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        return {"user": user_response(user, db)}

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
        return {"ok": True, "profile": candidate_view(db, user["id"])}

    @app.get("/api/jobs")
    def jobs(q: str = "", city: str = "", salary_min: int = 0, schedule: str = "",
             employment: str = "", db: sqlite3.Connection = Depends(get_connection)):
        """Public job search: profession/title, location, minimum acceptable salary, schedule."""
        if salary_min < 0 or salary_min > 10_000_000 or len(q) > 120 or len(city) > 100:
            raise HTTPException(422, "Проверьте параметры поиска")
        if schedule and schedule not in SCHEDULES:
            raise HTTPException(422, "Недопустимый график")
        if employment and employment not in EMPLOYMENTS:
            raise HTTPException(422, "Недопустимая занятость")
        sql = """SELECT v.*,e.company_name FROM vacancies v JOIN employer_profiles e
                 ON e.user_id=v.employer_id WHERE v.status='open'"""
        params: list = []
        if q.strip():
            # instr on Unicode-casefolded text ensures correct Cyrillic search.
            sql += " AND (instr(unicode_fold(v.title), ?) > 0 OR instr(unicode_fold(v.skills), ?) > 0)"
            needle = q.strip().casefold()
            params.extend([needle, needle])
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
        sql += " ORDER BY v.id DESC LIMIT 100"
        return {"jobs": [dict(row) for row in db.execute(sql, params).fetchall()]}

    @app.get("/api/candidate/jobs")
    def matching_jobs(user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "candidate")
        profile = candidate_view(db, user["id"])
        # Attach only the current candidate's application status. This keeps
        # the recommendation card authoritative across sessions and reloads;
        # no other candidate's application details are exposed.
        jobs_rows = db.execute(
            """SELECT v.*,e.company_name,
                      a.id AS application_id, a.status AS application_status
               FROM vacancies v
               JOIN employer_profiles e ON e.user_id=v.employer_id
               LEFT JOIN job_applications a
                    ON a.vacancy_id=v.id AND a.candidate_id=?
               WHERE v.status='open' LIMIT 500""",
            (user["id"],),
        ).fetchall()
        matches = []
        for row in jobs_rows:
            result = match_candidate(dict(row), profile)
            if result:
                matches.append({**dict(row), **result})
        return {"jobs": sorted(matches, key=lambda x: (-x["score"], -x["id"]))[:50]}

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
        return {"id": cursor.lastrowid, "ok": True}

    @app.get("/api/employer/vacancies")
    def employer_jobs(user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "employer")
        rows = db.execute("SELECT * FROM vacancies WHERE employer_id=? ORDER BY id DESC", (user["id"],)).fetchall()
        return {"jobs": [dict(row) for row in rows]}

    @app.patch("/api/employer/vacancies/{job_id}/status")
    def set_vacancy_status(
        job_id: int, data: VacancyStatus, user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)
    ):
        allowed(user, "employer")
        changed = db.execute("UPDATE vacancies SET status=? WHERE id=? AND employer_id=?", (data.status, job_id, user["id"]))
        if changed.rowcount == 0:
            raise HTTPException(404, "Вакансия не найдена")
        return {"ok": True}

    @app.get("/api/employer/vacancies/{job_id}/matches")
    def job_matches(job_id: int, user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "employer")
        vacancy = db.execute("SELECT * FROM vacancies WHERE id=? AND employer_id=?", (job_id, user["id"])).fetchone()
        if vacancy is None:
            raise HTTPException(404, "Вакансия не найдена")
        rows = db.execute(
            """SELECT c.*,u.id AS candidate_id FROM candidate_profiles c
               JOIN users u ON u.id=c.user_id WHERE c.is_active=1 AND u.role='candidate'"""
        ).fetchall()
        matches = []
        for row in rows:
            score = match_candidate(dict(vacancy), dict(row))
            if score:
                # Privacy: no name, phone, email or freeform about before candidate consent + demo payment.
                matches.append({k: row[k] for k in ("candidate_id", "profession", "city", "skills", "salary_min", "schedule", "employment")} | score)
        return {"matches": sorted(matches, key=lambda x: (-x["score"], x["candidate_id"]))[:50]}

    @app.post("/api/employer/invitations", status_code=201)
    def invite(data: InvitationIn, user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "employer")
        vacancy = db.execute(
            "SELECT * FROM vacancies WHERE id=? AND employer_id=? AND status='open'", (data.vacancy_id, user["id"])
        ).fetchone()
        if vacancy is None:
            raise HTTPException(404, "Нет активной вакансии с таким ID")
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
        enqueue_notice(db, data.candidate_id, "invitation", "Приглашение от компании — ОПЫТНО.РФ",
                       f"Вы получили приглашение на вакансию «{vacancy['title']}». Откройте личный кабинет.")
        return {"id": cursor.lastrowid, "ok": True}

    @app.get("/api/candidate/invitations")
    def candidate_invitations(user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "candidate")
        rows = db.execute(
            """SELECT i.id,i.status,i.share_consent,i.contact_shared,i.created_at,
               v.title,v.city,v.salary_min,v.salary_max,v.schedule,v.employment,v.description,
               e.company_name FROM invitations i JOIN vacancies v ON i.vacancy_id=v.id
               JOIN employer_profiles e ON e.user_id=i.employer_id
               WHERE i.candidate_id=? ORDER BY i.id DESC""", (user["id"],)
        ).fetchall()
        return {"invitations": [dict(row) for row in rows]}

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
        enqueue_notice(db, employer["employer_id"], "invitation_response", "Ответ кандидата — ОПЫТНО.РФ",
                       f"Кандидат ответил на приглашение: {data.decision}. Откройте кабинет.")
        return {"ok": True}

    @app.get("/api/employer/invitations")
    def employer_invitations(user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "employer")
        rows = db.execute(
            """SELECT i.*,v.title AS vacancy_title,u.name AS candidate_name,u.email AS candidate_email,
               u.phone AS candidate_phone,c.profession AS candidate_profession
               FROM invitations i JOIN vacancies v ON v.id=i.vacancy_id
               JOIN users u ON u.id=i.candidate_id
               JOIN candidate_profiles c ON c.user_id=i.candidate_id
               WHERE i.employer_id=? ORDER BY i.id DESC""", (user["id"],)
        ).fetchall()
        result = []
        for row in rows:
            item = {key: row[key] for key in (
                "id", "vacancy_id", "candidate_id", "status", "price_rub", "contact_shared",
                "vacancy_title", "candidate_profession", "created_at",
            )}
            if row["contact_shared"] and row["share_consent"]:
                item["contact"] = {"name": row["candidate_name"], "email": row["candidate_email"], "phone": row["candidate_phone"]}
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
        db.execute("UPDATE invitations SET contact_shared=1 WHERE id=?", (invitation_id,))
        contact = db.execute("SELECT name,email,phone FROM users WHERE id=?", (row["candidate_id"],)).fetchone()
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
