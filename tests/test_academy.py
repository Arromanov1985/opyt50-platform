"""Free courses and deterministic read-only release verification."""
import hashlib
import re

from fastapi.testclient import TestClient

from app.academy import academy_pages
from app.academy_content import COURSES
from app.main import create_app


def test_course_catalog_has_original_complete_self_checks():
    assert len(COURSES) >= 1
    for course in COURSES:
        assert course["revision"] >= 1
        assert len(course["lessons"]) >= 6
        assert len({lesson["slug"] for lesson in course["lessons"]}) == len(course["lessons"])
        for lesson in course["lessons"]:
            assert re.fullmatch(r"[a-z0-9-]+", lesson["slug"])
            assert lesson["minutes"] > 0
            assert len(lesson["sections"]) >= 2
            assert sum(len(p) for section in lesson["sections"] for p in section[1:]) > 400
            assert lesson["example"] and lesson["practice"] and len(lesson["questions"]) == 2
            for question in lesson["questions"]:
                assert len(question["options"]) == 3
                assert 0 <= question["correct"] < len(question["options"])
                assert question["feedback"]


def test_academy_is_free_public_and_includes_release_manifest(tmp_path):
    app = create_app(str(tmp_path / "academy.sqlite"))
    with TestClient(app, base_url="https://stazhno.ru") as visitor:
        pages = academy_pages()
        assert len(pages) == 8
        manifest = visitor.get("/api/public/journal/manifest").json()["pages"]
        sitemap = visitor.get("/sitemap.xml").text
        for path, expected in pages.items():
            result = visitor.get(path)
            assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
            assert result.headers["x-robots-tag"] == "noindex, nofollow"
            assert result.content == expected.body
            assert manifest[path] == hashlib.sha256(result.content).hexdigest()
            assert "https://stazhno.ru" + path in sitemap
        catalog = visitor.get("/academy").text
        assert 'id="ac-learning"' in catalog and "Моё обучение" in catalog
        for name in ("all", "active", "complete"):
            assert f'data-ac-filter="{name}"' in catalog
        assert catalog.count('class="ac-course-card"') == len(COURSES)
        assert 'data-ac-category="digital"' in catalog
        assert 'data-ac-level="beginner"' in catalog
        assert 'id="ac-course-search"' in catalog
        assert 'id="ac-category"' in catalog and 'id="ac-level"' in catalog
        assert 'href="/academy/ai-basics"' in catalog
        assert visitor.get("/academy/unknown").status_code == 404
        assert visitor.get("/academy/ai-basics/unknown").status_code == 404
        assert visitor.post("/academy/ai-basics/what-ai-does", json={}).status_code == 405
        assert 'href="/academy"' in visitor.get("/journal").text
        assert 'href="/academy"' in visitor.get("/journal/guide/learning").text
        lesson = visitor.get("/academy/ai-basics/what-ai-does").text
        assert "Пример запроса" in lesson and "Попробуйте сами" in lesson
        assert lesson.count('data-ac-correct="true"') == 2
        assert "не является сертификатом" in lesson
        assert "не передаётся на сервер" in lesson


def test_editor_checklist_targets_and_legacy_readiness_match():
    from app.academy_builder import CourseDraft, readiness, readiness_details
    draft = CourseDraft(lessons=[{"slug": "lesson-one"}]).model_dump()
    details = readiness_details(draft)
    assert readiness(draft) == [item["message"] for item in details]
    assert details[0]["field"] == "studio-title"
    assert any(item["lesson"] == 0 and item["lesson_step"] == "practice"
               and item["field"] == "studio-lessons-0-example" for item in details)
    assert any(item["lesson_step"] == "quiz" and item["field"] == "add-question" for item in details)
    ready = {key: COURSES[0][key] for key in ("title","description","audience","outcomes","lessons")}
    assert readiness_details(ready) == []


