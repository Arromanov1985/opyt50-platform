"""Public employer discovery: moderated content only, no private account data."""
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import database
from app.main import create_app

XHR = {"X-Requested-With": "OPYT50"}


def _register(client: TestClient, name: str, email: str) -> int:
    result = client.post("/api/register", headers=XHR, json={
        "role": "employer",
        "name": "Вымышленный представитель",
        "company_name": name,
        "email": email,
        "password": "SyntheticEmployerPass2026!",
    })
    assert result.status_code == 201, result.text
    return int(result.json()["user"]["id"])


def _job(client: TestClient, city: str, title: str = "Мастер склада") -> int:
    result = client.post("/api/employer/vacancies", headers=XHR, json={
        "title": title,
        "city": city,
        "skills": "Инвентаризация, учёт",
        "salary_min": 45000,
        "salary_max": 85000,
        "schedule": "Сменный",
        "employment": "Полная",
        "description": "Работа с товарами и документами.",
    })
    assert result.status_code == 201, result.text
    return int(result.json()["id"])


def test_directory_only_contains_active_employers_with_approved_open_jobs(tmp_path: Path):
    app = create_app(str(tmp_path / "directory.db"))
    with TestClient(app) as viewer, TestClient(app) as first, TestClient(app) as second:
        employer1 = _register(first, "Тестовая Логистика", "director1@example.invalid")
        employer2 = _register(second, "Тестовое Производство", "director2@example.invalid")
        empty = viewer.get("/employers")
        assert empty.status_code == 200
        assert 'id="employer-cards"' not in empty.text
        assert "Найдено компаний: 0" in empty.text
        assert viewer.get(f"/employers/{employer1}").status_code == 404
        assert viewer.post("/employers").status_code == 405

        open_job_id = _job(first, "Подольск")
        hidden_job_id = _job(second, "Москва", "Наладчик")
        with database(app.state.db_path) as db:
            db.execute(
                "UPDATE vacancy_moderation SET status='rejected' WHERE vacancy_id=?",
                (hidden_job_id,),
            )
        index = viewer.get("/employers")
        assert index.status_code == 200
        assert "Тестовая Логистика" in index.text
        assert "Тестовое Производство" not in index.text
        assert 'id="employer-cards"' in index.text
        assert "Найдено компаний: 1" in index.text
        assert "director1@example.invalid" not in index.text
        assert "director2@example.invalid" not in index.text
        assert "/employers" in viewer.get("/journal").text
        assert viewer.get(f"/employers/{employer2}").status_code == 404
        profile = viewer.get(f"/employers/{employer1}")
        assert profile.status_code == 200
        assert "Мастер склада" in profile.text
        assert f'href="/vacancies/{open_job_id}"' in profile.text
        assert "Инвентаризация" not in index.text  # No applicant or job descriptions
        assert "director1@example.invalid" not in profile.text
        assert "SyntheticEmployerPass2026" not in profile.text

        # An isolated public search narrows to a city and company name.
        assert "Тестовая Логистика" in viewer.get(
            "/employers", params={"q": "логист", "city": "Подольск"}
        ).text
        no_result = viewer.get("/employers", params={"city": "Казань"})
        assert 'id="employer-cards"' not in no_result.text
        assert "Показать все компании" in no_result.text
        assert viewer.get("/employers", params={"q": "x" * 101}).status_code == 422

        # Closed vacancy or disabled employer must never stay discoverable.
        with database(app.state.db_path) as db:
            db.execute("UPDATE vacancies SET status='closed' WHERE id=?", (open_job_id,))
        assert "Тестовая Логистика" not in viewer.get("/employers").text
        assert viewer.get(f"/employers/{employer1}").status_code == 404
        with database(app.state.db_path) as db:
            db.execute("UPDATE vacancies SET status='open' WHERE id=?", (open_job_id,))
            db.execute(
                "INSERT INTO account_controls(user_id,status) VALUES(?, 'disabled')"
                " ON CONFLICT(user_id) DO UPDATE SET status='disabled'",
                (employer1,),
            )
        assert "Тестовая Логистика" not in viewer.get("/employers").text
        assert viewer.get(f"/employers/{employer1}").status_code == 404


def test_employer_public_description_is_escaped_and_legacy_contacts_suppressed(tmp_path: Path):
    app = create_app(str(tmp_path / "privacy.db"))
    with TestClient(app) as client:
        employer_id = _register(client, "Проверка <скрипт>", "personal@example.invalid")
        _job(client, "Москва")
        with database(app.state.db_path) as db:
            db.execute(
                "INSERT INTO employer_public_profiles(employer_id,about,updated_at)"
                " VALUES(?,?,datetime('now'))",
                (employer_id, "<script>alert('bad')</script> Учёт склада"),
            )
        public = client.get(f"/employers/{employer_id}")
        assert public.status_code == 200
        assert "<script>alert('bad')</script>" not in public.text
        assert "&lt;script&gt;alert" in public.text
        assert "&lt;скрипт&gt;" in public.text
        with database(app.state.db_path) as db:
            db.execute(
                "UPDATE employer_public_profiles SET about=? WHERE employer_id=?",
                ("Пишите напрямую personal@example.invalid", employer_id),
            )
        assert "personal@example.invalid" not in client.get(
            f"/employers/{employer_id}"
        ).text


def test_employer_directory_preview_noindex_and_canonical(tmp_path: Path):
    app = create_app(str(tmp_path / "seo.db"))
    with TestClient(app, base_url="https://preview.twc1.net") as viewer:
        directory = viewer.get("/employers")
        assert directory.status_code == 200
        assert directory.headers.get("x-robots-tag") == "noindex, nofollow"
        assert 'href="https://stazhno.ru/employers"' in directory.text
        assert 'name="q"' in directory.text
        assert 'name="city"' in directory.text
    with TestClient(app, base_url="https://stazhno.ru") as public:
        assert public.get("/employers").headers.get("x-robots-tag") is None
        assert "https://stazhno.ru/employers" in public.get("/sitemap.xml").text
