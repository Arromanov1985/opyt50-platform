"""Editorial reading journeys use published CMS content, not private drafts."""
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import database
from app.main import create_app
from app.journal_paths import PATHS, visible_paths


def test_reading_paths_are_accessible_and_step_by_step(tmp_path: Path):
    app = create_app(str(tmp_path / "paths.db"))
    with TestClient(app) as client:
        catalog = client.get("/journal")
        assert catalog.status_code == 200
        assert 'href="/journal/paths"' in catalog.text
        assert 'href="/journal/paths"' in client.get("/").text
        index = client.get("/journal/paths")
        assert index.status_code == 200
        assert 'href="https://stazhno.ru/journal/paths"' in index.text
        assert len(PATHS) == 3
        for path in PATHS:
            assert 'href="/journal/paths/' + path["slug"] + '"' in index.text
            page = client.get("/journal/paths/" + path["slug"])
            assert page.status_code == 200
            assert path["title"] in page.text
            assert '<ol class="jr-path-steps">' in page.text
            assert 'href="' + path["href"] + '"' in page.text
            expected_action = "community_click" if path["href"] == "/community" else "jobs_click"
            assert 'data-growth-action="' + expected_action + '"' in page.text
            for slug, _ in path["steps"]:
                assert 'href="/journal/' + slug + '"' in page.text
            assert 'type="password"' not in page.text
        assert client.get("/journal/paths/no-such-path").status_code == 404
        assert client.post("/journal/paths").status_code == 405


def test_hidden_cms_articles_never_appear_in_guides(tmp_path: Path):
    app = create_app(str(tmp_path / "hidden-path.db"))
    with TestClient(app) as client:
        path = PATHS[1]
        first_slug = path["steps"][0][0]
        with database(app.state.db_path) as db:
            db.execute(
                "UPDATE journal_entries SET status='hidden' WHERE slug=?",
                (first_slug,),
            )
            db.commit()
        page = client.get("/journal/paths/" + path["slug"])
        assert page.status_code == 200
        assert "/journal/" + first_slug not in page.text
        assert client.get("/journal/" + first_slug).status_code == 404
        with database(app.state.db_path) as db:
            for slug, _ in path["steps"]:
                db.execute("UPDATE journal_entries SET status='hidden' WHERE slug=?", (slug,))
            db.commit()
        assert client.get("/journal/paths/" + path["slug"]).status_code == 404
        assert 'href="/journal/paths/' + path["slug"] + '"' not in client.get("/journal/paths").text


def test_guides_use_only_published_versions():
    live = [
        {"slug": "kak-proverit-vakansiyu", "title": "Действующая редакция",
         "description": "Проверенные советы", "category": "Безопасность"}
    ]
    result = visible_paths(live)
    assert len(result) == 1
    assert len(result[0]["steps"]) == 1
    assert result[0]["steps"][0]["article"]["title"] == "Действующая редакция"
