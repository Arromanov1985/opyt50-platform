"""Editorial CMS: publication gates, admin isolation and no data loss."""
from pathlib import Path

from fastapi.testclient import TestClient
from app.db import database
from app.main import create_app
from app.security import make_password_hash
from app.journal_cms import init_journal

HEADERS = {"X-Requested-With":"OPYT50"}
PASSWORD = "Synthetic-admin-password-2026!"

BODY = """## С чего начать проверку условий
Начните с конкретного описания работы. Сверьте город, график и диапазон оплаты с собственными ожиданиями. Задайте вопросы о важных условиях до принятия решения.

## Как проверить результат
Запишите, что было согласовано, проверьте доступные сведения о работодателе и не передавайте коды подтверждения. Если условия изменились, спокойно запросите пояснения до отклика.
"""


def request(client, method, path, data=None, headers=HEADERS):
    return client.request(method, path, json=data, headers=headers)


def setup_admin(app, client):
    with database(app.state.db_path) as db:
        db.execute(
            "INSERT INTO users(email,name,role,password_hash) VALUES(?,?,?,?)",
            ("editor@cms.example.invalid", "Вымышленный редактор", "admin",
             make_password_hash(PASSWORD)),
        )
    response = request(client, "POST", "/api/login", {
        "email":"editor@cms.example.invalid", "password":PASSWORD,
    })
    assert response.status_code == 200, response.text


def draft(slug="proverka-chernovika"):
    return {
        "slug":slug, "title":"Как проверить полезность профессионального курса",
        "description":"Последовательная проверка программы обучения, практических заданий и ожидаемого результата.",
        "category":"Навыки", "read":"5 минут", "body_text":BODY,
    }


def test_cms_admin_auth_seed_and_assets(tmp_path: Path):
    app = create_app(str(tmp_path / "cms.db"))
    with TestClient(app) as public, TestClient(app) as editor:
        assert public.get("/admin/journal").status_code == 401
        assert public.get("/api/admin/journal").status_code == 401
        assert public.get("/api/admin/journal/audit").status_code == 401
        assert request(public, "POST", "/api/admin/journal", draft()).status_code == 401
        signup = request(public, "POST", "/api/register", {
            "email":"person@cms.example.invalid","name":"Тестовый пользователь",
            "password":"Synthetic password 2026!", "role":"candidate",
        })
        assert signup.status_code == 201, signup.text
        assert public.get("/admin/journal").status_code == 403
        assert public.get("/api/admin/journal").status_code == 403
        setup_admin(app, editor)
        panel = editor.get("/admin/journal")
        assert panel.status_code == 200
        assert panel.headers["cache-control"] == "no-store"
        assert 'id="article-form"' in panel.text
        assert 'href="/static/journal-admin.css?v=3"' in panel.text
        assert 'id="article-type"' in panel.text
        result = editor.get("/api/admin/journal")
        assert result.status_code == 200
        assert len(result.json()["articles"]) == 10
        assert {x["status"] for x in result.json()["articles"]} == {"published"}
        assert editor.get("/api/admin/journal/audit").json()["events"] == []


