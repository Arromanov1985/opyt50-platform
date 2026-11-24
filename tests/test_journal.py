"""Public journal acceptance: SEO, no personal data, navigation, accessibility."""
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import create_app

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
SLUGS = (
    "kak-pokazat-opyt-v-profile",
    "kak-proverit-vakansiyu",
    "proektnaya-rabota-posle-50",
    "sobesedovanie-posle-50",
    "cifrovye-navyki-dlya-raboty",
    "rabotodatelyu-ocenit-opyt",
    "perehod-v-novuyu-professiyu",
    "kak-obsuzhdat-zarplatu",
    "nastavnichestvo-peredacha-opyta",
    "udalyonnaya-rabota-bez-riskov",
)


def test_journal_public_pages_and_no_leaks(tmp_path):
    app = create_app(str(tmp_path / "journal.sqlite"))
    with TestClient(app) as client:
        index = client.get("/journal")
        assert index.status_code == 200
        assert index.headers["content-type"].startswith("text/html")
        assert 'href="https://stazhno.ru/journal"' in index.text
        assert 'href="/static/journal.css?v=6"' in index.text
        assert 'id="reading-mode-toggle"' in index.text
        assert 'id="jr-article-search"' in index.text
        assert 'data-jr-category-filter="all"' in index.text
        assert 'id="jr-no-results"' in index.text
        assert 'href="/#jobs"' in index.text
        for slug in SLUGS:
            assert f'href="/journal/{slug}"' in index.text
            article = client.get(f"/journal/{slug}")
            assert article.status_code == 200
            assert f'href="https://stazhno.ru/journal/{slug}"' in article.text
            assert '<meta name="description"' in article.text
            assert '<h1>' in article.text
            assert 'Редакция СТАЖНО' in article.text
            assert 'Читайте также' in article.text
            assert 'href="/journal/paths/nayti-rabotu"' in article.text
            assert 'data-growth-action="profile_click"' not in article.text
            assert "Регистрация пока закрыта" in article.text
            assert 'type="password"' not in article.text
        assert client.get("/journal/no-such-article").status_code == 404


def test_journal_no_mutations_and_home_links(tmp_path):
    app = create_app(str(tmp_path / "journal.sqlite"))
    with TestClient(app) as client:
        homepage = client.get("/")
        assert homepage.status_code == 200
        assert 'id="journal-preview"' in homepage.text
        assert 'href="/journal"' in homepage.text
        assert 'href="/community"' in homepage.text
        assert 'id="journal-home-highlights"' in homepage.text
        assert 'editorial-directions-grid' in homepage.text
        assert client.get("/api/public/journal/highlights").status_code == 200
        assert len(client.get("/api/public/journal/highlights").json()["articles"]) == 4
        assert 'href="/static/journal-preview.css?v=1"' in homepage.text
        assert client.post("/journal").status_code == 405
        assert client.post("/journal/kak-proverit-vakansiyu").status_code == 405
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/jobs").status_code == 200


def test_journal_assets_exist_and_accessible(tmp_path):
    app = create_app(str(tmp_path / "journal.sqlite"))
    with TestClient(app) as client:
        for name, media in (
            ("journal.css", "text/css"),
            ("journal-preview.css", "text/css"),
            ("journal.js", "javascript"),
            ("journal-home.js", "javascript"),
            ("editorial-home.css", "text/css"),
            ("journal-admin.js", "javascript"),
            ("journal-admin.css", "text/css"),
        ):
            assert (STATIC / name).is_file()
            response = client.get("/static/" + name)
            assert response.status_code == 200
            assert media in response.headers["content-type"]
    script = (STATIC / "journal.js").read_text(encoding="utf-8")
    assert "stazhno-large-text" in script
    assert "aria-pressed" in script
    assert "localStorage" in script


def test_public_sitemap_lists_only_public_editorial_pages(tmp_path):
    import xml.etree.ElementTree as ET

    app = create_app(str(tmp_path / "seo.sqlite"))
    with TestClient(app, base_url="https://stazhno.ru") as client:
        response = client.get("/sitemap.xml")
        assert response.status_code == 200
        assert "application/xml" in response.headers["content-type"]
        root = ET.fromstring(response.text)
        namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        urls = [item.text for item in root.findall("s:url/s:loc", namespace)]
        assert urls == [
            "https://stazhno.ru/",
            "https://stazhno.ru/employers",
            "https://stazhno.ru/journal",
            *["https://stazhno.ru/journal/" + slug for slug in SLUGS],
            "https://stazhno.ru/journal/paths",
            *["https://stazhno.ru/journal/paths/" + slug for slug in
              ("nayti-rabotu", "novye-navyki", "delitsya-opytom")],
        ]
        assert all("/api/" not in url for url in urls)
        assert all("/dashboard" not in url for url in urls)


