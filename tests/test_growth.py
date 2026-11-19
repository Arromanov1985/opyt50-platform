"""Release 0.5.36 — aggregate growth metrics and access boundaries."""
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import database
from app.main import active_user, create_app

HEADERS = {"X-Requested-With": "OPYT50"}
STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def send(client, source="journal", action="view"):
    return client.post(
        "/api/growth/event",
        headers=HEADERS,
        json={"source": source, "action": action},
    )


def test_anonymous_metrics_persist_as_daily_counters_without_personal_data(tmp_path):
    app = create_app(str(tmp_path / "growth.sqlite"))
    with TestClient(app) as client:
        assert client.get("/journal").status_code == 200  # GET never writes metrics
        assert send(client).status_code == 204
        assert send(client).status_code == 204
        assert send(client, "kak-proverit-vakansiyu", "jobs_click").status_code == 204
        assert send(client, "kak-proverit-vakansiyu", "profile_click").status_code == 204
        assert client.get("/api/growth/event").status_code == 405
        assert client.post("/api/growth/event",
                           json={"source": "journal", "action": "view"}).status_code == 403
        assert send(client, "someone@example.com", "view").status_code == 422
        assert send(client, "journal", "email").status_code == 422
        assert send(client, "journal" + "x" * 150, "view").status_code == 422

    with database(app.state.db_path) as db:
        columns = [row["name"] for row in db.execute(
            "PRAGMA table_info(growth_daily_counts)"
        ).fetchall()]
        assert columns == ["event_date", "source", "action", "total"]
        rows = db.execute(
            "SELECT source,action,total FROM growth_daily_counts ORDER BY source,action"
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            ("journal", "view", 2),
            ("kak-proverit-vakansiyu", "jobs_click", 1),
            ("kak-proverit-vakansiyu", "profile_click", 1),
        ]


def test_admin_only_aggregate_report_counts_signups_independently(tmp_path):
    app = create_app(str(tmp_path / "growth.sqlite"))
    now = datetime.now(timezone.utc).date().isoformat() + " 12:00:00"
    with TestClient(app) as client:
        assert send(client, "proektnaya-rabota-posle-50", "view").status_code == 204
        assert send(client, "proektnaya-rabota-posle-50", "jobs_click").status_code == 204
        assert send(client, "proektnaya-rabota-posle-50", "profile_click").status_code == 204
        with database(app.state.db_path) as db:
            db.execute(
                """INSERT INTO users(email,password_hash,role,name,created_at)
                   VALUES(?,?,?,?,?)""",
                ("private-candidate@example.invalid", "test-not-real", "candidate", "Hidden name", now),
            )
            db.execute(
                """INSERT INTO users(email,password_hash,role,name,created_at)
                   VALUES(?,?,?,?,?)""",
                ("private-company@example.invalid", "test-not-real", "employer", "Private owner", now),
            )

        assert client.get("/api/admin/growth").status_code == 401
        app.dependency_overrides[active_user] = lambda: {"role": "employer"}
        assert client.get("/api/admin/growth").status_code == 403
        app.dependency_overrides[active_user] = lambda: {"role": "admin"}
        result = client.get("/api/admin/growth?days=30")
        assert result.status_code == 200
        assert result.headers["cache-control"] == "no-store"
        data = result.json()
        assert data["summary"] == {
            "journal_requests": 1,
            "jobs_clicks": 1,
            "profile_clicks": 1,
            "new_candidates": 1,
            "new_employers": 1,
        }
        assert data["by_article"][0]["source"] == "proektnaya-rabota-posle-50"
        assert {x["role"] for x in data["registrations"]} == {"candidate", "employer"}
        assert "источник конкретной регистрации" in data["limitations"]
        assert client.get("/api/admin/growth?days=0").status_code == 422
        assert client.get("/api/admin/growth?days=91").status_code == 422
        assert client.get("/api/admin/growth?days=1&source=user@example.com").status_code == 200
        payload = result.text
        assert "private-candidate" not in payload
        assert "private-company" not in payload
        assert "Hidden name" not in payload
        assert "Private owner" not in payload
        app.dependency_overrides.clear()


def test_growth_frontend_is_first_party_and_fails_open(tmp_path):
    app = create_app(str(tmp_path / "growth.sqlite"))
    script = (STATIC / "journal.js").read_text(encoding="utf-8")
    assert "credentials: 'omit'" in script
    assert "referrerPolicy: 'no-referrer'" in script
    assert "keepalive: true" in script
    assert "JSON.stringify({source, action})" in script
    assert "document.cookie" not in script
    assert "localStorage.setItem('growth" not in script
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'growth-admin.css?v=1' in html
    assert 'app.js?v=legalterms1' in html
    with TestClient(app) as client:
        article = client.get("/journal/kak-proverit-vakansiyu")
        assert article.status_code == 200
        assert 'data-growth-action="profile_click"' in article.text
        assert 'data-growth-action="jobs_click"' in article.text
        assert '/static/journal.js?v=2' in article.text
        assert client.get("/static/growth-admin.css").status_code == 200
