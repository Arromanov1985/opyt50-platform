"""End-to-end mail chain across isolated API clients and fake SMTP."""
from pathlib import Path
from fastapi.testclient import TestClient
from app import email_delivery
from app.db import database
from app.main import create_app
from app.mail_queue import process_due_workflow_mail

XHR = {"X-Requested-With": "OPYT50"}
CANDIDATE = "candidate@demo.example"
EMPLOYER = "employer@demo.example"


def post(client, route, body=None):
    return client.post(route, headers=XHR, json=body or {})


def register(client, role, email):
    body = {"role": role, "name": "Фиктивный участник",
            "email": email, "password": "StrongPass2026!"}
    if role == "employer":
        body["company_name"] = "Тестовая компания"
    result = post(client, "/api/register", body)
    assert result.status_code == 201, result.text


def prepare(candidate, employer):
    result = candidate.put("/api/candidate/profile", headers=XHR, json={
        "profession": "Кладовщик", "city": "Подольск", "skills": "1С, склад",
        "salary_min": 60000, "schedule": "Сменный", "employment": "Полная",
        "about": "", "is_active": True, "phone": "+70000000000",
    })
    assert result.status_code == 200, result.text
    result = post(employer, "/api/employer/vacancies", {
        "title": "Кладовщик", "city": "Подольск", "salary_min": 70000,
        "salary_max": 90000, "schedule": "Сменный", "employment": "Полная",
        "skills": "склад", "description": "Учебная вакансия",
    })
    assert result.status_code == 201, result.text
    return result.json()["id"]


def mock_smtp(monkeypatch):
    for key, value in {
        "OPYT50_SMTP_HOST": "smtp.example.invalid",
        "OPYT50_SMTP_PORT": "587",
        "OPYT50_MAIL_FROM": "noreply@example.invalid",
        "OPYT50_SMTP_USER": "fake-user",
        "OPYT50_SMTP_PASSWORD": "fake-secret",
        "OPYT50_SMTP_SSL": "0",
        "OPYT50_SMTP_STARTTLS": "1",
    }.items():
        monkeypatch.setenv(key, value)
    received = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=10):
            assert (host, port) == ("smtp.example.invalid", 587)
            self.tls = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self, context=None):
            assert context is not None
            self.tls = True

        def login(self, user, password):
            assert self.tls and (user, password) == ("fake-user", "fake-secret")

        def send_message(self, message):
            assert self.tls and message["From"] == "noreply@example.invalid"
            received.append((str(message["To"]), str(message["Subject"]),
                             message.get_content().strip()))
            return {}

    monkeypatch.setattr(email_delivery.smtplib, "SMTP", FakeSMTP)
    return received


def notice_rows(app):
    with database(app.state.db_path) as db:
        return [dict(row) for row in db.execute(
            "SELECT event,to_email,subject,body FROM email_outbox "
            "WHERE event IN ('new_application','invitation',"
            "'application_status','invitation_response','contact_opened',"
            "'application_withdrawn','introduction_outcome') "
            "ORDER BY id"
        )]


def assert_notice(app, mail, previous, event, recipient):
    records = notice_rows(app)
    assert len(records) == previous + 1, records
    row = records[-1]
    assert row["event"] == event
    assert row["to_email"] == mail[-1][0] == recipient
    assert row["subject"] == mail[-1][1]
    assert row["body"].strip() == mail[-1][2]


def dispatch_one(app):
    result = process_due_workflow_mail(app.state.db_path)
    assert result["processed"] == result["accepted"] == 1, result


