"""Existing daily counters survive expansion of the public funnel actions."""
import sqlite3

import pytest

from app.db import database, init_db
from app.release02 import init_release02


OLD_GROWTH_TABLE = """CREATE TABLE growth_daily_counts (
    event_date TEXT NOT NULL,
    source TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('view','jobs_click','profile_click')),
    total INTEGER NOT NULL DEFAULT 0 CHECK(total>=0),
    PRIMARY KEY(event_date,source,action)
)"""
EXISTING_COUNTS = [
    ("2026-11-01", "journal", "view", 17),
    ("2026-11-02", "kak-proverit-vakansiyu", "jobs_click", 5),
]


def old_growth_database(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    path = str(tmp_path / "existing-growth.sqlite")
    init_db(path)
    with database(path) as db:
        db.execute(OLD_GROWTH_TABLE)
        db.executemany("INSERT INTO growth_daily_counts VALUES(?,?,?,?)", EXISTING_COUNTS)
    return path


def test_sqlite_upgrade_preserves_counts_and_constraints(tmp_path, monkeypatch):
    path = old_growth_database(tmp_path, monkeypatch)
    init_release02(path)
    init_release02(path)

    with database(path) as db:
        assert [tuple(row) for row in db.execute(
            "SELECT event_date,source,action,total FROM growth_daily_counts ORDER BY event_date"
        )] == EXISTING_COUNTS
        columns = db.execute("PRAGMA table_info(growth_daily_counts)").fetchall()
        assert [row["name"] for row in columns] == ["event_date", "source", "action", "total"]
        assert [row["pk"] for row in columns] == [1, 2, 3, 0]
        for action in ("community_click", "company_click", "vacancy_click", "apply_click",
                       "article_click", "recommended_vacancy_click"):
            db.execute("INSERT INTO growth_daily_counts VALUES(?,?,?,?)",
                       ("2026-11-03", "journal", action, 2))

    for action, total in (("unknown", 1), ("community_click", -1)):
        with pytest.raises(sqlite3.IntegrityError):
            with database(path) as db:
                db.execute("INSERT INTO growth_daily_counts VALUES(?,?,?,?)",
                           ("2026-11-04", "journal", action, total))
    with pytest.raises(sqlite3.IntegrityError):
        with database(path) as db:
            db.execute("INSERT INTO growth_daily_counts VALUES(?,?,?,?)", EXISTING_COUNTS[0])


def test_sqlite_upgrade_rolls_back_if_later_startup_fails(tmp_path, monkeypatch):
    path = old_growth_database(tmp_path, monkeypatch)
    monkeypatch.setattr("app.release02.production_admin_email_migration_enabled", lambda: True)

    def fail_after_upgrade(_db):
        raise RuntimeError("simulate a later startup failure")

    monkeypatch.setattr("app.release02.migrate_legacy_admin_email", fail_after_upgrade)
    with pytest.raises(RuntimeError, match="later startup failure"):
        init_release02(path)
    with database(path) as db:
        assert [tuple(row) for row in db.execute(
            "SELECT event_date,source,action,total FROM growth_daily_counts ORDER BY event_date"
        )] == EXISTING_COUNTS
        definition = db.execute(
            "SELECT sql FROM sqlite_master WHERE name='growth_daily_counts'"
        ).fetchone()["sql"]
        assert "community_click" not in definition
        assert "apply_click" not in definition
        assert db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='growth_daily_counts_upgrade'"
        ).fetchone() is None


def test_latest_deployed_schema_upgrades_without_losing_public_events(tmp_path, monkeypatch):
    path = old_growth_database(tmp_path, monkeypatch)
    with database(path) as db:
        db.execute("DROP TABLE growth_daily_counts")
        db.execute(OLD_GROWTH_TABLE.replace(
            "'view','jobs_click','profile_click'",
            "'view','jobs_click','profile_click','community_click','company_click','vacancy_click','apply_click'",
        ))
        prior = ("2026-11-02", "vacancy:1", "apply_click", 8)
        db.execute("INSERT INTO growth_daily_counts VALUES(?,?,?,?)", prior)
    init_release02(path)
    init_release02(path)
    with database(path) as db:
        assert tuple(db.execute("SELECT * FROM growth_daily_counts").fetchone()) == prior
        for action in ("article_click", "recommended_vacancy_click"):
            db.execute("INSERT INTO growth_daily_counts VALUES(?,?,?,?)",
                       ("2026-11-03", "journal", action, 1))
