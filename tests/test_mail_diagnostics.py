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
        assert body["retry_queue"] == {
            "total": 0, "queued": 0, "retrying": 0,
            "sending": 0, "accepted": 0, "exhausted": 0,
            "suppressed": 0,
        }
        by_event = {entry["event"]: entry["generated"] for entry in body["events"]}
        assert by_event == {
            "new_application": 2, "invitation": 1, "invitation_response": 1,
            "contact_opened": 0, "application_status": 0, "introduction_outcome": 0,
            "application_withdrawn": 0,
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


def test_private_mail_readiness_identifies_stalled_queue_without_exposing_users(
    tmp_path, monkeypatch,
):
    from datetime import datetime, timedelta, timezone

    configure(monkeypatch)
    app = create_app(str(tmp_path / "mail-readiness.db"))
    create_admin(app)
    with TestClient(app) as admin, TestClient(app) as anon:
        login_admin(admin)
        assert anon.get("/api/admin/mail-diagnostics").status_code == 401
        idle = admin.get("/api/admin/mail-diagnostics").json()
        assert idle["mail_readiness"]["status"] == "worker_disabled"
        assert idle["mail_readiness"]["worker_configured"] is False
        assert idle["mail_readiness"]["worker_recently_seen"] is False
        assert idle["mail_readiness"]["worker_last_seen_seconds"] is None
        assert idle["mail_readiness"]["last_smtp_accept_at"] is None
        assert idle["mail_readiness"]["mailbox_confirmation_required"] is True
        assert idle["proven_delivery"] is False

        # This is a configuration flag, not a health assertion: it cannot prove
        # that a background worker is alive or that a mailbox received mail.
        monkeypatch.setenv("OPYT50_MAIL_WORKER_ENABLED", "1")
        no_heartbeat = admin.get("/api/admin/mail-diagnostics").json()
        assert no_heartbeat["mail_readiness"]["status"] == "worker_unconfirmed"
        assert no_heartbeat["mail_readiness"]["worker_recently_seen"] is False

        from app.mail_queue import record_worker_heartbeat
        now = datetime.now(timezone.utc)
        record_worker_heartbeat(app.state.db_path, now=now)
        no_mail = admin.get("/api/admin/mail-diagnostics").json()
        assert no_mail["mail_readiness"]["status"] == "no_workflow_mail_yet"
        assert no_mail["mail_readiness"]["worker_recently_seen"] is True
        assert no_mail["mail_readiness"]["worker_last_seen_seconds"] <= 5
        def stamp(delta):
            return (now + delta).isoformat(timespec="seconds")

        with database(app.state.db_path) as db:
            for idx, (state, attempts, due, accepted) in enumerate((
                ("accepted", 1, timedelta(minutes=-6), timedelta(minutes=-1)),
                ("pending", 0, timedelta(minutes=-3), None),
            )):
                inserted = db.execute(
                    "INSERT INTO email_outbox(to_email,event,subject,body) VALUES(?,?,?,?)",
                    ("private-candidate@example.invalid", "new_application",
                     "private subject", "secret token and +70000000000"),
                )
                db.execute(
                    """INSERT INTO email_delivery_jobs(
                         outbox_id,state,attempts,next_attempt_at,accepted_at,created_at
                       ) VALUES(?,?,?,?,?,?)""",
                    (inserted.lastrowid, state, attempts, stamp(due),
                     stamp(accepted) if accepted else None,
                     stamp(timedelta(minutes=-12 if idx else -7))),
                )
            before = db.execute("SELECT COUNT(*) FROM email_delivery_jobs").fetchone()[0]

        delayed = admin.get("/api/admin/mail-diagnostics")
        assert delayed.status_code == 200
        data = delayed.json()
        assert data["retry_queue"]["queued"] == 1
        assert data["retry_queue"]["accepted"] == 1
        status = data["mail_readiness"]
        assert status["status"] == "queue_overdue"
        assert status["worker_configured"] is True
        assert status["oldest_waiting_seconds"] >= 10 * 60
        assert status["overdue_seconds"] >= 2 * 60
        assert status["last_smtp_accept_at"] is not None
        assert data["proven_delivery"] is False
        for secret in ("private-candidate", "private subject", "secret token", "+70000000000"):
            assert secret not in delayed.text

        with database(app.state.db_path) as db:
            db.execute(
                "UPDATE email_delivery_jobs SET attempts=1, next_attempt_at=? WHERE state='pending'",
                (stamp(timedelta(minutes=2)),),
            )
        retry = admin.get("/api/admin/mail-diagnostics").json()
        assert retry["mail_readiness"]["status"] == "retrying"

        with database(app.state.db_path) as db:
            db.execute(
                "UPDATE email_delivery_jobs SET state='exhausted',last_error_code='smtp_not_accepted' "
                "WHERE state='pending'"
            )
        exhausted = admin.get("/api/admin/mail-diagnostics").json()
        assert exhausted["mail_readiness"]["status"] == "delivery_exhausted"
        assert exhausted["retry_queue"]["exhausted"] == 1

        monkeypatch.delenv("OPYT50_SMTP_HOST")
        unconfigured = admin.get("/api/admin/mail-diagnostics").json()
        assert unconfigured["delivery_mode"] == "outbox_only"
        assert unconfigured["mail_readiness"]["status"] == "smtp_not_configured"
        with database(app.state.db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM email_delivery_jobs").fetchone()[0] == before


def test_mail_readiness_handles_invalid_timestamps_without_exposing_details(
    tmp_path, monkeypatch,
):
    configure(monkeypatch)
    monkeypatch.setenv("OPYT50_MAIL_WORKER_ENABLED", "1")
    app = create_app(str(tmp_path / "mail-invalid-age.db"))
    create_admin(app)
    with TestClient(app) as admin:
        login_admin(admin)
        from app.mail_queue import record_worker_heartbeat
        record_worker_heartbeat(app.state.db_path)
        with database(app.state.db_path) as db:
            outbox = db.execute(
                "INSERT INTO email_outbox(to_email,event,subject,body) VALUES(?,?,?,?)",
                ("private@example.invalid", "invitation", "secret", "hidden"),
            )
            db.execute(
                "INSERT INTO email_delivery_jobs(outbox_id,state,attempts,next_attempt_at,created_at) "
                "VALUES(?,'pending',0,?,?)",
                (outbox.lastrowid, "corrupt due date", "corrupt created date"),
            )
        result = admin.get("/api/admin/mail-diagnostics")
        assert result.status_code == 200
        status = result.json()["mail_readiness"]
        assert status["status"] == "processing"
        assert status["oldest_waiting_seconds"] is None
        assert status["overdue_seconds"] is None
        assert "private@example.invalid" not in result.text


def test_worker_heartbeat_is_idempotent_and_stale_workers_are_flagged(
    tmp_path, monkeypatch,
):
    from datetime import datetime, timedelta, timezone
    from app.mail_queue import record_worker_heartbeat

    configure(monkeypatch)
    monkeypatch.setenv("OPYT50_MAIL_WORKER_ENABLED", "1")
    app = create_app(str(tmp_path / "worker-heartbeat.db"))
    create_admin(app)
    with TestClient(app) as admin:
        login_admin(admin)
        now = datetime.now(timezone.utc)
        record_worker_heartbeat(app.state.db_path, now=now - timedelta(minutes=3))
        stale = admin.get("/api/admin/mail-diagnostics")
        assert stale.status_code == 200
        status = stale.json()["mail_readiness"]
        assert status["status"] == "worker_unconfirmed"
        assert status["worker_configured"] is True
        assert status["worker_recently_seen"] is False
        assert status["worker_last_seen_seconds"] >= 179

        record_worker_heartbeat(app.state.db_path, now=now)
        fresh = admin.get("/api/admin/mail-diagnostics").json()["mail_readiness"]
        assert fresh["worker_recently_seen"] is True
        assert fresh["status"] == "no_workflow_mail_yet"
        assert fresh["worker_last_seen_seconds"] < 5

        with database(app.state.db_path) as db:
            rows = db.execute(
                "SELECT worker,seen_at FROM mail_worker_heartbeat"
            ).fetchall()
        assert len(rows) == 1
        assert rows[0]["worker"] == "workflow"
        assert "@" not in fresh.__repr__()
        assert "password" not in fresh.__repr__()


def test_mail_worker_heartbeat_loop_executes_without_sending(
    tmp_path, monkeypatch,
):
    import asyncio
    from app import mail_queue

    configure(monkeypatch)
    monkeypatch.setenv("OPYT50_MAIL_WORKER_ENABLED", "0")
    app = create_app(str(tmp_path / "loop-heartbeat.db"))
    create_admin(app)
    with TestClient(app):
        passes = []
        original_sleep = mail_queue.asyncio.sleep

        async def stop_after_first_poll(seconds):
            if seconds == mail_queue.POLL_SECONDS:
                raise asyncio.CancelledError()
            return await original_sleep(0)

        monkeypatch.setattr(mail_queue.asyncio, "sleep", stop_after_first_poll)
        monkeypatch.setattr(
            mail_queue, "process_due_workflow_mail",
            lambda _db_path: passes.append("processed"),
        )
        try:
            asyncio.run(mail_queue.workflow_mail_worker(app.state.db_path))
        except asyncio.CancelledError:
            pass
        assert passes == ["processed"]
        with database(app.state.db_path) as db:
            row = db.execute(
                "SELECT worker,seen_at FROM mail_worker_heartbeat WHERE worker='workflow'"
            ).fetchone()
        assert row is not None and row["seen_at"]
