"""Small DB-API compatibility layer for running the existing MVP routes on PostgreSQL.

The application historically used sqlite3 directly.  This adapter deliberately supports
only the SQL patterns used by the current routes; it is not a general SQL translator.
"""
from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from typing import Iterator

import psycopg


IDENTITY_TABLES = {
    "users", "vacancies", "invitations", "demo_transactions", "job_applications",
    "application_events", "email_outbox", "admin_audit", "vacancy_updates",
}


class HybridRow(dict):
    """Mapping row that also supports sqlite-style numeric indexes."""
    def __init__(self, names, values):
        super().__init__(zip(names, values))
        self._values = tuple(values)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


def hybrid_row(cursor):
    names = [col.name for col in cursor.description]
    def make_row(values):
        return HybridRow(names, values)
    return make_row


class Result:
    def __init__(self, cursor=None, *, lastrowid=None, scalar=None, rowcount=None):
        self._cursor = cursor
        self.lastrowid = lastrowid
        self._scalar = scalar
        self._scalar_used = False
        self.rowcount = cursor.rowcount if cursor is not None and rowcount is None else (rowcount or 0)

    def fetchone(self):
        if self._scalar is not None and not self._scalar_used:
            self._scalar_used = True
            return (self._scalar,)
        return self._cursor.fetchone() if self._cursor is not None else None

    def fetchall(self):
        if self._scalar is not None and not self._scalar_used:
            self._scalar_used = True
            return [(self._scalar,)]
        return self._cursor.fetchall() if self._cursor is not None else []


def _translate(sql: str) -> tuple[str, str | None]:
    text = sql
    text = re.sub(r"datetime\('now'\)", "CURRENT_TIMESTAMP", text, flags=re.I)
    text = re.sub(r"unicode_fold\(([^()]+)\)", r"lower(\1)", text, flags=re.I)
    # Current search queries use instr(lower(column), ?) > 0.
    text = re.sub(
        r"instr\((lower\([^()]+\)),\s*\?\)\s*>\s*0",
        r"position(? in \1) > 0",
        text,
        flags=re.I,
    )
    ignore = bool(re.match(r"\s*INSERT\s+OR\s+IGNORE\s+INTO\s+", text, flags=re.I))
    if ignore:
        text = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", text, count=1, flags=re.I)

    match = re.match(r"\s*INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)", text, flags=re.I)
    table = match.group(1).lower() if match else None
    if ignore:
        text = text.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    if table in IDENTITY_TABLES and " returning " not in text.lower():
        text = text.rstrip().rstrip(";") + " RETURNING id"

    text = text.replace("?", "%s")
    return text, table


class PostgresCompatConnection:
    def __init__(self, dsn: str):
        self._connection = psycopg.connect(dsn, connect_timeout=10, autocommit=False, row_factory=hybrid_row)
        self._last_changes = 0

    def execute(self, sql: str, params=()):
        if sql.strip().lower() == "select changes()":
            return Result(scalar=self._last_changes, rowcount=1)

        translated, table = _translate(sql)
        cursor = self._connection.cursor()
        try:
            cursor.execute(translated, tuple(params))
        except psycopg.IntegrityError as exc:
            # sqlite routes already translate integrity failures into HTTP 409.
            # Clear PostgreSQL's aborted transaction before preserving that contract.
            self._connection.rollback()
            raise sqlite3.IntegrityError(str(exc)) from exc
        lastrowid = None
        if table in IDENTITY_TABLES:
            row = cursor.fetchone()
            if row is not None:
                lastrowid = row["id"]
                self._last_changes = 1
            else:
                self._last_changes = 0
        else:
            self._last_changes = max(cursor.rowcount, 0)
        return Result(cursor, lastrowid=lastrowid)

    def executescript(self, _script: str):
        # PostgreSQL schema is provisioned by the explicit migration.  Runtime startup
        # must never try to execute SQLite DDL against the managed database.
        return None

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()


@contextmanager
def postgres_database(dsn: str) -> Iterator[PostgresCompatConnection]:
    connection = PostgresCompatConnection(dsn)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
