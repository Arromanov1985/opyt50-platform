"""Security regression tests for the production hardening baseline."""
import hashlib

import pytest

from fastapi.testclient import TestClient

from app.db import database
from app.main import create_app
from app.security import (
    LEGACY_PASSWORD_ROUNDS,
    make_password_hash,
    password_needs_rehash,
    verify_password,
)

XHR = {"X-Requested-With": "OPYT50"}


def legacy_pbkdf2(password: str) -> str:
    salt = bytes.fromhex("00112233445566778899aabbccddeeff")
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt, LEGACY_PASSWORD_ROUNDS
    )
    return "pbkdf2_sha256$" + str(LEGACY_PASSWORD_ROUNDS) + "$" + salt.hex() + "$" + digest.hex()


def test_argon2id_is_default_and_legacy_pbkdf2_remains_verifiable():
    password = "A very long secure passphrase 2026"
    current = make_password_hash(password)
    assert current.startswith("$argon2id$")
    assert verify_password(password, current)
    assert not verify_password(password + "x", current)
    assert not password_needs_rehash(current)

    legacy = legacy_pbkdf2(password)
    assert verify_password(password, legacy)
    assert password_needs_rehash(legacy)


def test_successful_login_transparently_upgrades_legacy_password(tmp_path):
    app = create_app(str(tmp_path / "security.db"))
    password = "Legacy password long enough 2026"
    with TestClient(app) as client:
        with database(app.state.db_path) as db:
            cursor = db.execute(
                "INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
                ("candidate", "legacy@example.test", "Legacy User", legacy_pbkdf2(password)),
            )
            db.execute(
                "INSERT INTO candidate_profiles(user_id) VALUES(?)",
                (cursor.lastrowid,),
            )

        response = client.post(
            "/api/login",
            headers=XHR,
            json={"email": "legacy@example.test", "password": password},
        )
        assert response.status_code == 200, response.text

        with database(app.state.db_path) as db:
            upgraded = db.execute(
                "SELECT password_hash FROM users WHERE email=?",
                ("legacy@example.test",),
            ).fetchone()["password_hash"]
        assert upgraded.startswith("$argon2id$")
        assert verify_password(password, upgraded)


def test_new_single_factor_passwords_require_15_characters(tmp_path):
    app = create_app(str(tmp_path / "password-policy.db"))
    with TestClient(app) as client:
        response = client.post(
            "/api/register",
            headers=XHR,
            json={
                "role": "candidate",
                "name": "Кандидат",
                "email": "short@example.test",
                "password": "12345678901234",
            },
        )
        assert response.status_code == 422


def test_security_headers_and_oversized_api_requests(tmp_path):
    app = create_app(str(tmp_path / "headers.db"))
    with TestClient(app) as client:
        page = client.get("/")
        assert page.headers["x-content-type-options"] == "nosniff"
        assert page.headers["x-frame-options"] == "DENY"
        assert page.headers["referrer-policy"] == "no-referrer"
        assert page.headers["x-xss-protection"] == "0"
        assert page.headers["cross-origin-opener-policy"] == "same-origin"
        assert page.headers["cross-origin-resource-policy"] == "same-origin"
        assert page.headers["strict-transport-security"] == "max-age=31536000"
        assert "geolocation=()" in page.headers["permissions-policy"]
        assert "form-action 'self'" in page.headers["content-security-policy"]

        huge = client.post(
            "/api/login",
            headers={**XHR, "Content-Type": "application/json"},
            content=b"x" * 262_145,
        )
        assert huge.status_code == 413


def test_production_hides_docs_and_sets_strict_secure_cookie(tmp_path, monkeypatch):
    monkeypatch.setenv("OPYT50_PUBLIC_URL", "https://stazhno.ru")
    monkeypatch.delenv("OPYT50_ENABLE_DOCS", raising=False)
    monkeypatch.delenv("OPYT50_COOKIE_SECURE", raising=False)
    app = create_app(str(tmp_path / "production.db"))

    with TestClient(app, base_url="https://stazhno.ru") as client:
        assert client.get("/api/docs").status_code == 404
        assert client.get("/api/redoc").status_code == 404
        assert client.get("/api/openapi.json").status_code == 404

        response = client.post(
            "/api/register",
            headers=XHR,
            json={
                "role": "candidate",
                "name": "Безопасный пользователь",
                "email": "secure@example.test",
                "password": "long secure password 2026",
            },
        )
        assert response.status_code == 201, response.text
        cookies = "\n".join(response.headers.get_list("set-cookie")).lower()
        assert "__host-stazhno_session=" in cookies
        assert "secure" in cookies
        assert "httponly" in cookies
        assert "samesite=strict" in cookies



def test_trusted_host_allowlist_rejects_forged_host(tmp_path, monkeypatch):
    monkeypatch.setenv("OPYT50_ALLOWED_HOSTS", "stazhno.ru,www.stazhno.ru")
    app = create_app(str(tmp_path / "trusted-host.db"))

    with TestClient(app, base_url="https://stazhno.ru") as client:
        assert client.get("/api/health").status_code == 200
    with TestClient(app, base_url="https://evil.example") as attacker:
        assert attacker.get("/api/health").status_code == 400



