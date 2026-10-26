"""PostgreSQL diagnostic must not touch a real database in unit tests."""
import sys
import types
from unittest.mock import MagicMock

import pytest

from scripts.check_postgres_connection import check_connection, main


def test_requires_database_url():
    with pytest.raises(ValueError, match="DATABASE_URL"):
        check_connection("")


def _mock_driver(monkeypatch, *, tls=False):
    cursor = MagicMock()
    cursor.fetchone.return_value = ("default_db", "gen_user", "17.0", tls)
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.cursor.return_value.__enter__.return_value = cursor
    driver = types.SimpleNamespace(connect=MagicMock(return_value=conn))
    monkeypatch.setitem(sys.modules, "psycopg", driver)
    return driver, cursor


def test_read_only_connection_diagnostic(monkeypatch):
    driver, cursor = _mock_driver(monkeypatch)
    report = check_connection("postgresql://test:secret@db.invalid/default_db")
    assert report["connected"] is True
    assert report["database"] == "default_db"
    assert report["tls_active"] is False
    assert "secret" not in str(report)
    sql = cursor.execute.call_args.args[0].lower()
    assert sql.startswith("select ")
    assert "insert" not in sql and "update" not in sql and "delete" not in sql
    assert driver.connect.call_args.kwargs["connect_timeout"] == 5


def test_tls_requirement_fails_closed(monkeypatch):
    _mock_driver(monkeypatch, tls=False)
    with pytest.raises(RuntimeError, match="TLS"):
        check_connection("postgresql://test@db.invalid/default_db", require_tls=True)


def test_exception_does_not_expose_password(monkeypatch, capsys):
    driver, _ = _mock_driver(monkeypatch)
    driver.connect.side_effect = Exception("postgresql://someone:SENSITIVE_SECRET@host/db")
    monkeypatch.setenv("DATABASE_URL", "postgresql://someone:SENSITIVE_SECRET@host/db")
    assert main() == 1
    assert "SENSITIVE_SECRET" not in capsys.readouterr().err