def test_events_send_one_correct_message_and_never_share_contacts_early(
    tmp_path: Path, monkeypatch,
):
    mail = mock_smtp(monkeypatch)  # Never connects to real SMTP or Timeweb.
    app = create_app(str(tmp_path / "mail-events.db"))
    with TestClient(app) as candidate, TestClient(app) as employer:
        register(candidate, "candidate", CANDIDATE)
        register(employer, "employer", EMPLOYER)
        job = prepare(candidate, employer)
        base = len(mail)
        applied = post(candidate, "/api/candidate/applications", {"vacancy_id": job})
        assert applied.status_code == 201, applied.text
        application = applied.json()["id"]
        dispatch_one(app)
        assert_notice(app, mail, 0, "new_application", EMPLOYER)
        assert len(mail) == base + 1
        assert CANDIDATE not in mail[-1][2]
        assert "+70000000000" not in mail[-1][2]
        assert post(candidate, "/api/candidate/applications", {"vacancy_id": job}).status_code == 409
        assert len(mail) == base + 1
        assert CANDIDATE not in employer.get("/api/employer/applications").text

        interested = post(employer, f"/api/employer/applications/{application}/interest")
        assert interested.status_code == 200, interested.text
        invitation = interested.json()["invitation_id"]
        assert interested.json()["created"] is True
        dispatch_one(app)
        assert_notice(app, mail, 1, "invitation", CANDIDATE)
        assert len(mail) == base + 2  # No second status email for same click.
        assert "отдельного согласия" in mail[-1][2]
        repeated = post(employer, f"/api/employer/applications/{application}/interest")
        assert repeated.status_code == 200 and not repeated.json()["created"]
        assert len(mail) == base + 2

        refused = post(candidate, f"/api/candidate/invitations/{invitation}/respond",
                       {"decision": "accepted", "share_consent": False})
        assert refused.status_code == 422
        assert post(employer, f"/api/employer/invitations/{invitation}/demo-pay").status_code == 409
        assert len(mail) == base + 2
        assert CANDIDATE not in employer.get("/api/employer/invitations").text

        accepted = post(candidate, f"/api/candidate/invitations/{invitation}/respond",
                        {"decision": "accepted", "share_consent": True})
        assert accepted.status_code == 200
        dispatch_one(app)
        assert_notice(app, mail, 2, "invitation_response", EMPLOYER)
        assert len(mail) == base + 3
        assert CANDIDATE not in employer.get("/api/employer/invitations").text
        assert post(candidate, f"/api/candidate/invitations/{invitation}/respond",
                    {"decision": "accepted", "share_consent": True}).status_code == 409
        assert len(mail) == base + 3

        opened = post(employer, f"/api/employer/invitations/{invitation}/demo-pay")
        assert opened.status_code == 200
        assert opened.json()["contact"]["email"] == CANDIDATE
        dispatch_one(app)
        assert_notice(app, mail, 3, "contact_opened", CANDIDATE)
        assert post(employer, f"/api/employer/invitations/{invitation}/demo-pay").status_code == 200
        assert len(mail) == base + 4
        assert [r["event"] for r in notice_rows(app)] == [
            "new_application", "invitation", "invitation_response", "contact_opened"
        ]

def test_existing_proactive_invitation_is_not_resent(tmp_path: Path, monkeypatch):
    mail = mock_smtp(monkeypatch)
    app = create_app(str(tmp_path / "proactive-invitation.db"))
    with TestClient(app) as candidate, TestClient(app) as employer:
        register(candidate, "candidate", CANDIDATE)
        register(employer, "employer", EMPLOYER)
        vacancy = prepare(candidate, employer)
        with database(app.state.db_path) as db:
            candidate_id = db.execute(
                "SELECT id FROM users WHERE email=?", (CANDIDATE,)
            ).fetchone()["id"]
        baseline = len(mail)
        direct = post(employer, "/api/employer/invitations", {
            "vacancy_id": vacancy, "candidate_id": candidate_id,
        })
        assert direct.status_code == 201, direct.text
        dispatch_one(app)
        assert_notice(app, mail, 0, "invitation", CANDIDATE)
        applied = post(candidate, "/api/candidate/applications", {
            "vacancy_id": vacancy,
        })
        assert applied.status_code == 201, applied.text
        dispatch_one(app)
        assert_notice(app, mail, 1, "new_application", EMPLOYER)
        linked = post(
            employer, f"/api/employer/applications/{applied.json()['id']}/interest"
        )
        assert linked.status_code == 200, linked.text
        assert linked.json()["created"] is False
        dispatch_one(app)
        # Existing introduction is reused: do not resend 'invitation',
        # but a separate application status change may be notified.
        assert_notice(app, mail, 2, "application_status", CANDIDATE)
        assert len(mail) == baseline + 3
        assert post(
            employer, f"/api/employer/applications/{applied.json()['id']}/interest"
        ).status_code == 200
        assert len(mail) == baseline + 3


