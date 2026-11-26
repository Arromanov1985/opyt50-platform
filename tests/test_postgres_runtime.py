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


def test_saved_search_api_in_postgresql(runtime_db):
    from fastapi.testclient import TestClient
    from app.main import create_app, active_user

    app = create_app("ignored-with-DATABASE_URL")
    app.dependency_overrides[active_user] = lambda: {"id": 1, "role": "candidate"}
    root = "/api/candidate/saved-searches"
    headers = {"X-Requested-With": "OPYT50"}
    with TestClient(app) as client:
        created = client.post(root, headers=headers, json={
            "q": "КЛАДОВЩИК", "city": "Москва", "alerts_enabled": True,
        })
        assert created.status_code == 201, created.text
        search = created.json()["search"]
        assert search["new_count"] == 0
        url = root + "/" + search["key"]
        assert [job["id"] for job in client.get(url + "/results").json()["jobs"]] == [3]
        with postgres_database(runtime_db) as db:
            new = db.execute(
                """INSERT INTO vacancies(employer_id,title,city,salary_min,salary_max)
                   VALUES(2,'Кладовщик смены','Москва',60000,90000)"""
            ).lastrowid
        assert client.get(url + "/results").json()["new_ids"] == [new]
        acknowledged = client.post(url + "/review", headers=headers,
                                   json={"revision": search["revision"], "vacancy_ids": [3, new]})
        assert acknowledged.status_code == 200, acknowledged.text
        assert acknowledged.json()["search"]["new_count"] == 0
        assert client.delete(url, headers=headers).status_code == 200
        assert client.get(root).json()["searches"] == []


def test_community_attention_and_read_cursor_in_postgresql(runtime_db):
    from fastapi.testclient import TestClient
    from app.main import create_app, active_user

    app = create_app("unused-with-DATABASE_URL")
    app.dependency_overrides[active_user] = lambda: {"id": 1, "role": "candidate"}
    with TestClient(app) as client:
        with postgres_database(runtime_db) as db:
            db.execute(
                """INSERT INTO community_connections(id,sender_id,recipient_id,pair_low,pair_high,
                   purpose,status,created_at,updated_at)
                   VALUES('pg-thread',2,1,1,2,'exchange','accepted','2026-01-01','2026-01-01')"""
            )
            for mid in ("pg-a", "pg-b"):
                db.execute(
                    """INSERT INTO community_messages(id,connection_id,sender_id,client_key,body,created_at)
                       VALUES(?,'pg-thread',2,?,'Fictional message','2026-01-02')""",
                    (mid, mid),
                )
        assert client.get("/api/community/activity").json()["unread_messages"] == 2
        assert client.get("/api/community/connections?attention=true").json()["total"] == 1
        path = "/api/community/connections/pg-thread/read"
        headers = {"X-Requested-With": "OPYT50"}
        first = client.post(path, headers=headers, json={"through_message_id": "pg-b"})
        assert first.status_code == 200, first.text
        assert first.json()["unread_count"] == 0
        older = client.post(path, headers=headers, json={"through_message_id": "pg-a"})
        assert older.status_code == 200, older.text
        assert older.json()["unread_count"] == 0
        assert client.get("/api/community/connections?attention=true").json()["total"] == 0
        with postgres_database(runtime_db) as db:
            row = db.execute("SELECT through_message_id FROM community_read_state WHERE user_id=1").fetchone()
            assert row["through_message_id"] == "pg-b"