def test_cross_site_mutations_are_rejected_by_origin_and_fetch_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("OPYT50_PUBLIC_URL", "https://stazhno.ru")
    app = create_app(str(tmp_path / "origin.db"))
    body = {
        "role": "candidate",
        "name": "Пользователь",
        "email": "origin@example.test",
        "password": "long secure password 2026",
    }
    with TestClient(app, base_url="https://stazhno.ru") as client:
        wrong_origin = client.post(
            "/api/register",
            headers={**XHR, "Origin": "https://evil.example"},
            json=body,
        )
        assert wrong_origin.status_code == 403

        cross_site = client.post(
            "/api/register",
            headers={**XHR, "Sec-Fetch-Site": "cross-site"},
            json=body,
        )
        assert cross_site.status_code == 403

        same_origin = client.post(
            "/api/register",
            headers={**XHR, "Origin": "https://stazhno.ru", "Sec-Fetch-Site": "same-origin"},
            json=body,
        )
        assert same_origin.status_code == 201, same_origin.text



def test_admin_login_revokes_previous_session_and_uses_short_lifetime(tmp_path):
    app = create_app(str(tmp_path / "admin-session.db"))
    password = "Administrator secure password 2026"
    with TestClient(app) as first:
        with database(app.state.db_path) as db:
            db.execute(
                "INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
                ("admin", "admin-security@example.test", "Администратор", make_password_hash(password)),
            )

        login1 = first.post(
            "/api/login",
            headers=XHR,
            json={"email": "admin-security@example.test", "password": password},
        )
        assert login1.status_code == 200, login1.text
        assert "max-age=1800" in "\n".join(login1.headers.get_list("set-cookie")).lower()
        assert first.get("/api/me").status_code == 200

        with TestClient(app) as second:
            login2 = second.post(
                "/api/login",
                headers=XHR,
                json={"email": "admin-security@example.test", "password": password},
            )
            assert login2.status_code == 200, login2.text
            assert second.get("/api/me").status_code == 200
            assert first.get("/api/me").status_code == 401

            with database(app.state.db_path) as db:
                count = db.execute(
                    "SELECT COUNT(*) FROM sessions WHERE user_id=(SELECT id FROM users WHERE email=?)",
                    ("admin-security@example.test",),
                ).fetchone()[0]
                assert count == 1



def test_admin_email_mfa_requires_second_factor_before_session(tmp_path, monkeypatch):
    monkeypatch.setenv("OPYT50_ENV", "development")
    monkeypatch.setenv("OPYT50_ADMIN_MFA_MODE", "email")
    monkeypatch.delenv("OPYT50_PUBLIC_URL", raising=False)
    app = create_app(str(tmp_path / "admin-mfa.db"))
    password = "Administrator secure password 2026"

    with TestClient(app) as client:
        with database(app.state.db_path) as db:
            db.execute(
                "INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
                ("admin", "mfa-admin@example.test", "Администратор", make_password_hash(password)),
            )

        login = client.post(
            "/api/login",
            headers=XHR,
            json={"email": "mfa-admin@example.test", "password": password},
        )
        assert login.status_code == 200, login.text
        payload = login.json()
        assert payload["mfa_required"] is True
        assert payload["challenge_id"]
        assert payload["debug_code"].isdigit() and len(payload["debug_code"]) == 8
        assert "set-cookie" not in login.headers
        assert client.get("/api/me").status_code == 401

        wrong = client.post(
            "/api/admin/mfa/verify",
            headers=XHR,
            json={"challenge_id": payload["challenge_id"], "code": "00000000"},
        )
        assert wrong.status_code == 401
        assert client.get("/api/me").status_code == 401

        verified = client.post(
            "/api/admin/mfa/verify",
            headers=XHR,
            json={"challenge_id": payload["challenge_id"], "code": payload["debug_code"]},
        )
        assert verified.status_code == 200, verified.text
        assert verified.json()["user"]["role"] == "admin"
        assert client.get("/api/me").status_code == 200

        reused = client.post(
            "/api/admin/mfa/verify",
            headers=XHR,
            json={"challenge_id": payload["challenge_id"], "code": payload["debug_code"]},
        )
        assert reused.status_code == 400

        with database(app.state.db_path) as db:
            events = db.execute(
                "SELECT event_type,detail FROM security_events ORDER BY created_at"
            ).fetchall()
            event_types = [row["event_type"] for row in events]
            assert "admin_mfa_challenge_issued" in event_types
            assert "login_password_verified_mfa_required" in event_types
            assert "admin_mfa_failed" in event_types
            assert "admin_mfa_success" in event_types
            serialized = "\n".join(str(dict(row)) for row in events)
            assert payload["debug_code"] not in serialized


