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
        assert 'href="/static/journal.css?v=3"' in index.text
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
            assert 'href="/#candidate-path"' in article.text
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
        ]
        assert all("/api/" not in url for url in urls)
        assert all("/dashboard" not in url for url in urls)


def test_preview_not_indexed_and_canonical_domain_indexable(tmp_path):
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
        assert "Disallow: /api/" in robots.text
        assert "https://stazhno.ru/sitemap.xml" in robots.text
        assert "Disallow: /\n" not in robots.text
        assert public.get("/journal").headers.get("x-robots-tag") is None