def test_moderated_feed_runtime_postgresql(runtime_db):
    from fastapi.testclient import TestClient
    from app.main import create_app, active_user
    from uuid import uuid4

    app = create_app("unused-with-DATABASE_URL")
    actor = {"id": 1, "role": "candidate"}
    app.dependency_overrides[active_user] = lambda: actor
    with TestClient(app) as client:
        with postgres_database(runtime_db) as db:
            db.execute(
                """INSERT INTO community_profiles(user_id,public_id,public_name,headline,
                   status,consent_at,consent_content_version,reviewed_content_version,created_at,updated_at)
                   VALUES(1,'feed-public','Опытный коллега','Наставник','published',
                   '2026-01-01',1,1,'2026-01-01','2026-01-01')"""
            )
            admin_id = db.execute(
                "INSERT INTO users(email,password_hash,role,name) VALUES(?,?,'admin','Admin')",
                ("feed-admin@example.invalid", "test-hash"),
            ).lastrowid
        url = "/api/community/feed"
        headers = {"X-Requested-With": "OPYT50"}
        response = client.post(url, headers=headers, json={
            "kind": "projects", "title": "Проект", "body": "Обмен опытом",
            "client_key": str(uuid4()), "publish_consent": True,
        })
        assert response.status_code == 200, response.text
        pending = response.json()["entry"]
        assert client.get(url).json()["entries"] == []
        actor.update(id=admin_id, role="admin")
        approved = client.patch("/api/admin/community/feed/" + pending["id"], headers=headers,
                                json={"decision": "approve", "expected_version": pending["version"]})
        assert approved.status_code == 200, approved.text
        actor.update(id=2, role="employer")
        visible = client.get(url + "?q=ПРОЕКТ&kind=projects")
        assert visible.status_code == 200, visible.text
        assert visible.json()["entries"][0]["id"] == pending["id"]
        assert "author_id" not in visible.json()["entries"][0]
        actor.update(id=1, role="candidate")
        comment = client.post(url, headers=headers, json={
            "kind": "comment", "parent_id": pending["id"], "body": "Полезная тема",
            "client_key": str(uuid4()), "publish_consent": True,
        })
        assert comment.status_code == 200, comment.text
        assert client.get(url + "/" + pending["id"] + "/comments").json()["entries"] == []
        reply = comment.json()["entry"]
        actor.update(id=admin_id, role="admin")
        approved_reply = client.patch("/api/admin/community/feed/" + reply["id"], headers=headers,
                                      json={"decision": "approve", "expected_version": reply["version"]})
        assert approved_reply.status_code == 200, approved_reply.text
        actor.update(id=2, role="employer")
        assert client.get(url + "/" + pending["id"] + "/comments").json()["entries"][0]["id"] == reply["id"]


