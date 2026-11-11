"""Administrator WebAuthn/passkey regression tests."""
from pathlib import Path
from types import SimpleNamespace

import pyotp
from fastapi.testclient import TestClient

import app.main as main_module
from app.db import database
from app.main import create_app
from app.security import make_password_hash

XHR = {"X-Requested-With": "OPYT50"}
PASSWORD = "Administrator secure password 2026"


def create_admin(app, email="passkey-admin@example.test"):
    with database(app.state.db_path) as db:
        db.execute(
            "INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
            ("admin", email, "Администратор", make_password_hash(PASSWORD)),
        )


def login(client, email="passkey-admin@example.test"):
    return client.post(
        "/api/login",
        headers=XHR,
        json={"email": email, "password": PASSWORD},
    )


def register_fake_passkey(client, monkeypatch):
    start = client.post("/api/admin/passkeys/register/options", headers=XHR)
    assert start.status_code == 200, start.text
    payload = start.json()
    assert payload["challenge_id"]
    assert payload["public_key"]["challenge"]
    assert payload["public_key"]["rp"]["id"] == "testserver"

    monkeypatch.setattr(
        main_module,
        "verify_registration_response",
        lambda **kwargs: SimpleNamespace(
            credential_id=b"\x01\x02\x03",
            credential_public_key=b"fake-public-key",
            sign_count=0,
            credential_device_type=SimpleNamespace(value="multi_device"),
            credential_backed_up=True,
        ),
    )
    completed = client.post(
        "/api/admin/passkeys/register/verify",
        headers=XHR,
        json={
            "challenge_id": payload["challenge_id"],
            "label": "Windows Hello",
            "credential": {
                "id": "AQID",
                "rawId": "AQID",
                "type": "public-key",
                "response": {
                    "attestationObject": "AA",
                    "clientDataJSON": "AA",
                    "transports": ["internal"],
                },
                "clientExtensionResults": {},
            },
        },
    )
    assert completed.status_code == 200, completed.text


def test_admin_can_register_passkey_and_use_it_in_hybrid_mfa(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPYT50_ENV", "development")
    monkeypatch.setenv("OPYT50_ADMIN_MFA_MODE", "off")
    monkeypatch.delenv("OPYT50_PUBLIC_URL", raising=False)
    app = create_app(str(tmp_path / "admin-passkey.db"))

    with TestClient(app) as enrolled:
        create_admin(app)
        assert login(enrolled).status_code == 200
        register_fake_passkey(enrolled, monkeypatch)

        security = enrolled.get("/api/account/security")
        assert security.status_code == 200
        passkeys = security.json()["passkeys"]
        assert len(passkeys) == 1
        assert passkeys[0]["label"] == "Windows Hello"
        assert passkeys[0]["backed_up"] is True

        secret = pyotp.random_base32()
        monkeypatch.setenv("OPYT50_ADMIN_TOTP_SECRET", secret)
        monkeypatch.setenv("OPYT50_ADMIN_MFA_MODE", "hybrid")

        with TestClient(app) as second:
            auth = login(second)
            assert auth.status_code == 200, auth.text
            challenge = auth.json()
            assert challenge["mfa_required"] is True
            assert challenge["mfa_method"] == "webauthn"
            assert challenge["totp_fallback"] is True
            assert challenge["public_key"]["allowCredentials"][0]["id"] == "AQID"
            assert second.get("/api/me").status_code == 401

            monkeypatch.setattr(
                main_module,
                "verify_authentication_response",
                lambda **kwargs: SimpleNamespace(new_sign_count=1),
            )
            verified = second.post(
                "/api/admin/mfa/webauthn/verify",
                headers=XHR,
                json={
                    "challenge_id": challenge["challenge_id"],
                    "credential": {
                        "id": "AQID",
                        "rawId": "AQID",
                        "type": "public-key",
                        "response": {
                            "authenticatorData": "AA",
                            "clientDataJSON": "AA",
                            "signature": "AA",
                            "userHandle": None,
                        },
                        "clientExtensionResults": {},
                    },
                },
            )
            assert verified.status_code == 200, verified.text
            assert verified.json()["user"]["role"] == "admin"
            assert second.get("/api/me").status_code == 200

        with database(app.state.db_path) as db:
            row = db.execute(
                "SELECT sign_count,last_used_at FROM admin_webauthn_credentials WHERE credential_id=?",
                ("AQID",),
            ).fetchone()
            assert row["sign_count"] == 1
            assert row["last_used_at"]


def test_hybrid_passkey_login_can_fall_back_to_totp(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPYT50_ENV", "development")
    monkeypatch.setenv("OPYT50_ADMIN_MFA_MODE", "off")
    monkeypatch.delenv("OPYT50_PUBLIC_URL", raising=False)
    app = create_app(str(tmp_path / "admin-passkey-fallback.db"))

    with TestClient(app) as enrolled:
        create_admin(app)
        assert login(enrolled).status_code == 200
        register_fake_passkey(enrolled, monkeypatch)

        secret = pyotp.random_base32()
        monkeypatch.setenv("OPYT50_ADMIN_TOTP_SECRET", secret)
        monkeypatch.setenv("OPYT50_ADMIN_MFA_MODE", "hybrid")

        with TestClient(app) as second:
            auth = login(second)
            assert auth.status_code == 200
            challenge = auth.json()
            assert challenge["mfa_method"] == "webauthn"

            fallback = second.post(
                "/api/admin/mfa/webauthn/fallback-totp",
                headers=XHR,
                json={"challenge_id": challenge["challenge_id"]},
            )
            assert fallback.status_code == 200, fallback.text
            fallback_data = fallback.json()
            assert fallback_data["mfa_method"] == "totp"

            verified = second.post(
                "/api/admin/mfa/verify",
                headers=XHR,
                json={
                    "challenge_id": fallback_data["challenge_id"],
                    "code": pyotp.TOTP(secret).now(),
                },
            )
            assert verified.status_code == 200, verified.text
            assert second.get("/api/me").status_code == 200



def test_passkey_add_and_delete_create_security_notices(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPYT50_ENV", "development")
    monkeypatch.setenv("OPYT50_ADMIN_MFA_MODE", "off")
    monkeypatch.delenv("OPYT50_PUBLIC_URL", raising=False)
    app = create_app(str(tmp_path / "admin-passkey-notices.db"))

    with TestClient(app) as client:
        create_admin(app)
        assert login(client).status_code == 200
        register_fake_passkey(client, monkeypatch)

        with database(app.state.db_path) as db:
            added = db.execute(
                """SELECT subject,body FROM email_outbox
                   WHERE event='security_admin_passkey_registered'
                   ORDER BY id DESC LIMIT 1"""
            ).fetchone()
            assert added is not None
            assert added["subject"] == "СТАЖНО — добавлен новый passkey"
            assert "Windows Hello" in added["body"]

        security = client.get("/api/account/security")
        assert security.status_code == 200, security.text
        passkey_id = security.json()["passkeys"][0]["id"]
        deleted = client.delete(
            f"/api/admin/passkeys/{passkey_id}",
            headers=XHR,
        )
        assert deleted.status_code == 200, deleted.text

        with database(app.state.db_path) as db:
            removed = db.execute(
                """SELECT subject,body FROM email_outbox
                   WHERE event='security_admin_passkey_deleted'
                   ORDER BY id DESC LIMIT 1"""
            ).fetchone()
            assert removed is not None
            assert removed["subject"] == "СТАЖНО — passkey удалён"
            assert "Windows Hello" in removed["body"]
