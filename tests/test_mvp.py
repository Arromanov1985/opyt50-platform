from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.db import database
from app.security import make_password_hash
from app.matching import match_candidate

XHR = {"X-Requested-With": "OPYT50"}


@pytest.fixture
def app(tmp_path: Path):
    return create_app(str(tmp_path / "test.sqlite"))


def post(client, url, body=None):
    return client.post(url, json=body or {}, headers=XHR)


def register(client, role, email, name="Тестовый пользователь", company="Компания Тест"):
    body = {"role": role, "email": email, "name": name, "password": "StrongPass2026!"}
    if role == "employer":
        body["company_name"] = company
    response = post(client, "/api/register", body)
    assert response.status_code == 201, response.text
    return response.json()["user"]["id"]


def fill_candidate(client, **patch):
    body = {
        "profession": "Кладовщик", "city": "Подольск", "skills": "1С, склад, Excel",
        "salary_min": 65000, "schedule": "Сменный", "employment": "Полная",
        "phone": "+70000000000", "about": "Много лет на складе", "is_active": True,
    }
    body.update(patch)
    response = client.put("/api/candidate/profile", json=body, headers=XHR)
    assert response.status_code == 200, response.text


def add_job(client, **patch):
    body = {
        "title": "Кладовщик", "city": "Подольск", "skills": "склад, 1С",
        "salary_min": 70000, "salary_max": 90000,
        "schedule": "Сменный", "employment": "Полная", "description": "Склад 2/2",
    }
    body.update(patch)
    response = post(client, "/api/employer/vacancies", body)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_health_and_frontend(app):
    with TestClient(app) as client:
        assert client.get("/api/health").json()["payments"] == "demo_only"
        assert client.get("/").status_code == 200
        assert "Ваш опыт" in client.get("/").text
        assert client.get("/static/styles.css").status_code == 200
        assert client.get("/static/app.js").status_code == 200


def test_registration_login_and_session(app):
    with TestClient(app) as client:
        register(client, "candidate", " Candidate@EXAMPLE.com ")
        assert client.get("/api/me").json()["user"]["email"] == "candidate@example.com"
        assert client.cookies.get("opyt50_session")
        assert post(client, "/api/logout").status_code == 200
        assert client.get("/api/me").status_code == 401
        assert post(client, "/api/login", {"email": "candidate@example.com", "password": "wrong-pass"}).status_code == 401
        assert post(client, "/api/login", {"email": "candidate@example.com", "password": "StrongPass2026!"}).status_code == 200
        assert client.get("/api/me").status_code == 200
        assert post(client, "/api/register", {"role":"candidate","name":"Другой кандидат","email":"candidate@example.com","password":"AnotherPass2026"}).status_code == 409


def test_csrf_and_roles(app):
    with TestClient(app) as candidate, TestClient(app) as employer:
        register(candidate, "candidate", "candidate@example.com")
        register(employer, "employer", "employer@example.com")
        assert candidate.post("/api/logout").status_code == 403  # missing required custom header
        assert post(candidate, "/api/employer/vacancies", {"title":"Кладовщик", "city":"Подольск", "salary_min":70000, "salary_max":95000}).status_code == 403
        assert candidate.get("/api/admin/stats").status_code == 403
        assert employer.put("/api/candidate/profile", json={}, headers=XHR).status_code == 422  # validation before role check
        assert employer.get("/api/candidate/invitations").status_code == 403


