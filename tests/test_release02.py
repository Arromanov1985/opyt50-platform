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
        assert visitor.get("/api/jobs",params={"sort":"unknown"}).status_code==422
        salary_desc=visitor.get("/api/jobs",params={"sort":"salary_desc"}).json()["jobs"]
        assert [j["salary_max"] for j in salary_desc] == sorted([j["salary_max"] for j in salary_desc], reverse=True)
        salary_asc=visitor.get("/api/jobs",params={"sort":"salary_asc"}).json()["jobs"]
        assert [j["salary_min"] for j in salary_asc] == sorted([j["salary_min"] for j in salary_asc])
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


def test_demo_mail_verification_reset_and_one_time_tokens(app, monkeypatch):
    delivered = []
    monkeypatch.setattr(
        "app.release02.send_email",
        lambda to_email, subject, body: delivered.append(body) or True,
    )
    with TestClient(app) as c:
        uid=register(c,"user@demo.example")
        assert c.get("/api/account/email/status").json()["email_verified"] is False
        assert post(c,"/api/account/email/request").status_code==200
        sent=delivered[-1]
        token=re.search(r"token=([A-Za-z0-9_-]+)",sent).group(1)
        with database(app.state.db_path) as db:
            row=db.execute("SELECT subject,body FROM email_outbox WHERE event='account_verify' ORDER BY id DESC").fetchone()
            stored=row["body"]
            assert row["subject"]=="СТАЖНО — подтверждение email"
            assert "token=" not in stored
        assert post(c,"/api/account/email/confirm",{"token":token}).status_code==200
        assert post(c,"/api/account/email/confirm",{"token":token}).status_code==400
        assert c.get("/api/account/email/status").json()["email_verified"] is True
        assert post(c,"/api/account/password/request",{"email":"unknown@demo.example"}).status_code==200
        assert post(c,"/api/account/password/request",{"email":"user@demo.example"}).status_code==200
        sent=delivered[-1]
        reset=re.search(r"token=([A-Za-z0-9_-]+)",sent).group(1)
        with database(app.state.db_path) as db:
            row=db.execute("SELECT subject,body FROM email_outbox WHERE event='account_reset' ORDER BY id DESC").fetchone()
            stored=row["body"]
            assert row["subject"]=="СТАЖНО — восстановление пароля"
            assert "token=" not in stored
            assert db.execute("SELECT COUNT(*) FROM email_outbox WHERE event='welcome'").fetchone()[0]==1
            db.execute(
                """INSERT INTO admin_mfa_challenges(
                       challenge_key,user_id,code_hash,expires_at,attempts,created_at
                   ) VALUES(?,?,?,?,0,?)""",
                ("pending-mfa-reset", uid, "totp-v1", "2099-01-01T00:00:00+00:00", "2026-01-01 00:00:00"),
            )
            db.execute(
                """INSERT INTO admin_webauthn_challenges(
                       challenge_key,user_id,kind,challenge_b64,rp_id,origin,
                       expires_at,attempts,created_at
                   ) VALUES(?,?,?,?,?,?,?,0,?)""",
                (
                    "pending-webauthn-reset",
                    uid,
                    "authentication",
                    "AA",
                    "testserver",
                    "https://testserver",
                    "2099-01-01T00:00:00+00:00",
                    "2026-01-01 00:00:00",
                ),
            )
        assert post(c,"/api/account/password/reset",{"token":reset,"password":"DifferentPass2026!"}).status_code==200
        with database(app.state.db_path) as db:
            assert db.execute(
                "SELECT email_verified FROM account_controls WHERE user_id=?",
                (uid,),
            ).fetchone()["email_verified"] == 1
            assert db.execute(
                """SELECT COUNT(*) FROM security_events
                   WHERE user_id=? AND event_type='email_verified_via_password_reset'""",
                (uid,),
            ).fetchone()[0] == 1
            assert db.execute(
                "SELECT COUNT(*) FROM admin_mfa_challenges WHERE user_id=?",
                (uid,),
            ).fetchone()[0] == 0
            assert db.execute(
                "SELECT COUNT(*) FROM admin_webauthn_challenges WHERE user_id=?",
                (uid,),
            ).fetchone()[0] == 0
            assert db.execute(
                """SELECT COUNT(*) FROM security_events
                   WHERE user_id=? AND event_type='pending_auth_challenges_revoked'""",
                (uid,),
            ).fetchone()[0] == 1
            notice=db.execute(
                "SELECT subject,body FROM email_outbox WHERE event='security_password_reset' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            assert notice is not None
            assert notice["subject"]=="СТАЖНО — пароль восстановлен"
            assert "Все ранее активные сессии завершены" in notice["body"]
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


def test_employer_trust_profile_verification_and_contact_guard(app):
    with TestClient(app) as employer, TestClient(app) as admin, TestClient(app) as visitor:
        eid = register(employer, "employer@demo.example", "employer")

        initial = employer.get("/api/employer/company").json()
        assert initial["trust"]["email_verified"] is False
        assert initial["trust"]["inn_provided"] is False
        assert initial["trust"]["verified"] is False

        saved = employer.put(
            "/api/employer/company",
            headers=HEADERS,
            json={"company_name": "Компания Демо", "inn": "7707083893"},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["trust"]["inn_provided"] is True
        assert saved.json()["trust"]["verified"] is False

        with database(app.state.db_path) as db:
            db.execute(
                "INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
                ("admin", "admin@demo.example", "Администратор", make_password_hash("StrongPass2026!")),
            )
        assert post(admin, "/api/login", {
            "email": "admin@demo.example", "password": "StrongPass2026!"
        }).status_code == 200

        # Verification is meaningful only after both requisites and email confirmation.
        blocked = admin.patch(
            f"/api/admin/employers/{eid}/verification",
            headers=HEADERS,
            json={"verified": True},
        )
        assert blocked.status_code == 422

        with database(app.state.db_path) as db:
            db.execute(
                """INSERT INTO account_controls(user_id,email_verified) VALUES(?,1)
                   ON CONFLICT(user_id) DO UPDATE SET email_verified=1""",
                (eid,),
            )

        verified = admin.patch(
            f"/api/admin/employers/{eid}/verification",
            headers=HEADERS,
            json={"verified": True},
        )
        assert verified.status_code == 200, verified.text
        assert verified.json()["trust"]["verified"] is True

        jid = vacancy(employer)
        public_job = visitor.get(f"/api/jobs/{jid}").json()["job"]
        assert public_job["employer_verified"] == 1
        assert public_job["employer_email_verified"] == 1
        assert public_job["employer_inn_provided"] == 1
        assert "inn" not in public_job

        # Changing legal identity data must invalidate the previous verification.
        changed = employer.put(
            "/api/employer/company",
            headers=HEADERS,
            json={"company_name": "Компания Демо Новая", "inn": "7707083893"},
        )
        assert changed.status_code == 200
        assert changed.json()["trust"]["verified"] is False

        email_in_job = post(employer, "/api/employer/vacancies", {
            "title": "Менеджер",
            "city": "Москва",
            "salary_min": 70000,
            "salary_max": 90000,
            "schedule": "Полный день",
            "employment": "Полная",
            "skills": "продажи",
            "description": "Пишите напрямую на hr@example.ru",
        })
        assert email_in_job.status_code == 422

        phone_in_job = post(employer, "/api/employer/vacancies", {
            "title": "Менеджер",
            "city": "Москва",
            "salary_min": 70000,
            "salary_max": 90000,
            "schedule": "Полный день",
            "employment": "Полная",
            "skills": "продажи",
            "description": "Звоните по номеру +7 (999) 123-45-67",
        })
        assert phone_in_job.status_code == 422


def test_one_click_introduction_reuses_record_and_requires_consent(app):
    """Self-initiated job application -> employer interest -> explicit consent -> demo unlock."""
    with TestClient(app) as candidate, TestClient(app) as employer, TestClient(app) as other:
        cid = register(candidate, "candidate@demo.example")
        register(employer, "employer@demo.example", "employer")
        register(other, "other@demo.example", "employer")
        profile(candidate)
        jid = vacancy(employer)
        assert post(other, "/api/employer/invitations", {
            "candidate_id": cid, "vacancy_id": jid
        }).status_code == 404
        assert post(candidate, "/api/employer/invitations", {
            "candidate_id": cid, "vacancy_id": jid
        }).status_code == 403

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
        assert stranger.get("/api/employer/invitations").json()["invitations"] == []
        assert candidate.get("/api/employer/invitations").status_code == 403
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


def test_recommended_jobs_include_only_my_application_state(app):
    """Recommendation payload is authoritative for returning applicants."""
    with TestClient(app) as a, TestClient(app) as b, TestClient(app) as employer:
        register(a, "applicant-a@demo.example")
        register(b, "applicant-b@demo.example")
        register(employer, "employer@demo.example", "employer")
        profile(a)
        profile(b)
        jid = vacancy(employer)
        before = a.get("/api/candidate/jobs")
        assert before.status_code == 200, before.text
        rows = [j for j in before.json()["jobs"] if j["id"] == jid]
        assert len(rows) == 1
        assert rows[0]["application_status"] is None
        first = post(a, "/api/candidate/applications", {"vacancy_id": jid})
        assert first.status_code == 201, first.text
        saved = a.get("/api/candidate/jobs").json()["jobs"][0]
        assert saved["application_status"] == "applied"
        assert saved["application_id"] == first.json()["id"]
        other = b.get("/api/candidate/jobs").json()["jobs"][0]
        assert other["application_status"] is None
        assert other["application_id"] is None
        assert post(a, f"/api/candidate/applications/{first.json()['id']}/withdraw").status_code == 200
        withdrawn = a.get("/api/candidate/jobs").json()["jobs"][0]
        assert withdrawn["application_status"] == "withdrawn"
        assert withdrawn["application_id"] == first.json()["id"]


def test_unified_status_timeline_consent_and_terminal_guards(app):
    """Both roles get the same non-sensitive milestones; contact unlock is final."""
    with TestClient(app) as candidate, TestClient(app) as employer, TestClient(app) as stranger:
        cid = register(candidate, "candidate@demo.example")
        register(employer, "employer@demo.example", "employer")
        register(stranger, "stranger@demo.example", "employer")
        profile(candidate)
        jid = vacancy(employer)
        aid = post(candidate, "/api/candidate/applications", {"vacancy_id": jid}).json()["id"]
        assert employer.patch(
            f"/api/employer/applications/{aid}/status", json={"status": "reviewing"}, headers=HEADERS
        ).status_code == 200
        requested = post(employer, f"/api/employer/applications/{aid}/interest")
        assert requested.status_code == 200, requested.text
        invite_id = requested.json()["invitation_id"]
        em = employer.get("/api/employer/applications").json()["applications"][0]
        cand = candidate.get("/api/candidate/applications").json()["applications"][0]
        assert em["introduction_stage"] == cand["introduction_stage"] == "awaiting_consent"
        assert [x["event"] for x in em["timeline"]][:2] == ["applied", "reviewing"]
        assert "invitation_sent" in [x["event"] for x in em["timeline"]]
        assert em["timeline"] == cand["timeline"]
        assert "phone" not in em and "email" not in em
        assert stranger.get("/api/employer/applications").json()["applications"] == []
        assert post(candidate, f"/api/candidate/invitations/{invite_id}/respond", {
            "decision": "accepted", "share_consent": True
        }).status_code == 200
        with database(app.state.db_path) as db:
            response_notice = db.execute(
                "SELECT subject,body FROM email_outbox WHERE event='invitation_response' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            assert response_notice["subject"] == "Ответ кандидата — СТАЖНО"
            assert "согласился на знакомство" in response_notice["body"]
            assert "accepted" not in response_notice["body"]
        after_consent = employer.get("/api/employer/applications").json()["applications"][0]
        assert after_consent["introduction_stage"] == "consented"
        assert "invitation_accepted" in [event["event"] for event in after_consent["timeline"]]
        assert "contact_opened" not in [event["event"] for event in after_consent["timeline"]]
        assert employer.get("/api/employer/invitations").json()["invitations"][0]["introduction_stage"] == "consented"
        assert "contact" not in employer.get("/api/employer/invitations").json()["invitations"][0]
        for status in ("reviewing", "interview", "rejected"):
            attempt = employer.patch(
                f"/api/employer/applications/{aid}/status",
                json={"status": status}, headers=HEADERS
            )
            assert attempt.status_code == 409, (status, attempt.text)
        assert post(candidate, f"/api/candidate/applications/{aid}/withdraw").status_code == 409
        assert stranger.patch(
            f"/api/employer/applications/{aid}/status",
            json={"status": "rejected"}, headers=HEADERS
        ).status_code == 404
        # Before demo unlock, the candidate's name/email/phone stay absent
        # from every employer application and invitation response.
        assert not employer.get("/api/employer/invitations").json()["invitations"][0].get("contact")
        # Ownership guard: another employer cannot unlock this contact, and a candidate
        # cannot call the employer-only endpoint.
        assert post(stranger, f"/api/employer/invitations/{invite_id}/demo-pay").status_code == 404
        assert post(candidate, f"/api/employer/invitations/{invite_id}/demo-pay").status_code == 403
        assert not employer.get("/api/employer/invitations").json()["invitations"][0].get("contact")

        paid = post(employer, f"/api/employer/invitations/{invite_id}/demo-pay")
        assert paid.status_code == 200, paid.text
        assert candidate.patch(
            f"/api/employer/applications/{aid}/status",
            json={"status": "hired"}, headers=HEADERS
        ).status_code == 403
        assert stranger.patch(
            f"/api/employer/applications/{aid}/status",
            json={"status": "hired"}, headers=HEADERS
        ).status_code == 404
        for payload in (
            candidate.get("/api/candidate/applications").json()["applications"][0],
            employer.get("/api/employer/applications").json()["applications"][0],
            candidate.get("/api/candidate/invitations").json()["invitations"][0],
            employer.get("/api/employer/invitations").json()["invitations"][0],
            candidate.get("/api/candidate/jobs").json()["jobs"][0],
        ):
            assert payload["introduction_stage"] == "introduced"
        final = candidate.get("/api/candidate/applications").json()["applications"][0]
        assert final["timeline"][-1]["event"] == "contact_opened"
        assert final["timeline"] == employer.get("/api/employer/applications").json()["applications"][0]["timeline"]
        assert employer.get("/api/employer/invitations").json()["invitations"][0]["contact"]["email"] == "candidate@demo.example"
        assert post(employer, f"/api/employer/invitations/{invite_id}/demo-pay").status_code == 200
        rejected = employer.patch(
            f"/api/employer/applications/{aid}/status", json={"status": "rejected"}, headers=HEADERS
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["status"] == "rejected"
        candidate_intro = candidate.get("/api/candidate/invitations").json()["invitations"][0]
        employer_intro = employer.get("/api/employer/invitations").json()["invitations"][0]
        assert candidate_intro["application_status"] == "rejected"
        assert employer_intro["application_status"] == "rejected"
        assert employer_intro["contact"]["email"] == "candidate@demo.example"
        assert candidate_intro["timeline"][-1]["event"] == "rejected"
        assert employer_intro["timeline"][-1]["event"] == "rejected"
        rejected_events = len([event for event in employer_intro["timeline"] if event["event"] == "rejected"])
        # Safe retry: the same terminal result is idempotent and creates no duplicate event.
        repeated = employer.patch(
            f"/api/employer/applications/{aid}/status", json={"status": "rejected"}, headers=HEADERS
        )
        assert repeated.status_code == 200, repeated.text
        repeated_intro = employer.get("/api/employer/invitations").json()["invitations"][0]
        assert len([event for event in repeated_intro["timeline"] if event["event"] == "rejected"]) == rejected_events
        # Terminal outcome is immutable: it cannot be flipped after it is recorded.
        assert employer.patch(
            f"/api/employer/applications/{aid}/status", json={"status": "hired"}, headers=HEADERS
        ).status_code == 409
        with database(app.state.db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM demo_transactions WHERE invitation_id=?", (invite_id,)).fetchone()[0] == 1
            assert db.execute(
                "SELECT COUNT(*) FROM email_outbox WHERE event='contact_opened'"
            ).fetchone()[0] == 1
            outcome_notice = db.execute(
                "SELECT subject,body FROM email_outbox WHERE event='application_status' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            assert outcome_notice["subject"] == "Итог знакомства — СТАЖНО"
            assert "без продолжения" in outcome_notice["body"]
            assert "rejected" not in outcome_notice["body"]
            assert db.execute("SELECT COUNT(*) FROM invitations WHERE vacancy_id=? AND candidate_id=?",
                              (jid, cid)).fetchone()[0] == 1


def test_proactive_invitation_has_unified_history_without_application(app):
    """Contact flow works even if an employer invited a candidate proactively."""
    with TestClient(app) as candidate, TestClient(app) as employer:
        cid = register(candidate, "candidate@demo.example")
        register(employer, "employer@demo.example", "employer")
        profile(candidate)
        jid = vacancy(employer)
        invitation = post(employer, "/api/employer/invitations", {
            "candidate_id": cid, "vacancy_id": jid
        })
        assert invitation.status_code == 201
        employer_item = employer.get("/api/employer/invitations").json()["invitations"][0]
        candidate_item = candidate.get("/api/candidate/invitations").json()["invitations"][0]
        assert employer_item["introduction_stage"] == "awaiting_consent"
        assert employer_item["timeline"] == candidate_item["timeline"]
        assert [e["event"] for e in employer_item["timeline"]] == ["invitation_sent"]
        assert employer_item["application_id"] is None
        assert employer_item["application_status"] is None
        assert candidate_item["application_id"] is None
        assert candidate_item["application_status"] is None
        assert "contact" not in employer_item

        accepted = post(candidate, f"/api/candidate/invitations/{invitation.json()['id']}/respond", {
            "decision": "accepted", "share_consent": True
        })
        assert accepted.status_code == 200, accepted.text
        opened = post(employer, f"/api/employer/invitations/{invitation.json()['id']}/demo-pay")
        assert opened.status_code == 200, opened.text
        employer_opened = employer.get("/api/employer/invitations").json()["invitations"][0]
        candidate_opened = candidate.get("/api/candidate/invitations").json()["invitations"][0]
        assert employer_opened["application_id"] is None
        assert employer_opened["application_status"] is None
        assert candidate_opened["application_id"] is None
        assert candidate_opened["application_status"] is None
        assert employer_opened["contact"]["email"] == "candidate@demo.example"
        assert employer_opened["timeline"][-1]["event"] == "contact_opened"


def test_candidate_interaction_ownership_guards(app):
    with TestClient(app) as candidate, TestClient(app) as other_candidate, TestClient(app) as employer:
        cid = register(candidate, "owner-candidate@demo.example")
        register(other_candidate, "other-candidate@demo.example")
        register(employer, "ownership-employer@demo.example", "employer")
        profile(candidate)
        profile(other_candidate)
        jid = vacancy(employer)

        submitted = post(candidate, "/api/candidate/applications", {"vacancy_id": jid})
        assert submitted.status_code == 201, submitted.text
        aid = submitted.json()["id"]

        interested = post(employer, f"/api/employer/applications/{aid}/interest")
        assert interested.status_code == 200, interested.text
        invitation_id = interested.json()["invitation_id"]

        assert other_candidate.get("/api/candidate/invitations").json()["invitations"] == []
        assert post(other_candidate, f"/api/candidate/invitations/{invitation_id}/respond", {
            "decision": "accepted", "share_consent": True
        }).status_code == 404
        assert post(other_candidate, f"/api/candidate/applications/{aid}/withdraw").status_code == 404

        owner_item = candidate.get("/api/candidate/invitations").json()["invitations"][0]
        assert owner_item["id"] == invitation_id
        assert owner_item["status"] == "sent"


def test_declined_invitation_notice_is_human_readable(app):
    with TestClient(app) as candidate, TestClient(app) as employer:
        cid = register(candidate, "decline-candidate@demo.example")
        register(employer, "decline-employer@demo.example", "employer")
        profile(candidate)
        jid = vacancy(employer)
        invitation = post(employer, "/api/employer/invitations", {
            "candidate_id": cid, "vacancy_id": jid
        })
        assert invitation.status_code == 201, invitation.text
        declined = post(candidate, f"/api/candidate/invitations/{invitation.json()['id']}/respond", {
            "decision": "declined", "share_consent": False
        })
        assert declined.status_code == 200, declined.text
        with database(app.state.db_path) as db:
            notice = db.execute(
                "SELECT subject,body FROM email_outbox WHERE event='invitation_response' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            assert notice["subject"] == "Ответ кандидата — СТАЖНО"
            assert "отказался от знакомства" in notice["body"]
            assert "declined" not in notice["body"]


def test_account_email_endpoints_are_rate_limited(app):
    with TestClient(app) as c:
        register(c, "ratelimit@demo.example")
        for _ in range(10):
            assert post(c, "/api/account/email/request").status_code == 200
        assert post(c, "/api/account/email/request").status_code == 429

    # A separate client/app path verifies anonymous password reset throttling.
    with TestClient(app) as c:
        for i in range(10):
            response = post(c, "/api/account/password/request", {"email": f"missing{i}@demo.example"})
            assert response.status_code == 200
        assert post(c, "/api/account/password/request", {"email": "missing-last@demo.example"}).status_code == 429


def test_account_email_links_use_public_origin(app, monkeypatch):
    monkeypatch.setenv("OPYT50_PUBLIC_URL", "https://example.invalid")
    delivered = []
    monkeypatch.setattr(
        "app.release02.send_email",
        lambda to_email, subject, body: delivered.append(body) or True,
    )
    with TestClient(app, base_url="https://testserver") as c:
        register(c, "public-link@demo.example")
        response = post(c, "/api/account/email/request")
        assert response.status_code == 200
        assert "token" not in response.text.lower()
        assert "Подтвердите ваш email для работы в СТАЖНО." in delivered[-1]
        assert (
            "https://example.invalid/?account_action=verify&token="
            in delivered[-1]
        )
        with database(app.state.db_path) as db:
            body = db.execute(
                "SELECT body FROM email_outbox WHERE event='account_verify' ORDER BY id DESC"
            ).fetchone()["body"]
        assert "token=" not in body
