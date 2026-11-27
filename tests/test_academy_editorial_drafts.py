"""Validate an editorial course source with the same import path as the studio.

This draft stays in docs; importing and publication require explicit author actions.
"""
from pathlib import Path

from app.academy_builder import AssistantImport, assistant_draft, readiness

ROOT = Path(__file__).resolve().parents[1]


def test_spreadsheets_course_is_ready_for_manual_import():
    source = (ROOT / "docs/academy-drafts/spreadsheets-basics.json").read_text(encoding="utf-8")
    result = assistant_draft(AssistantImport(expected_version=1, kind="course", source=source))
    draft = result["draft"]
    assert draft["title"] == "Электронные таблицы с нуля"
    assert not result["issues"] and not readiness(draft)
    assert len(draft["lessons"]) == 6
    assert sum(lesson["minutes"] for lesson in draft["lessons"]) == 95
    assert sum(len(lesson["questions"]) for lesson in draft["lessons"]) == 12
    assert len({lesson["slug"] for lesson in draft["lessons"]}) == 6
    assert all("media" not in lesson for lesson in draft["lessons"])
    assert all("owner_id" not in lesson for lesson in draft["lessons"])
