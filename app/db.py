"""SQLite persistence for the local MVP (replaceable with PostgreSQL later)."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('candidate', 'employer', 'admin')),
  name TEXT NOT NULL,
  phone TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS candidate_profiles (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  profession TEXT NOT NULL DEFAULT '',
  city TEXT NOT NULL DEFAULT '',
  skills TEXT NOT NULL DEFAULT '',
  salary_min INTEGER NOT NULL DEFAULT 0 CHECK(salary_min >= 0),
  schedule TEXT NOT NULL DEFAULT 'Любой',
  employment TEXT NOT NULL DEFAULT 'Любая',
  about TEXT NOT NULL DEFAULT '',
  is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS employer_profiles (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  company_name TEXT NOT NULL,
  inn TEXT NOT NULL DEFAULT '',
  verified INTEGER NOT NULL DEFAULT 0 CHECK(verified IN (0,1))
);
CREATE TABLE IF NOT EXISTS vacancies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  employer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  city TEXT NOT NULL,
  salary_min INTEGER NOT NULL CHECK(salary_min >= 0),
  salary_max INTEGER NOT NULL CHECK(salary_max >= salary_min),
  schedule TEXT NOT NULL DEFAULT 'Любой',
  employment TEXT NOT NULL DEFAULT 'Любая',
  skills TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed')),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS invitations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  vacancy_id INTEGER NOT NULL REFERENCES vacancies(id) ON DELETE CASCADE,
  candidate_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  employer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'sent' CHECK(status IN ('sent','accepted','declined')),
  share_consent INTEGER NOT NULL DEFAULT 0,
  contact_shared INTEGER NOT NULL DEFAULT 0,
  price_rub INTEGER NOT NULL CHECK(price_rub >= 0),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  responded_at TEXT,
  UNIQUE(vacancy_id,candidate_id)
);
CREATE TABLE IF NOT EXISTS demo_transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invitation_id INTEGER NOT NULL UNIQUE REFERENCES invitations(id) ON DELETE CASCADE,
  amount_rub INTEGER NOT NULL CHECK(amount_rub >= 0),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vacancies_status ON vacancies(status);
CREATE INDEX IF NOT EXISTS idx_invitations_employer ON invitations(employer_id);
CREATE INDEX IF NOT EXISTS idx_invitations_candidate ON invitations(candidate_id);
"""


@contextmanager
def database(path: str) -> Iterator[sqlite3.Connection]:
    """Always close connections and roll back failed writes."""
    # FastAPI may execute a sync dependency and its cleanup in different worker threads.
    # Connections are still created per request and never shared between requests.
    connection = sqlite3.connect(path, timeout=10, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    # SQLite lower()/LIKE only handle ASCII case folding by default; vacancies are in Russian.
    # A deterministic per-connection function provides correct Unicode casefold search.
    connection.create_function("unicode_fold", 1, lambda value: str(value or "").casefold(), deterministic=True)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with database(path) as connection:
        connection.executescript(SCHEMA)
        connection.execute("PRAGMA journal_mode = WAL")