def test_preview_and_unapproved_canonical_domain_are_not_indexable(tmp_path):
    app = create_app(str(tmp_path / "seo.sqlite"))
    with TestClient(app, base_url="https://preview.twc1.net") as preview:
        robots = preview.get("/robots.txt")
        assert robots.status_code == 200
        assert "Disallow: /\n" in robots.text
        assert "Sitemap:" not in robots.text
        assert preview.get("/journal").headers.get("x-robots-tag") == "noindex, nofollow"
        assert preview.get("/").headers.get("x-robots-tag") == "noindex, nofollow"
    with TestClient(app, base_url="https://stazhno.ru") as public:
        robots = public.get("/robots.txt")
        assert robots.status_code == 200
        assert "Disallow: /\n" in robots.text
        assert "Sitemap:" not in robots.text
        assert public.get("/journal").headers.get("x-robots-tag") == "noindex, nofollow"


def test_journal_preactivation_and_approved_actions(monkeypatch, tmp_path):
    """Reading can continue during prelaunch; approved signup restores normal CTA."""
    from app import journal
    app = create_app(str(tmp_path / "prelaunch-journal.db"))
    with TestClient(app) as client:
        first = client.get("/journal")
        assert first.status_code == 200
        assert 'class="jr-prelaunch-note"' in first.text
        assert 'href="/journal/paths/nayti-rabotu"' in first.text
        assert 'data-growth-action="profile_click"' not in first.text
        assert 'data-growth-action="jobs_click"' in first.text
        monkeypatch.setattr(journal, "_signup_available", lambda: True)
        ready = client.get("/journal")
        assert 'class="jr-prelaunch-note"' not in ready.text
        assert 'href="/#candidate-path" data-growth-action="profile_click"' in ready.text
        article = client.get("/journal/kak-proverit-vakansiyu")
        assert 'href="/#candidate-path" data-growth-action="profile_click"' in article.text



def test_article_recommends_only_current_public_vacancies_and_manifest_matches(tmp_path):
    import hashlib
    from app.db import database

    app = create_app(str(tmp_path / "journal-discovery.sqlite"))
    headers = {"X-Requested-With": "OPYT50"}
    with TestClient(app) as employer, TestClient(app) as visitor:
        registered = employer.post("/api/register", headers=headers, json={
            "role": "employer",
            "name": "Вымышленный работодатель",
            "company_name": "Учебный склад",
            "email": "discovery-owner@example.invalid",
            "password": "SyntheticDiscoveryPassword2026!",
        })
        assert registered.status_code == 201, registered.text
        vacancy = employer.post("/api/employer/vacancies", headers=headers, json={
            "title": "Кладовщик 1С",
            "city": "Москва",
            "skills": "Склад, учёт товаров",
            "salary_min": 60000,
            "salary_max": 85000,
            "schedule": "Сменный",
            "employment": "Полная",
            "description": "Приёмка товара, инвентаризация и работа с учётом.",
        })
        assert vacancy.status_code == 201, vacancy.text
        job_id = int(vacancy.json()["id"])

        path = "/journal/cifrovye-navyki-dlya-raboty"
        page = visitor.get(path)
        assert page.status_code == 200
        assert 'class="jr-opportunities"' in page.text
        assert "Кладовщик 1С" in page.text
        assert "Учебный склад" in page.text
        assert f'href="/vacancies/{job_id}" data-growth-action="jobs_click"' in page.text
        assert "Профиль и история посетителя не используются" in page.text

        manifest = visitor.get("/api/public/journal/manifest").json()
        assert manifest["pages"][path] == hashlib.sha256(page.content).hexdigest()

        with database(app.state.db_path) as db:
            db.execute(
                "UPDATE vacancy_moderation SET status='rejected' WHERE vacancy_id=?",
                (job_id,),
            )
        hidden = visitor.get(path)
        assert "Кладовщик 1С" not in hidden.text
        manifest = visitor.get("/api/public/journal/manifest").json()
        assert manifest["pages"][path] == hashlib.sha256(hidden.content).hexdigest()
