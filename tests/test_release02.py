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
