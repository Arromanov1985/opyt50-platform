"""Private draft flow: access control, version conflicts and idempotent publication."""
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app

XHR = {"X-Requested-With": "OPYT50"}


def register(client, email, role):
    payload = {
        "email": email, "password": "StrongPass2026!",
        "name": "Тестовый Пользователь", "role": role,
    }
    if role == "employer":
        payload["company_name"] = "Демо Компания"
    response = client.post("/api/register", json=payload, headers=XHR)
    assert response.status_code == 201, response.text


def fields(**extra):
    return {
        "title": "Кладовщик", "city": "Подольск",
        "salary_min": "70000", "salary_max": "90000",
        "schedule": "Сменный", "employment": "Полная",
        "skills": "1С", "responsibilities": "Учёт товаров",
        "requirements": "Знание 1С", "conditions": "График 2/2",
    } | extra


def test_private_drafts_and_publish_once(tmp_path: Path):
    app = create_app(str(tmp_path / "drafts.db"))
    with TestClient(app) as employer, TestClient(app) as other, TestClient(app) as candidate:
        register(employer, "draft-owner@example.test", "employer")
        register(other, "draft-other@example.test", "employer")
        register(candidate, "draft-candidate@example.test", "candidate")
        created = employer.post("/api/employer/vacancy-drafts", json={"fields": {"title": "Кладовщик"}}, headers=XHR)
        assert created.status_code == 201, created.text
        draft = created.json()
        did = draft["id"]
        assert candidate.get("/api/employer/vacancy-drafts").status_code == 403
        assert other.put(f"/api/employer/vacancy-drafts/{did}", json={
            "fields": fields(), "expected_version": draft["version"]
        }, headers=XHR).status_code == 404
        assert candidate.get("/api/jobs").json()["jobs"] == []
        updated = employer.put(f"/api/employer/vacancy-drafts/{did}", json={
            "fields": fields(), "expected_version": draft["version"]
        }, headers=XHR)
        assert updated.status_code == 200, updated.text
        assert updated.json()["version"] == draft["version"] + 1
        stale = employer.put(f"/api/employer/vacancy-drafts/{did}", json={
            "fields": fields(title="Старый заголовок"), "expected_version": draft["version"]
        }, headers=XHR)
        assert stale.status_code == 409
        assert candidate.get("/api/jobs").json()["jobs"] == []
        published = employer.post(f"/api/employer/vacancy-drafts/{did}/publish", headers=XHR)
        assert published.status_code == 200, published.text
        jid = published.json()["id"]
        second = employer.post(f"/api/employer/vacancy-drafts/{did}/publish", headers=XHR)
        assert second.status_code == 200
        assert second.json()["id"] == jid
        assert second.json()["already_published"] is True
        assert len(employer.get("/api/employer/vacancies").json()["jobs"]) == 1
        assert employer.get("/api/employer/vacancy-drafts").json()["drafts"] == []
        assert other.delete(f"/api/employer/vacancy-drafts/{did}", headers=XHR).status_code == 404


def test_incomplete_draft_cannot_publish(tmp_path: Path):
    app = create_app(str(tmp_path / "partial.db"))
    with TestClient(app) as employer:
        register(employer, "draft-partial@example.test", "employer")
        response = employer.post("/api/employer/vacancy-drafts", json={"fields": {"title": "Кладовщик"}}, headers=XHR)
        did = response.json()["id"]
        assert employer.post(f"/api/employer/vacancy-drafts/{did}/publish", headers=XHR).status_code == 422
        assert employer.get("/api/employer/vacancy-drafts").json()["drafts"][0]["id"] == did
        assert employer.get("/api/employer/vacancies").json()["jobs"] == []
