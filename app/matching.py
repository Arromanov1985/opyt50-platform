"""Explainable matching: no age-based scoring or filtering."""

from __future__ import annotations

import re
from collections.abc import Mapping


def words(value: str) -> set[str]:
    return {word for word in re.findall(r"[\w-]+", value.casefold()) if len(word) > 2}


def skill_set(value: str) -> set[str]:
    return {part.strip().casefold() for part in value.split(",") if part.strip()}


def match_candidate(vacancy: Mapping, candidate: Mapping) -> dict | None:
    """Reject incompatible location/schedule/pay before computing an explainable score."""
    if not candidate["profession"] or not candidate["city"] or not candidate["is_active"]:
        return None
    vc = vacancy["city"].strip().casefold()
    cc = candidate["city"].strip().casefold()
    location_match = vc == cc or vc in ("удалённо", "любой город")
    if not location_match:
        return None
    if int(vacancy["salary_max"]) < int(candidate["salary_min"]):
        return None
    for field, any_value in (("schedule", "Любой"), ("employment", "Любая")):
        if vacancy[field] != any_value and candidate[field] != any_value and vacancy[field] != candidate[field]:
            return None
    requested = skill_set(vacancy["skills"])
    present = skill_set(candidate["skills"])
    common = requested & present
    if requested and not common:
        return None
    job_words = words(vacancy["title"])
    profession_words = words(candidate["profession"])
    title_overlap = len(job_words & profession_words) / max(1, len(job_words))
    skills_ratio = len(common) / len(requested) if requested else 1.0
    score = round(min(100, 35 + 40 * skills_ratio + 20 * title_overlap + 5 * int(location_match)))
    notes = ["Подходит город/формат", "Подходят зарплатные ожидания"]
    if common:
        notes.append("Совпадают навыки: " + ", ".join(sorted(common)[:4]))
    if title_overlap:
        notes.append("Есть опыт по специальности")
    return {"score": score, "reasons": notes}


def lead_price(title: str) -> int:
    """Demo price by vacancy category; never uses age or applicant details."""
    senior = ("директор", "руководител", "начальник", "управляющ", "главный инженер")
    specialist = ("инженер", "бухгалтер", "менеджер", "технолог", "аналитик", "логист")
    normalized = title.casefold()
    if any(w in normalized for w in senior):
        return 7900
    if any(w in normalized for w in specialist):
        return 2990
    return 1490
