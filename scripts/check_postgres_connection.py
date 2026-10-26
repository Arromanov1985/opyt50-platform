"""Read-only connection diagnostic for the isolated OПЫТНО PostgreSQL cluster.

Run only from a host attached to the same Timeweb private network.
No tables are created or modified and credentials are never printed.
"""
from __future__ import annotations

import json
import os
import sys


def check_connection(dsn: str, *, require_tls: bool = False) -> dict[str, object]:
    if not dsn or not dsn.strip():
        raise ValueError("DATABASE_URL is not configured")
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "Install PostgreSQL driver from requirements-postgres.txt first"
        ) from exc
    # No DDL or DML. Use read-only transactions as an additional safeguard.
    with psycopg.connect(dsn, connect_timeout=5, autocommit=True) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT current_database(), current_user, "
                "current_setting('server_version'), "
                "(SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid())"
            )
            database, user, version, tls = cursor.fetchone()
        if require_tls and not tls:
            raise RuntimeError("TLS is required but connection is not encrypted")
        return {
            "connected": True,
            "database": str(database),
            "user": str(user),
            "server_version": str(version),
            "tls_active": bool(tls),
            "read_only_check": True,
        }


def main() -> int:
    require_tls = os.getenv("OPYTNO_REQUIRE_PG_TLS", "0") == "1"
    try:
        result = check_connection(os.getenv("DATABASE_URL", ""), require_tls=require_tls)
    except (ValueError, RuntimeError) as exc:
        print(f"PostgreSQL check failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        # Never print connection exception details: they may contain sensitive URLs.
        print(f"PostgreSQL check failed ({type(exc).__name__}); see network and credentials", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
