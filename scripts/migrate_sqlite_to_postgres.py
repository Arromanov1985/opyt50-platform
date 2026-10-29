"""One-shot SQLite -> PostgreSQL importer for an isolated, EMPTY database.

Safeguards:
- SQLite input is opened read-only; a consistent online snapshot is used.
- PostgreSQL receives a single transaction, rolled back on any failure.
- Refuses a populated target and refuses a missing/invalid SQLite source.
- Validates row counts and referential integrity before commit.
- No database credentials, row values, or personal data are printed.
- Requires explicit --apply; by default only inspects source and exits.

IMPORTANT: Do not import from a stale backup while the old preview accepts writes:
this is a one-time snapshot, NOT ongoing synchronization or a cutover.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

from scripts.postgres_schema import postgres_schema

# Parent tables before children to satisfy existing foreign keys.
ORDER = (
    "users", "candidate_profiles", "employer_profiles", "vacancies",
    "invitations", "demo_transactions", "sessions", "candidate_favorites",
    "job_applications", "application_events", "account_controls", "email_tokens",
    "email_outbox", "admin_audit", "vacancy_updates",
    "vacancy_update_recipients",
)
IDENTITY_TABLES = (
    "users", "vacancies", "invitations", "demo_transactions",
    "job_applications", "application_events", "email_outbox",
    "admin_audit", "vacancy_updates",
)


def source_snapshot(filename: str, destination: str) -> None:
    source = Path(filename)
    if not source.is_file():
        raise ValueError("SQLite source file is missing")
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(destination)) as target:
            src.backup(target)


def inspect_sqlite(filename: str) -> dict[str, int]:
    with closing(sqlite3.connect(f"file:{Path(filename).resolve()}?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed")
        fk_errors = db.execute("PRAGMA foreign_key_check").fetchall()
        if fk_errors:
            raise ValueError("SQLite foreign key check failed")
        present = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        missing = set(ORDER) - present
        if missing:
            raise ValueError("SQLite source is missing required tables: " + ", ".join(sorted(missing)))
        return {table: db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                for table in ORDER}


def migrate(snapshot: str, dsn: str) -> dict[str, int]:
    if not dsn:
        raise ValueError("DATABASE_URL is required")
    import psycopg
    from psycopg import sql

    source_counts = inspect_sqlite(snapshot)
    # The source is static during the entire migration, including verification.
    with closing(sqlite3.connect(f"file:{Path(snapshot).resolve()}?mode=ro", uri=True)) as source:
        with psycopg.connect(dsn, connect_timeout=10, autocommit=False) as target:
            # All operations, including schema creation, are atomic in PG.
            try:
                with target.cursor() as cur:
                    cur.execute("SELECT count(*) FROM information_schema.tables "
                                "WHERE table_schema=current_schema() AND table_type='BASE TABLE'")
                    if cur.fetchone()[0] != 0:
                        raise ValueError("Target schema is not empty; refusing to overwrite any data")
                    cur.execute(postgres_schema())
                    for table in ORDER:
                        columns = [row[1] for row in source.execute(f'PRAGMA table_info("{table}")')]
                        if not columns:
                            raise ValueError("No columns in " + table)
                        identifiers = sql.SQL(", ").join(map(sql.Identifier, columns))
                        statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                            sql.Identifier(table), identifiers,
                            sql.SQL(", ").join(sql.Placeholder() for _ in columns),
                        )
                        rows = source.execute(f'SELECT * FROM "{table}"').fetchall()
                        if rows:
                            cur.executemany(statement, rows)
                    for table in IDENTITY_TABLES:
                        cur.execute(
                            sql.SQL("SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                                    "COALESCE((SELECT max(id) FROM {}), 1), "
                                    "(SELECT count(*) > 0 FROM {}))").format(
                                        sql.Identifier(table), sql.Identifier(table)
                                    ),
                            (table,),
                        )
                    for table, expected in source_counts.items():
                        cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table)))
                        if cur.fetchone()[0] != expected:
                            raise ValueError("Row count mismatch in " + table)
                target.commit()
            except BaseException:
                target.rollback()
                raise
    return source_counts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="Local SQLite snapshot, NEVER a live database URL")
    parser.add_argument("--apply", action="store_true", help="Explicitly enable import into an empty PG database")
    args = parser.parse_args(argv)
    try:
        # Snapshot even if source is WAL-mode to avoid losing pending committed data.
        with tempfile.TemporaryDirectory(prefix="opytno-pg-migrate-") as tmp:
            snap = str(Path(tmp) / "source.db")
            source_snapshot(args.source, snap)
            counts = inspect_sqlite(snap)
            if not args.apply:
                print(json.dumps({"mode": "dry-run", "source_ok": True,
                                  "table_counts": counts}, ensure_ascii=False))
                return 0
            result = migrate(snap, os.getenv("DATABASE_URL", ""))
            print(json.dumps({"imported": True, "table_counts": result}, ensure_ascii=False))
            return 0
    except Exception as exc:
        # Do not disclose DB URLs or row data even if the driver contains them in errors.
        print(f"Migration failed: {type(exc).__name__}; no database details logged",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
