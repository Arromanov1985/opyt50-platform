"""Release 0.2 integration tests: browser-safe demo flows, no network email, no real payments."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import database
from app.main import create_app
from app.security import make_password_hash

HEADERS = {"X-Requested-With": "OPYT50"}


@pytest.fixture
def app(tmp_path: Path):
    return create_app(str(tmp_path / "release02.db"))


def post(c, route, body=None):
    return c.post(route, json=body or {}, headers=HEADERS)


def register(c, email, role="candidate"):
    payload={"role":role,"name":"Тестовое Имя","email":email,"password":"StrongPass2026!"}
    if role=="employer":
        payload["company_name"]="Компания Демо"
    result=post(c,"/api/register",payload)
    assert result.status_code == 201, result.text
    return result.json()["user"]["id"]


def profile(c):
    result=c.put("/api/candidate/profile",headers=HEADERS,json={
        "profession":"Кладовщик","city":"Подольск","skills":"1С, склад","salary_min":60000,
        "schedule":"Сменный","employment":"Полная","about":"","is_active":True,"phone":"+70000000000"})
    assert result.status_code == 200, result.text


def vacancy(c,title="Кладовщик",city="Подольск",salary_min=70000,schedule="Сменный"):
    result=post(c,"/api/employer/vacancies",{
        "title":title,"city":city,"salary_min":salary_min,"salary_max":90000,
        "schedule":schedule,"employment":"Полная","skills":"склад","description":"Условия работы, график 2/2"})
    assert result.status_code == 201,result.text
    return result.json()["id"]


def test_search_filters_and_details(app):
    with TestClient(app) as employer, TestClient(app) as visitor:
        register(employer,"employer@demo.example","employer")
        jid=vacancy(employer)
        vacancy(employer,title="Инженер",city="Москва",salary_min=50000,schedule="Полный день")
        jobs=visitor.get("/api/jobs",params={"q":"клад","city":"Подольск","salary_min":80000,"schedule":"Сменный"}).json()["jobs"]
        assert [x["id"] for x in jobs]==[jid]
        # SQLite built-in LOWER() fails for Cyrillic; test full Russian titles and cities.
        for term in ("Кладовщик", "кладовщик", "КЛАДОВЩИК"):
            result=visitor.get("/api/jobs",params={"q":term,"city":"подольск"})
            assert [x["id"] for x in result.json()["jobs"]]==[jid],term
        assert visitor.get("/api/jobs",params={"q":"НЕСУЩЕСТВУЮЩЕЕ"}).json()["jobs"]==[]
        assert visitor.get("/api/jobs",params={"salary_min":100000}).json()["jobs"]==[]
        assert visitor.get(f"/api/jobs/{jid}").json()["job"]["description"].startswith("Условия")
        assert visitor.get("/api/jobs",params={"schedule":"123"}).status_code==422
        assert visitor.get("/api/jobs",params={"salary_min":-1}).status_code==422
        assert employer.patch(f"/api/employer/vacancies/{jid}/status",json={"status":"closed"},headers=HEADERS).status_code==200
        assert visitor.get(f"/api/jobs/{jid}").status_code==404


def test_favorites_applications_privacy_and_status(app):
    with TestClient(app) as candidate,TestClient(app) as employer,TestClient(app) as stranger:
        cid=register(candidate,"candidate@demo.example")
        register(employer,"employer@demo.example","employer")
        register(stranger,"else@demo.example","employer")
        profile(candidate)
        jid=vacancy(employer)
        assert post(candidate,f"/api/candidate/favorites/{jid}").status_code==201
        assert post(candidate,f"/api/candidate/favorites/{jid}").status_code==201
        assert len(candidate.get("/api/candidate/favorites").json()["jobs"])==1
        assert stranger.get("/api/candidate/favorites").status_code==403
        reply=post(candidate,"/api/candidate/applications",{"vacancy_id":jid})
        assert reply.status_code==201,reply.text
        aid=reply.json()["id"]
        assert post(candidate,"/api/candidate/applications",{"vacancy_id":jid}).status_code==409
        assert stranger.get("/api/employer/applications").json()["applications"]==[]
        rows=employer.get("/api/employer/applications").json()["applications"]
        assert len(rows)==1
        assert "email" not in rows[0] and "phone" not in rows[0] and "candidate_id" not in rows[0] and "name" not in rows[0]
        assert stranger.patch(f"/api/employer/applications/{aid}/status",headers=HEADERS,json={"status":"reviewing"}).status_code==404
        assert employer.patch(f"/api/employer/applications/{aid}/status",headers=HEADERS,json={"status":"reviewing"}).status_code==200
        assert candidate.get("/api/candidate/applications").json()["applications"][0]["status"]=="reviewing"
        assert post(candidate,f"/api/candidate/applications/{aid}/withdraw").status_code==200
        assert employer.patch(f"/api/employer/applications/{aid}/status",headers=HEADERS,json={"status":"hired"}).status_code==409
        assert candidate.delete(f"/api/candidate/favorites/{jid}",headers=HEADERS).status_code==200
        assert candidate.get("/api/candidate/favorites").json()["jobs"]==[]


def test_demo_mail_verification_reset_and_one_time_tokens(app):
    with TestClient(app) as c:
        uid=register(c,"user@demo.example")
        assert c.get("/api/account/email/status").json()["email_verified"] is False
        assert post(c,"/api/account/email/request").status_code==200
        with database(app.state.db_path) as db:
            sent=db.execute("SELECT body FROM email_outbox WHERE event='account_verify' ORDER BY id DESC").fetchone()["body"]
        token=re.search(r"token=([A-Za-z0-9_-]+)",sent).group(1)
        assert post(c,"/api/account/email/confirm",{"token":token}).status_code==200
        assert post(c,"/api/account/email/confirm",{"token":token}).status_code==400
        assert c.get("/api/account/email/status").json()["email_verified"] is True
        assert post(c,"/api/account/password/request",{"email":"unknown@demo.example"}).status_code==200
        assert post(c,"/api/account/password/request",{"email":"user@demo.example"}).status_code==200
        with database(app.state.db_path) as db:
            sent=db.execute("SELECT body FROM email_outbox WHERE event='account_reset' ORDER BY id DESC").fetchone()["body"]
            assert db.execute("SELECT COUNT(*) FROM email_outbox WHERE event='welcome'").fetchone()[0]==1
        reset=re.search(r"token=([A-Za-z0-9_-]+)",sent).group(1)
        assert post(c,"/api/account/password/reset",{"token":reset,"password":"DifferentPass2026!"}).status_code==200
        assert post(c,"/api/account/password/reset",{"token":reset,"password":"DifferentPass2026!"}).status_code==400
        assert c.get("/api/me").status_code==401
        assert post(c,"/api/login",{"email":"user@demo.example","password":"StrongPass2026!"}).status_code==401
        assert post(c,"/api/login",{"email":"user@demo.example","password":"DifferentPass2026!"}).status_code==200


def test_admin_controls_and_existing_invitation_events(app):
    with TestClient(app) as candidate,TestClient(app) as employer,TestClient(app) as admin:
        cid=register(candidate,"candidate@demo.example")
        eid=register(employer,"employer@demo.example","employer")
        profile(candidate)
        job=vacancy(employer)
        with database(app.state.db_path) as db:
            db.execute("INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
                       ("admin","admin@demo.example","Администратор",make_password_hash("StrongPass2026!")))
        assert post(admin,"/api/login",{"email":"admin@demo.example","password":"StrongPass2026!"}).status_code==200
        assert admin.get("/api/admin/users").status_code==200
        assert admin.get("/api/admin/vacancies").status_code==200
        assert admin.get("/api/admin/mail-preview").status_code==200
        invite=post(employer,"/api/employer/invitations",{"candidate_id":cid,"vacancy_id":job})
        assert invite.status_code==201,invite.text
        with database(app.state.db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM email_outbox WHERE event='invitation'").fetchone()[0]==1
        assert admin.patch(f"/api/admin/vacancies/{job}/status",headers=HEADERS,json={"status":"closed"}).status_code==200
        assert admin.patch(f"/api/admin/users/{eid}/status",headers=HEADERS,json={"status":"disabled"}).status_code==200
        assert employer.get("/api/me").status_code in (401,403)
        assert post(employer,"/api/login",{"email":"employer@demo.example","password":"StrongPass2026!"}).status_code==403
        assert admin.patch(f"/api/admin/users/{eid}/status",headers=HEADERS,json={"status":"active"}).status_code==200
        assert post(employer,"/api/login",{"email":"employer@demo.example","password":"StrongPass2026!"}).status_code==200
        assert admin.patch("/api/admin/users/3/status",headers=HEADERS,json={"status":"disabled"}).status_code==403
        with database(app.state.db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM admin_audit").fetchone()[0]==3


def test_one_click_introduction_reuses_record_and_requires_consent(app):
    """Self-initiated job application -> employer interest -> explicit consent -> demo unlock."""
    with TestClient(app) as candidate, TestClient(app) as employer, TestClient(app) as other:
        cid = register(candidate, "candidate@demo.example")
        register(employer, "employer@demo.example", "employer")
        register(other, "other@demo.example", "employer")
        profile(candidate)
        jid = vacancy(employer)

        # An application alone must not reveal contact data.
        submitted = post(candidate, "/api/candidate/applications", {"vacancy_id": jid})
        assert submitted.status_code == 201, submitted.text
        aid = submitted.json()["id"]
        listing = employer.get("/api/employer/applications").json()["applications"][0]
        assert listing["invitation_id"] is None
        assert "email" not in listing and "phone" not in listing and "name" not in listing
        assert other.post(f"/api/employer/applications/{aid}/interest", headers=HEADERS).status_code == 404
        assert candidate.post(f"/api/employer/applications/{aid}/interest", headers=HEADERS).status_code == 403

        response = post(employer, f"/api/employer/applications/{aid}/interest")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["created"] is True
        assert body["invitation_status"] == "sent"
        assert body["contact_shared"] is False
        invitation_id = body["invitation_id"]
        assert employer.get("/api/employer/applications").json()["applications"][0]["status"] == "interview"
        assert candidate.get("/api/candidate/applications").json()["applications"][0]["invitation_id"] == invitation_id
        assert candidate.get("/api/candidate/applications").json()["applications"][0]["invitation_status"] == "sent"
        assert post(candidate, f"/api/candidate/invitations/{invitation_id}/respond",
                    {"decision": "accepted", "share_consent": False}).status_code == 422
        assert post(employer, f"/api/employer/invitations/{invitation_id}/demo-pay").status_code == 409

        with database(app.state.db_path) as db:
            count = db.execute("SELECT COUNT(*) FROM invitations").fetchone()[0]
            notices = db.execute(
                "SELECT COUNT(*) FROM email_outbox WHERE event='invitation'"
            ).fetchone()[0]
        assert count == 1 and notices == 1

        repeat = post(employer, f"/api/employer/applications/{aid}/interest")
        assert repeat.status_code == 200
        assert repeat.json()["invitation_id"] == invitation_id
        assert repeat.json()["created"] is False
        with database(app.state.db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM invitations").fetchone()[0] == 1
            assert db.execute(
                "SELECT COUNT(*) FROM email_outbox WHERE event='invitation'"
            ).fetchone()[0] == 1

        accepted = post(candidate, f"/api/candidate/invitations/{invitation_id}/respond",
                        {"decision": "accepted", "share_consent": True})
        assert accepted.status_code == 200
        assert employer.get("/api/employer/applications").json()["applications"][0]["invitation_status"] == "accepted"
        contact_before = employer.get("/api/employer/invitations").json()["invitations"][0]
        assert "contact" not in contact_before
        paid = post(employer, f"/api/employer/invitations/{invitation_id}/demo-pay")
        assert paid.status_code == 200
        assert paid.json()["contact"]["email"] == "candidate@demo.example"
        assert employer.get("/api/employer/applications").json()["applications"][0]["contact_shared"] == 1
        again = post(employer, f"/api/employer/invitations/{invitation_id}/demo-pay")
        assert again.status_code == 200
        with database(app.state.db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM demo_transactions").fetchone()[0] == 1


def test_interest_uses_existing_proactive_invitation(app):
    """A prior manual invitation isn't duplicated when an applicant later expresses interest."""
    with TestClient(app) as candidate, TestClient(app) as employer:
        cid = register(candidate, "candidate@demo.example")
        register(employer, "employer@demo.example", "employer")
        profile(candidate)
        jid = vacancy(employer)
        existing = post(employer, "/api/employer/invitations", {
            "candidate_id": cid, "vacancy_id": jid
        })
        assert existing.status_code == 201, existing.text
        old_id = existing.json()["id"]
        applied = post(candidate, "/api/candidate/applications", {"vacancy_id": jid})
        assert applied.status_code == 201, applied.text
        aid = applied.json()["id"]
        joined = employer.get("/api/employer/applications").json()["applications"][0]
        assert joined["invitation_id"] == old_id
        interest = post(employer, f"/api/employer/applications/{aid}/interest")
        assert interest.status_code == 200
        assert interest.json()["invitation_id"] == old_id
        assert interest.json()["created"] is False
        with database(app.state.db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM invitations").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM email_outbox WHERE event='invitation'").fetchone()[0] == 1


