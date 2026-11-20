"""Product reporting: retained records, date boundaries and truthful outcomes."""
import json
import sqlite3

import pytest

from app.db import SCHEMA
from app.growth_product import product_snapshot
from app.release02 import DIRECT_INTRO_OUTCOME_DDL, MIGRATION


@pytest.fixture
def db():
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        connection.executescript(SCHEMA + MIGRATION)
        for statement in DIRECT_INTRO_OUTCOME_DDL:
            connection.execute(statement)
        yield connection


def user(db, role="candidate", **profile):
    next_id = db.execute("SELECT COALESCE(MAX(id),0)+1 FROM users").fetchone()[0]
    db.execute(
        "INSERT INTO users(id,email,password_hash,role,name,phone) VALUES(?,?,?,?,?,?)",
        (next_id, f"private-{next_id}@example.invalid", "hash", role, "Private name", "+79999999999"),
    )
    if role == "candidate":
        values = {"profession": "Бухгалтер", "city": "Москва", "skills": "Excel",
                  "salary_min": 60000, "about": "Private experience", "is_active": 1}
        values.update(profile)
        db.execute(
            """INSERT INTO candidate_profiles
               (user_id,profession,city,skills,salary_min,about,is_active) VALUES(?,?,?,?,?,?,?)""",
            (next_id, *values.values()),
        )
    return next_id


def vacancy(db, employer, created_at="2026-11-01 00:00:00", status="open"):
    return db.execute(
        """INSERT INTO vacancies(employer_id,title,city,salary_min,salary_max,created_at,status)
           VALUES(?,'Private job','Москва',100,200,?,?)""",
        (employer, created_at, status),
    ).lastrowid


def introduction(db, employer, candidate, *, accepted="2026-11-03 10:00:00",
                 opened="2026-11-04 10:00:00", status="accepted", consent=1, shared=1):
    job = vacancy(db, employer)
    invite = db.execute(
        """INSERT INTO invitations
           (vacancy_id,candidate_id,employer_id,price_rub,status,share_consent,contact_shared,responded_at)
           VALUES(?,?,?,0,?,?,?,?)""",
        (job, candidate, employer, status, consent, shared, accepted),
    ).lastrowid
    if opened:
        db.execute("INSERT INTO demo_transactions(invitation_id,amount_rub,created_at) VALUES(?,0,?)",
                   (invite, opened))
    return invite, job


def application(db, job, candidate, *, created_at="2026-11-01 00:00:00", status="applied",
                event_at=None):
    app_id = db.execute(
        "INSERT INTO job_applications(vacancy_id,candidate_id,status,created_at) VALUES(?,?,?,?)",
        (job, candidate, status, created_at),
    ).lastrowid
    if event_at:
        db.execute("INSERT INTO application_events(application_id,event,created_at) VALUES(?,?,?)",
                   (app_id, status, event_at))
    return app_id


def test_current_profile_snapshot_is_independent_of_reporting_period(db):
    user(db)
    for missing in ("profession", "city", "skills", "about"):
        user(db, **{missing: "   "})
    user(db, salary_min=0)
    user(db, is_active=0)
    disabled = user(db)
    db.execute("INSERT INTO account_controls(user_id,status) VALUES(?,'disabled')", (disabled,))
    user(db, role="employer")
    current = product_snapshot(db, "2000-01-01", "2000-01-01")["current"]
    assert current == {"enabled_candidate_accounts": 7, "completed_active_candidate_profiles": 1}
    assert current == product_snapshot(db, "2026-11-01", "2026-11-20")["current"]