def test_smtp_failure_is_not_misreported_as_delivered(tmp_path: Path, monkeypatch):
    mock_smtp(monkeypatch)

    class UnavailableSMTP:
        def __init__(self, *args, **kwargs):
            raise OSError("Simulated offline transport")

    monkeypatch.setattr(email_delivery.smtplib, "SMTP", UnavailableSMTP)
    app = create_app(str(tmp_path / "smtp-unavailable.db"))
    with TestClient(app) as candidate, TestClient(app) as employer:
        register(candidate, "candidate", CANDIDATE)
        register(employer, "employer", EMPLOYER)
        vacancy = prepare(candidate, employer)
        applied = post(candidate, "/api/candidate/applications", {
            "vacancy_id": vacancy,
        })
        assert applied.status_code == 201, applied.text
        assert [row["event"] for row in notice_rows(app)] == ["new_application"]
        result = process_due_workflow_mail(app.state.db_path)
        assert result["processed"] == 1 and result["pending"] == 1
        with database(app.state.db_path) as db:
            state = db.execute(
                "SELECT state,attempts,last_error_code FROM email_delivery_jobs"
            ).fetchone()
            assert state["state"] == "pending"
            assert state["attempts"] == 1
            assert state["last_error_code"] == "smtp_not_accepted"
        # The outbox means generation, not SMTP acceptance or inbox delivery.
        # The worker will retry this stored business notice later.


def test_application_withdrawal_is_committed_before_smtp_and_queued_once(
    tmp_path: Path, monkeypatch,
):
    """A failed/slow SMTP server must never block a candidate's withdrawal."""
    mail = mock_smtp(monkeypatch)  # No external SMTP calls.
    app = create_app(str(tmp_path / "withdrawal-notification.db"))
    with TestClient(app) as candidate, TestClient(app) as employer:
        register(candidate, "candidate", CANDIDATE)
        register(employer, "employer", EMPLOYER)
        vacancy = prepare(candidate, employer)
        baseline = len(mail)  # Registration sends immediate welcome emails.
        applied = post(candidate, "/api/candidate/applications", {"vacancy_id": vacancy})
        assert applied.status_code == 201, applied.text
        aid = applied.json()["id"]
        dispatch_one(app)
        assert len(mail) == baseline + 1
        assert mail[-1][0] == EMPLOYER
        mail_before_withdrawal = list(mail)

        # No synchronous SMTP: the request returns after the database commit.
        withdrawn = post(candidate, f"/api/candidate/applications/{aid}/withdraw")
        assert withdrawn.status_code == 200, withdrawn.text
        assert mail == mail_before_withdrawal
        assert candidate.get("/api/candidate/applications").json()["applications"][0]["status"] == "withdrawn"
        assert employer.get("/api/employer/applications").json()["applications"][0]["status"] == "withdrawn"
        with database(app.state.db_path) as db:
            pending = db.execute(
                """SELECT q.state,q.attempts,q.outbox_id,r.user_id,o.to_email,o.body
                   FROM email_delivery_jobs q
                   JOIN email_outbox o ON o.id=q.outbox_id
                   JOIN email_delivery_recipients r ON r.outbox_id=q.outbox_id
                   WHERE o.event='application_withdrawn'"""
            ).fetchone()
            assert pending is not None, "Withdrawal must be queued atomically"
            assert (pending["state"], pending["attempts"]) == ("pending", 0)
            assert pending["to_email"] == EMPLOYER
            assert CANDIDATE not in pending["body"]
            assert "+70000000000" not in pending["body"]
            employer_id = db.execute("SELECT id FROM users WHERE email=?", (EMPLOYER,)).fetchone()["id"]
            assert pending["user_id"] == employer_id

        # A second withdrawal is rejected, with no duplicate notification.
        repeated = post(candidate, f"/api/candidate/applications/{aid}/withdraw")
        assert repeated.status_code == 409, repeated.text
        with database(app.state.db_path) as db:
            assert db.execute(
                "SELECT COUNT(*) FROM email_outbox WHERE event='application_withdrawn'"
            ).fetchone()[0] == 1
        assert mail == mail_before_withdrawal

        # Only the worker sends the saved alert after the action succeeded.
        dispatch_one(app)
        assert_notice(app, mail, 1, "application_withdrawn", EMPLOYER)
        assert "отозван" in mail[-1][2]
        assert process_due_workflow_mail(app.state.db_path)["processed"] == 0
        assert len(mail) == baseline + 2

        # Reapplication reuses the original id, and generates no withdrawal again.
        reapplied = post(candidate, "/api/candidate/applications", {"vacancy_id": vacancy})
        assert reapplied.status_code == 201, reapplied.text
        assert reapplied.json()["id"] == aid and reapplied.json()["reapplied"] is True
        dispatch_one(app)
        assert_notice(app, mail, 2, "new_application", EMPLOYER)
        assert [item["event"] for item in notice_rows(app)] == [
            "new_application", "application_withdrawn", "new_application"
        ]


