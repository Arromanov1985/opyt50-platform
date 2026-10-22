import sqlite3
import pytest
from scripts.backup_sqlite import backup


def test_backup_contains_committed_rows(tmp_path):
    source = tmp_path / "source.db"
    output = tmp_path / "backup.db"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        db.execute("INSERT INTO users VALUES (7)")
    backup(str(source), str(output))
    with sqlite3.connect(output) as db:
        assert db.execute("SELECT id FROM users").fetchall() == [(7,)]
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_refuses_overwrite(tmp_path):
    source = tmp_path / "source.db"
    output = tmp_path / "existing.db"
    sqlite3.connect(source).close()
    output.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        backup(str(source), str(output))
    assert output.read_bytes() == b"keep"


def test_missing_source_does_not_create_backup(tmp_path):
    output = tmp_path / "backup.db"
    with pytest.raises(FileNotFoundError):
        backup(str(tmp_path / "missing.db"), str(output))
    assert not output.exists()
