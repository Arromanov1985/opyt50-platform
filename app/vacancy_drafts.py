"""Private server-side employer vacancy drafts, never candidate-visible."""
from __future__ import annotations

import json
import sqlite3

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

# Only form fields are persisted; no browser storage or contact data.
DRAFT_FIELDS = (
    "title", "city", "salary_min", "salary_max", "schedule", "employment",
    "skills", "responsibilities", "requirements", "conditions",
)
DRAFT_LIMITS = {
    "title": 120, "city": 100, "schedule": 40, "employment": 40,
    "skills": 300, "responsibilities": 400, "requirements": 300,
    "conditions": 350,
}


class DraftIn(BaseModel):
    fields: dict = Field(default_factory=dict)
    expected_version: int | None = Field(default=None, ge=1)

    @staticmethod
    def clean(fields: dict) -> dict:
        if set(fields) - set(DRAFT_FIELDS):
            raise HTTPException(422, "Неизвестные поля черновика")
        result = {}
        for name, value in fields.items():
            if name in ("salary_min", "salary_max"):
                if not isinstance(value, (int, str)) or isinstance(value, bool):
                    raise HTTPException(422, "Некорректная сумма")
                if str(value).strip() and (not str(value).isdigit() or int(value) > 10_000_000):
                    raise HTTPException(422, "Некорректная сумма")
                result[name] = str(value)
            else:
                if not isinstance(value, str) or len(value) > DRAFT_LIMITS[name]:
                    raise HTTPException(422, "Слишком длинное поле черновика")
                result[name] = value
        return result


def register_draft_routes(app, active_user, get_connection, allowed, VacancyIn):
    def owned(db, user_id: int, draft_id: int):
        row = db.execute(
            "SELECT * FROM vacancy_drafts WHERE id=? AND employer_id=?",
            (draft_id, user_id),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Черновик не найден")
        return row

    def output(row):
        return {
            "id": row["id"], "fields": json.loads(row["fields_json"]),
            "version": row["version"], "published_vacancy_id": row["published_vacancy_id"],
            "updated_at": row["updated_at"],
        }

    @app.get("/api/employer/vacancy-drafts")
    def list_drafts(user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "employer")
        rows = db.execute(
            """SELECT * FROM vacancy_drafts WHERE employer_id=?
               AND published_vacancy_id IS NULL ORDER BY id DESC""",
            (user["id"],),
        ).fetchall()
        return {"drafts": [output(row) for row in rows]}

    @app.post("/api/employer/vacancy-drafts", status_code=201)
    def create_draft(data: DraftIn, user: dict = Depends(active_user), db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "employer")
        fields = DraftIn.clean(data.fields)
        cursor = db.execute(
            "INSERT INTO vacancy_drafts(employer_id,fields_json) VALUES(?,?)",
            (user["id"], json.dumps(fields, ensure_ascii=False)),
        )
        db.commit()
        row = owned(db, user["id"], cursor.lastrowid)
        return output(row)

    @app.put("/api/employer/vacancy-drafts/{draft_id}")
    def save_draft(draft_id: int, data: DraftIn, user: dict = Depends(active_user),
                   db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "employer")
        if data.expected_version is None:
            raise HTTPException(422, "Требуется версия черновика")
        fields = DraftIn.clean(data.fields)
        result = db.execute(
            """UPDATE vacancy_drafts SET fields_json=?,version=version+1,
                 updated_at=datetime('now')
               WHERE id=? AND employer_id=? AND version=?
                 AND published_vacancy_id IS NULL""",
            (json.dumps(fields, ensure_ascii=False), draft_id, user["id"], data.expected_version),
        )
        if result.rowcount != 1:
            row = owned(db, user["id"], draft_id)
            if row["published_vacancy_id"] is not None:
                raise HTTPException(409, "Черновик уже опубликован")
            raise HTTPException(409, "Черновик изменён на другом устройстве. Обновите список.")
        db.commit()
        return output(owned(db, user["id"], draft_id))

    @app.delete("/api/employer/vacancy-drafts/{draft_id}")
    def delete_draft(draft_id: int, user: dict = Depends(active_user),
                     db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "employer")
        result = db.execute(
            "DELETE FROM vacancy_drafts WHERE id=? AND employer_id=? AND published_vacancy_id IS NULL",
            (draft_id, user["id"]),
        )
        if result.rowcount != 1:
            raise HTTPException(404, "Неопубликованный черновик не найден")
        db.commit()
        return {"ok": True}

    @app.post("/api/employer/vacancy-drafts/{draft_id}/publish")
    def publish_draft(draft_id: int, user: dict = Depends(active_user),
                      db: sqlite3.Connection = Depends(get_connection)):
        allowed(user, "employer")
        row = owned(db, user["id"], draft_id)
        if row["published_vacancy_id"] is not None:
            return {"ok": True, "id": row["published_vacancy_id"], "already_published": True}
        fields = json.loads(row["fields_json"])
        description = "\n".join((
            "Обязанности:", fields.get("responsibilities", ""), "",
            "Требования:", fields.get("requirements", ""), "",
            "Условия работы:", fields.get("conditions", ""),
        ))
        data = VacancyIn(
            title=fields.get("title", ""), city=fields.get("city", ""),
            salary_min=int(fields.get("salary_min") or 0),
            salary_max=int(fields.get("salary_max") or 0),
            schedule=fields.get("schedule") or "Любой",
            employment=fields.get("employment") or "Любая",
            skills=fields.get("skills", ""), description=description,
        )
        # Lock the draft before the vacancy insert. The optimistic UPDATE ensures
        # only one concurrent publish wins; the other transaction rolls back.
        claim = db.execute(
            """UPDATE vacancy_drafts SET version=version+1,updated_at=datetime('now')
               WHERE id=? AND employer_id=? AND version=? AND published_vacancy_id IS NULL""",
            (draft_id, user["id"], row["version"]),
        )
        if claim.rowcount != 1:
            raise HTTPException(409, "Черновик уже изменён или опубликован")
        cursor = db.execute(
            """INSERT INTO vacancies(employer_id,title,city,salary_min,salary_max,schedule,employment,skills,description)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (user["id"], data.title.strip(), data.city.strip(), data.salary_min,
             data.salary_max, data.schedule, data.employment, data.skills.strip(), data.description.strip()),
        )
        from .release02 import utc_now_text
        db.execute(
            "INSERT INTO vacancy_moderation(vacancy_id,status,reason,updated_at) VALUES(?,?,?,?)",
            (cursor.lastrowid, "approved", "", utc_now_text()),
        )
        db.execute(
            "UPDATE vacancy_drafts SET published_vacancy_id=? WHERE id=? AND employer_id=?",
            (cursor.lastrowid, draft_id, user["id"]),
        )
        db.commit()
        return {"ok": True, "id": cursor.lastrowid, "already_published": False}