def test_draft_save_publish_hide_and_version_conflict(tmp_path: Path):
    app = create_app(str(tmp_path / "cms-state.db"))
    with TestClient(app) as public, TestClient(app) as editor:
        setup_admin(app, editor)
        base = "proverka-chernovika"
        payload = draft(base)
        assert request(editor, "POST", "/api/admin/journal", payload, headers={}).status_code == 403
        created = request(editor, "POST", "/api/admin/journal", payload)
        assert created.status_code == 201, created.text
        assert created.json()["version"] == 1
        assert request(editor, "POST", "/api/admin/journal", payload).status_code == 409
        assert public.get("/journal/" + base).status_code == 404
        assert base not in public.get("/sitemap.xml").text
        assert base not in str(public.get("/api/public/journal/highlights").json())

        details = editor.get("/api/admin/journal/" + base).json()["article"]
        assert details["status"] == "draft"
        assert "С чего начать" in details["body_text"]

        changed = {**payload, "version":1,"title":"Как сравнить два профессиональных курса обучения"}
        saved = request(editor, "PUT", "/api/admin/journal/" + base, changed)
        assert saved.status_code == 200, saved.text
        assert saved.json()["version"] == 2
        assert request(editor, "PUT", "/api/admin/journal/" + base, changed).status_code == 409
        assert request(editor, "POST", "/api/admin/journal/" + base + "/publish",
                       {"version":1}).status_code == 409

        published = request(editor, "POST", "/api/admin/journal/" + base + "/publish",
                            {"version":2})
        assert published.status_code == 200, published.text
        live = public.get("/journal/" + base)
        assert live.status_code == 200
        assert "Как сравнить два профессиональных курса" in live.text
        assert base in public.get("/sitemap.xml").text

        edit = {**changed, "version":3,"title":"Черновик правки уже опубликованной статьи"}
        assert request(editor, "PUT", "/api/admin/journal/" + base, edit).status_code == 200
        assert "Как сравнить" in public.get("/journal/" + base).text
        assert "Черновик правки" not in public.get("/journal/" + base).text
        hidden = request(editor, "POST", "/api/admin/journal/" + base + "/hide",
                         {"version":4})
        assert hidden.status_code == 200, hidden.text
        assert public.get("/journal/" + base).status_code == 404
        assert base not in public.get("/sitemap.xml").text

        assert request(editor, "POST", "/api/admin/journal/" + base + "/archive",
                       {"version":5}).status_code == 409
        assert request(editor, "POST", "/api/admin/journal/" + base + "/publish",
                       {"version":5}).status_code == 200
        assert "Черновик правки" in public.get("/journal/" + base).text
        events = editor.get("/api/admin/journal/audit").json()["events"]
        assert {row["action"] for row in events} >= {"create","save","publish","hide"}
        assert "body_text" not in str(events)


def test_archiving_and_reseed_do_not_restore_deleted_or_hidden_content(tmp_path: Path):
    path = str(tmp_path / "cms-seed.db")
    app = create_app(path)
    with TestClient(app) as public, TestClient(app) as editor:
        setup_admin(app, editor)
        original = "kak-proverit-vakansiyu"
        rows = editor.get("/api/admin/journal").json()["articles"]
        original_version = next(a["version"] for a in rows if a["slug"] == original)
        assert request(editor,"POST","/api/admin/journal/" + original + "/hide",
                       {"version":original_version}).status_code == 200
        new = request(editor, "POST", "/api/admin/journal", draft("otdelnyy-chernovik"))
        assert new.status_code == 201
        archive = request(editor, "POST", "/api/admin/journal/otdelnyy-chernovik/archive",
                          {"version":1})
        assert archive.status_code == 200
        assert public.get("/journal/otdelnyy-chernovik").status_code == 404

        init_journal(path)  # simulate a second deployment/startup
        assert public.get("/journal/" + original).status_code == 404
        assert request(editor, "POST", "/api/admin/journal/otdelnyy-chernovik/publish",
                       {"version":2}).status_code == 409
        with database(path) as db:
            assert db.execute("SELECT COUNT(*) FROM journal_entries").fetchone()[0] == 11


