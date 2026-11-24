"""Deterministic, privacy-minimal public discovery ranking."""
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import database
from app.main import create_app
from app.public_discovery import related_articles, related_jobs, terms

XHR = {"X-Requested-With": "OPYT50"}


def article(slug, title, description, category="Навыки"):
    return {
        "slug": slug,
        "title": title,
        "description": description,
        "category": category,
        "read": "4 минуты",
        "sections": [{"title": "Практика", "paragraphs": [description]}],
    }


def test_content_ranking_is_deterministic_and_not_visitor_based():
    articles = [
        article("bezopasnost", "Как проверить работодателя", "Безопасность вакансии и документов", "Безопасность"),
        article("tablitsy", "Таблицы и цифровой учёт", "Excel, таблицы, складской учёт и документы"),
        article("interview", "Подготовка к собеседованию", "Как отвечать работодателю на встрече", "Карьера"),
    ]
    selected = related_articles(
        articles,
        "Кладовщик: складской учёт, таблицы и документы",
        limit=2,
    )
    assert selected[0]["slug"] == "tablitsy"
    assert [item["slug"] for item in selected] == [
        item["slug"] for item in related_articles(
            articles, "Кладовщик: складской учёт, таблицы и документы", limit=2
        )
    ]
    assert "cookie" not in terms("таблицы документы")


def test_job_ranking_prefers_public_text_overlap_and_has_stable_fallback():
    source = article("digital", "Цифровой учёт", "Работа с таблицами и складским учётом")
    jobs = [
        {"id": 3, "title": "Курьер", "skills": "Доставка", "description": "Маршруты", "schedule": "", "employment": ""},
        {"id": 2, "title": "Кладовщик", "skills": "Складской учёт, таблицы", "description": "Инвентаризация", "schedule": "", "employment": ""},
    ]
    assert related_jobs(source, jobs, limit=1)[0]["id"] == 2
    unrelated = article("other", "Совсем другая тема", "Редкий контекст без совпадений")
    assert related_jobs(unrelated, jobs, limit=1)[0]["id"] == 3


def test_article_discovery_never_surfaces_privacy_restricted_employer(tmp_path: Path):
    app = create_app(str(tmp_path / "public-discovery.db"))
    with TestClient(app) as employer, TestClient(app) as visitor:
        registered = employer.post("/api/register", headers=XHR, json={
            "role": "employer",
            "name": "Вымышленный работодатель",
            "company_name": "Открытая компания",
            "email": "public-discovery@example.invalid",
            "password": "SyntheticDiscoveryOwner2026!",
        })
        assert registered.status_code == 201, registered.text
        owner_id = int(registered.json()["user"]["id"])
        created = employer.post("/api/employer/vacancies", headers=XHR, json={
            "title": "Оператор склада",
            "city": "Москва",
            "skills": "Складской учёт",
            "salary_min": 50000,
            "salary_max": 70000,
            "schedule": "Сменный",
            "employment": "Полная",
            "description": "Инвентаризация и учёт товара",
        })
        assert created.status_code == 201, created.text
        job_id = int(created.json()["id"])
        page = visitor.get("/journal/cifrovye-navyki-dlya-raboty")
        assert f'href="/vacancies/{job_id}"' in page.text

        with database(app.state.db_path) as db:
            db.execute(
                """INSERT INTO privacy_rights_requests(user_id,kind,status)
                   VALUES(?,'stop_processing','received')""",
                (owner_id,),
            )
        restricted = visitor.get("/journal/cifrovye-navyki-dlya-raboty")
        assert f'href="/vacancies/{job_id}"' not in restricted.text
