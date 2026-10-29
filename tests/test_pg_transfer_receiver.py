import hashlib
import sqlite3

from fastapi.testclient import TestClient

from app.db import SCHEMA
from app.release02 import MIGRATION
from scripts import pg_transfer_server as receiver

TOKEN = "test-token-that-is-long-enough-for-ci-only"


def _sample(path):
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA + "\n" + MIGRATION)
    return path.read_bytes()


def _headers(data):
    return {
        "Authorization": "Bearer " + TOKEN,
        "X-Opytno-Confirm": "copy-to-empty-postgres",
        "X-Snapshot-SHA256": hashlib.sha256(data).hexdigest(),
    }


def test_receiver_auth_required(monkeypatch):
    monkeypatch.setenv("OPYTNO_TRANSFER_TOKEN", TOKEN)
    with TestClient(receiver.app) as client:
        assert client.post("/transfer", content=b"x").status_code == 401


def test_receiver_accepts_valid_snapshot_with_mocked_migration(monkeypatch, tmp_path):
    monkeypatch.setenv("OPYTNO_TRANSFER_TOKEN", TOKEN)
    data = _sample(tmp_path / "source.db")
    monkeypatch.setattr(receiver, "migrate", lambda path, dsn: {"table_counts": {}, "content_verified": True})
    with TestClient(receiver.app) as client:
        r = client.post("/transfer", content=data, headers=_headers(data))
    assert r.status_code == 200
    assert r.json()["imported"] is True
