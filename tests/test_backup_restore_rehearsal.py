"""Restore rehearsal operates on a separate, disposable SQLite file."""
import sqlite3
from pathlib import Path
from scripts.backup_sqlite import backup


def test_recovery_rehearsal_uses_independent_database(tmp_path):
    source = tmp_path / "live.db"
    snapshot = tmp_path / "snapshot.db"
    recovered = tmp_path / "recovered.db"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE job_applications (id INTEGER PRIMARY KEY)")
        db.execute("INSERT INTO job_applications VALUES (17)")
    backup(str(source), str(snapshot))
    backup(str(snapshot), str(recovered))
    with sqlite3.connect(recovered) as db:
        assert db.execute("SELECT id FROM job_applications").fetchall() == [(17,)]
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert Path(source).exists()
