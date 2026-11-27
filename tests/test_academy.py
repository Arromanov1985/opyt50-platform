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