def test_complete_introduction_flow(app):
    with TestClient(app) as candidate, TestClient(app) as employer:
        cid = register(candidate, "candidate", "person@example.com", name="Светлана Иванова")
        eid = register(employer, "employer", "company@example.com")
        fill_candidate(candidate)
        job_id = add_job(employer)
        matches = employer.get(f"/api/employer/vacancies/{job_id}/matches").json()["matches"]
        assert len(matches) == 1 and matches[0]["candidate_id"] == cid
        assert 50 <= matches[0]["score"] <= 100
        assert "email" not in matches[0] and "phone" not in matches[0] and "name" not in matches[0]
        invitation = post(employer, "/api/employer/invitations", {"vacancy_id":job_id, "candidate_id":cid})
        assert invitation.status_code == 201
        iid = invitation.json()["id"]
        assert post(employer, f"/api/employer/invitations/{iid}/demo-pay").status_code == 409
        assert post(employer, "/api/employer/invitations", {"vacancy_id":job_id, "candidate_id":cid}).status_code == 409
        candidate_invite = candidate.get("/api/candidate/invitations").json()["invitations"]
        assert len(candidate_invite) == 1 and candidate_invite[0]["status"] == "sent"
        assert post(candidate, f"/api/candidate/invitations/{iid}/respond", {"decision":"accepted", "share_consent":False}).status_code == 422
        result = post(candidate, f"/api/candidate/invitations/{iid}/respond", {"decision":"accepted", "share_consent":True})
        assert result.status_code == 200
        before = employer.get("/api/employer/invitations").json()["invitations"][0]
        assert before["status"] == "accepted" and "contact" not in before
        paid = post(employer, f"/api/employer/invitations/{iid}/demo-pay")
        assert paid.status_code == 200
        assert paid.json()["amount_rub"] == 1490
        assert paid.json()["mode"] == "demo_only"
        assert paid.json()["contact"]["email"] == "person@example.com"
        assert post(employer, f"/api/employer/invitations/{iid}/demo-pay").status_code == 200  # idempotent
        after = employer.get("/api/employer/invitations").json()["invitations"][0]
        assert after["contact"]["name"] == "Светлана Иванова"
        with database(app.state.db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM demo_transactions").fetchone()[0] == 1
            assert db.execute("SELECT employer_id FROM invitations WHERE id=?", (iid,)).fetchone()[0] == eid


def test_employer_isolation_and_private_profiles(app):
    with TestClient(app) as candidate, TestClient(app) as first, TestClient(app) as second:
        cid = register(candidate, "candidate", "person@example.com")
        register(first, "employer", "first@example.com")
        register(second, "employer", "second@example.com")
        fill_candidate(candidate, about="Мой частный номер 555")
        jid = add_job(first)
        assert second.get(f"/api/employer/vacancies/{jid}/matches").status_code == 404
        assert first.get(f"/api/employer/vacancies/{jid}/matches").json()["matches"][0]["candidate_id"] == cid
        assert "Мой частный" not in str(first.get(f"/api/employer/vacancies/{jid}/matches").json())
        assert post(second, "/api/employer/invitations", {"vacancy_id": jid, "candidate_id": cid}).status_code == 404
        assert second.patch(f"/api/employer/vacancies/{jid}/status",json={"status":"closed"},headers=XHR).status_code == 404
        assert second.get("/api/employer/invitations").json()["invitations"] == []


def test_hard_filters_and_candidate_availability(app):
    with TestClient(app) as candidate, TestClient(app) as employer:
        cid = register(candidate, "candidate", "person@example.com")
        register(employer, "employer", "company@example.com")
        fill_candidate(candidate, city="Москва", salary_min=180000)
        jid = add_job(employer)
        assert employer.get(f"/api/employer/vacancies/{jid}/matches").json()["matches"] == []
        assert post(employer, "/api/employer/invitations", {"vacancy_id": jid, "candidate_id": cid}).status_code == 422
        fill_candidate(candidate, is_active=False, city="Подольск", salary_min=65000)
        assert employer.get(f"/api/employer/vacancies/{jid}/matches").json()["matches"] == []
        fill_candidate(candidate, is_active=True)
        assert len(employer.get(f"/api/employer/vacancies/{jid}/matches").json()["matches"]) == 1


def test_input_validation(app):
    with TestClient(app) as client:
        assert post(client, "/api/register", {"role":"candidate","email":"not-an-email","name":"abc","password":"1234567890"}).status_code == 422
        register(client,"employer","company@example.com")
        response = post(client, "/api/employer/vacancies", {
            "title":"Кладовщик","city":"Подольск", "salary_min":100000,"salary_max":50000,
        })
        assert response.status_code == 422
        assert len(client.get("/api/jobs").json()["jobs"]) == 0


def test_admin_only_aggregation(app):
    with TestClient(app) as admin, TestClient(app) as candidate:
        register(candidate,"candidate","person@example.com")
        with database(app.state.db_path) as db:
            db.execute("INSERT INTO users(email,role,name,password_hash) VALUES(?,?,?,?)", (
                "admin@example.com", "admin", "Admin", make_password_hash("SomePass2026!"),
            ))
        assert post(admin,"/api/login",{"email":"admin@example.com","password":"SomePass2026!"}).status_code == 200
        stats = admin.get("/api/admin/stats").json()
        assert stats["candidates"] == 1
        assert stats["demo_turnover_rub"] == 0
        assert candidate.get("/api/admin/stats").status_code == 403


def test_matching_never_reads_age():
    vacancy = {"city":"Москва","salary_max":120000,"schedule":"Любой","employment":"Любая","skills":"Excel","title":"Бухгалтер"}
    candidate = {"profession":"Бухгалтер","city":"Москва","salary_min":90000,"schedule":"Любой","employment":"Любая","skills":"Excel","is_active":1}
    score1 = match_candidate(vacancy, dict(candidate, age=25))
    score2 = match_candidate(vacancy, dict(candidate, age=67))
    assert score1 == score2


def test_password_protected_preview(app, monkeypatch):
    monkeypatch.setenv("OPYT50_PREVIEW_USERNAME", "review")
    monkeypatch.setenv("OPYT50_PREVIEW_PASSWORD", "strong-private-preview-password")
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/").status_code == 401
        assert client.get("/static/styles.css").status_code == 401
        assert client.get("/", auth=("review", "wrong-password")).status_code == 401
        assert client.get("/", auth=("wrong", "strong-private-preview-password")).status_code == 401
        assert client.get("/", auth=("review", "strong-private-preview-password")).status_code == 200
        assert client.get("/api/jobs", auth=("review", "strong-private-preview-password")).status_code == 200
