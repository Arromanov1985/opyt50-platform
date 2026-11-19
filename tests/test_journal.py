"""Public journal acceptance: SEO, no personal data, navigation, accessibility."""
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import create_app

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
SLUGS = (
    "kak-pokazat-opyt-v-profile",
    "kak-proverit-vakansiyu",
    "proektnaya-rabota-posle-50",
)


def test_journal_public_pages_and_no_leaks(tmp_path):
    app = create_app(str(tmp_path / "journal.sqlite"))
    with TestClient(app) as client:
        index = client.get("/journal")
        assert index.status_code == 200
        assert index.headers["content-type"].startswith("text/html")
        assert 'href="https://stazhno.ru/journal"' in index.text
        assert 'href="/static/journal.css?v=1"' in index.text
        assert 'id="reading-mode-toggle"' in index.text
        assert 'href="/#jobs"' in index.text
        for slug in SLUGS:
            assert f'href="/journal/{slug}"' in index.text
            article = client.get(f"/journal/{slug}")
            assert article.status_code == 200
            assert f'href="https://stazhno.ru/journal/{slug}"' in article.text
            assert '<meta name="description"' in article.text
            assert '<h1>' in article.text
            assert 'Редакция СТАЖНО' in article.text
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
        ):
            assert (STATIC / name).is_file()
            response = client.get("/static/" + name)
            assert response.status_code == 200
            assert media in response.headers["content-type"]
    script = (STATIC / "journal.js").read_text(encoding="utf-8")
    assert "stazhno-large-text" in script
    assert "aria-pressed" in script
    assert "localStorage" in script