def test_period_boundaries_and_unique_first_applications(db):
    employer, candidate = user(db, "employer"), user(db)
    dates = ("2026-10-31 23:59:59", "2026-11-01 00:00:00",
             "2026-11-20T23:59:59+00:00", "2026-11-21 00:00:00")
    for index, created_at in enumerate(dates):
        job = vacancy(db, employer, created_at, "closed" if index == 2 else "open")
        app_id = application(db, job, candidate, created_at=created_at)
        # Reapplications and current status changes cannot turn an old row into a new one.
        db.execute("INSERT INTO application_events(application_id,event,created_at) VALUES(?,'reapplied',?)",
                   (app_id, "2026-11-10 00:00:00"))
        db.execute("UPDATE job_applications SET updated_at='2026-11-10 00:00:00' WHERE id=?", (app_id,))
        introduction(db, employer, candidate, accepted=created_at, opened=created_at)
    data = product_snapshot(db, "2026-11-01", "2026-11-20")
    # Four extra vacancies support consent records and are also genuine created rows.
    assert data["period"]["vacancies_created"] == 6
    assert data["period"]["new_applications"] == 2
    assert data["period"]["consented_introductions"] == 2
    assert data["period"]["demo_contacts_opened"] == 2
    assert data["period"]["introductions_completed"] == 0
    assert product_snapshot(db, "2026-11-20", "2026-11-20")["period"]["new_applications"] == 1


def test_outcomes_require_consent_opening_and_recorded_result_without_double_counting(db):
    employer, candidate = user(db, "employer"), user(db)
    invite, job = introduction(db, employer, candidate)
    app_id = application(db, job, candidate, status="hired", event_at="2026-11-05T10:00:00+00:00")
    # Duplicate history events do not duplicate the one introduction.
    db.execute("INSERT INTO application_events(application_id,event,created_at) VALUES(?,'hired',?)",
               (app_id, "2026-11-05 10:00:01"))
    db.execute("INSERT OR IGNORE INTO demo_transactions(invitation_id,amount_rub) VALUES(?,0)", (invite,))

    direct, direct_job = introduction(db, employer, candidate)
    db.execute("INSERT INTO invitation_outcomes(invitation_id,outcome,recorded_at) VALUES(?,'rejected',?)",
               (direct, "2026-11-06 10:00:00"))
    # A later application on the same pair must not duplicate/replace the direct result.
    application(db, direct_job, candidate, status="hired", event_at="2026-11-07 10:00:00")

    _, old_job = introduction(db, employer, candidate)
    application(db, old_job, candidate, status="rejected", event_at="2026-11-02 10:00:00")
    _, missing_job = introduction(db, employer, candidate)
    application(db, missing_job, candidate, status="hired")  # No dated event: do not invent a date.

    future, _ = introduction(db, employer, candidate)
    db.execute("INSERT INTO invitation_outcomes(invitation_id,outcome,recorded_at) VALUES(?,'hired',?)",
               (future, "2026-11-21 00:00:00"))
    for settings in ({"consent": 0}, {"status": "declined"}, {"shared": 0}, {"opened": None}):
        invalid, invalid_job = introduction(db, employer, candidate, **settings)
        application(db, invalid_job, candidate, status="hired", event_at="2026-11-10 00:00:00")
        db.execute("INSERT INTO invitation_outcomes(invitation_id,outcome,recorded_at) VALUES(?,'hired',?)",
                   (invalid, "2026-11-10 00:00:00"))

    result = product_snapshot(db, "2026-11-01", "2026-11-20")
    assert result["period"]["demo_contacts_opened"] == 5
    assert result["period"]["introductions_completed"] == 2
    assert result["period"]["positive_outcomes"] == 1
    assert result["period"]["no_agreement_outcomes"] == 1
    payload = json.dumps(result, ensure_ascii=False)
    for private in ("Private", "private-", "example.invalid", "+79999999999", "Бухгалтер", "Москва"):
        assert private not in payload
    assert "демонстрационном" in payload and "не подтверждают" in payload


def test_empty_report_has_zero_totals_and_rejects_reversed_dates(db):
    result = product_snapshot(db, "2026-11-01", "2026-11-20")
    assert all(value == 0 for value in result["current"].values())
    assert all(value == 0 for value in result["period"].values())
    with pytest.raises(ValueError):
        product_snapshot(db, "2026-11-20", "2026-11-01")
