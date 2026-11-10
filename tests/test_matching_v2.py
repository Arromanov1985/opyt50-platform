"""Tests for transparent weighted matching introduced in release 0.12."""

from app.matching import evaluate_candidate, match_candidate, mismatch_reasons


def base_candidate(**patch):
    candidate = {
        "profession": "Кладовщик",
        "city": "Подольск",
        "salary_min": 70000,
        "schedule": "Сменный",
        "employment": "Полная",
        "skills": "склад, 1С, Excel",
        "is_active": 1,
    }
    candidate.update(patch)
    return candidate


def base_vacancy(**patch):
    vacancy = {
        "title": "Кладовщик",
        "city": "Подольск",
        "salary_min": 75000,
        "salary_max": 95000,
        "schedule": "Сменный",
        "employment": "Полная",
        "skills": "склад, 1С",
    }
    vacancy.update(patch)
    return vacancy


def test_perfect_match_is_100_and_has_six_transparent_factors():
    result = match_candidate(base_vacancy(), base_candidate())
    assert result is not None
    assert result["score"] == 100
    assert result["match_level"] == "Очень сильное совпадение"
    assert len(result["score_breakdown"]) == 6
    assert sum(f["max_points"] for f in result["score_breakdown"]) == 100
    assert result["cautions"] == []
    assert all(f["percent"] == 100 for f in result["score_breakdown"])


def test_partial_match_gets_lower_score_and_actionable_cautions():
    candidate = base_candidate(
        profession="Менеджер",
        city="Москва",
        salary_min=95000,
        schedule="Полный день",
        skills="Excel, продажи",
    )
    vacancy = base_vacancy(
        title="Региональный менеджер",
        city="Москва",
        salary_min=80000,
        salary_max=100000,
        schedule="Полный день",
        skills="продажи, CRM, переговоры, Excel",
    )
    result = match_candidate(vacancy, candidate)
    assert result is not None
    assert 65 <= result["score"] < 100
    assert result["score"] % 5 == 0
    assert result["cautions"]
    assert any("верхней границе" in caution for caution in result["cautions"])
    assert any("Не указаны" in caution for caution in result["cautions"])


def test_hard_mismatch_stays_out_of_strict_matching_but_is_explained():
    candidate = base_candidate(salary_min=120000)
    vacancy = base_vacancy(salary_max=95000)
    assert match_candidate(vacancy, candidate) is None
    reasons = mismatch_reasons(vacancy, candidate)
    assert "Зарплата ниже ваших ожиданий" in reasons
    snapshot = evaluate_candidate(vacancy, candidate)
    assert snapshot["eligible"] is False
    assert snapshot["score"] <= 65
    assert any(f["key"] == "salary" and f["blocker"] for f in snapshot["score_breakdown"])


def test_matching_score_never_reads_age_or_other_personal_characteristics():
    vacancy = base_vacancy()
    younger = base_candidate(age=25, gender="female")
    older = base_candidate(age=67, gender="male")
    assert match_candidate(vacancy, younger) == match_candidate(vacancy, older)


def test_profession_relevance_remains_a_hard_requirement():
    candidate = base_candidate(
        profession="Бухгалтер",
        skills="1С, Excel, бухгалтерия",
        city="Москва",
    )
    vacancy = base_vacancy(
        title="Инженер по эксплуатации",
        skills="Excel, диагностика",
        city="Москва",
    )
    assert match_candidate(vacancy, candidate) is None
    assert any("Другая профессия" in item for item in mismatch_reasons(vacancy, candidate))