def test_plain_text_validation_and_escaped_public_render(tmp_path: Path):
    app = create_app(str(tmp_path / "cms-escape.db"))
    with TestClient(app) as public, TestClient(app) as editor:
        setup_admin(app, editor)
        invalid = {**draft(), "body_text":"Один абзац без заголовка"*12}
        assert request(editor,"POST","/api/admin/journal",invalid).status_code == 422
        for reserved in ("journal", "paths"):
            assert request(editor, "POST", "/api/admin/journal", draft(reserved)).status_code == 422
        html = {**draft("tekst-bez-html"),
                "body_text": BODY.replace("условиях", "<img src=x onerror=alert(1)> условиях")}
        assert request(editor, "POST", "/api/admin/journal", html).status_code == 201
        assert request(editor, "POST", "/api/admin/journal/tekst-bez-html/publish",
                       {"version":1}).status_code == 200
        public_page = public.get("/journal/tekst-bez-html")
        assert public_page.status_code == 200
        assert "<img src=x" not in public_page.text
        assert "&lt;img src=x" in public_page.text
        assert "editor@cms.example.invalid" not in public_page.text
        assert public.get("/api/public/journal/highlights").status_code == 200


def test_editorial_navigator_news_learning_events_use_only_published_versions(tmp_path):
    import hashlib

    app = create_app(str(tmp_path / "editorial-guide.db"))
    with TestClient(app) as public, TestClient(app) as editor:
        setup_admin(app, editor)
        guide = "/journal/guide/"
        overview = public.get(guide + "overview")
        assert overview.status_code == 200
        assert "Подтверждённых анонсов пока нет" in overview.text
        assert "Цифровые навыки для работы" in public.get(guide + "learning").text
        assert public.get(guide + "unknown").status_code == 404
        assert public.post(guide + "news").status_code == 405
        assert "noindex" in overview.headers["x-robots-tag"]
        assert public.get(guide + "events").headers["cache-control"] == "no-store"
        news = {**draft("test-editorial-news"), "content_type": "news",
                "title": "Вымышленная новость для изолированного теста"}
        assert request(editor, "POST", "/api/admin/journal", news).status_code == 422
        news.update(source_name="Тестовый первоисточник", source_url="javascript:alert(1)")
        assert request(editor, "POST", "/api/admin/journal", news).status_code == 422
        news["source_url"] = "https://name:password@example.invalid/news"
        assert request(editor, "POST", "/api/admin/journal", news).status_code == 422
        news["source_url"] = "https://example.invalid/news"
        assert request(editor, "POST", "/api/admin/journal", news).status_code == 201
        assert news["title"] not in public.get(guide + "news").text
        assert request(editor, "POST", "/api/admin/journal/test-editorial-news/publish",
                       {"version": 1}).status_code == 200
        assert news["title"] in public.get(guide + "news").text
        article = public.get("/journal/test-editorial-news")
        assert 'href="https://example.invalid/news"' in article.text
        assert 'rel="noopener noreferrer"' in article.text
        assert "Тестовый первоисточник" in article.text
        assert request(editor, "PUT", "/api/admin/journal/test-editorial-news",
                       {**news, "version": 2, "title": "Черновик новой редакции новости"}).status_code == 200
        assert "Черновик новой редакции новости" not in public.get(guide + "news").text

        event = {**draft("test-editorial-event"), "content_type": "event",
                 "title": "Тестовый учебный вебинар", "source_name": "Вымышленный организатор"}
        assert request(editor, "POST", "/api/admin/journal", event).status_code == 422
        event.update(event_date="2027-02-30", event_format="online")
        assert request(editor, "POST", "/api/admin/journal", event).status_code == 422
        event["event_date"] = "2027-02-15"
        assert request(editor, "POST", "/api/admin/journal", event).status_code == 201
        assert event["title"] not in public.get(guide + "events").text
        assert request(editor, "POST", "/api/admin/journal/test-editorial-event/publish",
                       {"version": 1}).status_code == 200
        events = public.get(guide + "events").text
        assert event["title"] in events and "15.02.2027" in events and "Онлайн" in events
        assert "Вымышленный организатор" in events
        assert event["title"] not in public.get(guide + "news").text
        detail = editor.get("/api/admin/journal/test-editorial-event").json()["article"]
        assert detail["content_type"] == "event" and detail["event_date"] == "2027-02-15"
        assert detail["event_format"] == "online"

        learning = {**draft("test-editorial-lesson"), "content_type": "learning",
                    "title": "Тестовый материал по обучению"}
        assert request(editor, "POST", "/api/admin/journal", learning).status_code == 201
        assert request(editor, "POST", "/api/admin/journal/test-editorial-lesson/publish",
                       {"version": 1}).status_code == 200
        assert learning["title"] in public.get(guide + "learning").text
        assert learning["title"] not in public.get(guide + "events").text
        assert request(editor, "POST", "/api/admin/journal/test-editorial-event/hide",
                       {"version": 2}).status_code == 200
        assert event["title"] not in public.get(guide + "events").text
        assert "Подтверждённых анонсов пока нет" in public.get(guide + "events").text
        manifest = public.get("/api/public/journal/manifest").json()["pages"]
        sitemap = public.get("/sitemap.xml").text
        for section in ("overview", "news", "learning", "events"):
            path = guide + section
            assert manifest[path] == hashlib.sha256(public.get(path).content).hexdigest()
            assert "https://stazhno.ru" + path in sitemap
        assert "test-editorial-event" not in sitemap
        assert "editor@cms.example.invalid" not in public.get(guide + "overview").text


