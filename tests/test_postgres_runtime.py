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
    from app.journal_cms import init_journal
    from app.release02 import init_release02

    # Startup is idempotent for existing production schemas.
    init_release02("ignored-when-DATABASE_URL-present")
    init_release02("ignored-when-DATABASE_URL-present")
    init_journal("ignored-when-DATABASE_URL-present")
    record_event("ignored-when-DATABASE_URL-present", "journal", "view")
    record_event("ignored-when-DATABASE_URL-present", "journal", "view")
    record_event("ignored-when-DATABASE_URL-present", "kak-proverit-vakansiyu", "jobs_click")
    record_event("ignored-when-DATABASE_URL-present", "path:delitsya-opytom", "view")
    record_event("ignored-when-DATABASE_URL-present", "path:delitsya-opytom", "community_click")
    with postgres_database(runtime_db) as db:
        payload = aggregate_snapshot(db, days=30)
        assert payload["summary"]["journal_requests"] == 3
        assert payload["summary"]["jobs_clicks"] == 1
        assert payload["summary"]["community_clicks"] == 1
        assert payload["summary"]["new_candidates"] == 1
        assert payload["summary"]["new_employers"] == 1
        rows = db.execute("SELECT source,action,total FROM growth_daily_counts ORDER BY source,action").fetchall()
        assert [(r["source"], r["action"], r["total"]) for r in rows] == [
            ("journal", "view", 2),
            ("kak-proverit-vakansiyu", "jobs_click", 1),
            ("path:delitsya-opytom", "community_click", 1),
            ("path:delitsya-opytom", "view", 1),
        ]



