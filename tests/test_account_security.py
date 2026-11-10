"""Self-service account security regression tests."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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