def test_personal_guide_uses_explicit_editorial_topics_and_published_catalog(tmp_path):
    import hashlib
    app = create_app(str(tmp_path / "personal-guide.db"))
    with TestClient(app) as public, TestClient(app) as editor:
        setup_admin(app, editor)
        path = "/journal/guide/personal"
        original = public.get(path)
        assert original.status_code == 200 and original.headers["cache-control"] == "no-store"
        assert 'data-jr-topic value="technology"' in original.text
        assert 'data-jr-material="cifrovye-navyki-dlya-raboty"' in original.text
        assert 'data-jr-kind="learning"' in original.text
        assert 'data-jr-save="cifrovye-navyki-dlya-raboty"' in original.text
        assert "не синхронизируются между устройствами" in original.text
        seed = editor.get("/api/admin/journal/cifrovye-navyki-dlya-raboty").json()["article"]
        assert seed["topics"] == ["technology", "education"]
        payload = {**draft("test-topic-learning"), "content_type": "learning",
                   "title": "Тестовое обучение работе с клиентами",
                   "topics": ["sales", "technology", "sales"]}
        assert request(editor, "POST", "/api/admin/journal", {**payload, "topics": ["unknown"]}).status_code == 422
        assert request(editor, "POST", "/api/admin/journal", payload).status_code == 201
        assert payload["title"] not in public.get(path).text
        assert request(editor, "POST", "/api/admin/journal/test-topic-learning/publish",
                       {"version": 1}).status_code == 200
        details = editor.get("/api/admin/journal/test-topic-learning").json()["article"]
        assert details["topics"] == ["sales", "technology"]
        live = public.get(path)
        assert payload["title"] in live.text
        assert 'data-jr-material="test-topic-learning" data-jr-kind="learning" data-jr-topics="sales technology"' in live.text
        assert 'data-jr-save="test-topic-learning"' in public.get("/journal/test-topic-learning").text
        updated = {**payload, "version": 2, "topics": ["finance"], "title": "Неопубликованный текст"}
        assert request(editor, "PUT", "/api/admin/journal/test-topic-learning", updated).status_code == 200
        assert updated["title"] not in public.get(path).text
        assert 'data-jr-topics="sales technology"' in public.get(path).text
        assert request(editor, "POST", "/api/admin/journal/test-topic-learning/hide",
                       {"version": 3}).status_code == 200
        hidden = public.get(path)
        assert 'data-jr-material="test-topic-learning"' not in hidden.text
        assert public.get("/journal/test-topic-learning").status_code == 404
        manifest = public.get("/api/public/journal/manifest").json()["pages"]
        assert manifest[path] == hashlib.sha256(hidden.content).hexdigest()
        assert "https://stazhno.ru" + path in public.get("/sitemap.xml").text

