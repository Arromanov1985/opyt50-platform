"""Release 0.10 trust, moderation and public-company integration tests."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import database
from app.main import create_app
from app.security import make_password_hash

HEADERS = {"X-Requested-With": "OPYT50"}
PASSWORD = "test-only-password-2026!"


@pytest.fixture
def app(tmp_path: Path):
    return create_app(str(tmp_path / "release10.db"))


def post(client, path, body=None):
    return client.post(path, json=body or {}, headers=HEADERS)


def register(client, email, role="candidate"):
    body = {"role": role, "name": "Тестовый пользователь", "email": email, "password": PASSWORD}
    if role == "employer":
        body["company_name"] = "Компания Тест"
    response = post(client, "/api/register", body)
    assert response.status_code == 201, response.text
    return response.json()["user"]["id"]


def candidate_profile(client):
    response = client.put(
        "/api/candidate/profile",
        headers=HEADERS,
        json={
            "profession": "Кладовщик",
            "city": "Подольск",
            "skills": "склад, 1С",
            "salary_min": 60000,
            "schedule": "Сменный",
            "employment": "Полная",
            "about": "",
            "is_active": True,
            "phone": "+70000000000",
        },
    )
    assert response.status_code == 200, response.text


def create_vacancy(client):
    response = post(
        client,
        "/api/employer/vacancies",
        {
            "title": "Кладовщик",
            "city": "Подольск",
            "salary_min": 70000,
            "salary_max": 90000,
            "schedule": "Сменный",
            "employment": "Полная",
            "skills": "склад, 1С",
            "description": "Обязанности и условия работы на складе, график два через два.",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def login_admin(client, app):
    with database(app.state.db_path) as db:
        db.execute(
            "INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
            ("admin", "admin-release10@example.test", "Администратор", make_password_hash(PASSWORD)),
        )
    response = post(client, "/api/login", {"email": "admin-release10@example.test", "password": PASSWORD})
    assert response.status_code == 200, response.text


def test_public_company_and_risk_based_moderation(app):
    with (
        TestClient(app) as employer,
        TestClient(app) as first_candidate,
        TestClient(app) as second_candidate,
        TestClient(app) as visitor,
        TestClient(app) as admin,
    ):
        employer_id = register(employer, "employer-release10@example.test", "employer")
        register(first_candidate, "candidate-one-release10@example.test")
        register(second_candidate, "candidate-two-release10@example.test")
        candidate_profile(first_candidate)
        candidate_profile(second_candidate)

        company = employer.put(
            "/api/employer/company",
            headers=HEADERS,
            json={
                "company_name": "Компания Тест",
                "inn": "7707083893",
                "about": "Работаем с 2010 года. Ищем специалистов в складскую команду.",
            },
        )
        assert company.status_code == 200, company.text

        vacancy_id = create_vacancy(employer)
        public_company = visitor.get(f"/api/companies/{employer_id}")
        assert public_company.status_code == 200
        assert public_company.json()["company"]["open_vacancies"] == 1
        assert "Работаем с 2010 года" in public_company.json()["company"]["about"]
        assert visitor.get(f"/api/jobs/{vacancy_id}").status_code == 200

        first = post(
            first_candidate,
            "/api/reports",
            {
                "vacancy_id": vacancy_id,
                "target_type": "vacancy",
                "reason": "misleading",
                "details": "Условия требуют проверки.",
            },
        )
        assert first.status_code == 201, first.text
        assert first.json()["vacancy_pending_review"] is False
        assert visitor.get(f"/api/jobs/{vacancy_id}").status_code == 200

        duplicate = post(
            first_candidate,
            "/api/reports",
            {
                "vacancy_id": vacancy_id,
                "target_type": "vacancy",
                "reason": "other",
                "details": "Повтор.",
            },
        )
        assert duplicate.status_code == 409

        second = post(
            second_candidate,
            "/api/reports",
            {
                "vacancy_id": vacancy_id,
                "target_type": "vacancy",
                "reason": "fraud",
                "details": "Нужна проверка модератором.",
            },
        )
        assert second.status_code == 201, second.text
        assert second.json()["vacancy_pending_review"] is True
        assert visitor.get(f"/api/jobs/{vacancy_id}").status_code == 404
        assert visitor.get("/api/jobs").json()["jobs"] == []
        assert employer.get(f"/api/employer/vacancies/{vacancy_id}/matches").status_code == 409

        login_admin(admin, app)
        moderation = admin.get("/api/admin/vacancies").json()["jobs"][0]
        assert moderation["moderation_status"] == "pending"
        assert moderation["active_reports"] == 2

        reports = admin.get("/api/admin/reports").json()["reports"]
        assert len(reports) == 2
        assert admin.patch(
            f"/api/admin/reports/{reports[0]['report_key']}/status",
            headers=HEADERS,
            json={"status": "reviewed"},
        ).status_code == 200

        approved = admin.patch(
            f"/api/admin/vacancies/{vacancy_id}/moderation",
            headers=HEADERS,
            json={"status": "approved", "reason": ""},
        )
        assert approved.status_code == 200, approved.text
        assert visitor.get(f"/api/jobs/{vacancy_id}").status_code == 200


def test_rejected_vacancy_edit_resubmits_for_review(app):
    with TestClient(app) as employer, TestClient(app) as admin, TestClient(app) as visitor:
        register(employer, "employer-edit-release10@example.test", "employer")
        vacancy_id = create_vacancy(employer)
        login_admin(admin, app)

        rejected = admin.patch(
            f"/api/admin/vacancies/{vacancy_id}/moderation",
            headers=HEADERS,
            json={"status": "rejected", "reason": "Нужно уточнить условия"},
        )
        assert rejected.status_code == 200
        assert visitor.get(f"/api/jobs/{vacancy_id}").status_code == 404

        job = employer.get("/api/employer/vacancies").json()["jobs"][0]
        edited = employer.patch(
            f"/api/employer/vacancies/{vacancy_id}",
            headers=HEADERS,
            json={
                "title": job["title"],
                "city": job["city"],
                "salary_min": job["salary_min"],
                "salary_max": job["salary_max"],
                "schedule": job["schedule"],
                "employment": job["employment"],
                "skills": job["skills"],
                "description": job["description"] + " Уточнённые условия.",
                "expected_revision": job["revision"],
            },
        )
        assert edited.status_code == 200, edited.text
        refreshed = employer.get("/api/employer/vacancies").json()["jobs"][0]
        assert refreshed["moderation_status"] == "pending"
        assert visitor.get(f"/api/jobs/{vacancy_id}").status_code == 404
