"""Complete editorial rollups, publication gates and truthful event ratios."""
from datetime import datetime, timedelta, timezone
import json

from fastapi.testclient import TestClient

from app.db import database
from app.journal import ARTICLES
from app.journal_paths import PATHS
from app.main import active_user, create_app

HEADERS = {"X-Requested-With": "OPYT50"}


def event(client, source, action="view", **extra):
    return client.post("/api/growth/event", headers=HEADERS,
                       json={"source": source, "action": action, **extra})


def report(app, client, days=30):
    app.dependency_overrides[active_user] = lambda: {"role": "admin"}
    try:
        response = client.get(f"/api/admin/growth?days={days}")
        assert response.status_code == 200, response.text
        return response.json()
    finally:
        app.dependency_overrides.clear()


def published_article(db, slug, title):
    encoded = json.dumps({**ARTICLES[0], "slug": slug, "title": title}, ensure_ascii=False)
    db.execute(
        """INSERT INTO journal_entries(slug,draft_json,published_json,status,updated_at)
           VALUES(?,?,?,'published',?)""",
        (slug, encoded, encoded, datetime.now(timezone.utc).isoformat()),
    )


def test_catalog_covers_new_long_slugs_and_disjoint_route_sources(tmp_path):
    app = create_app(str(tmp_path / "sources.db"))
    with TestClient(app) as client:
        article_source = "path-nayti-rabotu"
        long_source = "new-" + "a" * 86
        with database(app.state.db_path) as db:
            published_article(db, article_source, "Отдельная статья с похожим адресом")
            published_article(db, long_source, "Новая статья с длинным адресом")
        assert event(client, article_source).status_code == 204
        assert event(client, article_source, "jobs_click").status_code == 204
        assert event(client, article_source, "community_click").status_code == 204
        assert event(client, long_source, "profile_click").status_code == 204
        assert event(client, "path:nayti-rabotu").status_code == 204
        assert event(client, "path:invented").status_code == 422
        assert event(client, "journal", email="private@example.invalid").status_code == 422
        data = report(app, client)
        rows = {row["source"]: row for row in data["by_source"]}
        assert len(rows) == len(ARTICLES) + len(PATHS) + 1 + 2
        assert rows[article_source]["kind"] == "article"
        assert rows[article_source]["clicks_per_view_percent"] == 200
        assert rows[long_source]["title"] == "Новая статья с длинным адресом"
        assert rows[long_source]["clicks_per_view_percent"] is None
        assert rows["path:nayti-rabotu"]["kind"] == "path"
        assert rows["path:nayti-rabotu"]["view"] == 1
        assert rows["path:nayti-rabotu"]["jobs_click"] == 0
        assert data["summary"]["community_clicks"] == 1
        assert "private@example.invalid" not in json.dumps(data)


def test_hidden_articles_and_empty_routes_stop_counting_but_keep_history(tmp_path):
    app = create_app(str(tmp_path / "hidden.db"))
    path = PATHS[0]
    source = "path:" + path["slug"]
    article_source = path["steps"][0][0]
    with TestClient(app) as client:
        assert event(client, source).status_code == 204
        assert event(client, article_source).status_code == 204
        with database(app.state.db_path) as db:
            for slug, _ in path["steps"]:
                db.execute("UPDATE journal_entries SET status='hidden' WHERE slug=?", (slug,))
        assert client.get("/journal/paths/" + path["slug"]).status_code == 404
        assert event(client, source).status_code == 422
        assert event(client, article_source).status_code == 422
        rows = {row["source"]: row for row in report(app, client)["by_source"]}
        assert rows[source]["view"] == 1 and rows[source]["published"] is False
        assert rows[article_source]["view"] == 1 and rows[article_source]["published"] is False
        assert path["steps"][1][0] not in rows  # hidden and no historical events
        manifest = client.get("/api/public/journal/manifest").json()["pages"]
        assert "/journal/paths/" + path["slug"] not in manifest
        assert "/journal/paths" in manifest


def test_utc_report_includes_boundaries_and_excludes_future_data(tmp_path):
    app = create_app(str(tmp_path / "dates.db"))
    today = datetime.now(timezone.utc).date()
    with TestClient(app) as client:
        with database(app.state.db_path) as db:
            for offset, count in ((-30, 100), (-29, 2), (0, 3), (1, 100)):
                day = (today + timedelta(days=offset)).isoformat()
                db.execute("INSERT INTO growth_daily_counts VALUES(?,?,?,?)",
                           (day, "journal", "view", count))
                db.execute(
                    "INSERT INTO users(email,password_hash,role,name,created_at) VALUES(?,?,?,?,?)",
                    (f"date-{offset}@example.invalid", "fictional", "candidate", "Hidden name", day + "T12:00:00Z"),
                )
        data = report(app, client)
        assert data["summary"]["journal_requests"] == 5
        assert data["summary"]["new_candidates"] == 2
        assert len(data["by_article"]) == 2
        one_day = report(app, client, days=1)
        assert one_day["summary"]["journal_requests"] == 3
        assert one_day["summary"]["new_candidates"] == 1
