"""Public employer profile pages, visibility and XSS/privacy regression."""
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import database
from app.main import create_app

XHR = {"X-Requested-With": "OPYT50"}


def test_public_employer_page_preserves_moderation_and_privacy(tmp_path: Path):
    app = create_app(str(tmp_path / "employer-public.db"))
    with TestClient(app) as employer, TestClient(app) as visitor:
        registration = employer.post("/api/register", headers=XHR, json={
            "role": "employer", "name": "Тестовый работодатель",
            "company_name": "Учебная & Компания",
            "email": "private-employer@example.invalid",
            "password": "SyntheticPassword2026!",
        })
        assert registration.status_code == 201, registration.text
        owner_id = int(registration.json()["user"]["id"])
        company_update = employer.put("/api/employer/company", headers=XHR, json={
            "company_name": "Учебная & Компания",
            "inn": "",
            "about": "Приглашаем специалистов. <script>alert('xss')</script>",
        })
        assert company_update.status_code == 200, company_update.text

        job_resp = employer.post("/api/employer/vacancies", headers=XHR, json={
            "title": "Кладовщик",
            "city": "Москва",
            "skills": "1С, склад",
            "salary_min": 55000,
            "salary_max": 90000,
            "schedule": "Сменный",
            "employment": "Полная",
            "description": "Работа на складе",
        })
        assert job_resp.status_code == 201, job_resp.text
        job_id = int(job_resp.json()["id"])

        page = visitor.get(f"/companies/{owner_id}")
        assert page.status_code == 200, page.text
        assert page.headers["content-type"].startswith("text/html")
        assert "Учебная &amp; Компания" in page.text
        assert "Кладовщик" in page.text
        assert f'href="/vacancies/{job_id}"' in page.text
        assert f'https://stazhno.ru/companies/{owner_id}' in page.text
        assert "private-employer@example.invalid" not in page.text
        assert "SyntheticPassword2026!" not in page.text
        assert "<script>alert" not in page.text
        assert "&lt;script&gt;alert" in page.text
        assert "Проверена СТАЖНО" not in page.text
        assert visitor.get("/static/employer-share.css").status_code == 200
        vacancy = visitor.get(f"/vacancies/{job_id}")
        assert f'href="/companies/{owner_id}"' in vacancy.text

        with database(app.state.db_path) as db:
            db.execute(
                "UPDATE vacancy_moderation SET status='rejected' WHERE vacancy_id=?",
                (job_id,),
            )
        page = visitor.get(f"/companies/{owner_id}")
        assert "Кладовщик" not in page.text
        assert f'href="/vacancies/{job_id}"' not in page.text
        with database(app.state.db_path) as db:
            db.execute(
                "UPDATE vacancy_moderation SET status='approved' WHERE vacancy_id=?",
                (job_id,),
            )
            db.execute("UPDATE vacancies SET status='closed' WHERE id=?", (job_id,))
        assert "Кладовщик" not in visitor.get(f"/companies/{owner_id}").text

        with database(app.state.db_path) as db:
            db.execute(
                "UPDATE account_controls SET status='disabled' WHERE user_id=?",
                (owner_id,),
            )
        assert visitor.get(f"/companies/{owner_id}").status_code == 404
        assert visitor.get("/companies/999999").status_code == 404
        with database(app.state.db_path) as db:
            assert db.execute(
                "SELECT COUNT(*) FROM employer_profiles WHERE user_id=?", (owner_id,)
            ).fetchone()[0] == 1
