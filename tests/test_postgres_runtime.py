"""PostgreSQL runtime adapter checks against disposable CI PostgreSQL 17."""
import os
import sqlite3

import pytest

from app.db import SCHEMA
from app.release02 import MIGRATION, interaction_timeline
pytest.importorskip("psycopg")
from app.pg_compat import postgres_database
from scripts.migrate_sqlite_to_postgres import migrate


@pytest.fixture
def runtime_db(tmp_path, monkeypatch):
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Only run with isolated CI PostgreSQL")
    import psycopg
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")

    source = tmp_path / "runtime.db"
    with sqlite3.connect(source) as conn:
        conn.executescript(SCHEMA + "\n" + MIGRATION)
        conn.execute("INSERT INTO users(id,email,password_hash,role,name) VALUES(1,'c@example.invalid','h','candidate','C')")
        conn.execute("INSERT INTO users(id,email,password_hash,role,name) VALUES(2,'e@example.invalid','h','employer','E')")
        conn.execute("INSERT INTO candidate_profiles(user_id,profession,city) VALUES(1,'Кладовщик','Москва')")
        conn.execute("INSERT INTO employer_profiles(user_id,company_name) VALUES(2,'Тест')")
        conn.execute("INSERT INTO vacancies(id,employer_id,title,city,salary_min,salary_max,skills) VALUES(3,2,'Кладовщик','Москва',60000,90000,'Склад')")
        conn.commit()
    migrate(str(source), dsn)
    monkeypatch.setenv("DATABASE_URL", dsn)
    yield dsn
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")


def test_runtime_read_write_and_sqlite_compatibility(runtime_db):
    with postgres_database(runtime_db) as db:
        row = db.execute("SELECT * FROM users WHERE email=?", ("c@example.invalid",)).fetchone()
        assert row["id"] == 1 and row[0] == 1

        created = db.execute(
            "INSERT INTO job_applications(vacancy_id,candidate_id) VALUES(?,?)", (3, 1)
        )
        assert created.lastrowid is not None

        db.execute(
            "UPDATE job_applications SET status='reviewing',updated_at=datetime('now') WHERE id=?",
            (created.lastrowid,),
        )

        jobs = db.execute(
            "SELECT * FROM vacancies v WHERE instr(unicode_fold(v.title), ?) > 0",
            ("клад",),
        ).fetchall()
        assert len(jobs) == 1

        db.execute(
            "INSERT OR IGNORE INTO candidate_favorites(candidate_id,vacancy_id) VALUES(?,?)",
            (1, 3),
        )
        db.execute(
            "INSERT OR IGNORE INTO candidate_favorites(candidate_id,vacancy_id) VALUES(?,?)",
            (1, 3),
        )
        assert db.execute("SELECT COUNT(*) FROM candidate_favorites").fetchone()[0] == 1


def test_full_introduction_timeline_persists_and_has_stable_timestamps(runtime_db):
    with postgres_database(runtime_db) as db:
        application = db.execute(
            "INSERT INTO job_applications(vacancy_id,candidate_id) VALUES(?,?)", (3, 1)
        )
        app_id = application.lastrowid
        db.execute(
            "INSERT INTO application_events(application_id,event) VALUES(?,?)",
            (app_id, "applied"),
        )
        invitation = db.execute(
            "INSERT INTO invitations(vacancy_id,candidate_id,employer_id,status,price_rub) VALUES(?,?,?,'sent',?)",
            (3, 1, 2, 1490),
        )
        invitation_id = invitation.lastrowid
        db.execute(
            "UPDATE invitations SET status='accepted',share_consent=1,responded_at=datetime('now') WHERE id=?",
            (invitation_id,),
        )
        db.execute(
            "INSERT INTO demo_transactions(invitation_id,amount_rub) VALUES(?,?)",
            (invitation_id, 1490),
        )
        db.execute(
            "UPDATE invitations SET contact_shared=1 WHERE id=?",
            (invitation_id,),
        )

    # A fresh connection simulates a new request/container process reading persisted state.
    with postgres_database(runtime_db) as db:
        timeline = interaction_timeline(db, app_id, invitation_id)
        assert [item["event"] for item in timeline] == [
            "applied", "invitation_sent", "invitation_accepted", "contact_opened"
        ]
        assert all(
            len(item["created_at"]) == 19
            and "T" not in item["created_at"]
            and "+" not in item["created_at"]
            and "." not in item["created_at"]
            for item in timeline
        )
        row = db.execute(
            "SELECT status,share_consent,contact_shared FROM invitations WHERE id=?",
            (invitation_id,),
        ).fetchone()
        assert row["status"] == "accepted"
        assert row["share_consent"] == 1
        assert row["contact_shared"] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM demo_transactions WHERE invitation_id=?",
            (invitation_id,),
        ).fetchone()[0] == 1


