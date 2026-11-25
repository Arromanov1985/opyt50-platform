"""Candidate-owned search presets and opt-in, in-app-only discovery alerts.

Compare the current first 100 public results with explicitly reviewed IDs.
A vacancy may newly enter the result set after moderation, editing or reopening;
this is not a publication timestamp or a history of individual page views.
No worker, push service, email delivery, visitor tracking or profile disclosure.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, StrictBool, StrictInt, field_validator

from .privacy_restriction import restriction_is_active

MAX_SEARCHES = 10
RESULT_LIMIT = 100
SAVED_SEARCH_DDL = (
    """CREATE TABLE IF NOT EXISTS candidate_saved_searches (
        candidate_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        search_key TEXT NOT NULL,
        slot INTEGER NOT NULL CHECK(slot BETWEEN 1 AND 10),
        filter_key TEXT NOT NULL,
        q TEXT NOT NULL DEFAULT '',
        city TEXT NOT NULL DEFAULT '',
        salary_min INTEGER NOT NULL DEFAULT 0 CHECK(salary_min BETWEEN 0 AND 10000000),
        schedule TEXT NOT NULL DEFAULT '',
        employment TEXT NOT NULL DEFAULT '',
        alerts_enabled INTEGER NOT NULL DEFAULT 0 CHECK(alerts_enabled IN (0,1)),
        reviewed_ids_json TEXT NOT NULL DEFAULT '[]',
        revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY(candidate_id,search_key),
        UNIQUE(candidate_id,slot),
        UNIQUE(candidate_id,filter_key)
    )""",
)
FILTER_FIELDS = ("q", "city", "salary_min", "schedule", "employment")


class SearchIn(BaseModel):
    model_config = {"extra": "forbid"}
    q: str = Field(default="", max_length=120)
    city: str = Field(default="", max_length=100)
    salary_min: StrictInt = Field(default=0, ge=0, le=10_000_000)
    schedule: str = Field(default="", max_length=30)
    employment: str = Field(default="", max_length=30)
    alerts_enabled: StrictBool = False

    @field_validator("q", "city", "schedule", "employment")
    @classmethod
    def clean_text(cls, value):
        return value.strip()


class AlertChangeIn(BaseModel):
    model_config = {"extra": "forbid"}
    enabled: StrictBool
    revision: StrictInt = Field(gt=0)


class ReviewIn(BaseModel):
    model_config = {"extra": "forbid"}
    revision: StrictInt = Field(gt=0)
    vacancy_ids: list[Annotated[StrictInt, Field(gt=0)]] = Field(max_length=RESULT_LIMIT)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _filters(row) -> dict:
    return {name: row[name] for name in FILTER_FIELDS}


def _ids(jobs) -> set[int]:
    return {int(job["id"]) for job in jobs[:RESULT_LIMIT]}


def _reviewed(row) -> set[int]:
    return {int(item) for item in json.loads(row["reviewed_ids_json"])}


def _encode_ids(ids: set[int]) -> str:
    return json.dumps(sorted(ids), separators=(",", ":"))


def _filter_key(filters: dict) -> str:
    normalized = {key: value.casefold() if key in {"q", "city"} else value
                  for key, value in filters.items()}
    return hashlib.sha256(json.dumps(normalized, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _owned(db, owner: int, key: str):
    if len(key) != 32 or any(c not in "0123456789abcdef" for c in key):
        raise HTTPException(404, "Поиск не найден")
    row = db.execute(
        "SELECT * FROM candidate_saved_searches WHERE candidate_id=? AND search_key=?",
        (owner, key),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Поиск не найден")
    return row


def _serialize(row, jobs=None) -> dict:
    active = bool(row["alerts_enabled"])
    new_count = len(_ids(jobs) - _reviewed(row)) if active and jobs is not None else None
    return {
        "key": row["search_key"],
        "filters": _filters(row),
        "alerts_enabled": active,
        "revision": row["revision"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "new_count": new_count,
    }


def _assert_unrestricted(db, owner: int) -> None:
    if restriction_is_active(db, owner):
        raise HTTPException(409, "Подбор приостановлен по обращению о персональных данных")


def _update(db, owner, row, *, enabled, reviewed, revision):
    if row["revision"] != revision:
        raise HTTPException(409, "Поиск уже изменился. Обновите список.")
    changed = db.execute(
        """UPDATE candidate_saved_searches
           SET alerts_enabled=?,reviewed_ids_json=?,revision=revision+1,updated_at=?
           WHERE candidate_id=? AND search_key=? AND revision=?""",
        (int(enabled), _encode_ids(reviewed), _now(), owner, row["search_key"], revision),
    )
    if changed.rowcount != 1:
        raise HTTPException(409, "Поиск уже изменился. Обновите список.")
    db.commit()
    return _owned(db, owner, row["search_key"])


def install_saved_search_routes(app, public_jobs, active_user, get_connection, allowed):
    """Use the same validated query as the public search, including privacy gates."""
    from .main import CONTACT_EMAIL_PATTERN, CONTACT_PHONE_PATTERN

    def match(db, filters):
        return public_jobs(db=db, sort="recent", **filters)["jobs"][:RESULT_LIMIT]

    @app.get("/api/candidate/saved-searches")
    def list_searches(user=Depends(active_user), db=Depends(get_connection)):
        allowed(user, "candidate")
        owner = user["id"]
        restricted = restriction_is_active(db, owner)
        rows = db.execute(
            """SELECT * FROM candidate_saved_searches
               WHERE candidate_id=? ORDER BY slot""", (owner,),
        ).fetchall()
        return {
            "searches": [
                _serialize(row, match(db, _filters(row))
                           if row["alerts_enabled"] and not restricted else None)
                for row in rows
            ],
            "restricted": restricted,
            "limit": MAX_SEARCHES,
            "result_limit": RESULT_LIMIT,
        }

    @app.post("/api/candidate/saved-searches", status_code=201)
    def create_search(data: SearchIn, user=Depends(active_user), db=Depends(get_connection)):
        allowed(user, "candidate")
        owner = user["id"]
        _assert_unrestricted(db, owner)
        filters = _filters(data.model_dump())
        if filters["schedule"] == "Любой":
            filters["schedule"] = ""
        if filters["employment"] == "Любая":
            filters["employment"] = ""
        for value in (filters["q"], filters["city"]):
            if CONTACT_EMAIL_PATTERN.search(value) or CONTACT_PHONE_PATTERN.search(value):
                raise HTTPException(422, "Укажите профессию и город без контактных данных")
        jobs = match(db, filters)
        filter_key = _filter_key(filters)
        rows = db.execute(
            "SELECT * FROM candidate_saved_searches WHERE candidate_id=?", (owner,),
        ).fetchall()
        existing = next((row for row in rows if row["filter_key"] == filter_key), None)
        if existing is not None:
            return {"search": _serialize(existing, jobs), "created": False}
        used = {row["slot"] for row in rows}
        slot = next((i for i in range(1, MAX_SEARCHES + 1) if i not in used), None)
        if slot is None:
            raise HTTPException(409, "Можно сохранить не более 10 поисков. Удалите ненужный.")
        key = secrets.token_hex(16)
        now = _now()
        created = db.execute(
            """INSERT INTO candidate_saved_searches(
                 candidate_id,search_key,slot,filter_key,q,city,salary_min,schedule,employment,
                 alerts_enabled,reviewed_ids_json,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING""",
            (owner, key, slot, filter_key, *(filters[name] for name in FILTER_FIELDS),
             int(data.alerts_enabled), _encode_ids(_ids(jobs)) if data.alerts_enabled else "[]",
             now, now),
        )
        if created.rowcount != 1:
            existing = db.execute(
                "SELECT * FROM candidate_saved_searches WHERE candidate_id=? AND filter_key=?",
                (owner, filter_key),
            ).fetchone()
            if existing is not None:
                return {"search": _serialize(existing, jobs), "created": False}
            raise HTTPException(409, "Список поисков изменился. Повторите сохранение.")
        db.commit()
        return {"search": _serialize(_owned(db, owner, key), jobs), "created": True}

    @app.get("/api/candidate/saved-searches/{key}/results")
    def search_results(key: str, user=Depends(active_user), db=Depends(get_connection)):
        allowed(user, "candidate")
        owner = user["id"]
        _assert_unrestricted(db, owner)
        row = _owned(db, owner, key)
        jobs = match(db, _filters(row))
        new_ids = sorted(_ids(jobs) - _reviewed(row)) if row["alerts_enabled"] else []
        return {"search": _serialize(row, jobs), "jobs": jobs,
                "new_ids": new_ids, "result_limit": RESULT_LIMIT}

    @app.patch("/api/candidate/saved-searches/{key}/alerts")
    def change_alerts(key: str, data: AlertChangeIn,
                      user=Depends(active_user), db=Depends(get_connection)):
        allowed(user, "candidate")
        owner = user["id"]
        _assert_unrestricted(db, owner)
        row = _owned(db, owner, key)
        if row["revision"] != data.revision:
            raise HTTPException(409, "Поиск уже изменился. Обновите список.")
        jobs = match(db, _filters(row)) if data.enabled else None
        # Resuming starts from the current result set; no backlog or email.
        if bool(row["alerts_enabled"]) != data.enabled:
            row = _update(db, owner, row, enabled=data.enabled,
                          reviewed=_ids(jobs) if data.enabled else set(),
                          revision=data.revision)
        return {"search": _serialize(row, jobs)}

    @app.post("/api/candidate/saved-searches/{key}/review")
    def review_results(key: str, data: ReviewIn,
                       user=Depends(active_user), db=Depends(get_connection)):
        allowed(user, "candidate")
        owner = user["id"]
        _assert_unrestricted(db, owner)
        row = _owned(db, owner, key)
        if not row["alerts_enabled"]:
            raise HTTPException(409, "Уведомления по этому поиску выключены")
        jobs = match(db, _filters(row))
        current = _ids(jobs)
        # Only IDs the caller explicitly reviewed, still in current results.
        # A vacancy arriving between display and acknowledgement stays new.
        seen = current & (_reviewed(row) | set(data.vacancy_ids))
        row = _update(db, owner, row, enabled=True, reviewed=seen, revision=data.revision)
        return {"search": _serialize(row, jobs)}

    @app.delete("/api/candidate/saved-searches/{key}")
    def delete_search(key: str, user=Depends(active_user), db=Depends(get_connection)):
        allowed(user, "candidate")
        owner = user["id"]
        _assert_unrestricted(db, owner)
        _owned(db, owner, key)
        db.execute(
            "DELETE FROM candidate_saved_searches WHERE candidate_id=? AND search_key=?",
            (owner, key),
        )
        db.commit()
        return {"ok": True}