def test_existing_growth_check_upgrades_without_losing_postgres_counts(runtime_db):
    from app.release02 import init_release02

    # Simulate the most recent deployed CHECK, including apply_click.
    with postgres_database(runtime_db) as db:
        db.execute("""ALTER TABLE growth_daily_counts
            DROP CONSTRAINT growth_daily_counts_action_check,
            ADD CONSTRAINT growth_daily_counts_action_check
            CHECK(action IN ('view','jobs_click','profile_click','community_click',
                             'company_click','vacancy_click','apply_click'))""")
        db.execute("INSERT INTO growth_daily_counts VALUES(?,?,?,?)",
                   ("2026-11-01", "journal", "view", 17))
        db.execute("INSERT INTO growth_daily_counts VALUES(?,?,?,?)",
                   ("2026-11-02", "kak-proverit-vakansiyu", "jobs_click", 5))

    init_release02("ignored-for-postgres")
    init_release02("ignored-for-postgres")
    with postgres_database(runtime_db) as db:
        rows = db.execute(
            "SELECT event_date,source,action,total FROM growth_daily_counts ORDER BY event_date"
        ).fetchall()
        assert [(r["event_date"], r["source"], r["action"], r["total"]) for r in rows] == [
            ("2026-11-01", "journal", "view", 17),
            ("2026-11-02", "kak-proverit-vakansiyu", "jobs_click", 5),
        ]
        assert [row["column_name"] for row in db.execute(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema=current_schema() AND table_name='growth_daily_counts'
               ORDER BY ordinal_position"""
        ).fetchall()] == ["event_date", "source", "action", "total"]
        for action in ("community_click", "article_click", "recommended_vacancy_click"):
            db.execute("INSERT INTO growth_daily_counts VALUES(?,?,?,?)",
                       ("2026-11-03", "journal", action, 2))

    for action, total in (("unknown", 1), ("community_click", -1)):
        with pytest.raises(sqlite3.IntegrityError):
            with postgres_database(runtime_db) as db:
                db.execute("INSERT INTO growth_daily_counts VALUES(?,?,?,?)",
                           ("2026-11-04", "journal", action, total))
    with pytest.raises(sqlite3.IntegrityError):
        with postgres_database(runtime_db) as db:
            db.execute("INSERT INTO growth_daily_counts VALUES(?,?,?,?)",
                       ("2026-11-01", "journal", "view", 1))

def test_privacy_requests_are_private_idempotent_and_audited_in_postgres(runtime_db):
    from app.release02 import init_release02
    from app.privacy_rights import (
        submit_request, requests_for_user, admin_request_list, admin_change_status,
    )

    init_release02("ignored-when-DATABASE_URL-present")
    init_release02("ignored-when-DATABASE_URL-present")
    with postgres_database(runtime_db) as db:
        db.execute(
            "INSERT INTO users(id,email,password_hash,role,name) VALUES(4,?,?,?,?)",
            ("rightsadmin@example.invalid", "test-hash", "admin", "Rights Admin"),
        )
        saved = submit_request(db, 1, "deletion")
        same = submit_request(db, 1, "deletion")
        assert saved["request_key"] == same["request_key"]
        assert [x["kind"] for x in requests_for_user(db, 1)] == ["deletion"]
        assert requests_for_user(db, 2) == []
        assert admin_request_list(db)[0]["email"] == "c@example.invalid"
        reviewed = admin_change_status(
            db, saved["request_key"], 4, "in_review",
            manual_response_confirmed=False, closure_reason=None,
        )
        assert reviewed["status"] == "in_review"
        closed = admin_change_status(
            db, saved["request_key"], 4, "declined",
            manual_response_confirmed=True, closure_reason="retention_required",
        )
        assert closed["status"] == "declined"
        assert submit_request(db, 1, "deletion")["request_key"] != saved["request_key"]

    with postgres_database(runtime_db) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM privacy_rights_requests WHERE user_id=?", (1,)
        ).fetchone()[0] == 2
        assert db.execute(
            "SELECT COUNT(*) FROM privacy_rights_admin_actions WHERE admin_user_id=?", (4,)
        ).fetchone()[0] == 2



def test_personal_data_export_is_bounded_and_private_in_postgresql(runtime_db):
    from app.data_export import build_personal_data_snapshot
    from app.release02 import init_release02

    init_release02("ignored-when-DATABASE_URL-present")
    with postgres_database(runtime_db) as db:
        db.execute(
            """INSERT INTO privacy_rights_requests
               (request_key,user_id,kind,status,submitted_at,updated_at)
               VALUES(?,?,?,'received',?,?)""",
            ("pg-self-data-request", 1, "access",
             "2026-11-19T00:00:00+00:00", "2026-11-19T00:00:00+00:00"),
        )
        account = build_personal_data_snapshot(db, 1)
        employer = build_personal_data_snapshot(db, 2)
        assert account["account"]["role"] == "candidate"
        assert account["account"]["email"] == "c@example.invalid"
        assert len(account["sections"]["privacy_requests"]) == 1
        assert account["candidate_profile"]["profession"] == "Кладовщик"
        assert employer["company_profile"]["company_name"] == "Тест"
        assert "candidate_profile" not in employer
        assert "my_applications" not in employer["sections"]
        assert "password_hash" not in account["account"]
        assert "token_hash" not in str(account)
        assert "c@example.invalid" not in str(employer)



def test_postgres_disposal_impact_and_manual_gate_are_non_destructive(runtime_db):
    from app.release02 import init_release02
    from app.privacy_rights import admin_change_status
    from app.privacy_disposal import (
        CHECKS, impact_preview, review_state, update_review,
    )
    from app.privacy_external import SYSTEMS, save_external_review

    init_release02("ignored-when-DATABASE_URL-present")
    init_release02("ignored-when-DATABASE_URL-present")
    with postgres_database(runtime_db) as db:
        db.execute(
            "INSERT INTO users(id,email,password_hash,role,name) VALUES(4,?,?,?,?)",
            ("disposaladmin@example.invalid", "test-hash", "admin", "Admin"),
        )
        db.execute(
            """INSERT INTO job_applications(vacancy_id,candidate_id)
               VALUES(?,?)""", (3,1),
        )
        db.execute(
            """INSERT INTO privacy_rights_requests
               (request_key,user_id,kind,status,submitted_at,updated_at)
               VALUES(?,?,'deletion','in_review',?,?)""",
            ("pg-disposal-request-001",1,
             "2026-11-19T00:00:00+00:00", "2026-11-19T00:00:00+00:00"),
        )
        plan = impact_preview(db, "pg-disposal-request-001")
        assert plan["counts"]["applications"] == 1
        assert plan["counts"]["professional_profile"] == 1
        assert plan["automatic_deletion"] is False
        assert not review_state(db, "pg-disposal-request-001")["ready_for_manual_closure"]
        with pytest.raises(ValueError, match="manual checklist"):
            admin_change_status(
                db, "pg-disposal-request-001",4,"completed",
                manual_response_confirmed=True,closure_reason="fulfilled",
            )
        checklist = {key:True for key in CHECKS}
        assert update_review(
            db, "pg-disposal-request-001",4,checklist,
        )["ready_for_manual_closure"] is False
        for system_key, _ in SYSTEMS:
            save_external_review(db,"pg-disposal-request-001",4,system_key,"reviewed")
        assert review_state(db,"pg-disposal-request-001")["external_checks_ready"] is True
        assert review_state(db,"pg-disposal-request-001")["ready_for_manual_closure"] is True
        db.execute(
            "INSERT INTO candidate_favorites(candidate_id,vacancy_id) VALUES(?,?)",
            (1,3),
        )
        assert review_state(db, "pg-disposal-request-001")["counts_changed_since_review"]
        with pytest.raises(ValueError, match="manual checklist"):
            admin_change_status(
                db,"pg-disposal-request-001",4,"completed",
                manual_response_confirmed=True,closure_reason="fulfilled",
            )
        assert update_review(
            db,"pg-disposal-request-001",4,checklist,
        )["ready_for_manual_closure"] is True
        assert admin_change_status(
            db,"pg-disposal-request-001",4,"completed",
            manual_response_confirmed=True,closure_reason="fulfilled",
        )["status"] == "completed"
        assert db.execute("SELECT COUNT(*) FROM users WHERE id=1").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM job_applications").fetchone()[0] == 1

    with postgres_database(runtime_db) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM privacy_disposal_review_actions"
        ).fetchone()[0] == 2
        assert db.execute(
            "SELECT status FROM privacy_rights_requests WHERE request_key=?",
            ("pg-disposal-request-001",),
        ).fetchone()["status"] == "completed"
        assert db.execute(
            "SELECT COUNT(*) FROM privacy_external_review_events"
        ).fetchone()[0] == len(SYSTEMS)
