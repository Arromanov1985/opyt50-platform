"""Explainable matching: transparent factors, no age-based scoring or filtering."""

from __future__ import annotations

import re
from collections.abc import Mapping


MATCH_WEIGHTS = {
    "profession": 30,
    "skills": 25,
    "salary": 20,
    "schedule": 10,
    "employment": 8,
    "location": 7,
}

# Small, explicit taxonomy. Every relationship here is reviewable and
# deterministic; there is no embedding/model inference behind the score.
PROFESSION_FAMILIES = {
    "regional_sales": {
        "label": "региональные продажи",
        "aliases": {
            "региональный менеджер",
            "территориальный менеджер",
            "менеджер по развитию региона",
            "менеджер по развитию территории",
            "региональный представитель",
            "территориальный представитель",
        },
    },
    "b2b_sales": {
        "label": "B2B-продажи",
        "aliases": {
            "менеджер по b2b продажам",
            "менеджер b2b",
            "менеджер по корпоративным продажам",
            "менеджер по оптовым продажам",
            "менеджер по дилерским продажам",
        },
    },
    "recruiting": {
        "label": "подбор персонала",
        "aliases": {
            "рекрутер",
            "специалист по подбору персонала",
            "менеджер по подбору персонала",
            "специалист по рекрутингу",
        },
    },
    "procurement": {
        "label": "закупки и снабжение",
        "aliases": {
            "менеджер по закупкам",
            "специалист по закупкам",
            "специалист по снабжению",
            "менеджер по снабжению",
            "снабженец",
        },
    },
    "logistics": {
        "label": "логистика",
        "aliases": {
            "логист",
            "менеджер по логистике",
            "специалист по логистике",
        },
    },
}

GENERIC_PROFESSION_WORDS = {
    "менеджер",
    "специалист",
    "руководитель",
    "директор",
    "начальник",
    "сотрудник",
    "работник",
    "ведущий",
    "старший",
    "младший",
}

SKILL_ALIASES = {
    "1с": {"1с", "1c", "1с предприятие", "1c enterprise"},
    "excel": {"excel", "ms excel", "microsoft excel"},
    "crm": {"crm", "crm система", "crm-система"},
    "битрикс24": {"битрикс24", "bitrix24", "битрикс 24"},
    "amocrm": {"amocrm", "amo crm"},
    "переговоры": {"переговоры", "ведение переговоров", "деловые переговоры"},
    "холодные звонки": {"холодные звонки", "холодный обзвон", "cold calls"},
    "b2b продажи": {"b2b продажи", "продажи b2b", "b2b-продажи"},
    "складской учет": {"складской учет", "учет на складе", "складской учёт", "учёт на складе"},
}

# Candidate knowledge may satisfy a broader requested skill. Direction matters:
# Bitrix24 proves CRM experience, but generic "CRM" does not prove Bitrix24.
SKILL_IMPLIES = {
    "битрикс24": {"crm"},
    "amocrm": {"crm"},
}


