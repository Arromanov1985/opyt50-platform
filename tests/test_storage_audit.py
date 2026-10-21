"""Regression tests: audit never creates or modifies the SQLite database."""
import sqlite3
from scripts.audit_storage import audit

def test_missing_database_not_created(tmp_path):
    path = tmp_path / "missing.db"
    result = audit(str(path))
    assert result["exists"] is False
    assert not path.exists()

def test_counts_are_read_only(tmp_path):
    path = tmp_path / "existing.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE users (id INTEGER)")
        db.execute("CREATE TABLE vacancies (id INTEGER)")
        db.execute("CREATE TABLE job_applications (id INTEGER)")
        db.execute("INSERT INTO users VALUES (1)")
        db.execute("INSERT INTO job_applications VALUES (1)")
    before = path.read_bytes()
    result = audit(str(path))
    assert result["counts"] == {"users": 1, "vacancies": 0, "job_applications": 1}
    assert result["integrity"] == "ok"
    assert path.read_bytes() == before
