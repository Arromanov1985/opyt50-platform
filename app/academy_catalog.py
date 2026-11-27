"""Fixed public Academy classifications; legacy snapshots remain valid."""
from typing import Literal

CourseCategory = Literal["digital", "career", "business", "mentoring", "professional", "uncategorized"]
CourseLevel = Literal["beginner", "intermediate", "advanced", "unspecified"]
CATALOG_FIELDS = ("category", "level")
CATEGORIES = {
    "digital": "Цифровые навыки",
    "career": "Карьера и поиск работы",
    "business": "Бизнес и управление",
    "mentoring": "Наставничество",
    "professional": "Профессиональные навыки",
    "uncategorized": "Без категории",
}
LEVELS = {
    "beginner": "Начальный",
    "intermediate": "Средний",
    "advanced": "Продвинутый",
    "unspecified": "Уровень не указан",
}
# Display-only classification for the original seeded course, without
# rewriting its stored content, publication version or learner progress.
LEGACY_CLASSIFICATION = {"ai-basics": {"category": "digital", "level": "beginner"}}


def catalog_classification(course: dict, slug: str | None = None) -> dict:
    legacy = LEGACY_CLASSIFICATION.get(slug or course.get("slug"), {})
    defaults = {"category": legacy.get("category", "uncategorized"),
                "level": legacy.get("level", "unspecified")}
    for key, options in (("category", CATEGORIES), ("level", LEVELS)):
        value = course.get(key)
        if isinstance(value, str) and value in options:
            defaults[key] = value
    return defaults