def test_program_is_visible_only_with_all_approved_revisions(tmp_path, monkeypatch):
    from copy import deepcopy
    import json
    from app import academy_programs
    from app.db import database

    first = deepcopy(COURSES[0])
    second = deepcopy(first)
    second.update(slug="course-test-program", revision=4, title="Учебный второй курс")
    definition = {"slug":"digital-work", "title":"Цифровые навыки для работы",
                  "description":"Последовательная учебная программа.", "goal":"Научиться применять цифровые инструменты.",
                  "steps":((first["slug"],first["revision"]),(second["slug"],second["revision"]))}
    monkeypatch.setattr(academy_programs, "PROGRAMS", (definition,))
    path = "/academy/programs/digital-work"
    assert academy_programs.visible_programs([first]) == []
    assert path not in academy_pages([first])
    assert path in academy_pages([first,second])
    assert academy_programs.visible_programs([first,{**second,"revision":5}]) == []
    app = create_app(str(tmp_path / "academy-program.sqlite"))
    with TestClient(app, base_url="https://stazhno.ru") as visitor:
        assert visitor.get(path).status_code == 404
        assert path not in visitor.get("/academy").text
        # Use only isolated fixture data; the live site is not modified.
        draft = {key:second[key] for key in ("title","description","audience","outcomes","lessons")}
        stamp = "2026-01-01T00:00:00+00:00"
        with database(app.state.db_path) as db:
            db.execute("""INSERT INTO academy_courses(slug,draft_json,published_json,state,version,created_at,updated_at,published_at)
                          VALUES(?,?,?,'published',4,?,?,?)""",
                       (second["slug"],json.dumps(draft),json.dumps(second),stamp,stamp,stamp))
        page = visitor.get(path)
        assert page.status_code == 200 and page.headers["cache-control"] == "no-store"
        assert page.headers["x-robots-tag"] == "noindex, nofollow"
        assert page.text.index(first["title"]) < page.text.index(second["title"])
        assert page.text.count('class="ac-lesson-row ac-program-step"') == 2
        assert path in visitor.get("/academy").text
        assert path in visitor.get("/academy/" + first["slug"]).text
        assert path in visitor.get("/academy/" + first["slug"] + "/" + first["lessons"][0]["slug"]).text
        manifest = visitor.get("/api/public/journal/manifest").json()
        assert manifest["academy_programs"] == {"digital-work":[first["slug"],second["slug"]]}
        assert manifest["pages"][path] == hashlib.sha256(page.content).hexdigest()
        assert "https://stazhno.ru" + path in visitor.get("/sitemap.xml").text
        # An unpublished draft edit must not change the pinned publication.
        with database(app.state.db_path) as db:
            db.execute("UPDATE academy_courses SET state='draft',version=5 WHERE slug=?", (second["slug"],))
        assert visitor.get(path).status_code == 200
        with database(app.state.db_path) as db:
            db.execute("UPDATE academy_courses SET published_json=? WHERE slug=?",
                       (json.dumps({**second,"revision":6}),second["slug"]))
        assert visitor.get(path).status_code == 404
        assert path not in visitor.get("/academy").text
        assert path not in visitor.get("/api/public/journal/manifest").json()["pages"]
        with database(app.state.db_path) as db:
            db.execute("UPDATE academy_courses SET published_json=NULL,state='hidden' WHERE slug=?", (second["slug"],))
        assert visitor.get(path).status_code == 404
        assert path not in visitor.get("/sitemap.xml").text


def test_program_registry_rejects_duplicate_courses_and_invalid_revisions(monkeypatch):
    import pytest
    from app import academy_programs
    for steps in ((("ai-basics",1),("ai-basics",1)),
                  (("ai-basics",1),("course-test",0))):
        monkeypatch.setattr(academy_programs,"PROGRAMS",({"slug":"test-program","steps":steps},))
        with pytest.raises(ValueError):
            list(academy_programs.configured_programs())
