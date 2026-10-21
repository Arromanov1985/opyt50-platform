"""Create and verify a consistent SQLite backup without stopping the application.

Usage: python scripts/backup_sqlite.py --output /tmp/opyt50-backup.db
Download the resulting file outside the container immediately.
"""
import argparse
import os
import sqlite3
from pathlib import Path


def backup(source: str, destination: str) -> None:
    src = Path(source)
    dst = Path(destination)
    if not src.is_file():
        raise FileNotFoundError(f"Database does not exist: {src}")
    if src.resolve() == dst.resolve():
        raise ValueError("Backup destination must differ from source")
    if dst.exists():
        raise FileExistsError(f"Refusing to overwrite existing backup: {dst}")
    if not dst.parent.is_dir():
        raise FileNotFoundError(f"Backup directory does not exist: {dst.parent}")
    # Exclusive creation avoids silently replacing previous backups.
    with dst.open("xb"):
        pass
    try:
        with sqlite3.connect(src.resolve().as_uri() + "?mode=ro", uri=True) as original:
            with sqlite3.connect(dst) as copy:
                original.backup(copy)
                check = copy.execute("PRAGMA integrity_check").fetchone()[0]
                if check != "ok":
                    raise RuntimeError(f"Backup integrity check failed: {check}")
    except Exception:
        dst.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=os.getenv("OPYT50_DB_PATH", "/srv/data/opyt50.db"))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    backup(args.source, args.output)
    print(f"Backup verified: {args.output}")
