"""Search preparation and anonymous directional discovery regression."""
import hashlib
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient

from app.db import database
from app.main import active_user, create_app

XHR = {"X-Requested-With": "OPYT50"}
ARTICLE = "cifrovye-navyki-dlya-raboty"


def register(client, suffix):
    response = client.post("/api/register", headers=XHR, json={
        "role": "employer", "name": "Вымышленный представитель",
        "company_name": "Учебная компания " + suffix,
        "email": f"search-{suffix}@example.invalid",
        "password": "SyntheticSearchPassword2026!",
    })
    assert response.status_code == 201, response.text
    return int(response.json()["user"]["id"])


def job(client, title):
    response = client.post("/api/employer/vacancies", headers=XHR, json={
        "title": title, "city": "Москва", "skills": "Учёт, таблицы",
        "salary_min": 50000, "salary_max": 70000,
        "schedule": "Полный день", "employment": "Полная",
        "description": "Учебное предложение, работа с таблицами.",
    })
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def sitemap(visitor):
    result = visitor.get("/sitemap.xml")
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert result.headers["x-robots-tag"] == "noindex, nofollow"
    manifest = visitor.get("/api/public/journal/manifest").json()
    assert manifest["pages"]["/sitemap.xml"] == hashlib.sha256(result.content).hexdigest()
    root = ET.fromstring(result.content)
    namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = [item.text for item in root.findall("s:url/s:loc", namespace)]
    assert len(urls) == len(set(urls))
    assert all(url.startswith("https://stazhno.ru/") for url in urls)
    assert not any("/employers/" in url or "/api/" in url for url in urls)
    return set(urls)


def test_dynamic_sitemap_and_redirect_respect_public_visibility(tmp_path):
    app = create_app(str(tmp_path / "search.db"))
    with TestClient(app) as first, TestClient(app) as second, TestClient(app) as visitor:
        company = register(first, "open")
        first_job = job(first, "Оператор таблиц")
        another_job = job(first, "Бухгалтер")
        restricted = register(second, "restricted")
        hidden_job = job(second, "Ограниченное предложение")
        with database(app.state.db_path) as db:
            db.execute("UPDATE vacancy_moderation SET status='rejected' WHERE vacancy_id=?", (hidden_job,))
        urls = sitemap(visitor)
        origin = "https://stazhno.ru"
        assert origin + f"/companies/{company}" in urls
        assert origin + f"/vacancies/{first_job}" in urls
        assert origin + f"/vacancies/{another_job}" in urls
        assert origin + f"/companies/{restricted}" not in urls
        assert origin + f"/vacancies/{hidden_job}" not in urls
        alias = visitor.get(f"/employers/{company}", follow_redirects=False)
        assert alias.status_code == 301
        assert alias.headers["location"] == f"/companies/{company}"
        assert alias.headers["cache-control"] == "no-store"
        assert visitor.get(f"/employers/{restricted}", follow_redirects=False).status_code == 404
        assert "Disallow: /\n" in visitor.get("/robots.txt").text
        assert visitor.get(f"/vacancies/{first_job}").headers["x-robots-tag"] == "noindex, nofollow"

        with database(app.state.db_path) as db:
            db.execute("UPDATE vacancies SET status='closed' WHERE id=?", (first_job,))
        urls = sitemap(visitor)
        assert origin + f"/vacancies/{first_job}" not in urls
        assert origin + f"/companies/{company}" in urls

        rights = first.post("/api/account/privacy-requests", headers=XHR,
                            json={"kind": "stop_processing"})
        assert rights.status_code == 201, rights.text
        urls = sitemap(visitor)
        assert origin + f"/vacancies/{another_job}" not in urls
        assert origin + f"/companies/{company}" not in urls
        assert visitor.get(f"/employers/{company}", follow_redirects=False).status_code == 404


def test_directional_events_use_existing_aggregate_storage(tmp_path):
    app = create_app(str(tmp_path / "directions.db"))
    with TestClient(app) as employer, TestClient(app) as visitor:
        company = register(employer, "analytics")
        job_id = job(employer, "Оператор таблиц")
        article = visitor.get("/journal/" + ARTICLE)
        assert f'href="/vacancies/{job_id}" data-growth-action="recommended_vacancy_click"' in article.text
        vacancy = visitor.get(f"/vacancies/{job_id}")
        company_page = visitor.get(f"/companies/{company}")
        assert vacancy.text.count('data-growth-action="article_click"') == 2
        assert 'class="employer-reading-card"' in company_page.text
        assert 'data-growth-action="article_click"' in company_page.text

        def send(source, action, **extra):
            return visitor.post("/api/growth/event", headers=XHR,
                                json={"source": source, "action": action, **extra})
        assert send(ARTICLE, "recommended_vacancy_click").status_code == 204
        assert send(f"vacancy:{job_id}", "article_click").status_code == 204
        assert send(f"company:{company}", "article_click").status_code == 204
        assert send("journal", "article_click").status_code == 422
        assert send("journal", "recommended_vacancy_click").status_code == 422
        assert send(f"vacancy:{job_id}", "recommended_vacancy_click").status_code == 422
        assert send("path:nayti-rabotu", "recommended_vacancy_click").status_code == 422
        assert send(ARTICLE, "recommended_vacancy_click", visitor="private").status_code == 422
        assert visitor.get("/api/admin/growth").status_code == 401
        app.dependency_overrides[active_user] = lambda: {"role": "admin"}
        try:
            summary = visitor.get("/api/admin/growth").json()["summary"]
            assert summary["journal_vacancy_clicks"] == 1
            assert summary["vacancy_article_clicks"] == 1
            assert summary["company_article_clicks"] == 1
            assert summary["jobs_clicks"] == 0
        finally:
            app.dependency_overrides.clear()
        with database(app.state.db_path) as db:
            assert [r["name"] for r in db.execute("PRAGMA table_info(growth_daily_counts)")] == [
                "event_date", "source", "action", "total"
            ]
            db.execute("UPDATE vacancies SET status='closed' WHERE id=?", (job_id,))
        assert send(f"vacancy:{job_id}", "article_click").status_code == 422
        with database(app.state.db_path) as db:
            db.execute("UPDATE journal_entries SET status='hidden' WHERE slug=?", (ARTICLE,))
        assert send(ARTICLE, "recommended_vacancy_click").status_code == 422
