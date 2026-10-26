"""Real PostgreSQL 17 checks, restricted to a disposable CI database."""
import os
import sqlite3

import pytest

from app.db import SCHEMA
from app.release02 import MIGRATION
from scripts.migrate_sqlite_to_postgres import migrate


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
        conn.commit()
    return path


def test_import_preserves_ids_consents_and_relations(target, sample):
    import psycopg
    before = sample.read_bytes()
    counts = migrate(str(sample), target)
    assert counts["users"] == 2
    assert counts["job_applications"] == 1
    with psycopg.connect(target) as conn:
        assert conn.execute("SELECT id,vacancy_id,candidate_id FROM job_applications").fetchone() == (4, 3, 1)
        assert conn.execute("SELECT share_consent, contact_shared FROM invitations WHERE id=5").fetchone() == (1, 1)
        assert conn.execute("SELECT password_hash FROM users WHERE id=1").fetchone()[0] == "test-hash"
    assert sample.read_bytes() == before


def test_nonempty_target_is_rejected(target, sample):
    import psycopg
    migrate(str(sample), target)
    with pytest.raises(ValueError, match="not empty"):
        migrate(str(sample), target)
    with psycopg.connect(target) as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
