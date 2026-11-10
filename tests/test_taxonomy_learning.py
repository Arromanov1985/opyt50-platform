"""Learning queue for profession/skill suggestions without unsafe auto-merging."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import database
from app.main import create_app
from app.matching import match_candidate
from app.security import make_password_hash

HEADERS = {"X-Requested-With": "OPYT50"}
PASSWORD = "TaxonomyLearn2026!"


@pytest.fixture
def app(tmp_path: Path):
    return create_app(str(tmp_path / "taxonomy-learning.db"))


def register(client, email, role):
    body = {
        "role": role,
        "name": "Тестовый пользователь",
        "email": email,
        "password": PASSWORD,
    }
    if role == "employer":
        body["company_name"] = "Тестовая компания"
    response = client.post("/api/register", headers=HEADERS, json=body)
    assert response.status_code == 201, response.text
    return response.json()["user"]["id"]


def login_admin(client, app):
    with database(app.state.db_path) as db:
        db.execute(
            "INSERT INTO users(role,email,name,password_hash) VALUES(?,?,?,?)",
            ("admin", "taxonomy-admin@example.test", "Администратор", make_password_hash(PASSWORD)),
        )
    response = client.post(
        "/api/login",
        headers=HEADERS,
        json={"email": "taxonomy-admin@example.test", "password": PASSWORD},
    )
    assert response.status_code == 200, response.text


def test_observed_terms_require_admin_approval_before_public_suggestions(app):
    with (
        TestClient(app) as candidate,
        TestClient(app) as employer,
        TestClient(app) as admin,
        TestClient(app) as visitor,
    ):
        register(candidate, "taxonomy-candidate@example.test", "candidate")
        register(employer, "taxonomy-employer@example.test", "employer")

        profile = candidate.put(
            "/api/candidate/profile",
            headers=HEADERS,
            json={
                "profession": "Менеджер маркетплейсов",
                "city": "Москва",
                "skills": "Юнит-экономика маркетплейсов, Контент-планирование",
                "salary_min": 90000,
                "schedule": "Любой",
                "employment": "Любая",
                "about": "",
                "is_active": True,
                "phone": "",
            },
        )
        assert profile.status_code == 200, profile.text

        vacancy = employer.post(
            "/api/employer/vacancies",
            headers=HEADERS,
            json={
                "title": "Менеджер маркетплейсов",
                "city": "Москва",
                "salary_min": 90000,
                "salary_max": 130000,
                "schedule": "Любой",
                "employment": "Любая",
                "skills": "Юнит-экономика маркетплейсов",
                "description": "Работа с ассортиментом, аналитикой и развитием продаж на маркетплейсах.",
            },
        )
        assert vacancy.status_code == 201, vacancy.text

        before = visitor.get("/api/taxonomy").json()
        assert "Менеджер маркетплейсов" not in {item["value"] for item in before["professions"]}
        assert "Юнит-экономика маркетплейсов" not in {item["value"] for item in before["skills"]}

        login_admin(admin, app)
        queue = admin.get("/api/admin/taxonomy")
        assert queue.status_code == 200, queue.text
        data = queue.json()
        assert data["summary"]["pending"] >= 3

        profession = next(
            item for item in data["terms"]
            if item["kind"] == "profession" and item["display_value"] == "Менеджер маркетплейсов"
        )
        skill = next(
            item for item in data["terms"]
            if item["kind"] == "skill" and item["display_value"] == "Юнит-экономика маркетплейсов"
        )
        rejected = next(
            item for item in data["terms"]
            if item["kind"] == "skill" and item["display_value"] == "Контент-планирование"
        )

        assert profession["candidate_seen"] == 1
        assert profession["vacancy_seen"] == 1
        assert skill["candidate_seen"] == 1
        assert skill["vacancy_seen"] == 1
        # The queue intentionally contains no user/vacancy identity fields.
        assert "user_id" not in profession
        assert "vacancy_id" not in profession
        assert "email" not in profession

        for item in (profession, skill):
            approved = admin.patch(
                f"/api/admin/taxonomy/{item['term_key']}",
                headers=HEADERS,
                json={"status": "approved"},
            )
            assert approved.status_code == 200, approved.text

        declined = admin.patch(
            f"/api/admin/taxonomy/{rejected['term_key']}",
            headers=HEADERS,
            json={"status": "rejected"},
        )
        assert declined.status_code == 200, declined.text

        after = visitor.get("/api/taxonomy").json()
        assert "Менеджер маркетплейсов" in {item["value"] for item in after["professions"]}
        assert "Юнит-экономика маркетплейсов" in {item["value"] for item in after["skills"]}
        assert "Контент-планирование" not in {item["value"] for item in after["skills"]}


def test_approved_standalone_profession_does_not_auto_merge_matching():
    candidate = {
        "profession": "Менеджер маркетплейсов",
        "city": "Москва",
        "salary_min": 90000,
        "schedule": "Любой",
        "employment": "Любая",
        "skills": "Excel",
        "is_active": 1,
    }
    unrelated_sales_vacancy = {
        "title": "Менеджер по продажам",
        "city": "Москва",
        "salary_min": 90000,
        "salary_max": 130000,
        "schedule": "Любой",
        "employment": "Любая",
        "skills": "Excel",
    }
    assert match_candidate(unrelated_sales_vacancy, candidate) is None
