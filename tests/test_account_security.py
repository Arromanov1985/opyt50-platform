"""Self-service account security regression tests."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import database
from app.main import create_app

XHR = {"X-Requested-With": "OPYT50"}
OLD_PASSWORD = "Original secure password 2026"
NEW_PASSWORD = "Different secure password 2026"


@pytest.fixture
def app(tmp_path: Path):
    return create_app(str(tmp_path / "account-security.db"))


def register(client, email="security-user@example.test"):
    response = client.post(
        "/api/register",
        headers=XHR,
        json={
            "role": "candidate",
            "name": "Тестовый пользователь",
            "email": email,
            "password": OLD_PASSWORD,
        },
    )
    assert response.status_code == 201, response.text


def login(client, password=OLD_PASSWORD):
    return client.post(
        "/api/login",
        headers=XHR,
        json={"email": "security-user@example.test", "password": password},
    )


def test_revoke_other_sessions_keeps_only_current_session(app):
    with TestClient(app) as first, TestClient(app) as second:
        register(first)
        assert login(second).status_code == 200
        assert first.get("/api/me").status_code == 200
        assert second.get("/api/me").status_code == 200

        before = first.get("/api/account/security")
        assert before.status_code == 200, before.text
        assert before.json()["active_sessions"] == 2

        revoked = first.post("/api/account/sessions/revoke-others", headers=XHR)
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["revoked"] == 1

        assert first.get("/api/me").status_code == 200
        assert second.get("/api/me").status_code == 401
        after = first.get("/api/account/security").json()
        assert after["active_sessions"] == 1
        assert any(
            event["event_type"] == "other_sessions_revoked"
            for event in after["events"]
        )


def test_password_change_rotates_current_session_and_revokes_all_others(app):
    with TestClient(app) as first, TestClient(app) as second, TestClient(app) as fresh:
        register(first)
        assert login(second).status_code == 200

        changed = first.post(
            "/api/account/password/change",
            headers=XHR,
            json={
                "current_password": OLD_PASSWORD,
                "new_password": NEW_PASSWORD,
            },
        )
        assert changed.status_code == 200, changed.text

        # The browser that changed the password receives a fresh session.
        assert first.get("/api/me").status_code == 200
        # Every session created before the change is invalid immediately.
        assert second.get("/api/me").status_code == 401

        assert login(fresh, OLD_PASSWORD).status_code == 401
        assert login(fresh, NEW_PASSWORD).status_code == 200

        security = first.get("/api/account/security")
        assert security.status_code == 200
        event_types = [item["event_type"] for item in security.json()["events"]]
        assert "password_changed_all_sessions_revoked" in event_types


def test_password_change_requires_current_password_and_rate_limits_failures(app):
    with TestClient(app) as client:
        register(client)
        for _ in range(5):
            failed = client.post(
                "/api/account/password/change",
                headers=XHR,
                json={
                    "current_password": "Wrong current password 2026",
                    "new_password": NEW_PASSWORD,
                },
            )
            assert failed.status_code == 401

        limited = client.post(
            "/api/account/password/change",
            headers=XHR,
            json={
                "current_password": OLD_PASSWORD,
                "new_password": NEW_PASSWORD,
            },
        )
        assert limited.status_code == 429
        assert limited.headers.get("retry-after")


def test_new_device_login_alerts_once_and_does_not_store_raw_ip(app):
    browser_a = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/152.0 YaBrowser/26.10.0.0",
    }
    browser_b = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Firefox/145.0",
    }

    with (
        TestClient(app, headers=browser_a) as first,
        TestClient(app, headers=browser_b) as second,
        TestClient(app, headers=browser_b) as third,
    ):
        register(first)

        with database(app.state.db_path) as db:
            assert db.execute(
                "SELECT COUNT(*) FROM email_outbox WHERE event='new_device_login'"
            ).fetchone()[0] == 0

        second_login = login(second)
        assert second_login.status_code == 200, second_login.text

        security = second.get("/api/account/security")
        assert security.status_code == 200, security.text
        labels = {item["device_label"] for item in security.json()["sessions"]}
        assert "Яндекс Браузер · Windows" in labels
        assert "Firefox · Linux" in labels
        assert any(
            item["event_type"] == "new_device_login"
            for item in security.json()["events"]
        )

        with database(app.state.db_path) as db:
            notices = db.execute(
                "SELECT subject,body FROM email_outbox WHERE event='new_device_login'"
            ).fetchall()
            assert len(notices) == 1
            assert "Firefox · Linux" in notices[0]["body"]
            serialized_devices = "\n".join(
                str(dict(row))
                for row in db.execute("SELECT * FROM account_devices").fetchall()
            )
            assert "127.0.0.1" not in serialized_devices
            assert "testclient" not in serialized_devices

        third_login = login(third)
        assert third_login.status_code == 200, third_login.text
        with __import__("app.db", fromlist=["database"]).database(app.state.db_path) as db:
            assert db.execute(
                "SELECT COUNT(*) FROM email_outbox WHERE event='new_device_login'"
            ).fetchone()[0] == 1