def normalize_phrase(value: str) -> str:
    text = str(value or "").casefold().replace("ё", "е")
    text = re.sub(r"[^\w+#-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def words(value: str) -> set[str]:
    return {word for word in re.findall(r"[\w-]+", normalize_phrase(value)) if len(word) > 2}


def profession_family(value: str) -> tuple[str, str] | None:
    normalized = normalize_phrase(value)
    if not normalized:
        return None
    for key, group in PROFESSION_FAMILIES.items():
        aliases = {normalize_phrase(alias) for alias in group["aliases"]}
        # Allow a precise alias inside a longer title such as
        # "Региональный менеджер по продажам B2B".
        if any(normalized == alias or alias in normalized for alias in aliases):
            return key, str(group["label"])
    return None


def _canonical_skill(value: str) -> str:
    normalized = normalize_phrase(value)
    for canonical, aliases in SKILL_ALIASES.items():
        if normalized in {normalize_phrase(alias) for alias in aliases}:
            return canonical
    return normalized


def skill_set(value: str, *, expand_implied: bool = False) -> set[str]:
    parts = {
        _canonical_skill(part)
        for part in re.split(r"[,;\n]+", str(value or ""))
        if normalize_phrase(part)
    }
    if expand_implied:
        expanded = set(parts)
        for skill in parts:
            expanded.update(SKILL_IMPLIES.get(skill, set()))
        return expanded
    return parts


def _text(item: Mapping, key: str, default: str = "") -> str:
    value = item.get(key, default)
    return str(value if value is not None else default).strip()


def _int(item: Mapping, key: str, default: int = 0) -> int:
    try:
        return int(item.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def _round_score(value: float) -> int:
    """Round to 5-point steps to avoid false precision."""
    bounded = max(0.0, min(100.0, value))
    return int(((bounded + 2.5) // 5) * 5)


def _factor(
    key: str,
    fit: float,
    text: str,
    *,
    caution: str = "",
    blocker: str = "",
) -> dict:
    maximum = MATCH_WEIGHTS[key]
    fit = max(0.0, min(1.0, fit))
    points = round(maximum * fit, 1)
    if fit >= 0.9:
        state = "strong"
    elif fit >= 0.65:
        state = "good"
    else:
        state = "weak"
    return {
        "key": key,
        "label": {
            "profession": "Профессия",
            "skills": "Навыки",
            "salary": "Зарплата",
            "schedule": "График",
            "employment": "Занятость",
            "location": "Локация",
        }[key],
        "points": points,
        "max_points": maximum,
        "percent": round(fit * 100),
        "state": state,
        "text": text,
        "caution": caution,
        "blocker": blocker,
    }


def _profession_factor(vacancy: Mapping, candidate: Mapping) -> dict:
    title = _text(vacancy, "title")
    profession = _text(candidate, "profession")
    normalized_title = normalize_phrase(title)
    normalized_profession = normalize_phrase(profession)

    if normalized_title == normalized_profession:
        return _factor("profession", 1.0, "Профессия совпадает")

    vacancy_family = profession_family(title)
    candidate_family = profession_family(profession)
    if vacancy_family and candidate_family and vacancy_family[0] == candidate_family[0]:
        return _factor(
            "profession",
            0.95,
            "Эквивалентная профессия по словарю: " + vacancy_family[1],
        )

    job_words = words(title)
    profession_words = words(profession)
    meaningful_job = job_words - GENERIC_PROFESSION_WORDS
    meaningful_profession = profession_words - GENERIC_PROFESSION_WORDS
    common = meaningful_job & meaningful_profession

    if common:
        candidate_coverage = len(common) / max(1, len(meaningful_profession))
        vacancy_coverage = len(common) / max(1, len(meaningful_job))
        fit = min(1.0, 0.6 * candidate_coverage + 0.4 * vacancy_coverage)
        return _factor(
            "profession",
            fit,
            "Есть совпадение по специальности: " + ", ".join(sorted(common)[:3]),
            caution=(
                "Название вакансии шире вашей указанной профессии — проверьте обязанности"
                if fit < 0.9
                else ""
            ),
        )

    # A profile can still say only "Менеджер" or "Специалист". Keep such a
    # broad profile eligible for a title with the same generic role, but lower
    # the score and explicitly ask the person to clarify the specialization.
    shared_generic = job_words & profession_words & GENERIC_PROFESSION_WORDS
    if shared_generic and not meaningful_profession:
        role = sorted(shared_generic)[0]
        return _factor(
            "profession",
            0.55,
            "Совпадает общий тип роли: " + role,
            caution="Уточните специализацию в профиле — сейчас профессия указана слишком широко",
        )

    return _factor(
        "profession",
        0,
        "Профессия не совпадает",
        blocker="Другая профессия: " + (title or "не указана"),
    )

def _skills_factor(vacancy: Mapping, candidate: Mapping) -> dict:
    requested = skill_set(_text(vacancy, "skills"))
    present_direct = skill_set(_text(candidate, "skills"))
    present = skill_set(_text(candidate, "skills"), expand_implied=True)
    if not requested:
        return _factor("skills", 1.0, "Обязательные навыки отдельно не указаны")
    common = requested & present
    if not common:
        return _factor(
            "skills",
            0,
            "Нет совпадающих навыков",
            blocker="Не совпадают указанные навыки",
        )
    fit = len(common) / len(requested)
    names = ", ".join(sorted(common)[:4])
    caution_parts = []
    missing = sorted(requested - common)
    if missing:
        caution_parts.append("Не указаны в вашем профиле: " + ", ".join(missing[:3]))
    implied = sorted(common - present_direct)
    if implied:
        caution_parts.append(
            "Засчитано по связанному навыку: " + ", ".join(implied[:3])
        )
    return _factor(
        "skills",
        fit,
        "Совпадают навыки: " + names,
        caution=" · ".join(caution_parts),
    )

def _salary_factor(vacancy: Mapping, candidate: Mapping) -> dict:
    expected = _int(candidate, "salary_min")
    salary_min = _int(vacancy, "salary_min")
    salary_max = _int(vacancy, "salary_max")
    if expected <= 0:
        return _factor("salary", 1.0, "Минимальная зарплата в профиле не задана")
    if salary_max and salary_max < expected:
        return _factor(
            "salary",
            0,
            "Диапазон ниже ожиданий",
            blocker="Зарплата ниже ваших ожиданий",
        )
    # Some legacy/unit fixtures do not specify the lower bound. If the upper
    # bound covers the expectation, do not invent a penalty from a missing value.
    if salary_min <= 0:
        return _factor("salary", 1.0, "Подходят зарплатные ожидания")
    if expected <= salary_min:
        return _factor("salary", 1.0, "Подходят зарплатные ожидания")
    if salary_max <= salary_min:
        return _factor("salary", 0.7, "Ожидания укладываются в заявленный уровень")
    headroom = max(0.0, min(1.0, (salary_max - expected) / (salary_max - salary_min)))
    fit = 0.65 + 0.35 * headroom
    caution = "Ваш минимум ближе к верхней границе зарплаты — уточните итоговое предложение"
    return _factor(
        "salary",
        fit,
        "Ожидания входят в зарплатный диапазон",
        caution=caution if fit < 0.9 else "",
    )


def _option_factor(
    vacancy: Mapping,
    candidate: Mapping,
    *,
    key: str,
    any_value: str,
    label: str,
) -> dict:
    vacancy_value = _text(vacancy, key, any_value) or any_value
    candidate_value = _text(candidate, key, any_value) or any_value
    if vacancy_value != any_value and candidate_value != any_value and vacancy_value != candidate_value:
        return _factor(
            key,
            0,
            f"{label} не совпадает",
            blocker=f"Другой {label.casefold()}: {vacancy_value}",
        )
    if vacancy_value == candidate_value:
        return _factor(key, 1.0, f"{label} совпадает")
    # A wildcard is compatible, but slightly less informative than an exact match.
    return _factor(
        key,
        0.85,
        f"{label} совместим",
        caution=f"{label} указан как «{any_value}» у одной из сторон — уточните условия",
    )


def _location_factor(vacancy: Mapping, candidate: Mapping) -> dict:
    vacancy_city = _text(vacancy, "city")
    candidate_city = _text(candidate, "city")
    vc = vacancy_city.casefold()
    cc = candidate_city.casefold()
    if vc == cc:
        return _factor("location", 1.0, "Город совпадает")
    if vc in {"удалённо", "любой город"}:
        return _factor("location", 1.0, "Вакансия подходит независимо от города")
    return _factor(
        "location",
        0,
        "Другой город",
        blocker="Другой город: " + vacancy_city,
    )


def evaluate_candidate(vacancy: Mapping, candidate: Mapping | None) -> dict:
    """Return a transparent compatibility snapshot, including blockers.

    The function intentionally never reads age, date of birth, gender or any
    other protected/personal characteristic. Only job conditions and the
    professional profile are considered.
    """
    if not candidate:
        return {
            "eligible": False,
            "score": 0,
            "match_level": "Профиль ещё не заполнен",
            "reasons": [],
            "strengths": [],
            "cautions": [],
            "mismatch_reasons": [],
            "score_breakdown": [],
        }
    profession = _text(candidate, "profession")
    city = _text(candidate, "city")
    active = bool(candidate.get("is_active"))
    if not profession or not city or not active:
        return {
            "eligible": False,
            "score": 0,
            "match_level": "Профиль не участвует в подборе",
            "reasons": [],
            "strengths": [],
            "cautions": [],
            "mismatch_reasons": [],
            "score_breakdown": [],
        }

    factors = [
        _profession_factor(vacancy, candidate),
        _skills_factor(vacancy, candidate),
        _salary_factor(vacancy, candidate),
        _option_factor(vacancy, candidate, key="schedule", any_value="Любой", label="График"),
        _option_factor(vacancy, candidate, key="employment", any_value="Любая", label="Занятость"),
        _location_factor(vacancy, candidate),
    ]
    blockers = [factor["blocker"] for factor in factors if factor["blocker"]]
    raw_score = sum(float(factor["points"]) for factor in factors)
    score = _round_score(raw_score if not blockers else min(raw_score, 65))

    if score >= 90:
        level = "Очень сильное совпадение"
    elif score >= 80:
        level = "Сильное совпадение"
    elif score >= 70:
        level = "Хорошее совпадение"
    else:
        level = "Подходит по основным условиям"

    strengths = [
        factor["text"]
        for factor in factors
        if not factor["blocker"] and factor["percent"] >= 80
    ]
    cautions = [
        factor["caution"]
        for factor in factors
        if factor["caution"] and not factor["blocker"]
    ]
    return {
        "eligible": not blockers,
        "score": score,
        "match_level": level,
        # Backward-compatible field used by existing UI/tests.
        "reasons": strengths,
        "strengths": strengths,
        "cautions": cautions,
        "mismatch_reasons": blockers,
        "score_breakdown": factors,
    }


def match_candidate(vacancy: Mapping, candidate: Mapping) -> dict | None:
    """Strict personalized match with an explainable score."""
    result = evaluate_candidate(vacancy, candidate)
    if not result["eligible"]:
        return None
    return {
        "score": result["score"],
        "match_level": result["match_level"],
        "reasons": result["reasons"],
        "strengths": result["strengths"],
        "cautions": result["cautions"],
        "score_breakdown": result["score_breakdown"],
    }


def mismatch_reasons(vacancy: Mapping, candidate: Mapping) -> list[str]:
    """Explain why a vacancy is outside strict matching; never uses age."""
    return evaluate_candidate(vacancy, candidate)["mismatch_reasons"]


def lead_price(title: str) -> int:
    """Demo price by vacancy category; never uses age or applicant details."""
    senior = ("директор", "руководител", "начальник", "управляющ", "главный инженер")
    specialist = ("инженер", "бухгалтер", "менеджер", "технолог", "аналитик", "логист")
    normalized = title.casefold()
    if any(word in normalized for word in senior):
        return 7900
    if any(word in normalized for word in specialist):
        return 2990
    return 1490
