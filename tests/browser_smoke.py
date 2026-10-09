"""Real-browser smoke test for release 0.2 using fictional data. No external services."""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect


ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8765"


def login(page, email):
    page.locator("#login-open").click()
    expect(page.locator("#auth-dialog")).to_be_visible()
    page.locator("#auth-email").fill(email)
    page.locator("#auth-password").fill("DemoPass2026!")
    with page.expect_response(lambda response: (
        response.url.endswith("/api/login") and response.request.method == "POST"
    ), timeout=20000) as login_reply:
        page.locator("#auth-submit").click()
    assert login_reply.value.status == 200, (
        f"Login rejected for fictional account {email}: "
        f"HTTP {login_reply.value.status} {login_reply.value.text()}"
    )
    expect(page.locator("#auth-dialog")).not_to_be_visible(timeout=15000)
    expect(page.locator("#dashboard")).to_be_visible(timeout=15000)


def run_browser(page):
    console_errors = []
    page.on("pageerror", lambda error: console_errors.append(str(error)))
    page.goto(URL, wait_until="networkidle")
    expect(page.locator(".release-ribbon")).to_contain_text("0.3.0-dev")
    # Search first; registration is not required to inspect a vacancy.
    page.get_by_role("link", name="Посмотреть вакансии").first.click()
    assert page.evaluate("location.hash") == "#jobs"
    expect(page.locator("#guest-actions")).to_be_visible()

    mode = page.locator("#reading-mode-toggle")
    expect(mode).to_have_attribute("aria-pressed", "false")
    mode.click()
    expect(mode).to_have_attribute("aria-pressed", "true")
    # The horizontal menu must remain readable in large-text mode without
    # wrapping «О сервисе» into two lines, as happened in manual testing.
    assert page.evaluate("""() => {
      const links = [...document.querySelectorAll('.nav-links a')];
      return links.every(el => el.getBoundingClientRect().height
        <= parseFloat(getComputedStyle(el).lineHeight) + 2);
    }"""), "Desktop navigation link wrapped in large text mode"
    assert page.evaluate("""() => {
      const nav = document.querySelector('.nav-inner');
      return nav.scrollWidth <= nav.clientWidth + 2;
    }"""), "Desktop navigation overflows its container"
    page.reload(wait_until="networkidle")
    expect(page.locator("#reading-mode-toggle")).to_have_attribute("aria-pressed", "true")
    page.locator("#reading-mode-toggle").click()
    expect(page.locator("#reading-mode-toggle")).to_have_attribute("aria-pressed", "false")
    # At intermediate widths the full menu moves to a readable second row.
    page.set_viewport_size({"width": 1060, "height": 760})
    expect(page.locator(".mobile-quick-nav")).to_be_visible()
    expect(page.locator(".nav-links")).not_to_be_visible()
    page.set_viewport_size({"width": 1280, "height": 720})

    page.locator("#register-open").click()
    expect(page.locator("#auth-name")).to_be_focused()
    expect(page.locator("#auth-guidance")).to_contain_text("вымышленные данные")
    page.locator("#modal-close").click()
    expect(page.locator("#profession-filter")).to_be_visible()
    expect(page.locator("#schedule-filter")).to_be_visible()

    page.locator("#profession-filter").fill("Кладовщик")
    page.locator("#city-filter").fill("Подольск")
    page.locator("#salary-filter").fill("70000")
    page.locator("#schedule-filter").select_option(label="Сменный")
    page.locator("#jobs-filter").click()
    expect(page.locator("#public-jobs .job-card")).to_have_count(1)
    expect(page.locator("#jobs-count")).to_contain_text("Найдено: 1")
    expect(page.locator("#public-jobs .job-card")).to_contain_text("Кладовщик")

    page.locator("#public-jobs [data-v02-action='details']").click()
    expect(page.locator("#job-dialog")).to_be_visible()
    expect(page.locator("#job-dialog-content")).to_contain_text("Складской учёт")
    page.locator("#job-dialog-close").click()
    expect(page.locator("#job-dialog")).not_to_be_visible()

    login(page, "kladovshik@demo.example")
    expect(page.locator("#profile-form")).to_be_visible()
    expect(page.locator("#profile-profession")).to_have_value("Кладовщик")
    expect(page.locator(".profile-optional")).not_to_have_attribute("open", "")
    expect(page.locator("#profile-phone")).not_to_be_visible()
    # The guide is reachable directly from the main profile fields:
    # one click opens both optional sections and focuses the first question.
    page.locator("#experience-start").click()
    expect(page.locator(".profile-optional")).to_have_attribute("open", "")
    expect(page.locator("#experience-helper")).to_have_attribute("open", "")
    expect(page.locator("#experience-start")).to_have_attribute("aria-expanded", "true")
    expect(page.locator("#experience-work")).to_be_focused()
    expect(page.locator("#profile-phone")).to_be_visible()
    expect(page.locator("#experience-build")).to_be_visible()
    page.locator("#experience-build").click()
    expect(page.locator("#experience-helper-message")).to_contain_text("хотя бы один ответ")
    page.locator("#experience-work").fill("example@demo.example")
    page.locator("#experience-build").click()
    expect(page.locator("#experience-helper-message")).to_contain_text("телефон или email")
    expect(page.locator("#experience-insert")).to_be_disabled()
    page.locator("#experience-work").fill("Складской учёт")
    page.locator("#experience-tasks").fill("Приёмка поставок и инвентаризация")
    page.locator("#experience-strengths").fill("1С и ведение документов")
    page.locator("#profile-about").fill("Ранее записанный опыт.")
    page.locator("#experience-build").click()
    expect(page.locator("#experience-preview")).to_contain_text("Складской учёт")
    expect(page.locator("#profile-about")).to_have_value("Ранее записанный опыт.")
    page.locator("#experience-insert").click()
    assert page.locator("#profile-about").input_value().startswith("Ранее записанный опыт.\n\nНаправление работы:")
    assert "1С и ведение документов" in page.locator("#profile-about").input_value()
    expect(page.locator("#experience-insert")).to_be_disabled()
    expect(page.locator("#experience-helper-message")).to_contain_text("Для сохранения профиля")
    with page.expect_response(lambda response: (
        response.url.endswith("/api/candidate/profile") and response.request.method == "PUT"
    )) as save_profile:
        page.locator("#profile-form button[type='submit']").click()
    assert save_profile.value.status == 200, save_profile.value.text()
    expect(page.locator("#toast")).to_contain_text("Профиль сохранён")
    # Check the toast before reload; otherwise it disappears correctly.
    toast = page.locator("#toast").bounding_box()
    assert toast and toast["x"] >= 0 and toast["x"] + toast["width"] <= 1281
    saved_profile = page.request.get(URL + "/api/me").json()["user"]["profile"]
    assert saved_profile["about"].startswith("Ранее записанный опыт.\n\nНаправление работы:")
    assert "1С и ведение документов" in saved_profile["about"]
    # A full browser reload must retain what the candidate saved.
    page.reload(wait_until="networkidle")
    expect(page.locator("#profile-about")).to_have_value(saved_profile["about"])
    expect(page.locator(".profile-optional")).not_to_have_attribute("open", "")
    expect(page.locator("#experience-start")).to_contain_text("Помочь описать опыт")
    # Open the editor again; the description must still be available.
    page.locator("#experience-start").click()
    expect(page.locator("#profile-about")).to_have_value(saved_profile["about"])
    page.locator(".profile-next-actions [data-tab='offers']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Подходящие вакансии")
    page.locator("#public-jobs .job-card").filter(has_text="Кладовщик").locator("[data-v02-action='favorite']").click()
    expect(page.locator("#toast")).to_contain_text("сохранена")
    page.locator(".dashboard-tabs [data-tab='favorites']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Избранные вакансии")
    expect(page.locator("#dashboard-main")).to_contain_text("Кладовщик")
    page.locator("#public-jobs .job-card").filter(has_text="Кладовщик").locator("[data-v02-action='apply']").click()
    expect(page.locator("#toast")).to_contain_text("Отклик отправлен")
    page.locator(".dashboard-tabs [data-tab='applications']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("История откликов")
    expect(page.locator("#dashboard-main")).to_contain_text("Отправлен")
    with page.expect_response(lambda response: (
        "/api/candidate/applications/" in response.url and
        response.url.endswith("/withdraw") and response.request.method == "POST"
    )) as withdraw_reply:
        page.locator("#dashboard-main [data-v02-action='withdraw']").click()
    assert withdraw_reply.value.status == 200
    expect(page.locator("#dashboard-main")).to_contain_text("Отозван")
    with page.expect_response(lambda response: (
        response.url.endswith("/api/candidate/applications") and
        response.request.method == "POST"
    )) as retry_reply:
        page.locator("#dashboard-main [data-v02-action='reapply']").click()
    assert retry_reply.value.status == 201
    assert retry_reply.value.json()["reapplied"] is True
    expect(page.locator("#dashboard-main")).to_contain_text("Отклик отправлен повторно")
    expect(page.locator("#dashboard-main")).to_contain_text("Отправлен")
    page.locator(".dashboard-tabs [data-tab='favorites']").click()
    with page.expect_response(lambda response: (
        "/api/candidate/favorites/" in response.url and
        response.request.method == "DELETE"
    )) as delete_response:
        page.locator("#dashboard-main [data-v02-action='remove-favorite']").click()
    assert delete_response.value.status == 200, delete_response.value.text()
    expect(page.locator("#dashboard-main")).to_contain_text("Вы ещё не сохранили вакансий", timeout=10000)
    page.locator("#logout").click()

    login(page, "company@demo.example")
    page.locator(".dashboard-tabs [data-tab='applications']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Отклики соискателей")
    expect(page.locator("#dashboard-main")).to_contain_text("Кладовщик")
    page.locator("#dashboard-main [data-v02-action='application-status'][data-status='reviewing']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("На рассмотрении")
    page.locator("#dashboard-main [data-v02-action='express-interest']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Запрос отправлен")
    expect(page.locator("#dashboard-main [data-v02-action='express-interest']")).to_have_count(0)
    page.locator("#logout").click()

    login(page, "kladovshik@demo.example")
    page.locator(".dashboard-tabs [data-tab='applications']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Работодатель заинтересован")
    expect(page.locator("#dashboard-main")).to_contain_text("Ожидается ваше решение")
    page.locator("#dashboard-main [data-v02-action='open-introductions']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Приглашения от компаний")
    page.locator("#dashboard-main [id^='consent-']").check()
    page.locator("#dashboard-main [data-action='accept']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Согласие получено")
    page.locator("#logout").click()

    login(page, "company@demo.example")
    page.locator(".dashboard-tabs [data-tab='invitations']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Согласие получено")
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#dashboard-main [data-action='demo-pay']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Контакт открыт (демо)")
    expect(page.locator("#dashboard-main")).to_contain_text("Знакомство состоялось (демо)")
    expect(page.locator("#dashboard-main")).to_contain_text("История взаимодействия")
    page.locator(".dashboard-tabs [data-tab='applications']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Знакомство состоялось (демо)")
    expect(page.locator("#dashboard-main")).to_contain_text("Приглашение отправлено")
    expect(page.locator("#dashboard-main")).to_contain_text("Согласие получено")
    expect(page.locator("#dashboard-main")).to_contain_text("Знакомство состоялось (демо)")
    expect(page.locator("#dashboard-main [data-v02-action='application-status']")).to_have_count(0)
    page.locator("#logout").click()

    login(page, "kladovshik@demo.example")
    page.locator(".dashboard-tabs [data-tab='applications']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Знакомство состоялось (демо)")
    expect(page.locator("#dashboard-main [data-v02-action='withdraw']")).to_have_count(0)
    page.locator(".dashboard-tabs [data-tab='invitations']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Знакомство состоялось (демо)")
    page.locator("#logout").click()

    # Accountant must not receive an engineer recommendation merely
    # because both profiles mention Excel.
    login(page, "buhgalter@demo.example")
    page.locator(".dashboard-tabs [data-tab='offers']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Бухгалтер")
    expect(page.locator("#dashboard-main")).not_to_contain_text("Инженер по эксплуатации")
    expect(page.locator("#dashboard-main [data-v02-action='apply']")).to_have_count(1)
    page.locator("#dashboard-main [data-v02-action='apply']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Отклик: Отправлен")
    expect(page.locator("#dashboard-main [data-v02-action='apply']")).to_have_count(0)
    # Reproduce the real screenshot: account has an existing application
    # before reloading the website and opening recommended jobs again.
    page.reload(wait_until="networkidle")
    expect(page.locator(".release-ribbon")).to_contain_text("0.3.0-dev")
    page.locator(".dashboard-tabs [data-tab='offers']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Отклик: Отправлен")
    expect(page.locator("#dashboard-main [data-v02-action='apply']")).to_have_count(0)
    page.locator("#dashboard-main [data-v02-action='see-applications']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("История откликов")
    page.locator("#logout").click()

    login(page, "admin@demo.example")
    expect(page.locator("#admin-stats")).to_contain_text("Активные отклики")
    expect(page.locator("#admin-stats")).to_contain_text("Отозванные отклики")
    expect(page.locator("[data-v02-action='admin-users']")).to_be_visible()
    page.locator("[data-v02-action='admin-users']").click()
    expect(page.locator("#admin-v02-results")).to_contain_text("Пользователи")
    page.locator("[data-v02-action='admin-jobs']").click()
    expect(page.locator("#admin-v02-results")).to_contain_text("Вакансии")
    page.locator("[data-v02-action='admin-mail']").click()
    expect(page.locator("#admin-v02-results")).to_contain_text("Тестовая очередь")
    expect(page.locator("#admin-v02-results")).to_contain_text("contact_opened")
    # The same linked journey must remain navigable on a narrow phone viewport.
    page.set_viewport_size({"width": 390, "height": 844})
    expect(page.locator(".mobile-quick-nav")).to_be_visible()
    expect(page.locator("#admin-v02-results")).to_be_visible()
    page.locator("#logout").click()
    login(page, "kladovshik@demo.example")
    expect(page.locator(".dashboard-tabs")).to_be_visible()
    assert page.locator(".dashboard-tabs [data-tab='profile']").bounding_box()["height"] >= 44
    expect(page.locator("#profile-form")).to_be_visible()
    page.locator(".dashboard-tabs [data-tab='applications']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Знакомство состоялось (демо")

    # New employer vacancy flow runs after all candidate/admin regressions.
    # Only fictional job data is used and no external service is called.
    page.locator("#logout").click()
    page.set_viewport_size({"width": 1280, "height": 800})
    login(page, "company@demo.example")
    page.locator(".dashboard-tabs [data-tab='create']").click()
    expect(page.locator("#vacancy-form")).to_be_visible()
    expect(page.locator("#vacancy-publish")).to_be_disabled()
    page.locator("#vacancy-show-preview").click()
    expect(page.locator("#vacancy-form-message")).to_contain_text("Заполните обязательные поля")
    expect(page.locator("#vacancy-publish")).to_be_disabled()

    title = "Тестовый специалист по учёту"
    page.locator("#vacancy-title").fill(title)
    page.locator("#vacancy-city").fill("Тестоград")
    page.locator("#vacancy-skills").fill("Excel, учёт")
    page.locator("#vacancy-salary-min").fill("78000")
    page.locator("#vacancy-salary-max").fill("65000")
    page.locator("#vacancy-schedule").select_option(label="Гибкий")
    page.locator("#vacancy-employment").select_option(label="Полная")
    page.locator("#vacancy-responsibilities").fill("<b>Учёт товаров</b>, сверка накладных")
    page.locator("#vacancy-requirements").fill("Знание Excel, внимательность к данным")
    page.locator("#vacancy-conditions").fill("Гибкий график, тестовая компания, обучение на месте")
    page.locator("#vacancy-show-preview").click()
    expect(page.locator("#vacancy-form-message")).to_contain_text("верхняя граница")
    expect(page.locator("#vacancy-publish")).to_be_disabled()

    page.locator("#vacancy-salary-max").fill("92000")
    page.locator("#vacancy-show-preview").click()
    expect(page.locator("#vacancy-preview")).to_be_visible()
    expect(page.locator("#vacancy-preview-title")).to_have_text(title)
    expect(page.locator("#vacancy-preview-description")).to_contain_text("Обязанности:")
    expect(page.locator("#vacancy-preview-description")).to_contain_text("Требования:")
    expect(page.locator("#vacancy-preview-description")).to_contain_text("Условия работы:")
    expect(page.locator("#vacancy-preview-description")).to_contain_text("<b>Учёт товаров</b>")
    assert page.locator("#vacancy-preview-description b").count() == 0, "Unsafe HTML in preview"
    expect(page.locator("#vacancy-publish")).to_be_enabled()
    page.locator("#vacancy-conditions").fill("Гибкий график 5/2, вымышленная компания")
    expect(page.locator("#vacancy-publish")).to_be_disabled()
    expect(page.locator("#vacancy-preview")).to_be_hidden()
    expect(page.locator("#vacancy-form-message")).to_contain_text("Повторно откройте предпросмотр")
    page.locator("#vacancy-show-preview").click()
    expect(page.locator("#vacancy-publish")).to_be_enabled()
    expect(page.locator("#vacancy-preview-description")).to_contain_text("Гибкий график 5/2")

    page.set_viewport_size({"width": 390, "height": 844})
    expect(page.locator("#vacancy-publish")).to_be_visible()
    assert page.evaluate("""() => {
      const form = document.querySelector('#vacancy-form');
      return form.scrollWidth <= form.clientWidth + 3;
    }"""), "Vacancy composer overflows narrow viewport"

    with page.expect_response(lambda response: (
        response.url.endswith("/api/employer/vacancies") and response.request.method == "POST"
    )) as new_vacancy:
        page.locator("#vacancy-publish").click()
    assert new_vacancy.value.status == 201, new_vacancy.value.text()
    expect(page.locator("#dashboard-main")).to_contain_text("Мои вакансии")
    expect(page.locator("#dashboard-main")).to_contain_text(title)
    job_list = page.request.get(URL + "/api/employer/vacancies").json()["jobs"]
    created = [job for job in job_list if job["title"] == title]
    assert len(created) == 1, "The preview/publish workflow must create exactly one vacancy"
    description = created[0]["description"]
    assert "Обязанности:\n<b>Учёт товаров</b>" in description
    assert "Требования:\nЗнание Excel" in description
    assert "Условия работы:\nГибкий график 5/2" in description

    page.locator("#public-jobs .job-card").filter(has_text=title).locator(
        "[data-v02-action='details']").click()
    expect(page.locator("#job-dialog")).to_be_visible()
    expect(page.locator("#job-dialog-content")).to_contain_text("Гибкий график 5/2")
    assert page.locator("#job-dialog-content b").count() == 0, "Unsafe HTML in public job"
    page.locator("#job-dialog-close").click()

    # Editing a freshly published structured vacancy preserves its ID and
    # requires the same preview gate as new publication.
    published_id = created[0]["id"]
    old_revision = created[0]["revision"]
    page.locator("#dashboard-main .item-card").filter(has_text=title).locator(
        "[data-action='edit-job']").click()
    expect(page.locator("#vacancy-form")).to_be_visible()
    expect(page.locator("#vacancy-form")).to_have_attribute("data-edit-id", str(published_id))
    expect(page.locator("#vacancy-title")).to_have_value(title)
    expect(page.locator("#vacancy-responsibilities")).to_contain_text("<b>Учёт товаров</b>")
    expect(page.locator("#vacancy-publish")).to_be_disabled()
    expect(page.locator("#vacancy-publish")).to_have_text("Сохранить изменения ↗")
    page.locator("#vacancy-show-preview").click()
    expect(page.locator("#vacancy-publish")).to_be_enabled()
    page.locator("#vacancy-salary-min").fill("82000")
    page.locator("#vacancy-conditions").fill("Гибкий график 4/4, вымышленная компания")
    expect(page.locator("#vacancy-preview")).to_be_hidden()
    expect(page.locator("#vacancy-publish")).to_be_disabled()
    page.locator("#vacancy-show-preview").click()
    expect(page.locator("#vacancy-preview")).to_be_visible()
    expect(page.locator("#vacancy-preview-description")).to_contain_text("Гибкий график 4/4")
    assert page.evaluate("""() => {
      const form = document.querySelector('#vacancy-form');
      return form.scrollWidth <= form.clientWidth + 3;
    }"""), "Edit form overflows 390px viewport"
    with page.expect_response(lambda response: (
        response.url.endswith(f"/api/employer/vacancies/{published_id}") and
        response.request.method == "PATCH"
    )) as edited:
        page.locator("#vacancy-publish").click()
    assert edited.value.status == 200, edited.value.text()
    jobs_after_edit = page.request.get(URL + "/api/employer/vacancies").json()["jobs"]
    assert len(jobs_after_edit) == len(job_list), "Editing must not create a second vacancy"
    same_job = next(job for job in jobs_after_edit if job["id"] == published_id)
    assert same_job["revision"] != old_revision
    assert same_job["salary_min"] == 82000
    assert "Гибкий график 4/4" in same_job["description"]
    expect(page.locator("#dashboard-main")).to_contain_text(title)

    # Old plain-text vacancies open without splitting or truncating description.
    old_job = next(job for job in jobs_after_edit if job["title"] == "Кладовщик")
    page.locator("#dashboard-main .item-card").filter(has_text="Кладовщик").locator(
        "[data-action='edit-job']").click()
    expect(page.locator("#vacancy-legacy")).to_have_value(old_job["description"])
    expect(page.locator("#vacancy-responsibilities")).to_have_count(0)
    page.locator("#vacancy-salary-min").fill(str(old_job["salary_min"] + 2000))
    page.locator("#vacancy-show-preview").click()
    expect(page.locator("#vacancy-preview-description")).to_have_text(old_job["description"])
    with page.expect_response(lambda response: (
        response.url.endswith(f"/api/employer/vacancies/{old_job['id']}") and
        response.request.method == "PATCH"
    )) as legacy_edit:
        page.locator("#vacancy-publish").click()
    assert legacy_edit.value.status == 200, legacy_edit.value.text()
    legacy_updated = next(job for job in
        page.request.get(URL + "/api/employer/vacancies").json()["jobs"]
        if job["id"] == old_job["id"])
    assert legacy_updated["description"] == old_job["description"]
    assert legacy_updated["salary_min"] == old_job["salary_min"] + 2000
    assert legacy_updated["status"] == old_job["status"]

    # A concurrent edit in a second tab cannot be silently overwritten.
    page.locator("#dashboard-main .item-card").filter(has_text="Кладовщик").locator(
        "[data-action='edit-job']").click()
    stale = legacy_updated
    competing = {field:stale[field] for field in (
        "title", "city", "salary_min", "salary_max",
        "schedule", "employment", "skills", "description"
    )}
    competing["expected_revision"] = stale["revision"]
    competing["salary_min"] = stale["salary_min"] + 1000
    response = page.request.patch(
        URL + f"/api/employer/vacancies/{stale['id']}",
        headers={"X-Requested-With": "OPYT50"},
        data=competing,
    )
    assert response.status == 200, response.text()
    page.locator("#vacancy-show-preview").click()
    with page.expect_response(lambda response: (
        response.url.endswith(f"/api/employer/vacancies/{stale['id']}") and
        response.request.method == "PATCH"
    )) as conflict:
        page.locator("#vacancy-publish").click()
    assert conflict.value.status == 409, conflict.value.text()
    expect(page.locator("#vacancy-form-message")).to_contain_text("Отмените редактирование")
    expect(page.locator("#vacancy-publish")).to_be_disabled()
    page.locator("[data-action='cancel-job-edit']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Мои вакансии")

    if console_errors:
        raise AssertionError("Uncaught browser errors: " + " | ".join(console_errors))


def main():
    with tempfile.TemporaryDirectory(prefix="opytno-smoke-") as tmp:
        env = dict(os.environ, OPYT50_DB_PATH=str(Path(tmp) / "demo.db"),
                   OPYT50_PREVIEW_SEED_DEMO="0", OPYT50_COOKIE_SECURE="0")
        subprocess.run([sys.executable, "scripts/seed_demo.py", "--db", env["OPYT50_DB_PATH"]],
                       cwd=ROOT, env=env, check=True, capture_output=True)
        server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app",
                                   "--host", "127.0.0.1", "--port", "8765"],
                                  cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        try:
            for attempt in range(80):
                try:
                    with urlopen(URL+"/api/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except Exception:
                    time.sleep(.25)
            else:
                raise RuntimeError("Local server did not become ready")
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                try:
                    context = browser.new_context(viewport={"width": 1366, "height": 900}, locale="ru-RU")
                    page = context.new_page()
                    try:
                        run_browser(page)
                    except Exception:
                        page.screenshot(path=str(Path(tmp) / "failure.png"), full_page=True)
                        raise
                    finally:
                        context.close()
                finally:
                    browser.close()
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
    print("Browser smoke: 0.3 vacancy preview/edit, legacy preservation, conflict guard and 0.2 regression PASSED")


if __name__ == "__main__":
    main()
