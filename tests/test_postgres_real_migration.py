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
               VALUES('z-parent',1,'post-key','mentoring','Test title','Test body',
               '2026-01-01','test','2026-01-01','2026-01-01')"""
        )
        conn.execute(
            """INSERT INTO community_feed_entries(id,author_id,parent_id,client_key,kind,body,
               consent_at,consent_version,created_at,updated_at)
               VALUES('a-reply',1,'z-parent','reply-key','comment','Test reply',
               '2026-01-02','test','2026-01-02','2026-01-02')"""
        )
        conn.execute(
            """INSERT INTO community_profiles(user_id,public_id,public_name,headline,created_at,updated_at)
               VALUES(1,'feed-profile','Test name','Test headline','2026-01-01','2026-01-01')"""
        )
        conn.execute("INSERT INTO community_group_memberships VALUES(1,'engineering','2026-01-03')")
        conn.execute("INSERT INTO community_group_posts VALUES('z-parent','engineering')")
        conn.execute("INSERT INTO community_opportunities VALUES('z-parent','offer','online','regular')")
        conn.execute(
            "INSERT INTO users(id,email,password_hash,role,name) VALUES(6,?,?,?,?)",
            ("peer@example.invalid", "test-hash", "candidate", "Peer"),
        )
        conn.execute(
            """INSERT INTO community_profiles(user_id,public_id,public_name,headline,created_at,updated_at)
               VALUES(6,'peer-profile','Test peer','Test headline','2026-01-01','2026-01-01')"""
        )
        conn.execute(
            """INSERT INTO community_connections(id,sender_id,recipient_id,pair_low,pair_high,
               purpose,status,created_at,updated_at)
               VALUES('reputation-thread',1,6,1,6,'exchange','accepted','2026-01-01','2026-01-01')"""
        )
        conn.execute(
            """INSERT INTO community_recommendations(id,connection_id,author_id,recipient_id,
               client_key,skill,context,body,status,author_consent_at,recipient_consent_at,consent_version,
               created_at,updated_at) VALUES('recommendation-1','reputation-thread',1,6,'rec-key',
               'Test skill','Shared project','Test recommendation','pending','2026-01-01','2026-01-02',
               'test-consent','2026-01-01','2026-01-02')"""
        )
        conn.execute(
            """INSERT INTO community_portfolio_entries(id,user_id,client_key,kind,title,period,
               contribution,result,created_at,updated_at)
               VALUES('portfolio-1',1,'portfolio-client','project','Test project','2020–2024',
               'Personal contribution','Test result','2026-01-03','2026-01-03')"""
        )
        conn.execute("INSERT INTO community_saved_entries VALUES(2,'z-parent','2026-01-03')")
        conn.execute("INSERT INTO community_discovery_preferences VALUES(2,'Test topic','','mentoring','rev-1','2026-01-03')")
        conn.execute("INSERT INTO community_feed_follows VALUES(2,1,'2026-01-01')")
        conn.execute("INSERT INTO community_feed_alert_reads VALUES(1,'a-reply','2026-01-03')")
        conn.execute(
            """INSERT INTO community_feed_reports(id,reporter_id,entry_id,reason,created_at)
               VALUES('feed-report',2,'z-parent','spam','2026-01-03')"""
        )
        conn.commit()
    return path


def test_import_preserves_ids_consents_and_relations(target, sample):
    import psycopg
    before = sample.read_bytes()
    counts = migrate(str(sample), target)
    assert counts["users"] == 3
    assert counts["job_applications"] == 1
    assert counts["candidate_saved_searches"] == 1
    assert counts["community_connections"] == 2
    assert counts["community_recommendations"] == 1
    assert counts["community_messages"] == 1
    assert counts["community_read_state"] == 1
    assert counts["community_feed_entries"] == 2
    assert counts["community_opportunities"] == 1
    assert counts["community_group_memberships"] == counts["community_group_posts"] == 1
    assert counts["community_portfolio_entries"] == 1
    assert counts["community_saved_entries"] == counts["community_discovery_preferences"] == 1
    assert counts["community_feed_follows"] == counts["community_feed_alert_reads"] == counts["community_feed_reports"] == 1
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
        assert conn.execute("SELECT entry_id,intent,meeting_format,commitment FROM community_opportunities").fetchone() == ("z-parent", "offer", "online", "regular")
        assert conn.execute("SELECT follower_id,target_id FROM community_feed_follows").fetchone() == (2, 1)
        assert conn.execute("SELECT user_id,entry_id FROM community_feed_alert_reads").fetchone() == (1, "a-reply")
        assert conn.execute("SELECT reporter_id,entry_id FROM community_feed_reports").fetchone() == (2, "z-parent")
        assert conn.execute("SELECT user_id,entry_id FROM community_saved_entries").fetchone() == (2, "z-parent")
        assert conn.execute("SELECT user_id,keyword,focus FROM community_discovery_preferences").fetchone() == (2, "Test topic", "mentoring")
        assert conn.execute("SELECT id,user_id,kind,title FROM community_portfolio_entries").fetchone() == (
            "portfolio-1", 1, "project", "Test project")
        assert conn.execute(
            "SELECT id,author_id,recipient_id,author_consent_at,recipient_consent_at FROM community_recommendations"
        ).fetchone() == ("recommendation-1", 1, 6, "2026-01-01", "2026-01-02")
        assert conn.execute("SELECT user_id,group_slug FROM community_group_memberships").fetchone() == (1, "engineering")
        assert conn.execute("SELECT entry_id,group_slug FROM community_group_posts").fetchone() == ("z-parent", "engineering")
    assert sample.read_bytes() == before


def test_nonempty_target_is_rejected(target, sample):
    import psycopg
    migrate(str(sample), target)
    with pytest.raises(ValueError, match="not empty"):
        migrate(str(sample), target)
    with psycopg.connect(target) as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 3


def test_production_cutover_preflight_is_read_only_and_detects_nonempty_target(target, sample):
    empty = inspect_target(target)
    assert empty["target_empty"] is True
    assert empty["target_table_count"] == 0
    migrate(str(sample), target)
    populated = inspect_target(target)
    assert populated["target_empty"] is False
    assert populated["target_table_count"] > 0