def test_private_drafts_work_in_real_postgresql(runtime_db):
    """Ensure the new additive schema and ID RETURNING work with PostgreSQL 17."""
    from app.release02 import init_release02
    init_release02("unused-with-DATABASE_URL")
    with postgres_database(runtime_db) as db:
        created = db.execute(
            "INSERT INTO vacancy_drafts(employer_id,fields_json) VALUES(?,?)",
            (2, '{"title":"Оператор склада"}'),
        )
        draft_id = created.lastrowid
        assert isinstance(draft_id, int) and draft_id > 0
        row = db.execute(
            "SELECT * FROM vacancy_drafts WHERE id=? AND employer_id=?",
            (draft_id, 2),
        ).fetchone()
        assert row["version"] == 1
        assert row["published_vacancy_id"] is None
        updated = db.execute(
            """UPDATE vacancy_drafts SET fields_json=?,version=version+1,
               updated_at=datetime('now')
               WHERE id=? AND employer_id=? AND version=?""",
            ('{"title":"Оператор склада","city":"Москва"}', draft_id, 2, 1),
        )
        assert updated.rowcount == 1
        assert db.execute(
            "SELECT version FROM vacancy_drafts WHERE id=?", (draft_id,)
        ).fetchone()["version"] == 2



def test_first_draft_create_key_is_atomic_in_postgres(runtime_db):
    """The new ledger is additive, unique per employer, and survives deletion."""
    from app.release02 import init_release02
    init_release02("ignored-when-DATABASE_URL-present")
    init_release02("ignored-when-DATABASE_URL-present")
    key = "319ccb12-8b14-4878-b81e-179c0c505c10"
    with postgres_database(runtime_db) as db:
        reserved = db.execute(
            """INSERT OR IGNORE INTO vacancy_draft_create_requests
               (employer_id,request_key,payload_sha256) VALUES(?,?,?)""",
            (2, key, "sha256-test"),
        )
        assert reserved.rowcount == 1
        draft = db.execute(
            "INSERT INTO vacancy_drafts(employer_id,fields_json) VALUES(?,?)",
            (2, '{"title":"Тест идемпотентности"}'),
        )
        did = draft.lastrowid
        db.execute(
            """UPDATE vacancy_draft_create_requests SET draft_id=?
               WHERE employer_id=? AND request_key=?""",
            (did, 2, key),
        )
        db.commit()

    with postgres_database(runtime_db) as db:
        replay = db.execute(
            """INSERT OR IGNORE INTO vacancy_draft_create_requests
               (employer_id,request_key,payload_sha256) VALUES(?,?,?)""",
            (2, key, "sha256-test"),
        )
        assert replay.rowcount == 0
        row = db.execute(
            """SELECT draft_id,payload_sha256 FROM vacancy_draft_create_requests
               WHERE employer_id=? AND request_key=?""",
            (2, key),
        ).fetchone()
        assert row["draft_id"] == did
        assert row["payload_sha256"] == "sha256-test"
        db.execute("DELETE FROM vacancy_drafts WHERE id=? AND employer_id=?", (did, 2))
        db.commit()

    with postgres_database(runtime_db) as db:
        tombstone = db.execute(
            """SELECT draft_id FROM vacancy_draft_create_requests
               WHERE employer_id=? AND request_key=?""",
            (2, key),
        ).fetchone()
        assert tombstone is not None and tombstone["draft_id"] is None
        assert db.execute(
            """INSERT OR IGNORE INTO vacancy_draft_create_requests
               (employer_id,request_key,payload_sha256) VALUES(?,?,?)""",
            (2, key, "sha256-test"),
        ).rowcount == 0


def test_growth_aggregate_is_atomic_and_private_in_postgresql(runtime_db):
    from app.growth import aggregate_snapshot, record_event
    from app.release02 import init_release02

    # Startup is idempotent for existing production schemas.
    init_release02("ignored-when-DATABASE_URL-present")
    init_release02("ignored-when-DATABASE_URL-present")
    record_event("ignored-when-DATABASE_URL-present", "journal", "view")
    record_event("ignored-when-DATABASE_URL-present", "journal", "view")
    record_event("ignored-when-DATABASE_URL-present", "kak-proverit-vakansiyu", "jobs_click")
    with postgres_database(runtime_db) as db:
        payload = aggregate_snapshot(db, days=30)
        assert payload["summary"]["journal_requests"] == 2
        assert payload["summary"]["jobs_clicks"] == 1
        assert payload["summary"]["new_candidates"] == 1
        assert payload["summary"]["new_employers"] == 1
        rows = db.execute("SELECT source,action,total FROM growth_daily_counts ORDER BY source").fetchall()
        assert [(r["source"], r["action"], r["total"]) for r in rows] == [
            ("journal", "view", 2),
            ("kak-proverit-vakansiyu", "jobs_click", 1),
        ]
