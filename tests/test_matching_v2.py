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



def test_regional_and_territorial_sales_titles_match_by_reviewed_taxonomy():
    candidate = base_candidate(
        profession="Территориальный менеджер",
        city="Москва",
        skills="B2B продажи, переговоры, Microsoft Excel",
    )
    vacancy = base_vacancy(
        title="Региональный менеджер по продажам B2B",
        city="Москва",
        skills="продажи B2B, ведение переговоров, MS Excel",
    )
    result = match_candidate(vacancy, candidate)
    assert result is not None
    profession = next(f for f in result["score_breakdown"] if f["key"] == "profession")
    skills = next(f for f in result["score_breakdown"] if f["key"] == "skills")
    assert profession["percent"] == 95
    assert "региональные продажи" in profession["text"]
    assert skills["percent"] == 100


def test_generic_manager_word_does_not_create_cross_domain_match():
    candidate = base_candidate(
        profession="Менеджер по персоналу",
        city="Москва",
        skills="Excel, собеседования",
    )
    vacancy = base_vacancy(
        title="Менеджер по продажам",
        city="Москва",
        skills="Excel, продажи",
    )
    assert match_candidate(vacancy, candidate) is None
    reasons = mismatch_reasons(vacancy, candidate)
    assert any("Другая профессия" in reason for reason in reasons)


def test_skill_aliases_are_normalized_without_penalizing_candidate():
    candidate = base_candidate(skills="1C, Microsoft Excel")
    vacancy = base_vacancy(skills="1С, MS Excel")
    result = match_candidate(vacancy, candidate)
    assert result is not None
    skills = next(f for f in result["score_breakdown"] if f["key"] == "skills")
    assert skills["percent"] == 100
    assert "1с" in skills["text"]
    assert "excel" in skills["text"]


def test_specific_crm_product_satisfies_generic_crm_but_not_reverse():
    candidate_with_bitrix = base_candidate(skills="Битрикс24")
    generic_crm_vacancy = base_vacancy(skills="CRM")
    result = match_candidate(generic_crm_vacancy, candidate_with_bitrix)
    assert result is not None
    skills = next(f for f in result["score_breakdown"] if f["key"] == "skills")
    assert skills["percent"] == 100
    assert any("связанному навыку" in caution for caution in result["cautions"])

    candidate_with_generic_crm = base_candidate(skills="CRM")
    bitrix_vacancy = base_vacancy(skills="Bitrix24")
    assert match_candidate(bitrix_vacancy, candidate_with_generic_crm) is None


def test_regional_hr_title_is_not_misclassified_as_regional_sales():
    candidate = base_candidate(
        profession="Региональный менеджер по персоналу",
        city="Москва",
        skills="подбор персонала, Excel",
    )
    vacancy = base_vacancy(
        title="Региональный менеджер по продажам",
        city="Москва",
        skills="продажи, Excel",
    )
    assert match_candidate(vacancy, candidate) is None
