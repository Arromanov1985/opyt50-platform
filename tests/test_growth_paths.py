"""Privacy-safe growth reporting for the three editorial journeys."""
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import database
from app.main import active_user, create_app
from app.journal_paths import PATHS

HEADERS = {"X-Requested-With": "OPYT50"}


def post(client, source, action):
    return client.post("/api/growth/event", headers=HEADERS,
                       json={"source": source, "action": action})


def test_published_paths_have_counted_cta_and_aggregate_only(tmp_path: Path):
    app = create_app(str(tmp_path / "journeys.sqlite"))
    with TestClient(app) as client:
        for path in PATHS:
            source = "path:" + path["slug"]
            page = client.get("/journal/paths/" + path["slug"])
            assert page.status_code == 200
            assert "data-growth-action=" in page.text
            assert "/static/journal.js?v=6" in page.text
            action = "community_click" if path["href"] == "/community" else "jobs_click"
            assert 'data-growth-action="' + action + '"' in page.text
            assert post(client, source, "view").status_code == 204
            assert post(client, source, action).status_code == 204
        assert post(client, "path:nonexistent", "view").status_code == 422
        assert post(client, "path:../../users", "view").status_code == 422
        assert post(client, "journal", "community_click").status_code == 204
        assert client.post("/api/growth/event", json={
            "source": "path:nayti-rabotu", "action": "view"
        }).status_code == 403
        assert client.get("/api/admin/growth").status_code == 401
        app.dependency_overrides[active_user] = lambda: {"role": "admin"}
        result = client.get("/api/admin/growth")
        assert result.status_code == 200
        stats = result.json()["by_article"]
        for path in PATHS:
            source = "path:" + path["slug"]
            action = "community_click" if path["href"] == "/community" else "jobs_click"
            assert any(item["source"] == source and item["action"] == action and item["total"] == 1
                       for item in stats)
        with database(app.state.db_path) as db:
            columns = [row["name"] for row in db.execute("PRAGMA table_info(growth_daily_counts)")]
            assert columns == ["event_date", "source", "action", "total"]
        app.dependency_overrides.clear()


def test_journal_client_tracks_only_whitelisted_actions():
    source = (Path(__file__).resolve().parents[1] / "app/static/journal.js").read_text()
    assert "path.startsWith('/journal/paths/')" in source
    assert "'community_click'" in source
    assert "'company_click'" in source
    assert "'vacancy_click'" in source
    assert "'apply_click'" in source
    assert "'article_click'" in source
    assert "'recommended_vacancy_click'" in source
    assert ".includes(action)" in source
    assert "credentials: 'omit'" in source
    assert "referrerPolicy: 'no-referrer'" in source
    assert "data-growth-action" in source