def test_feed_engagement_runtime_postgresql(runtime_db):
    from fastapi.testclient import TestClient
    from app.main import create_app, active_user
    from uuid import uuid4

    app = create_app("unused-with-DATABASE_URL")
    actor = {"id": 1, "role": "candidate"}
    app.dependency_overrides[active_user] = lambda: actor
    with TestClient(app) as client:
        with postgres_database(runtime_db) as db:
            other_id = db.execute(
                "INSERT INTO users(email,password_hash,role,name) VALUES(?,?,'candidate','Other')",
                ("feed-other@example.invalid", "test-hash"),
            ).lastrowid
            admin_id = db.execute(
                "INSERT INTO users(email,password_hash,role,name) VALUES(?,?,'admin','Admin')",
                ("feed-moderator@example.invalid", "test-hash"),
            ).lastrowid
            for uid, public_id in ((1, "pg-author"), (other_id, "pg-reader")):
                db.execute(
                    """INSERT INTO community_profiles(user_id,public_id,public_name,headline,goal,
                       status,consent_at,consent_content_version,reviewed_content_version,created_at,updated_at)
                       VALUES(?,?,'Коллега','Наставник','mentoring','published','2026-01-01',1,1,'2026-01-01','2026-01-01')""",
                    (uid, public_id),
                )
        url = "/api/community/feed"
        headers = {"X-Requested-With": "OPYT50"}
        post = client.post(url, headers=headers, json={
            "kind": "mentoring", "title": "Опыт", "body": "Передача знаний",
            "opportunity": {"intent": "offer", "meeting_format": "online", "commitment": "regular"},
            "client_key": str(uuid4()), "publish_consent": True,
        })
        assert post.status_code == 200, post.text
        root = post.json()["entry"]
        actor.update(id=admin_id, role="admin")
        approval = client.patch("/api/admin/community/feed/" + root["id"], headers=headers,
                                json={"decision": "approve", "expected_version": root["version"]})
        assert approval.status_code == 200, approval.text
        actor.update(id=other_id, role="candidate")
        follow = client.post(url + "/follows", headers=headers, json={"public_id": "pg-author"})
        assert follow.status_code == 200, follow.text
        assert client.get(url + "?following=true").json()["entries"][0]["id"] == root["id"]
        offers = client.get("/api/community/opportunities?kind=mentoring&intent=offer&meeting_format=online&commitment=regular")
        assert offers.status_code == 200, offers.text
        assert [row["id"] for row in offers.json()["entries"]] == [root["id"]]
        assert offers.json()["entries"][0]["opportunity"]["intent"] == "offer"
        assert client.get("/api/community/opportunities?kind=projects").json()["entries"] == []
        saved_url = url + "/saved/" + root["id"]
        saved = client.put(saved_url, headers=headers, json={})
        assert saved.status_code == 200, saved.text
        assert client.get(url + "/saved").json()["records"][0]["entry"]["id"] == root["id"]
        rec_url = "/api/community/recommendations"
        preferences = client.put(rec_url + "/preferences", headers=headers,
                                 json={"keyword": "Наставник", "focus": "mentoring"})
        assert preferences.status_code == 200, preferences.text
        rec = client.get(rec_url)
        assert rec.status_code == 200, rec.text
        assert rec.json()["feed"]["saved_entry_ids"] == [root["id"]]
        assert rec.json()["people"]["people"][0]["public_id"] == "pg-author"
        comment = client.post(url, headers=headers, json={
            "kind": "comment", "parent_id": root["id"], "body": "Ответ коллеги",
            "client_key": str(uuid4()), "publish_consent": True,
        })
        assert comment.status_code == 200, comment.text
        reply = comment.json()["entry"]
        actor.update(id=admin_id, role="admin")
        approval = client.patch("/api/admin/community/feed/" + reply["id"], headers=headers,
                                json={"decision": "approve", "expected_version": reply["version"]})
        assert approval.status_code == 200, approval.text
        actor.update(id=1, role="candidate")
        assert client.get(url + "/alerts").json()["entries"][0]["id"] == reply["id"]
        read = client.post(url + "/alerts/" + reply["id"] + "/read", headers=headers, json={})
        assert read.status_code == 200, read.text
        assert client.get(url + "/alerts").json()["entries"] == []
        report = client.post(url + "/" + reply["id"] + "/reports", headers=headers,
                             json={"reason": "spam"})
        assert report.status_code == 200, report.text
        report_id = report.json()["report"]["id"]
        actor.update(id=admin_id, role="admin")
        decision = client.patch("/api/admin/community/feed/reports/" + report_id, headers=headers,
                                json={"decision": "hide", "reason": "Проверка жалобы"})
        assert decision.status_code == 200, decision.text
        actor.update(id=other_id, role="candidate")
        assert client.get(url + "/" + root["id"] + "/comments").json()["entries"] == []
        assert client.get(url + "?following=true").json()["entries"][0]["id"] == root["id"]


def test_professional_portfolio_runtime_postgresql(runtime_db):
    from fastapi.testclient import TestClient
    from app.main import create_app, active_user
    from uuid import uuid4

    app = create_app("unused-with-DATABASE_URL")
    actor = {"id": 1, "role": "candidate"}
    app.dependency_overrides[active_user] = lambda: actor
    with TestClient(app) as client:
        with postgres_database(runtime_db) as db:
            admin_id = db.execute(
                "INSERT INTO users(email,password_hash,role,name) VALUES(?,?,'admin','Admin')",
                ("portfolio-moderator@example.invalid", "test-hash"),
            ).lastrowid
            db.execute(
                """INSERT INTO community_profiles(user_id,public_id,public_name,headline,
                   status,consent_at,consent_content_version,reviewed_content_version,created_at,updated_at)
                   VALUES(1,'pg-portfolio','Коллега','Наставник','published',
                   '2026-01-01',1,1,'2026-01-01','2026-01-01')"""
            )
        url = "/api/community/portfolio"
        public = "/api/community/people/pg-portfolio/portfolio"
        headers = {"X-Requested-With": "OPYT50"}
        response = client.post(url, headers=headers, json={
            "client_key": str(uuid4()), "kind": "project", "title": "Внедрение учёта",
            "contribution": "Организовал процесс и обучил команду", "result": "Новый порядок работы",
        })
        assert response.status_code == 200, response.text
        item = response.json()["entry"]
        assert client.get(public).json()["entries"] == []
        submitted = client.post(url + "/" + item["id"] + "/submit", headers=headers,
                                json={"expected_version": item["version"], "publish_consent": True})
        assert submitted.status_code == 200, submitted.text
        pending = submitted.json()["entry"]
        actor.update(id=admin_id, role="admin")
        approved = client.patch("/api/admin/community/portfolio/" + item["id"], headers=headers,
                                json={"expected_version": pending["version"], "decision": "approve"})
        assert approved.status_code == 200, approved.text
        assert client.get(public).json()["entries"][0]["id"] == item["id"]
        actor.update(id=1, role="candidate")
        hidden = client.request("DELETE", "/api/community/profile/publication", headers=headers,
                                json={"expected_version": 1})
        assert hidden.status_code == 200, hidden.text
        assert client.get(public).status_code == 404
        assert client.get(url).json()["entries"][0]["status"] == "hidden"


