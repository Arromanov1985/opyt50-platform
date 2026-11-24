"""Public vacancy landing pages: only moderated open job data is disclosed."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import database
from app.main import create_app
from app.vacancy_pages import _pay

XHR = {"X-Requested-With": "OPYT50"}


def register_employer(client):
    response = client.post("/api/register", headers=XHR, json={
        "role": "employer",
        "name": "Вымышленный работодатель",
        "company_name": "Тестовая фирма",
        "email": "private-owner@example.invalid",
        "password": "OnlySyntheticPassword2026!",
    })
    assert response.status_code == 201, response.text
    return response.json()["user"]["id"]


def create_public_job(client):
    response = client.post("/api/employer/vacancies", headers=XHR, json={
        "title": "Кладовщик",
        "city": "Москва",
        "skills": "Склад, 1С",
        "salary_min": 50000,
        "salary_max": 80000,
        "schedule": "Сменный",
        "employment": "Полная",
        "description": "Поддерживать учёт. <script>alert('xss')</script>",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_shareable_vacancy_page_shows_public_information_only(tmp_path: Path):
    app = create_app(str(tmp_path / "public-job.db"))
    with TestClient(app) as client:
        owner_id = register_employer(client)
        job_id = create_public_job(client)
        page = client.get(f"/vacancies/{job_id}")
        assert page.status_code == 200, page.text
        assert page.headers["cache-control"].startswith("public")
        assert "Кладовщик" in page.text
        assert "Тестовая фирма" in page.text
        assert "Москва" in page.text
        assert "от 50 000 до 80 000 ₽" in page.text
        assert "Сменный" in page.text
        assert f'href="/?vacancy={job_id}#jobs" data-growth-action="apply_click"' in page.text
        assert 'data-growth-action="company_click"' in page.text
        assert 'data-growth-action="jobs_click"' in page.text
        assert "Полезно перед откликом" in page.text
        assert 'class="reading-grid"' in page.text
        assert 'href="/journal/kak-proverit-vakansiyu"' in page.text
        assert "без данных о посетителе" in page.text
        assert f'https://stazhno.ru/vacancies/{job_id}' in page.text
        assert "Контакты" not in page.text or "Контакты не" in page.text
        assert "private-owner@example.invalid" not in page.text
        assert "<script>alert('xss')</script>" not in page.text
        assert "&lt;script&gt;alert" in page.text
        assert client.get("/static/vacancy-share.css").status_code == 200
        assert client.get("/static/employer-directory.css").status_code == 200

        with database(app.state.db_path) as db:
            db.execute(
                "UPDATE journal_entries SET status='hidden' WHERE slug='kak-proverit-vakansiyu'"
            )
        after_editor_hide = client.get(f"/vacancies/{job_id}")
        assert 'href="/journal/kak-proverit-vakansiyu"' not in after_editor_hide.text
        assert "Полезно перед откликом" in after_editor_hide.text

        with database(app.state.db_path) as db:
            # Publishing the job already creates its moderation row.
            db.execute(
                "UPDATE vacancy_moderation SET status='rejected' WHERE vacancy_id=?",
                (job_id,),
            )
        assert client.get(f"/vacancies/{job_id}").status_code == 404
        with database(app.state.db_path) as db:
            db.execute(
                "UPDATE vacancy_moderation SET status='approved' WHERE vacancy_id=?",
                (job_id,),
            )
            db.execute("UPDATE vacancies SET status='closed' WHERE id=?", (job_id,))
        assert client.get(f"/vacancies/{job_id}").status_code == 404
        assert client.get("/vacancies/999999").status_code == 404
        # The public page never modifies or deletes the user's vacancy.
        with database(app.state.db_path) as db:
            assert db.execute("SELECT employer_id FROM vacancies WHERE id=?", (job_id,)).fetchone()[0] == owner_id


def test_shared_vacancy_link_does_not_auto_apply(tmp_path: Path):
    app = create_app(str(tmp_path / "link.db"))
    with TestClient(app) as client:
        register_employer(client)
        job_id = create_public_job(client)
        page = client.get(f"/?vacancy={job_id}")
        assert page.status_code == 200
        script = client.get("/static/release02.js").text
        assert "linkedVacancyId" in script
        assert "showJobDetails(linkedVacancyId)" in script
        with database(app.state.db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM job_applications").fetchone()[0] == 0


@pytest.mark.parametrize("low,high,expected", [
    (0, 0, "По договорённости"),
    (None, None, "По договорённости"),
    (0, 80000, "до 80 000 ₽"),
    (50000, 0, "от 50 000 ₽"),
    (60000, 60000, "60 000 ₽"),
    (50000, 80000, "от 50 000 до 80 000 ₽"),
])
def test_pay_preserves_the_employers_actual_boundaries(low, high, expected):
    assert _pay(low, high) == expected


def test_public_vacancy_explains_prelaunch_without_changing_application_state(tmp_path, monkeypatch):
    app = create_app(str(tmp_path / "prelaunch-vacancy.db"))
    with TestClient(app) as client:
        register_employer(client)
        job_id = create_public_job(client)
        ordinary = client.get(f"/vacancies/{job_id}")
        assert "Переход по ссылке не отправляет отклик" in ordinary.text
        assert "Регистрация пока закрыта" not in ordinary.text
        monkeypatch.setenv("OPYT50_PUBLIC_URL", "https://stazhno.ru")
        prelaunch = client.get(f"/vacancies/{job_id}")
        assert prelaunch.status_code == 200
        assert "Регистрация пока закрыта" in prelaunch.text
        assert "с существующим аккаунтом" in prelaunch.text
        assert 'href="/journal/paths/nayti-rabotu"' in prelaunch.text
        assert f'href="/?vacancy={job_id}#jobs"' in prelaunch.text
        assert 'id="reading-mode-toggle"' in prelaunch.text
        assert prelaunch.headers["x-robots-tag"] == "noindex, nofollow"
        with database(app.state.db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM job_applications").fetchone()[0] == 0
        # When the existing legal gate is genuinely ready, ordinary navigation
        # returns automatically; this patch never changes the gate itself.
        monkeypatch.setattr("app.legal_config.legal_approved", lambda: True)
        assert "Регистрация пока закрыта" not in client.get(f"/vacancies/{job_id}").text
