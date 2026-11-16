"""End-to-end mail chain across isolated API clients and fake SMTP."""
from pathlib import Path
from fastapi.testclient import TestClient
from app import email_delivery
from app.db import database
from app.main import create_app

XHR = {"X-Requested-With": "OPYT50"}
CANDIDATE = "candidate@example.invalid"
EMPLOYER = "employer@example.invalid"


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
            "'application_status','invitation_response','contact_opened') "
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
        assert_notice(app, mail, 2, "invitation_response", EMPLOYER)
        assert len(mail) == base + 3
        assert CANDIDATE not in employer.get("/api/employer/invitations").text
        assert post(candidate, f"/api/candidate/invitations/{invitation}/respond",
                    {"decision": "accepted", "share_consent": True}).status_code == 409
        assert len(mail) == base + 3

        opened = post(employer, f"/api/employer/invitations/{invitation}/demo-pay")
        assert opened.status_code == 200
        assert opened.json()["contact"]["email"] == CANDIDATE
        assert_notice(app, mail, 3, "contact_opened", CANDIDATE)
        assert post(employer, f"/api/employer/invitations/{invitation}/demo-pay").status_code == 200
        assert len(mail) == base + 4
        assert [r["event"] for r in notice_rows(app)] == [
            "new_application", "invitation", "invitation_response", "contact_opened"
        ]