def test_outage_full_application_and_direct_introduction_recover_after_restart(
    tmp_path: Path, monkeypatch,
):
    """Production-like isolated journey: all business actions commit while SMTP is down.

    Two independent paths, eleven queued messages, bounded retry, restart, and
    eventual delivery. There is no real SMTP connection or external recipient.
    """
    from datetime import datetime, timedelta, timezone

    from app import mail_queue

    welcome = mock_smtp(monkeypatch)
    monkeypatch.setenv("OPYT50_MAIL_WORKER_ENABLED", "0")
    db_path = str(tmp_path / "journey-outage.db")
    app = create_app(db_path)
    with TestClient(app) as candidate, TestClient(app) as employer:
        register(candidate, "candidate", CANDIDATE)
        register(employer, "employer", EMPLOYER)
        assert len(welcome) == 2, "Only welcome messages are synchronous"
        first_job = prepare(candidate, employer)
        application = post(candidate, "/api/candidate/applications", {
            "vacancy_id": first_job
        })
        assert application.status_code == 201, application.text
        application_id = application.json()["id"]
        assert post(candidate, f"/api/candidate/applications/{application_id}/withdraw").status_code == 200
        repeated = post(candidate, f"/api/candidate/applications/{application_id}/withdraw")
        assert repeated.status_code == 409
        restored = post(candidate, "/api/candidate/applications", {"vacancy_id": first_job})
        assert restored.status_code == 201 and restored.json()["reapplied"]
        assert restored.json()["id"] == application_id

        interest = post(employer, f"/api/employer/applications/{application_id}/interest")
        assert interest.status_code == 200, interest.text
        first_invitation_id = interest.json()["invitation_id"]
        assert CANDIDATE not in employer.get("/api/employer/invitations").text
        accepted = post(candidate, f"/api/candidate/invitations/{first_invitation_id}/respond",
                        {"decision": "accepted", "share_consent": True})
        assert accepted.status_code == 200, accepted.text
        assert CANDIDATE not in employer.get("/api/employer/invitations").text
        opened = post(employer, f"/api/employer/invitations/{first_invitation_id}/demo-pay")
        assert opened.status_code == 200, opened.text
        concluded = employer.patch(
            f"/api/employer/applications/{application_id}/status",
            headers=XHR, json={"status": "hired"},
        )
        assert concluded.status_code == 200, concluded.text

        second_job = prepare(candidate, employer)
        with database(db_path) as db:
            candidate_id = db.execute(
                "SELECT id FROM users WHERE email=?", (CANDIDATE,)
            ).fetchone()["id"]
        direct = post(employer, "/api/employer/invitations", {
            "vacancy_id": second_job, "candidate_id": candidate_id,
        })
        assert direct.status_code == 201, direct.text
        direct_id = direct.json()["id"]
        direct_record = next(
            x for x in employer.get("/api/employer/invitations").json()["invitations"]
            if x["id"] == direct_id
        )
        assert "contact" not in direct_record, "Contacts hidden before separate consent"
        assert CANDIDATE not in str(direct_record)
        assert post(candidate, f"/api/candidate/invitations/{direct_id}/respond", {
            "decision": "accepted", "share_consent": True,
        }).status_code == 200
        assert post(employer, f"/api/employer/invitations/{direct_id}/demo-pay").status_code == 200
        final = employer.patch(
            f"/api/employer/invitations/{direct_id}/outcome",
            headers=XHR, json={"status": "rejected"},
        )
        assert final.status_code == 200, final.text
        assert employer.patch(
            f"/api/employer/invitations/{direct_id}/outcome",
            headers=XHR, json={"status": "hired"},
        ).status_code == 409
        assert candidate.get("/api/candidate/applications").json()["applications"][0]["status"] == "hired"
        assert len(welcome) == 2, "No business workflow should contact SMTP synchronously"
        assert [entry["event"] for entry in notice_rows(app)] == [
            "new_application", "application_withdrawn", "new_application",
            "invitation", "invitation_response", "contact_opened",
            "application_status", "invitation", "invitation_response",
            "contact_opened", "introduction_outcome",
        ]
        with database(db_path) as db:
            jobs = db.execute(
                "SELECT state,attempts FROM email_delivery_jobs ORDER BY outbox_id"
            ).fetchall()
            assert len(jobs) == 11
            assert all(j["state"] == "pending" and j["attempts"] == 0 for j in jobs)
            assert db.execute(
                "SELECT COUNT(*) FROM email_delivery_recipients"
            ).fetchone()[0] == 11
            assert db.execute(
                "SELECT COUNT(*) FROM job_applications"
            ).fetchone()[0] == 1, "Direct invitation must not create a fake application"
            outbox_before_recovery = db.execute(
                "SELECT COUNT(*) FROM email_outbox"
            ).fetchone()[0]

    # The outage begins AFTER all business actions have committed. Each job
    # is attempted once and scheduled for a retry; no action is rolled back.
    attempts = []
    monkeypatch.setattr(
        mail_queue, "send_email",
        lambda recipient, subject, body: attempts.append((recipient, subject, body)) or False,
    )
    first_attempt = datetime.now(timezone.utc) + timedelta(seconds=2)
    first_batch = process_due_workflow_mail(db_path, now=first_attempt)
    second_batch = process_due_workflow_mail(db_path, now=first_attempt)
    assert first_batch == {"processed": 8, "accepted": 0, "pending": 8, "exhausted": 0}
    assert second_batch == {"processed": 3, "accepted": 0, "pending": 3, "exhausted": 0}
    assert len(attempts) == 11
    assert process_due_workflow_mail(
        db_path, now=first_attempt + timedelta(seconds=29)
    )["processed"] == 0, "Do not retry before backoff expires"
    with database(db_path) as db:
        assert all(
            r["state"] == "pending" and r["attempts"] == 1
            for r in db.execute("SELECT state,attempts FROM email_delivery_jobs")
        )
        assert db.execute(
            "SELECT status FROM job_applications WHERE id=?", (application_id,)
        ).fetchone()["status"] == "hired"
        assert db.execute(
            "SELECT outcome FROM invitation_outcomes WHERE invitation_id=?", (direct_id,)
        ).fetchone()["outcome"] == "rejected"

    # Simulate app restart and SMTP recovery without losing pending messages.
    recovered = []
    monkeypatch.setattr(
        mail_queue, "send_email",
        lambda recipient, subject, body: recovered.append((recipient, subject, body)) or True,
    )
    new_app = create_app(db_path)
    with TestClient(new_app):
        recovery_time = first_attempt + timedelta(seconds=31)
        first_recovered = process_due_workflow_mail(db_path, now=recovery_time)
        rest_recovered = process_due_workflow_mail(db_path, now=recovery_time)
        assert first_recovered["accepted"] == 8
        assert rest_recovered["accepted"] == 3
        assert len(recovered) == 11
        assert all(address in {CANDIDATE, EMPLOYER} for address, _, _ in recovered)
        assert all(CANDIDATE not in body and "+70000000000" not in body
                   for address, _, body in recovered if address == EMPLOYER)
        assert process_due_workflow_mail(
            db_path, now=recovery_time + timedelta(hours=1)
        )["processed"] == 0
        with database(db_path) as db:
            assert all(
                row["state"] == "accepted" and row["attempts"] == 2
                for row in db.execute("SELECT state,attempts FROM email_delivery_jobs")
            )
            assert db.execute(
                "SELECT COUNT(*) FROM email_outbox"
            ).fetchone()[0] == outbox_before_recovery
