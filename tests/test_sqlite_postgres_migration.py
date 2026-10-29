"""Dry-run validation uses only ephemeral SQLite; never an external PostgreSQL."""
import sqlite3

from app.db import SCHEMA
from app.release02 import MIGRATION
from scripts.migrate_sqlite_to_postgres import (
    IDENTITY_TABLES, ORDER, inspect_sqlite, main, source_snapshot,
)


def _sample_db(path):
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA + "\n" + MIGRATION)
        db.execute(
            "INSERT INTO users(email,password_hash,role,name) VALUES(?,?,?,?)",
            ("candidate@example.invalid", "fake-hash", "candidate", "Тест"),
        )
        db.execute(
            "INSERT INTO users(email,password_hash,role,name) VALUES(?,?,?,?)",
            ("employer@example.invalid", "fake-hash", "employer", "Тест"),
        )
        db.execute(
            "INSERT INTO vacancies(employer_id,title,city,salary_min,salary_max) "
            "VALUES(?,?,?,?,?)", (2, "Кладовщик", "Подольск", 70000, 100000),
        )
        db.execute(
            "INSERT INTO job_applications(vacancy_id,candidate_id) VALUES(?,?)", (1, 1),
        )


def test_dry_run_preserves_sqlite_source(tmp_path, capsys):
    dbfile = tmp_path / "source.db"
    _sample_db(dbfile)
    before = dbfile.read_bytes()
    assert main(["--source", str(dbfile)]) == 0
    assert dbfile.read_bytes() == before
    report = capsys.readouterr().out
    assert '"source_ok": true' in report
    assert '"job_applications": 1' in report
    assert '"users": 2' in report


def test_snapshot_keeps_referential_integrity(tmp_path):
    source = tmp_path / "source.db"
    snap = tmp_path / "snapshot.db"
    _sample_db(source)
    source_snapshot(str(source), str(snap))
    counts = inspect_sqlite(str(snap))
    assert counts["users"] == 2
    assert counts["vacancies"] == 1
    assert counts["job_applications"] == 1


def test_missing_source_is_rejected(tmp_path, capsys):
    assert main(["--source", str(tmp_path / "not-there.db")]) == 1
    assert "Migration failed" in capsys.readouterr().err


def test_apply_without_credentials_does_not_modify_source(tmp_path):
    dbfile = tmp_path / "source.db"
    _sample_db(dbfile)
    assert main(["--source", str(dbfile), "--apply"]) == 1
    assert inspect_sqlite(str(dbfile))["users"] == 2


def test_all_identity_tables_are_in_migration_order():
    assert set(IDENTITY_TABLES).issubset(ORDER)
    assert ORDER.index("users") < ORDER.index("vacancies") < ORDER.index("job_applications")
    assert ORDER.index("invitations") < ORDER.index("demo_transactions")