def test_admin_mfa_challenge_locks_after_five_wrong_codes(tmp_path, monkeypatch):
    monkeypatch.setenv("OPYT50_ENV", "development")
    monkeypatch.setenv("OPYT50_ADMIN_MFA_MODE", "email")
    monkeypatch.delenv("OPYT50_PUBLIC_URL", raising=False)
    app = create_app(str(tmp_path / "admin-mfa-lock.db"))
    password = "Administrator secure password 2026"

    with TestClient(app) as client:
        with database(app.state.db_path) as db:
            db.execute(
                "INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
                ("admin", "mfa-lock@example.test", "Администратор", make_password_hash(password)),
            )

        login = client.post(
            "/api/login",
            headers=XHR,
            json={"email": "mfa-lock@example.test", "password": password},
        ).json()
        challenge = login["challenge_id"]
        correct = login["debug_code"]
        wrong = "00000000" if correct != "00000000" else "11111111"

        for attempt in range(1, 6):
            response = client.post(
                "/api/admin/mfa/verify",
                headers=XHR,
                json={"challenge_id": challenge, "code": wrong},
            )
            assert response.status_code == (429 if attempt == 5 else 401)

        blocked_correct = client.post(
            "/api/admin/mfa/verify",
            headers=XHR,
            json={"challenge_id": challenge, "code": correct},
        )
        assert blocked_correct.status_code in {400, 429}
        assert client.get("/api/me").status_code == 401


def test_admin_security_events_endpoint_is_admin_only(tmp_path):
    app = create_app(str(tmp_path / "security-events.db"))
    password = "Administrator secure password 2026"

    with TestClient(app) as admin, TestClient(app) as candidate:
        with database(app.state.db_path) as db:
            db.execute(
                "INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
                ("admin", "events-admin@example.test", "Администратор", make_password_hash(password)),
            )

        admin_login = admin.post(
            "/api/login",
            headers=XHR,
            json={"email": "events-admin@example.test", "password": password},
        )
        assert admin_login.status_code == 200

        candidate_registration = candidate.post(
            "/api/register",
            headers=XHR,
            json={
                "role": "candidate",
                "name": "Кандидат",
                "email": "events-candidate@example.test",
                "password": "candidate secure password 2026",
            },
        )
        assert candidate_registration.status_code == 201

        allowed = admin.get("/api/admin/security-events")
        assert allowed.status_code == 200
        assert isinstance(allowed.json()["events"], list)
        assert candidate.get("/api/admin/security-events").status_code == 403



def test_login_throttle_limits_repeated_failures_for_same_identity_and_source(tmp_path):
    app = create_app(str(tmp_path / "login-throttle.db"))
    password = "Candidate secure password 2026"
    with TestClient(app) as client:
        with database(app.state.db_path) as db:
            cursor = db.execute(
                "INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
                ("candidate", "throttle@example.test", "Кандидат", make_password_hash(password)),
            )
            db.execute("INSERT INTO candidate_profiles(user_id) VALUES(?)", (cursor.lastrowid,))

        for _ in range(10):
            response = client.post(
                "/api/login",
                headers=XHR,
                json={"email": "throttle@example.test", "password": "wrong password"},
            )
            assert response.status_code == 401

        blocked = client.post(
            "/api/login",
            headers=XHR,
            json={"email": "throttle@example.test", "password": password},
        )
        assert blocked.status_code == 429
        assert blocked.headers["retry-after"] == "900"


def test_admin_security_status_reports_hardening_without_secrets(tmp_path):
    app = create_app(str(tmp_path / "security-status.db"))
    password = "Administrator secure password 2026"
    with TestClient(app) as client:
        with database(app.state.db_path) as db:
            db.execute(
                "INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
                ("admin", "status-admin@example.test", "Администратор", make_password_hash(password)),
            )
        login = client.post(
            "/api/login",
            headers=XHR,
            json={"email": "status-admin@example.test", "password": password},
        )
        assert login.status_code == 200
        status = client.get("/api/admin/security-status")
        assert status.status_code == 200
        data = status.json()
        assert data["password_hash"] == "argon2id"
        assert data["admin_session_minutes"] == 30
        assert data["admin_mfa_mode"] in {"off", "email"}
        assert "password" not in str(data).casefold()
        assert "token" not in str(data).casefold()


def test_production_refuses_email_mfa_without_smtp(tmp_path, monkeypatch):
    monkeypatch.setenv("OPYT50_ENV", "production")
    monkeypatch.setenv("OPYT50_PUBLIC_URL", "https://stazhno.ru")
    monkeypatch.setenv("OPYT50_COOKIE_SECURE", "1")
    monkeypatch.setenv("OPYT50_ENABLE_DOCS", "0")
    monkeypatch.setenv("OPYT50_ADMIN_MFA_MODE", "email")
    monkeypatch.delenv("OPYT50_SMTP_HOST", raising=False)
    monkeypatch.delenv("OPYT50_MAIL_FROM", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    app = create_app(str(tmp_path / "unsafe-production.db"))
    with pytest.raises(RuntimeError, match="admin email MFA requires configured SMTP"):
        with TestClient(app):
            pass
