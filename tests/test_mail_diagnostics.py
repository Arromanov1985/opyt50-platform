"""Admin-only delivery diagnostics. No test messages leave the local test process."""
from pathlib import Path

from fastapi.testclient import TestClient

from app import email_delivery
from app.db import database, init_db
from app.release02 import init_release02
from app.main import create_app
from app.security import make_password_hash

HEADERS = {"X-Requested-With": "OPYT50"}


def create_admin(app):
    # Schema is normally created at TestClient startup. This helper installs
    # it explicitly before inserting the first fictional administrator.
    init_db(app.state.db_path)
    init_release02(app.state.db_path)
    with database(app.state.db_path) as db:
        db.execute(
            "INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
            ("admin", "admin@demo.example", "Тестовый Администратор",
             make_password_hash("StrongPass2026!")),
        )


def login_admin(client):
    response = client.post(
        "/api/login", headers=HEADERS,
        json={"email": "admin@demo.example", "password": "StrongPass2026!"},
    )
    assert response.status_code == 200, response.text()


def configure(monkeypatch):
    monkeypatch.setenv("OPYT50_ADMIN_MFA_MODE", "off")
    monkeypatch.setenv("OPYT50_SMTP_HOST", "smtp.example.invalid")
    monkeypatch.setenv("OPYT50_SMTP_PORT", "587")
    monkeypatch.setenv("OPYT50_SMTP_STARTTLS", "1")
    monkeypatch.setenv("OPYT50_MAIL_FROM", "noreply@example.invalid")
    monkeypatch.setenv("OPYT50_SMTP_USER", "sender")
    monkeypatch.setenv("OPYT50_SMTP_PASSWORD", "fake-secret")


def test_test_messages_go_only_to_admin_and_do_not_create_business_events(
    tmp_path: Path, monkeypatch,
):
    configure(monkeypatch)
    sent = []
    monkeypatch.setattr(
        email_delivery, "send_email",
        lambda recipient, subject, body: sent.append((recipient, subject, body)) or True,
    )
    app = create_app(str(tmp_path / "smtp-diagnostics.db"))
    create_admin(app)
    with TestClient(app) as admin:
        login_admin(admin)
        with database(app.state.db_path) as db:
            before = db.execute("SELECT COUNT(*) FROM email_outbox").fetchone()[0]
        for scenario in ("connection", "employer_application", "candidate_invitation"):
            response = admin.post(
                "/api/admin/smtp/test-email",
                headers=HEADERS, json={"scenario": scenario},
            )
            assert response.status_code == 200, response.text
            assert response.json() == {
                "ok": True, "scenario": scenario,
                "smtp_accepted": True, "mailbox_confirmation_required": True,
            }
        assert len(sent) == 3
        assert all(address == "admin@demo.example" for address, _, _ in sent)
        assert all("ТЕСТ" in subject for _, subject, _ in sent)
        assert all("администратора" in body for _, _, body in sent)
        assert "новый отклик" in sent[1][1]
        assert "приглашение" in sent[2][1]
        with database(app.state.db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM email_outbox").fetchone()[0] == before
            assert db.execute("SELECT COUNT(*) FROM job_applications").fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM invitations").fetchone()[0] == 0
            events = db.execute(
                "SELECT event_type,detail FROM security_events "
                "WHERE event_type='admin_smtp_test_email'"
            ).fetchall()
            assert len(events) == 3
            assert {row["detail"] for row in events} == {
                "scenario=connection accepted=1",
                "scenario=employer_application accepted=1",
                "scenario=candidate_invitation accepted=1",
            }
            assert all("@" not in row["detail"] for row in events)


def test_mail_diagnostics_is_private_read_only_and_redacted(tmp_path, monkeypatch):
    configure(monkeypatch)
    app = create_app(str(tmp_path / "mail-counters.db"))
    create_admin(app)
    with TestClient(app) as admin, TestClient(app) as anon:
        login_admin(admin)
        assert anon.get("/api/admin/mail-diagnostics").status_code == 401
        assert anon.post(
            "/api/admin/smtp/test-email", headers=HEADERS,
            json={"scenario": "candidate_invitation"},
        ).status_code == 401
        with database(app.state.db_path) as db:
            for event in ("new_application", "new_application", "invitation",
                          "invitation_response", "other_private_event"):
                db.execute(
                    "INSERT INTO email_outbox(to_email,event,subject,body) "
                    "VALUES(?,?,?,?)",
                    ("private-person@example.invalid", event,
                     "Private subject", "hidden reset token and other secrets"),
                )
            count = db.execute("SELECT COUNT(*) FROM email_outbox").fetchone()[0]

        response = admin.get("/api/admin/mail-diagnostics")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["delivery_mode"] == "smtp"
        assert body["proven_delivery"] is False
        by_event = {entry["event"]: entry["generated"] for entry in body["events"]}
        assert by_event == {
            "new_application": 2, "invitation": 1, "invitation_response": 1,
            "contact_opened": 0, "application_status": 0,
        }
        assert "private-person@" not in response.text
        assert "hidden reset token" not in response.text
        assert "Private subject" not in response.text
        assert "other_private_event" not in response.text
        with database(app.state.db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM email_outbox").fetchone()[0] == count


def test_invalid_scenario_and_failed_smtp_are_safe(tmp_path, monkeypatch):
    configure(monkeypatch)
    app = create_app(str(tmp_path / "smtp-failure.db"))
    create_admin(app)
    sent = []
    monkeypatch.setattr(
        email_delivery, "send_email",
        lambda *args: sent.append(args) or False,
    )
    with TestClient(app) as admin:
        login_admin(admin)
        bad = admin.post(
            "/api/admin/smtp/test-email", headers=HEADERS,
            json={"scenario": "all_users"},
        )
        assert bad.status_code == 422
        assert sent == []
        failed = admin.post(
            "/api/admin/smtp/test-email", headers=HEADERS,
            json={"scenario": "candidate_invitation"},
        )
        assert failed.status_code == 503
        assert len(sent) == 1
        assert "secret" not in failed.text
        assert "admin@" not in failed.text
        with database(app.state.db_path) as db:
            event = db.execute(
                "SELECT detail FROM security_events WHERE event_type='admin_smtp_test_email'"
            ).fetchone()
            assert event["detail"] == "scenario=candidate_invitation accepted=0"


def test_smtp_tests_are_rate_limited_per_admin(tmp_path, monkeypatch):
    configure(monkeypatch)
    app = create_app(str(tmp_path / "smtp-limited.db"))
    create_admin(app)
    captured = []
    monkeypatch.setattr(
        email_delivery, "send_email",
        lambda *args: captured.append(args) or True,
    )
    with TestClient(app) as admin:
        login_admin(admin)
        for _ in range(6):
            response = admin.post(
                "/api/admin/smtp/test-email", headers=HEADERS,
                json={"scenario": "connection"},
            )
            assert response.status_code == 200, response.text
        refused = admin.post(
            "/api/admin/smtp/test-email", headers=HEADERS,
            json={"scenario": "connection"},
        )
        assert refused.status_code == 429
        assert int(refused.headers["Retry-After"]) > 0
        assert len(captured) == 6
