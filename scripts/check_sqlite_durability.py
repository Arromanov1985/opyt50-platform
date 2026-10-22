"""Read-only check of SQLite durability and backup readiness.

This script never writes to the application database.
"""
import argparse
import json
import os
import sqlite3
from pathlib import Path


def inspect(db_path: str) -> dict:
    db = Path(db_path)
    result = {"database": str(db), "exists": db.is_file()}
    if not db.is_file():
        result["integrity"] = "missing"
        return result
    with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        result["integrity"] = conn.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        result["counts"] = {
            name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            for name in ("users", "vacancies", "job_applications", "invitations")
            if name in tables
        }
    result["mount"] = _mount_for(db)
    result["durability_verified"] = False
    result["warning"] = (
        "Mount type alone does not prove persistence. Confirm a configured "
        "persistent volume and rehearse a redeploy before real users."
    )
    return result


def _mount_for(path: Path) -> dict:
    try:
        mounts = []
        for line in Path("/proc/mounts").read_text().splitlines():
            fields = line.split()
            if len(fields) >= 3:
                mounts.append((fields[1].replace("\\040", " "), fields[2]))
        resolved = path.resolve()
        matches = [
            (mount, fs) for mount, fs in mounts
            if str(resolved) == mount or str(resolved).startswith(mount.rstrip("/") + "/")
        ]
        mount, fs = max(matches, key=lambda x: len(x[0]))
        return {"path": mount, "filesystem": fs}
    except (OSError, ValueError):
        return {"path": "unknown", "filesystem": "unknown"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=os.getenv("OPYT50_DB_PATH", "/srv/data/opyt50.db"))
    args = parser.parse_args()
    print(json.dumps(inspect(args.source), ensure_ascii=False, indent=2))
