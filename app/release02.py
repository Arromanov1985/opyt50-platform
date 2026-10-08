"""Release 0.2 routes. Demo-only mail outbox: no external delivery or personal-data rollout."""
from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from .db import database
from .security import make_password_hash, token_hash


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
"""


def init_release02(path: str) -> None:
    with database(path) as db:
        db.executescript(MIGRATION)


def enqueue_notice(db: sqlite3.Connection, user_id: int, event: str, subject: str, message: str) -> None:
    """Write ONLY to local demo outbox; SMTP/API transport is deliberately absent."""
    user = db.execute("SELECT email FROM users WHERE id=?", (user_id,)).fetchone()
    if user is not None:
        db.execute("INSERT INTO email_outbox(to_email,event,subject,body) VALUES(?,?,?,?)",
                   (user["email"], event, subject, message))


class ApplicationIn(BaseModel):
    vacancy_id: int = Field(gt=0)


class ApplicationStatusIn(BaseModel):
    status: Literal["reviewing", "interview", "rejected", "hired"]


class AccountStatusIn(BaseModel):
    status: Literal["active", "disabled"]


class VacancyAdminStatusIn(BaseModel):
    status: Literal["open", "closed"]


class EmailTokenIn(BaseModel):
    token: str = Field(min_length=20, max_length=256)


class PasswordRequestIn(BaseModel):
    email: str = Field(min_length=5, max_length=254)


class PasswordResetIn(EmailTokenIn):
    password: str = Field(min_length=10, max_length=128)


def issue_email_token(db: sqlite3.Connection, user_id: int, purpose: str) -> None:
    token = secrets.token_urlsafe(40)
    expires = (datetime.now(timezone.utc) + timedelta(minutes=30 if purpose == "reset" else 1440)).isoformat()
    db.execute("DELETE FROM email_tokens WHERE user_id=? AND purpose=?", (user_id, purpose))
    db.execute("INSERT INTO email_tokens(token_hash,user_id,purpose,expires_at) VALUES(?,?,?,?)",
               (token_hash(token), user_id, purpose, expires))
    # No network requests, no token in HTTP response or application logs.
    route = "reset" if purpose == "reset" else "verify"
    enqueue_notice(db, user_id, f"account_{purpose}", "ОПЫТНО.РФ — подтверждение",
                   f"ДЕМО. Ссылка для проверки: /?account_action={route}&token={token} (30 мин для сброса, 24 ч для подтверждения)")


def redeem_token(db: sqlite3.Connection, raw: str, purpose: str) -> sqlite3.Row:
    row = db.execute("SELECT * FROM email_tokens WHERE token_hash=? AND purpose=? AND used_at IS NULL",
                     (token_hash(raw), purpose)).fetchone()
    if row is None or datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
        raise HTTPException(400, "Ссылка недействительна или срок истёк")
    db.execute("UPDATE email_tokens SET used_at=datetime('now') WHERE token_hash=?", (row["token_hash"],))
    return row


def introduction_stage(status: str | None, contact_shared: int | bool | None) -> str | None:
    """Single, non-sensitive workflow status for all dashboards."""
    if contact_shared:
        return "introduced"
    return {"sent": "awaiting_consent", "accepted": "consented", "declined": "declined"}.get(status)


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
            entries.append((row["created_at"], row["id"], {
                "event": row["event"], "created_at": row["created_at"]
            }))
    if invitation_id is not None:
        invitation = db.execute(
            """SELECT status,contact_shared,created_at,responded_at
               FROM invitations WHERE id=?""", (invitation_id,)
        ).fetchone()
        if invitation:
            entries.append((invitation["created_at"], 1000000, {
                "event": "invitation_sent", "created_at": invitation["created_at"]
            }))
            if invitation["responded_at"] and invitation["status"] in ("accepted", "declined"):
                entries.append((invitation["responded_at"], 2000000, {
                    "event": "invitation_accepted" if invitation["status"] == "accepted" else "invitation_declined",
                    "created_at": invitation["responded_at"]
                }))
            if invitation["contact_shared"]:
                txn = db.execute(
                    "SELECT created_at FROM demo_transactions WHERE invitation_id=?",
                    (invitation_id,),
                ).fetchone()
                if txn:
                    entries.append((txn["created_at"], 3000000, {
                        "event": "contact_opened", "created_at": txn["created_at"]
                    }))
    # SQLite timestamps are second-resolution; an explicit sequence makes
    # events from one request deterministic, without relying on client clocks.
    entries.sort(key=lambda row: (row[0], row[1]))
    return [entry for _, __, entry in entries]


def install_routes(app) -> None:
    # Imported here to avoid a circular module initialization.
    from .main import active_user, allowed, candidate_view, get_connection

    @app.get("/api/jobs/{job_id}")
    def job_detail(job_id: int, db: sqlite3.Connection = Depends(get_connection)):
        row = db.execute("""SELECT v.*,e.company_name FROM vacancies v
                            JOIN employer_profiles e ON e.user_id=v.employer_id
                            WHERE v.id=? AND v.status='open'""", (job_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Вакансия не найдена или закрыта")
        return {"job": dict(row)}

    @app.get("/api/candidate/favorites")
    def favorites(user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "candidate")
        rows = db.execute("""SELECT v.*, e.company_name FROM candidate_favorites f
                             JOIN vacancies v ON v.id=f.vacancy_id
                             JOIN employer_profiles e ON e.user_id=v.employer_id
                             WHERE f.candidate_id=? ORDER BY f.created_at DESC,v.id DESC""", (user["id"],)).fetchall()
        return {"jobs": [dict(r) for r in rows]}

    @app.post("/api/candidate/favorites/{job_id}", status_code=201)
    def save_favorite(job_id: int, user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "candidate")
        if db.execute("SELECT 1 FROM vacancies WHERE id=? AND status='open'", (job_id,)).fetchone() is None:
            raise HTTPException(404, "Вакансия не найдена")
        db.execute("INSERT OR IGNORE INTO candidate_favorites(candidate_id,vacancy_id) VALUES(?,?)",
                   (user["id"], job_id))
        return {"ok": True}

    @app.delete("/api/candidate/favorites/{job_id}")
    def remove_favorite(job_id: int, user: dict = Depends(active_user),
                        db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "candidate")
        db.execute("DELETE FROM candidate_favorites WHERE candidate_id=? AND vacancy_id=?", (user["id"], job_id))
        return {"ok": True}

    @app.post("/api/candidate/applications", status_code=201)
    def apply(data: ApplicationIn, user: dict = Depends(active_user),
              db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "candidate")
        profile = candidate_view(db, user["id"])
        if profile is None or not profile["profession"] or not profile["city"]:
            raise HTTPException(422, "Сначала заполните профессию и город в профиле")
        job = db.execute("SELECT id,employer_id,title,status FROM vacancies WHERE id=?",
                         (data.vacancy_id,)).fetchone()
        if job is None or job["status"] != "open":
            raise HTTPException(404, "Вакансия закрыта или не найдена")
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
        enqueue_notice(db, job["employer_id"], "new_application", "Новый отклик — ОПЫТНО.РФ",
                       f"Получен обезличенный отклик на вакансию «{job['title']}». Откройте кабинет.")
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
        enqueue_notice(db, item["employer_id"], "application_withdrawn", "Отклик отозван — ОПЫТНО.РФ",
                       f"Отклик на вакансию «{item['title']}» отозван.")
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
                      v.title,v.status AS vacancy_status
               FROM job_applications a JOIN vacancies v ON v.id=a.vacancy_id
               WHERE a.id=? AND v.employer_id=?""",
            (application_id, user["id"]),
        ).fetchone()
        if item is None:
            raise HTTPException(404, "Отклик не найден")
        if item["vacancy_status"] != "open":
            raise HTTPException(409, "Вакансия закрыта")
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
                    "Работодатель заинтересован — ОПЫТНО.РФ",
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
                "Статус отклика — ОПЫТНО.РФ",
                f"Работодатель заинтересовался откликом на «{item['title']}». Откройте кабинет.",
            )
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
        enqueue_notice(db, item["candidate_id"], "application_status", "Статус отклика — ОПЫТНО.РФ",
                       f"Статус отклика на «{item['title']}» изменён на {body.status}. Откройте кабинет.")
        return {"ok": True, "status": body.status}

    @app.get("/api/account/email/status")
    def email_status(user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        row = db.execute("SELECT email_verified FROM account_controls WHERE user_id=?",
                         (user["id"],)).fetchone()
        return {"email_verified": bool(row and row["email_verified"]), "delivery": "demo_outbox_only"}

    @app.post("/api/account/email/request")
    def request_verification(user: dict = Depends(active_user),
                             db: sqlite3.Connection = Depends(get_connection)):
        issue_email_token(db, user["id"], "verify")
        return {"ok": True, "delivery": "demo_outbox_only"}

    @app.post("/api/account/email/confirm")
    def confirm_email(data: EmailTokenIn, db: sqlite3.Connection = Depends(get_connection)):
        row = redeem_token(db, data.token, "verify")
        db.execute("""INSERT INTO account_controls(user_id,email_verified) VALUES(?,1)
                      ON CONFLICT(user_id) DO UPDATE SET email_verified=1""", (row["user_id"],))
        return {"ok": True}

    @app.post("/api/account/password/request")
    def request_reset(data: PasswordRequestIn, db: sqlite3.Connection = Depends(get_connection)):
        row = db.execute("SELECT id FROM users WHERE email=?", (data.email.strip().casefold(),)).fetchone()
        if row:
            issue_email_token(db, row["id"], "reset")
        return {"ok": True, "delivery": "demo_outbox_only"}

    @app.post("/api/account/password/reset")
    def reset_password(data: PasswordResetIn, db: sqlite3.Connection = Depends(get_connection)):
        row = redeem_token(db, data.token, "reset")
        db.execute("UPDATE users SET password_hash=? WHERE id=?",
                   (make_password_hash(data.password), row["user_id"]))
        db.execute("DELETE FROM sessions WHERE user_id=?", (row["user_id"],))
        return {"ok": True}

    @app.get("/api/admin/users")
    def admin_users(user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "admin")
        rows = db.execute("""SELECT u.id,u.name,u.email,u.role,u.created_at,
                             COALESCE(c.status,'active') AS status,
                             COALESCE(c.email_verified,0) AS email_verified
                             FROM users u LEFT JOIN account_controls c ON c.user_id=u.id
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
        return {"ok": True}

    @app.get("/api/admin/vacancies")
    def admin_vacancies(user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "admin")
        rows = db.execute("""SELECT v.id,v.title,v.city,v.status,v.created_at,e.company_name
                             FROM vacancies v JOIN employer_profiles e ON e.user_id=v.employer_id
                             ORDER BY v.id DESC LIMIT 300""").fetchall()
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
        return {"ok": True}

    @app.get("/api/admin/mail-preview")
    def admin_demo_mail(user: dict = Depends(active_user),
                        db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "admin")
        # Never return reset/verification secrets to the public demo admin.
        rows = db.execute("""SELECT id,event,subject,created_at FROM email_outbox
                             ORDER BY id DESC LIMIT 50""").fetchall()
        return {"delivery": "demo_outbox_only", "messages": [dict(r) for r in rows]}
