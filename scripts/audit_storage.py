"""Read-only SQLite storage audit for the fictional preview environment."""
import json
import os
import sqlite3
from pathlib import Path

TABLES = ("users", "vacancies", "job_applications", "invitations")

def audit(path: str) -> dict:
    target = Path(path)
    result = {"path": str(target), "exists": target.is_file(), "counts": {}, "integrity": None}
    if not target.is_file():
        return result
    # URI mode=ro prevents accidentally creating a new empty database.
    with sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        result["counts"] = {
            table: db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in TABLES if table in tables
        }
        result["integrity"] = db.execute("PRAGMA integrity_check").fetchone()[0]
    return result

if __name__ == "__main__":
    print(json.dumps(audit(os.getenv("OPYT50_DB_PATH", "/srv/data/opyt50.db")), ensure_ascii=False, indent=2))
