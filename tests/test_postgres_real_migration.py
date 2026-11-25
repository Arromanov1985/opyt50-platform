"""Real PostgreSQL 17 checks, restricted to a disposable CI database."""
import os
import sqlite3

import pytest

from app.db import SCHEMA
from app.release02 import MIGRATION
from scripts.migrate_sqlite_to_postgres import migrate
from scripts.production_cutover_preflight import inspect_target


@pytest.fixture
def target():
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Only run with isolated CI PostgreSQL")
    import psycopg
    with psycopg.connect(dsn, autocommit=True) as conn:
        assert conn.execute("SELECT current_database()").fetchone()[0] == "opytno_migration_test"
        assert conn.execute("SELECT current_user").fetchone()[0] == "ci_migration"
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")
    yield dsn
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")


@pytest.fixture
def sample(tmp_path):
    path = tmp_path / "source.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA + "\n" + MIGRATION)
        conn.execute(
            "INSERT INTO users(id,email,password_hash,role,name) VALUES(1,?,?,?,?)",
            ("candidate@example.invalid", "test-hash", "candidate", "Candidate"),
        )
        conn.execute(
            "INSERT INTO users(id,email,password_hash,role,name) VALUES(2,?,?,?,?)",
            ("employer@example.invalid", "test-hash", "employer", "Employer"),
        )
        conn.execute(
            "INSERT INTO vacancies(id,employer_id,title,city,salary_min,salary_max) VALUES(3,2,?,?,?,?)",
            ("Кладовщик", "Подольск", 65000, 90000),
        )
        conn.execute(
            "INSERT INTO job_applications(id,vacancy_id,candidate_id) VALUES(4,3,1)"
        )
        conn.execute(
            "INSERT INTO invitations(id,vacancy_id,candidate_id,employer_id,status,share_consent,contact_shared,price_rub) VALUES(5,3,1,2,'accepted',1,1,1490)"
        )
        conn.execute(
            """INSERT INTO candidate_saved_searches
               (candidate_id,search_key,slot,filter_key,q,alerts_enabled,reviewed_ids_json,created_at,updated_at)
               VALUES(1,'test-key',1,'test-filter','Кладовщик',1,'[3]','2026-11-25','2026-11-25')"""
        )
        conn.execute(
            """INSERT INTO community_connections(id,sender_id,recipient_id,pair_low,pair_high,
               purpose,status,created_at,updated_at)
               VALUES('test-thread',2,1,1,2,'exchange','accepted','2026-01-01','2026-01-01')"""
        )
        conn.execute(
            """INSERT INTO community_messages(id,connection_id,sender_id,client_key,body,created_at)
               VALUES('test-message','test-thread',2,'test-client','Test message','2026-01-02')"""
        )
        conn.execute(
            """INSERT INTO community_read_state(user_id,connection_id,through_created_at,through_message_id)
               VALUES(1,'test-thread','2026-01-02','test-message')"""
        )
        conn.execute(
            """INSERT INTO community_feed_entries(id,author_id,client_key,kind,title,body,
               consent_at,consent_version,created_at,updated_at)
               VALUES('z-parent',1,'post-key','experience','Test title','Test body',
               '2026-01-01','test','2026-01-01','2026-01-01')"""
        )
        conn.execute(
            """INSERT INTO community_feed_entries(id,author_id,parent_id,client_key,kind,body,
               consent_at,consent_version,created_at,updated_at)
               VALUES('a-reply',1,'z-parent','reply-key','comment','Test reply',
               '2026-01-02','test','2026-01-02','2026-01-02')"""
        )
        conn.commit()
    return path


def test_import_preserves_ids_consents_and_relations(target, sample):
    import psycopg
    before = sample.read_bytes()
    counts = migrate(str(sample), target)
    assert counts["users"] == 2
    assert counts["job_applications"] == 1
    assert counts["candidate_saved_searches"] == 1
    assert counts["community_connections"] == 1
    assert counts["community_messages"] == 1
    assert counts["community_read_state"] == 1
    assert counts["community_feed_entries"] == 2
    with psycopg.connect(target) as conn:
        assert conn.execute("SELECT id,vacancy_id,candidate_id FROM job_applications").fetchone() == (4, 3, 1)
        assert conn.execute("SELECT share_consent, contact_shared FROM invitations WHERE id=5").fetchone() == (1, 1)
        assert conn.execute("SELECT password_hash FROM users WHERE id=1").fetchone()[0] == "test-hash"
        assert conn.execute(
            "SELECT q,alerts_enabled,reviewed_ids_json FROM candidate_saved_searches WHERE candidate_id=1"
        ).fetchone() == ("Кладовщик", 1, "[3]")
        assert conn.execute(
            "SELECT user_id,connection_id,through_message_id FROM community_read_state"
        ).fetchone() == (1, "test-thread", "test-message")
        assert conn.execute(
            "SELECT parent_id FROM community_feed_entries WHERE id='a-reply'"
        ).fetchone() == ("z-parent",)
    assert sample.read_bytes() == before


def test_nonempty_target_is_rejected(target, sample):
    import psycopg
    migrate(str(sample), target)
    with pytest.raises(ValueError, match="not empty"):
        migrate(str(sample), target)
    with psycopg.connect(target) as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2


def test_production_cutover_preflight_is_read_only_and_detects_nonempty_target(target, sample):
    empty = inspect_target(target)
    assert empty["target_empty"] is True
    assert empty["target_table_count"] == 0
    migrate(str(sample), target)
    populated = inspect_target(target)
    assert populated["target_empty"] is False
    assert populated["target_table_count"] > 0