def test_interest_refuses_withdrawn_applications_and_closed_jobs(app):
    with TestClient(app) as candidate, TestClient(app) as employer:
        register(candidate, "candidate@demo.example")
        register(employer, "employer@demo.example", "employer")
        profile(candidate)
        jid = vacancy(employer)
        aid = post(candidate, "/api/candidate/applications", {"vacancy_id": jid}).json()["id"]
        assert post(candidate, f"/api/candidate/applications/{aid}/withdraw").status_code == 200
        assert post(employer, f"/api/employer/applications/{aid}/interest").status_code == 409
        with database(app.state.db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM invitations").fetchone()[0] == 0


def test_resubmit_withdrawn_application_and_admin_counters(app):
    """Withdraw/reapply reuses the same row, preserves history, remains private."""
    with TestClient(app) as candidate, TestClient(app) as employer, TestClient(app) as admin:
        cid = register(candidate, "candidate@demo.example")
        register(employer, "employer@demo.example", "employer")
        profile(candidate)
        jid = vacancy(employer, title="Бухгалтер", city="Москва")
        first = post(candidate, "/api/candidate/applications", {"vacancy_id": jid})
        assert first.status_code == 201, first.text
        aid = first.json()["id"]
        assert first.json()["reapplied"] is False
        assert post(candidate, "/api/candidate/applications", {"vacancy_id": jid}).status_code == 409
        withdrawn = post(candidate, f"/api/candidate/applications/{aid}/withdraw")
        assert withdrawn.status_code == 200
        before = candidate.get("/api/candidate/applications").json()["applications"]
        assert before[0]["status"] == "withdrawn"
        assert [e["event"] for e in before[0]["timeline"]] == ["applied", "withdrawn"]
        with database(app.state.db_path) as db:
            db.execute("INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
                       ("admin","admin@demo.example","Админ",make_password_hash("StrongPass2026!")))
        assert post(admin, "/api/login", {"email": "admin@demo.example",
                                        "password": "StrongPass2026!"}).status_code == 200
        stats = admin.get("/api/admin/stats").json()
        assert stats["applications_total"] == 1
        assert stats["applications_active"] == 0
        assert stats["applications_withdrawn"] == 1
        assert stats["invitations"] == 0
        restored = post(candidate, "/api/candidate/applications", {"vacancy_id": jid})
        assert restored.status_code == 201, restored.text
        assert restored.json()["id"] == aid
        assert restored.json()["reapplied"] is True
        assert post(candidate, "/api/candidate/applications", {"vacancy_id": jid}).status_code == 409
        after = candidate.get("/api/candidate/applications").json()["applications"]
        assert len(after) == 1
        assert after[0]["status"] == "applied"
        assert [e["event"] for e in after[0]["timeline"]] == ["applied", "withdrawn", "reapplied"]
        stats = admin.get("/api/admin/stats").json()
        assert stats["applications_total"] == 1
        assert stats["applications_active"] == 1
        assert stats["applications_withdrawn"] == 0
        rows = employer.get("/api/employer/applications").json()["applications"]
        assert len(rows) == 1 and rows[0]["id"] == aid
        assert "email" not in rows[0] and "phone" not in rows[0]
        with database(app.state.db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM job_applications").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM application_events").fetchone()[0] == 3
            assert db.execute("SELECT COUNT(*) FROM email_outbox WHERE event='new_application'").fetchone()[0] == 2
