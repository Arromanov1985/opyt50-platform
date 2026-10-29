"""PostgreSQL runtime adapter checks against disposable CI PostgreSQL 17."""
import os
import sqlite3

import pytest

from app.db import SCHEMA
from app.release02 import MIGRATION
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
