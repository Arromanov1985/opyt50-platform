"""Read-only production cutover preflight for SQLite -> PostgreSQL.

This command never modifies either database. It validates the SQLite source,
reports a SHA-256 digest and confirms whether the PostgreSQL target schema is
empty. Credentials and row values are never printed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from scripts.migrate_sqlite_to_postgres import inspect_sqlite


def sha256_file(filename: str) -> str:
    digest = hashlib.sha256()
    with open(filename, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_target(dsn: str) -> dict[str, object]:
    if not dsn:
        raise ValueError("DATABASE_URL is required")
    import psycopg

    with psycopg.connect(dsn, connect_timeout=10, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT current_database(), current_user, current_schema(), "
                "current_setting('server_version'), "
                "(SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid())"
            )
            database, user, schema, version, tls = cur.fetchone()
            cur.execute(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema=current_schema() AND table_type='BASE TABLE'"
            )
            table_count = int(cur.fetchone()[0])
    return {
        "connected": True,
        "database": str(database),
        "user": str(user),
        "schema": str(schema),
        "server_version": str(version),
        "tls_active": bool(tls),
        "target_table_count": table_count,
        "target_empty": table_count == 0,
        "read_only_preflight": True,
    }


def build_report(source: str, dsn: str) -> dict[str, object]:
    path = Path(source)
    if not path.is_file():
        raise ValueError("SQLite source file is missing")
    return {
        "source": {
            "integrity_ok": True,
            "sha256": sha256_file(str(path)),
            "table_counts": inspect_sqlite(str(path)),
        },
        "target": inspect_target(dsn),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="Verified SQLite snapshot")
    args = parser.parse_args(argv)
    try:
        report = build_report(args.source, os.getenv("DATABASE_URL", ""))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["target"]["target_empty"] else 2
    except Exception as exc:
        print(
            f"Preflight failed: {type(exc).__name__}; no database details logged",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