def test_colleague_recommendations_runtime_postgresql(runtime_db):
    from fastapi.testclient import TestClient
    from app.main import create_app, active_user
    from uuid import uuid4

    app = create_app("unused-with-DATABASE_URL")
    actor = {"id": 1, "role": "candidate"}
    app.dependency_overrides[active_user] = lambda: actor
    with TestClient(app) as client:
        with postgres_database(runtime_db) as db:
            colleague = db.execute(
                "INSERT INTO users(email,password_hash,role,name) VALUES(?,?,'candidate','Colleague')",
                ("reputation-peer@example.invalid", "test-hash"),
            ).lastrowid
            admin = db.execute(
                "INSERT INTO users(email,password_hash,role,name) VALUES(?,?,'admin','Admin')",
                ("reputation-admin@example.invalid", "test-hash"),
            ).lastrowid
            for uid, public_id in ((1, "pg-author"), (colleague, "pg-recipient")):
                db.execute(
                    """INSERT INTO community_profiles(user_id,public_id,public_name,headline,status,
                       consent_at,consent_content_version,reviewed_content_version,created_at,updated_at)
                       VALUES(?,?,'Коллега','Наставник','published','2026-01-01',1,1,'2026-01-01','2026-01-01')""",
                    (uid, public_id),
                )
            db.execute(
                """INSERT INTO community_connections(id,sender_id,recipient_id,pair_low,pair_high,
                   purpose,status,created_at,updated_at) VALUES('pg-reputation-thread',1,?,1,?,
                   'exchange','accepted','2026-01-01','2026-01-01')""",
                (colleague, colleague),
            )
        headers = {"X-Requested-With": "OPYT50"}
        url = "/api/community/reputation"
        public = "/api/community/people/pg-recipient/reputation"
        response = client.post(url, headers=headers, json={
            "connection_id": "pg-reputation-thread", "client_key": str(uuid4()),
            "skill": "Обучение", "context": "Работали над совместным проектом",
            "body": "Помогал коллегам освоить новые процессы.", "publish_consent": True,
        })
        assert response.status_code == 200, response.text
        item = response.json()["entry"]
        assert client.get(public).json()["entries"] == []
        actor.update(id=colleague, role="candidate")
        consent = client.post(url + "/" + item["id"] + "/respond", headers=headers,
                              json={"expected_version": item["version"], "decision": "accept",
                                    "publish_consent": True})
        assert consent.status_code == 200, consent.text
        pending = consent.json()["entry"]
        actor.update(id=admin, role="admin")
        approved = client.patch("/api/admin/community/reputation/" + item["id"], headers=headers,
                                json={"expected_version": pending["version"], "decision": "approve"})
        assert approved.status_code == 200, approved.text
        assert client.get(public).json()["entries"][0]["id"] == item["id"]
        actor.update(id=colleague, role="candidate")
        blocked = client.post("/api/community/connections/pg-reputation-thread/block", headers=headers, json={})
        assert blocked.status_code == 200, blocked.text
        assert client.get(public).json()["entries"] == []
        assert client.get(url).json()["entries"][0]["status"] == "hidden"

