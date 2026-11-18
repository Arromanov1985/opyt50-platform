"""Candidate resume: additive compatibility, professional privacy and employer visibility."""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.db import database

XHR = {"X-Requested-With": "OPYT50"}
DETAILS = {
    "profession": "Кладовщик", "city": "Подольск", "skills": "склад, 1С",
    "salary_min": 65000, "schedule": "Сменный", "employment": "Полная",
    "phone": "+79991112233", "about": "Приватное описание", "is_active": True,
}
PUBLIC = {
    "experience_years": 24,
    "education": "Среднее профессиональное — логистика",
    "achievements": "Настроил складской учёт",
    "work_history": [
        {"position": "Старший кладовщик", "period": "2014–2024",
         "duties": "Приёмка, инвентаризация, работа с 1С"},
        {"position": "Комплектовщик", "period": "2000–2014",
         "duties": "Подготовка заказов"},
    ],
}


def post(client, path, body):
    return client.post(path, json=body, headers=XHR)


def test_resume_round_trip_old_clients_and_private_employer_view(tmp_path):
    app = create_app(str(tmp_path / "resume.db"))
    with TestClient(app) as candidate, TestClient(app) as employer, TestClient(app) as outsider:
        candidate_id = post(candidate, "/api/register", {
            "role": "candidate", "email": "resume-candidate@example.invalid",
            "name": "Закрытое Имя", "password": "ExamplePassword2026!",
        }).json()["user"]["id"]
        post(employer, "/api/register", {
            "role": "employer", "email": "employer-resume@example.invalid",
            "name": "Работодатель", "company_name": "Склад Тест",
            "password": "ExamplePassword2026!",
        })
        post(outsider, "/api/register", {
            "role": "employer", "email": "employer-other@example.invalid",
            "name": "Другая компания", "company_name": "Чужой работодатель",
            "password": "ExamplePassword2026!",
        })
        old = candidate.put("/api/candidate/profile", json=DETAILS, headers=XHR)
        assert old.status_code == 200, old.text
        assert old.json()["profile"]["work_history"] == []

        rich = candidate.put("/api/candidate/profile", json=DETAILS | PUBLIC, headers=XHR)
        assert rich.status_code == 200, rich.text
        profile = candidate.get("/api/me").json()["user"]["profile"]
        assert profile["work_history"] == PUBLIC["work_history"]
        assert profile["experience_years"] == 24
        assert profile["education"] == PUBLIC["education"]

        # An older tablet client must not erase fields it doesn't know.
        update = candidate.put("/api/candidate/profile", json=DETAILS | {
            "skills": "1С, Excel, логистика"
        }, headers=XHR)
        assert update.status_code == 200, update.text
        assert update.json()["profile"]["work_history"] == PUBLIC["work_history"]
        assert update.json()["profile"]["achievements"] == PUBLIC["achievements"]

        job = post(employer, "/api/employer/vacancies", {
            "title": "Кладовщик", "city": "Подольск", "salary_min": 70000,
            "salary_max": 100000, "schedule": "Сменный",
            "employment": "Полная", "skills": "склад, 1С",
        })
        assert job.status_code == 201, job.text
        job_id = job.json()["id"]
        matches = employer.get(f"/api/employer/vacancies/{job_id}/matches")
        assert matches.status_code == 200
        own = next(x for x in matches.json()["matches"] if x["candidate_id"] == candidate_id)
        assert own["work_history"] == PUBLIC["work_history"]
        assert own["education"] == PUBLIC["education"]
        assert own["experience_years"] == 24
        assert "phone" not in own and "email" not in own and "name" not in own
        assert DETAILS["phone"] not in matches.text
        assert "Закрытое Имя" not in matches.text
        assert outsider.get(f"/api/employer/vacancies/{job_id}/matches").status_code == 404

        application = post(candidate, "/api/candidate/applications", {"vacancy_id": job_id})
        assert application.status_code == 201, application.text
        own_apps = employer.get("/api/employer/applications")
        assert own_apps.status_code == 200
        row = own_apps.json()["applications"][0]
        assert row["work_history"] == PUBLIC["work_history"]
        assert row["achievements"] == PUBLIC["achievements"]
        assert row["education"] == PUBLIC["education"]
        assert "candidate_id" not in row and "resume_candidate_id" not in row
        assert "phone" not in row and "email" not in row and "name" not in row
        assert DETAILS["phone"] not in own_apps.text
        assert outsider.get("/api/employer/applications").json()["applications"] == []

        with database(app.state.db_path) as db:
            assert db.execute(
                "SELECT COUNT(*) FROM candidate_resume_details WHERE user_id=?", (candidate_id,)
            ).fetchone()[0] == 1

        # An explicit empty work history may be saved without deleting education.
        clear = candidate.put("/api/candidate/profile", json=DETAILS | {
            "work_history": [],
        }, headers=XHR)
        assert clear.status_code == 200, clear.text
        assert clear.json()["profile"]["work_history"] == []
        assert clear.json()["profile"]["education"] == PUBLIC["education"]


@pytest.mark.parametrize("invalid", [
    {"experience_years": 99},
    {"work_history": [
        {"position": "Должность", "period": "2020–2024"}
    ] * 6},
    {"work_history": [{"position": "Должность", "period": "+79991112233"}]},
    {"work_history": [{"position": "Склад", "period": "2020–2024",
                       "duties": "Пишите: hidden@example.invalid"}]},
    {"work_history": [{"position": "Склад", "period": "2020–2024",
                       "duties": "https://example.invalid"}]},
    {"education": "Контакты: hidden@example.invalid"},
    {"achievements": "Свяжитесь со мной через t.me/hidden"},
])
def test_resume_rejects_invalid_or_contact_leaking_public_fields(tmp_path, invalid):
    app = create_app(str(tmp_path / "invalid-resume.db"))
    with TestClient(app) as candidate:
        assert post(candidate, "/api/register", {
            "role": "candidate", "email": "test-resume@example.invalid",
            "name": "Тест", "password": "ExamplePassword2026!",
        }).status_code == 201
        rejected = candidate.put(
            "/api/candidate/profile", json=DETAILS | invalid, headers=XHR
        )
        assert rejected.status_code == 422, rejected.text
        current = candidate.get("/api/me").json()["user"]["profile"]
        assert current["work_history"] == []
        assert current["achievements"] == ""


def test_resume_preserves_existing_data_when_experience_is_optional(tmp_path):
    app = create_app(str(tmp_path / "preserve-resume.db"))
    with TestClient(app) as candidate:
        post(candidate, "/api/register", {
            "role": "candidate", "email": "old-resume@example.invalid",
            "name": "Тест", "password": "ExamplePassword2026!",
        })
        assert candidate.put("/api/candidate/profile", json=DETAILS, headers=XHR).status_code == 200
        profile = candidate.get("/api/me").json()["user"]["profile"]
        assert profile["experience_years"] == 0
        assert profile["work_history"] == []
        assert profile["education"] == ""
