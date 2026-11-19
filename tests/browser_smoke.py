"""Real-browser smoke test for release 0.2 using fictional data. No external services."""
import re
import json
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
    # Journal discovery is local-only; suppress reporting in the browser test
    # so editorial visits do not change unrelated admin growth assertions.
    page.route("**/api/growth/event", lambda route: route.fulfill(status=204))
    page.goto(URL + "/journal", wait_until="networkidle")
    expect(page.locator("#jr-article-grid .jr-card")).to_have_count(6)
    journal_search = page.locator("#jr-article-search")
    journal_search.fill("собеседован")
    expect(page.locator("#jr-article-grid .jr-card:visible")).to_have_count(1)
    expect(page.locator("#jr-results-count")).to_contain_text("1 из 6")
    page.locator("[data-jr-category-filter='Работодателям']").click()
    expect(page.locator("#jr-no-results")).to_be_visible()
    page.locator("#jr-reset-search").click()
    expect(page.locator("#jr-article-grid .jr-card:visible")).to_have_count(6)
    page.locator("[data-jr-category-filter='Работодателям']").click()
    expect(page.locator("#jr-article-grid .jr-card:visible")).to_have_count(1)
    page.locator("#jr-article-grid .jr-card:visible").click()
    expect(page.locator(".jr-article h1")).to_contain_text("Работодателю")
    expect(page.locator(".jr-related .jr-card")).to_have_count(2)
    page.goto(URL, wait_until="networkidle")
    page.unroute("**/api/growth/event")
    expect(page.locator(".brand-word").first).to_contain_text("стажно")
    assert "СТАЖНО" in page.title()
    assert "опытно.рф" not in page.locator("body").inner_text().casefold()
    expect(page.locator(".product-strip")).to_contain_text("Без возрастных барьеров")
    expect(page.locator("#candidate-path")).to_be_visible()
    expect(page.locator("#employer-path")).to_be_visible()
    # Search first; registration is not required to inspect a vacancy.
    page.get_by_role("link", name="Найти работу").first.click()
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

    # The public phone homepage has one navigation layer, while sign-in and
    # registration remain possible without hunting through the page.
    page.set_viewport_size({"width": 390, "height": 844})
    expect(page.locator(".mobile-quick-nav")).to_be_hidden()
    expect(page.locator("#mobile-guest-actions")).to_be_visible()
    expect(page.locator("#mobile-guest-actions #login-open")).to_be_visible()
    expect(page.locator("#mobile-guest-actions #register-open")).to_be_visible()
    expect(page.locator("#home .hero-actions a[href='#jobs']")).to_be_hidden()
    expect(page.locator("#home .hero-actions [data-register='employer']")).to_be_visible()
    page.locator("#mobile-guest-actions #login-open").click()
    expect(page.locator("#auth-dialog")).to_be_visible()
    page.locator("#modal-close").click()
    mode.click()
    expect(mode).to_have_attribute("aria-pressed", "true")
    assert page.evaluate("""() => document.documentElement.scrollWidth
      <= document.documentElement.clientWidth + 3"""), "Large-text mobile homepage overflows"
    mode.click()
    page.set_viewport_size({"width": 320, "height": 740})
    expect(page.locator("#mobile-guest-actions #login-open")).to_be_visible()
    expect(page.locator("#mobile-guest-actions #register-open")).to_be_visible()
    assert page.evaluate("""() => document.documentElement.scrollWidth
      <= document.documentElement.clientWidth + 3"""), "Narrow mobile homepage overflows"
    page.set_viewport_size({"width": 1280, "height": 720})

    page.locator("#register-open").click()
    expect(page.locator("#auth-name")).to_be_focused()
    expect(page.locator("#auth-guidance")).to_contain_text("Профессию, навыки")
    page.locator(".role-btn[data-role='employer']").click()
    expect(page.locator("#auth-company-row")).to_be_visible()
    expect(page.locator("#auth-guidance")).to_contain_text("Первую вакансию")
    page.locator(".role-btn[data-role='candidate']").click()
    page.locator("#modal-close").click()
    expect(page.locator("#profession-filter")).to_be_visible()
    expect(page.locator("#schedule-filter")).to_be_visible()
    expect(page.locator("#employment-filter")).to_be_visible()
    expect(page.locator("#sort-filter")).to_be_visible()

    page.locator("#profession-filter").fill("Кладовщик")
    page.locator("#city-filter").fill("Подольск")
    page.locator("#salary-filter").fill("70000")
    page.locator("#schedule-filter").select_option(label="Сменный")
    page.locator("#employment-filter").select_option(label="Полная")
    page.locator("#sort-filter").select_option("salary_desc")
    page.locator("#jobs-filter").click()
    expect(page.locator("#public-jobs .job-card")).to_have_count(1)
    expect(page.locator("#jobs-count")).to_contain_text("Найдено: 1")
    expect(page.locator("#job-filter-summary")).to_contain_text("Занятость: Полная")
    expect(page.locator("#job-filter-summary")).to_contain_text("Сортировка: Сначала выше зарплата")
    # Individual filter chips remove only one condition.
    page.locator("#job-filter-summary [data-filter-id='employment-filter']").click()
    expect(page.locator("#employment-filter")).to_have_value("")
    expect(page.locator("#job-filter-summary")).not_to_contain_text("Занятость:")
    page.locator("#employment-filter").select_option(label="Полная")
    expect(page.locator("#job-filter-summary")).to_contain_text("Занятость: Полная")
    expect(page.locator("#public-jobs .job-card")).to_contain_text("Кладовщик")
    expect(page.locator("#public-jobs .job-skill-tags")).to_contain_text("склад")

    page.locator("#public-jobs [data-v02-action='details']").click()
    expect(page.locator("#job-dialog")).to_be_visible()
    expect(page.locator("#job-dialog-content")).to_contain_text("Складской учёт")
    page.locator("#job-dialog-close").click()
    expect(page.locator("#job-dialog")).not_to_be_visible()

    # Public job URL is shareable and returns to the SAME vacancy without
    # submitting an application or exposing applicant contact data.
    shared_id = int(page.locator("#public-jobs .job-card").first.get_attribute("data-job-id"))
    share_link = page.locator("#public-jobs .job-card").first.locator(
        f"a[href='/vacancies/{shared_id}']"
    )
    expect(share_link).to_be_visible()
    landing = page.request.get(URL + f"/vacancies/{shared_id}")
    assert landing.status == 200, landing.text()
    assert "Кладовщик" in landing.text()
    assert f'/?vacancy={shared_id}#jobs' in landing.text()
    application_posts = []
    page.on("request", lambda request: application_posts.append(request.url) if (
        request.method == "POST" and request.url.endswith("/api/candidate/applications")
    ) else None)
    page.goto(URL + f"/?vacancy={shared_id}#jobs", wait_until="networkidle")
    expect(page.locator("#job-dialog")).to_be_visible()
    expect(page.locator("#job-dialog-title")).to_have_text("Кладовщик")
    assert not application_posts, "Opening a shared vacancy must never submit an application"
    assert "vacancy=" not in page.evaluate("location.search"), "Link should be consumed once"
    page.locator("#job-dialog-close").click()
    expect(page.locator("#job-dialog")).not_to_be_visible()

    # A search with no results must offer a clear recovery action, preserving
    # the original job-search workflow and keyboard-accessible controls.
    page.locator("#profession-filter").fill("несуществующая профессия 98765")
    page.locator("#jobs-filter").click()
    empty = page.locator("#public-jobs .jobs-empty-state")
    expect(empty).to_contain_text("По этим условиям вакансий пока нет.")
    expect(empty.locator("[data-v02-action='reset-public-job-filters']")).to_be_visible()
    empty.locator("[data-v02-action='reset-public-job-filters']").click()
    expect(page.locator("#profession-filter")).to_have_value("")
    expect(page.locator("#public-jobs .job-card").first).to_be_visible()

    login(page, "kladovshik@demo.example")
    expect(page.locator("#dashboard-main")).to_contain_text("ВАШ СЛЕДУЮЩИЙ ШАГ")
    expect(page.locator("#dashboard-main .overview-stat-card")).to_have_count(4)
    candidate_tabs = page.locator(".dashboard-tabs [data-tab]")
    expect(candidate_tabs).to_have_count(9)
    expect(page.locator(".dashboard-tabs [data-tab='applications']")).to_contain_text("Отклики")
    expect(page.locator(".dashboard-tabs [data-tab='invitations']")).to_contain_text("Знакомства")
    expect(page.locator(".dashboard-tabs [data-tab='security']")).to_be_visible()
    page.locator(".dashboard-tabs [data-tab='profile']").click()
    expect(page.locator("#profile-form")).to_be_visible()
    expect(page.locator(".profile-health")).to_be_visible()
    expect(page.locator(".profile-health")).to_contain_text("%")
    expect(page.locator("#profile-profession")).to_have_value("Кладовщик")
    expect(page.locator(".profile-optional")).not_to_have_attribute("open", "")
    expect(page.locator("#profile-phone")).not_to_be_visible()
    # Release 0.5.31: structured work experience does not require a long CV.
    page.locator("#resume-years").fill("24")
    page.locator("#resume-education").fill("Среднее профессиональное — логистика")
    page.locator("#resume-achievements").fill("Настроил складской учёт")
    page.locator("#resume-add-role").click()
    first_role = page.locator("#resume-work-list [data-resume-role]").first
    expect(first_role.locator("[data-role-position]")).to_be_focused()
    first_role.locator("[data-role-position]").fill("Старший кладовщик")
    first_role.locator("[data-role-period]").fill("2014–2024")
    first_role.locator("[data-role-duties]").fill("Приёмка и инвентаризация")
    page.locator("#resume-add-role").click()
    expect(page.locator("#resume-work-list [data-resume-role]")).to_have_count(2)
    page.locator("#resume-work-list [data-resume-role]").last.locator(
        "[data-action='remove-resume-role']").click()
    expect(page.locator("#resume-work-list [data-resume-role]")).to_have_count(1)
    # Release 0.5.32: optional training and certificates, including removal.
    expect(page.locator("#resume-training-section")).not_to_have_attribute("open", "")
    page.locator("#resume-training-section summary").click()
    page.locator("#resume-specializations").fill("Складская логистика, 1С")
    page.locator("#resume-add-course").click()
    first_course = page.locator("#resume-course-list [data-resume-course]").first
    expect(first_course.locator("[data-course-title]")).to_be_focused()
    first_course.locator("[data-course-title]").fill("Управление складом в 1С")
    first_course.locator("[data-course-provider]").fill("Учебный центр")
    first_course.locator("[data-course-year]").fill("2021")
    first_course.locator("[data-course-certificate]").check()
    page.locator("#resume-add-course").click()
    expect(page.locator("#resume-course-list [data-resume-course]")).to_have_count(2)
    page.locator("#resume-course-list [data-resume-course]").last.locator(
        "[data-action='remove-resume-course']").click()
    expect(page.locator("#resume-course-list [data-resume-course]")).to_have_count(1)
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
    page.locator("#profile-about").fill(
        "Направление работы: профессия «Складской учёт». Основные задачи: "
        "«Приёмка поставок и инвентаризация». Сильные стороны и навыки: "
        "«1С и ведение документов»."
    )
    previous = page.locator("#profile-about").input_value()
    page.locator("#experience-insert").click()
    expect(page.locator("#experience-helper-message")).to_contain_text("Похожее описание")
    assert page.locator("#profile-about").input_value() == previous
    expect(page.locator("#experience-insert")).to_be_disabled()
    page.locator("#profile-about").fill("Ранее записанный опыт.")
    page.locator("#experience-build").click()
    page.locator("#experience-insert").click()
    assert page.locator("#profile-about").input_value().startswith("Ранее записанный опыт.\n\nНаправление работы:")
    assert "1С и ведение документов" in page.locator("#profile-about").input_value()
    expect(page.locator("#experience-insert")).to_be_disabled()
    expect(page.locator("#experience-helper-message")).to_contain_text("Сохранить профиль")
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
    assert saved_profile["experience_years"] == 24
    assert saved_profile["education"] == "Среднее профессиональное — логистика"
    assert len(saved_profile["work_history"]) == 1
    assert saved_profile["work_history"][0]["position"] == "Старший кладовщик"
    assert saved_profile["specializations"] == "Складская логистика, 1С"
    assert len(saved_profile["courses"]) == 1
    assert saved_profile["courses"][0]["title"] == "Управление складом в 1С"
    assert saved_profile["courses"][0]["has_certificate"] is True
    # A full browser reload returns to the overview; profile data must remain intact.
    page.reload(wait_until="networkidle")
    expect(page.locator("#dashboard-main")).to_contain_text("ВАШ СЛЕДУЮЩИЙ ШАГ")
    page.locator(".dashboard-tabs [data-tab='profile']").click()
    expect(page.locator("#profile-about")).to_have_value(saved_profile["about"])
    expect(page.locator("#resume-years")).to_have_value("24")
    expect(page.locator("#resume-education")).to_have_value(saved_profile["education"])
    expect(page.locator("#resume-work-list [data-resume-role]")).to_have_count(1)
    expect(page.locator("#resume-course-list [data-resume-course]")).to_have_count(1)
    expect(page.locator("#resume-training-section")).not_to_have_attribute("open", "")
    page.locator("#resume-training-section summary").click()
    expect(page.locator("#resume-specializations")).to_have_value(saved_profile["specializations"])
    expect(page.locator("#resume-course-list [data-course-certificate]")).to_be_checked()
    expect(page.locator(".profile-public-preview")).to_contain_text("Управление складом в 1С")
    expect(page.locator(".profile-public-preview")).to_contain_text("Складская логистика, 1С")
    expect(page.locator(".profile-public-preview")).to_contain_text("не проверен")
    expect(page.locator(".profile-public-preview")).to_contain_text("Старший кладовщик")
    expect(page.locator(".profile-public-preview")).to_contain_text("Настроил складской учёт")
    expect(page.locator(".profile-public-preview")).not_to_contain_text("kladovshik@demo.example")
    # Release 0.5.33: only saved resume data is printed; contacts require opt-in.
    page.locator("[data-action='open-resume-print']").click()
    dialog = page.locator("#resume-print-dialog")
    expect(dialog).to_be_visible()
    sheet = dialog.locator("#resume-print-document")
    expect(sheet).to_contain_text("Старший кладовщик")
    expect(sheet).to_contain_text("Управление складом в 1С")
    expect(sheet).to_contain_text("Складская логистика, 1С")
    expect(sheet).to_contain_text("Без имени и контактных данных")
    expect(sheet).not_to_contain_text("kladovshik@demo.example")
    expect(dialog.locator("#resume-print-include-contacts")).not_to_be_checked()
    # Public resume text is escaped and obvious contact strings are masked
    # even if an old legacy profile contained them.
    unsafe = page.evaluate("""() => resumePrintDocumentMarkup({
      profession: '<img src=x onerror=alert(1)>',
      city: 'Москва',
      skills: 'Excel, hidden@example.invalid',
      about: 'Пишите +7 999 111-22-33, @privatehandle или https://example.invalid',
      work_history: [{position:'Администратор',period:'2020–2024',
                      duties:'Контакт hidden@example.invalid'}],
      courses: [{title:'Курс',provider:'https://example.invalid'}]
    }, {name:'Частное имя',email:'private@example.invalid'}, false)""")
    assert "<img" not in unsafe and "&lt;img" in unsafe
    for secret in ("hidden@example.invalid", "private@example.invalid",
                   "https://example.invalid", "+7 999 111-22-33", "@privatehandle", "Частное имя"):
        assert secret not in unsafe
    dialog.locator("#resume-print-include-contacts").check()
    expect(sheet).to_contain_text("kladovshik@demo.example")
    dialog.locator("#resume-print-include-contacts").uncheck()
    expect(sheet).not_to_contain_text("kladovshik@demo.example")
    page.evaluate("""() => {
        window.__resumePrintCount = 0;
        window.print = () => { window.__resumePrintCount++; };
    }""")
    dialog.locator("[data-resume-print='print']").click()
    assert page.evaluate("window.__resumePrintCount") == 1
    assert page.locator("body").evaluate("el=>el.classList.contains('resume-printing')")
    page.emulate_media(media="print")
    assert sheet.evaluate("el=>getComputedStyle(el).display") != "none"
    pdf = page.pdf(format="A4", print_background=True)
    assert pdf.startswith(b"%PDF") and len(pdf) > 4000
    page.emulate_media(media="screen")
    dialog.locator("[data-resume-print='close']").click()
    expect(dialog).to_have_count(0)
    assert not page.locator("body").evaluate("el=>el.classList.contains('resume-printing')")
    expect(page.locator(".profile-optional")).not_to_have_attribute("open", "")
    expect(page.locator("#experience-start")).to_contain_text("Помочь описать опыт")
    # Open the editor again; the description must still be available.
    page.locator("#experience-start").click()
    expect(page.locator("#profile-about")).to_have_value(saved_profile["about"])
    page.locator(".profile-next-actions [data-tab='offers']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Подходящие вакансии")
    expect(page.locator("#dashboard-main")).to_contain_text("Другие вакансии, которые могут вас заинтересовать")
    expect(page.locator("#dashboard-main")).to_contain_text("Что не совпадает:")
    expect(page.locator("#dashboard-main .match-explanation").first).to_be_visible()
    page.locator("#dashboard-main .match-explanation summary").first.click()
    expect(page.locator("#dashboard-main .match-explanation").first).to_contain_text("Подходят зарплатные ожидания")
    expect(page.locator("#dashboard-main .match-explanation").first).to_contain_text("не гарантирует приглашение")
    page.locator("#public-jobs .job-card").filter(has_text="Кладовщик").locator("[data-v02-action='favorite']").click()
    expect(page.locator("#toast")).to_contain_text("сохранена")
    expect(page.locator("#public-jobs .job-card").filter(has_text="Кладовщик").locator(".favorite-toggle")).to_have_attribute("aria-pressed","true")
    expect(page.locator("#public-jobs .job-card").filter(has_text="Кладовщик").locator(".favorite-toggle")).to_contain_text("♥")
    page.locator(".dashboard-tabs [data-tab='favorites']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Избранные вакансии")
    expect(page.locator("#dashboard-main")).to_contain_text("Кладовщик")
    page.locator("#public-jobs .job-card").filter(has_text="Кладовщик").locator("[data-v02-action='apply']").click()
    expect(page.locator("#toast")).to_contain_text("Отклик отправлен")
    page.locator(".dashboard-tabs [data-tab='applications']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("История откликов")
    expect(page.locator("#dashboard-main")).to_contain_text("Отправлен")
    # Release 0.5.20: candidate queue uses locally held application metadata
    # and prioritizes invitations. 45 records are fictional response fixtures.
    original_candidate_apps = page.request.get(URL + "/api/candidate/applications").json()
    sample_candidate_app = original_candidate_apps["applications"][0]
    fictional_apps = []
    for idx in range(45):
        entry = dict(sample_candidate_app)
        entry["id"] = 70000 + idx
        entry["vacancy_id"] = 90000 + idx
        entry["title"] = f"Тестовая вакансия {idx:02d}"
        entry["company_name"] = "Учебная компания"
        entry["city"] = "Подольск"
        entry["status"] = "applied"
        entry["contact_shared"] = False
        entry["invitation_id"] = None
        entry["invitation_status"] = None
        entry["timeline"] = []
        if idx == 44:
            entry["invitation_id"] = 80044
            entry["invitation_status"] = "sent"
        if idx == 43:
            entry["status"] = "rejected"
        fictional_apps.append(entry)

    def fake_candidate_applications(route):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"applications": fictional_apps}, ensure_ascii=False))

    page.route("**/api/candidate/applications", fake_candidate_applications)
    page.locator(".dashboard-tabs [data-tab='favorites']").click()
    page.locator(".dashboard-tabs [data-tab='applications']").click()
    candidate_cards = page.locator("#candidate-application-results .candidate-application-card:visible")
    expect(candidate_cards).to_have_count(20)
    expect(page.locator("#candidate-application-visible-count")).to_have_text("20")
    expect(page.locator("#candidate-application-matched-count")).to_have_text("45")
    expect(candidate_cards.first).to_contain_text("Тестовая вакансия 44")
    candidate_next = page.locator("[data-candidate-app-action='more']")
    expect(candidate_next).to_contain_text("20")
    candidate_next.click()
    expect(candidate_cards).to_have_count(40)
    expect(page.locator("#candidate-application-results .candidate-application-card").nth(20)).to_be_focused()
    expect(candidate_next).to_contain_text("5")
    candidate_next.click()
    expect(candidate_cards).to_have_count(45)
    expect(page.locator("#candidate-application-pagination")).to_be_hidden()

    candidate_search = page.locator("#candidate-application-search")
    candidate_reads = []
    page.on("request", lambda request: candidate_reads.append(request)
            if request.method == "GET" and request.url.endswith("/api/candidate/applications")
            else None)
    candidate_search.fill("ваКАнсия 00")
    expect(candidate_cards).to_have_count(1)
    expect(candidate_cards).to_contain_text("Тестовая вакансия 00")
    candidate_search.fill("несуществующая-компания-abcdef")
    expect(candidate_cards).to_have_count(0)
    expect(page.locator("#candidate-application-empty")).to_be_visible()
    assert not candidate_reads, "Typing in candidate queue must not request applications"
    page.locator("[data-candidate-app-action='reset']").click()
    expect(candidate_search).to_be_focused()
    expect(candidate_search).to_have_value("")
    expect(candidate_cards).to_have_count(20)

    page.locator("[data-candidate-app-action='filter'][data-filter='reply']").click()
    expect(candidate_cards).to_have_count(1)
    expect(candidate_cards).to_contain_text("Тестовая вакансия 44")
    expect(page.locator("[data-candidate-app-action='filter'][data-filter='reply']")).to_have_attribute("aria-pressed", "true")
    page.locator("[data-candidate-app-action='filter'][data-filter='closed']").click()
    expect(candidate_cards).to_have_count(1)
    expect(candidate_cards).to_contain_text("Тестовая вакансия 43")
    page.locator("[data-candidate-app-action='filter'][data-filter='all']").click()
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("""() => {
      const root = document.querySelector('#dashboard-main');
      const filters = document.querySelector('.candidate-application-filters');
      return root.scrollWidth <= root.clientWidth + 3 &&
        getComputedStyle(filters).gridTemplateColumns.trim().split(/\s+/).length === 2;
    }"""), "Candidate application queue must fit 390px"
    page.set_viewport_size({"width": 1280, "height": 800})
    page.unroute("**/api/candidate/applications", fake_candidate_applications)
    page.locator(".dashboard-tabs [data-tab='favorites']").click()
    page.locator(".dashboard-tabs [data-tab='applications']").click()
    expect(candidate_cards).to_have_count(1)
    expect(candidate_cards).to_contain_text("Кладовщик")
    # Continue with actual API state, never mutation on fictional entries.
    before_withdraw = page.request.get(URL + "/api/candidate/applications").json()["applications"][0]
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.locator("#dashboard-main [data-v02-action='withdraw']").click()
    after_cancel = page.request.get(URL + "/api/candidate/applications").json()["applications"][0]
    assert before_withdraw["status"] == after_cancel["status"] == "applied"
    page.once("dialog", lambda dialog: dialog.accept())
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
    expect(page.locator("#account-action-count")).to_have_text("1")
    expect(page.locator(".dashboard-tabs [data-tab='applications'] .dashboard-action-count")).to_have_text("1")
    expect(page.locator("#account-open")).to_have_attribute("aria-label", "Мой кабинет, действий требуют внимания: 1")
    expect(page.locator("#dashboard-main")).to_contain_text("ПРИОРИТЕТ СЕЙЧАС")
    expect(page.locator("#dashboard-main .overview-stat-card")).to_have_count(4)
    expect(page.locator("#dashboard-main .overview-funnel")).to_be_visible()
    expect(page.locator("#dashboard-main .overview-action-center")).to_be_visible()
    expect(page.locator("#dashboard-main .overview-action-center")).to_contain_text("В работе у компании")
    expect(page.locator("#dashboard-main .overview-action-center .overview-action-item").first).to_be_visible()
    expect(page.locator("#dashboard-main .overview-funnel")).to_contain_text("Согласия")
    expect(page.locator("#dashboard-main .overview-funnel")).to_contain_text("Контакты")
    expect(page.locator("#dashboard-main .overview-funnel")).to_contain_text("Положительные итоги")
    employer_tabs = page.locator(".dashboard-tabs [data-tab]")
    expect(employer_tabs).to_have_count(7)
    expect(page.locator(".dashboard-tabs [data-tab='applications']")).to_contain_text("Отклики")
    expect(page.locator(".dashboard-tabs [data-tab='invitations']")).to_contain_text("Знакомства и контакты")
    expect(page.locator(".dashboard-tabs [data-tab='security']")).to_be_visible()
    page.locator(".dashboard-tabs [data-tab='vacancies']").click()
    expect(page.locator(".employer-next")).to_be_visible()
    # Release 0.6: vacancy overview and direct navigation to its applications.
    expect(page.locator("#dashboard-main")).to_contain_text("Запросы на знакомство")
    expect(page.locator("#dashboard-main")).to_contain_text("Открытые контакты")
    # The two KPI grids must be siblings, not incorrectly nested inside each other.
    expect(page.locator("#dashboard-main .stat-grid")).to_have_count(2)
    expect(page.locator("#dashboard-main .stat-grid[aria-label='Статистика вакансий'] > .stat-tile")).to_have_count(3)
    expect(page.locator("#dashboard-main .stat-grid[aria-label='Воронка подбора'] > .stat-tile")).to_have_count(3)
    # Release 0.5.17: employer worklist is searchable without new API calls.
    vacancy_search = page.locator("#employer-vacancy-search")
    expect(vacancy_search).to_be_visible()
    expect(page.locator("#employer-vacancy-results .employer-vacancy-card:visible")).to_have_count(4)
    expect(page.locator("#employer-vacancy-count")).to_contain_text("Показываем 4 из 4")
    vacancy_search.fill("пОдОлЬсК")
    expect(page.locator("#employer-vacancy-results .employer-vacancy-card:visible")).to_have_count(1)
    expect(page.locator("#employer-vacancy-results .employer-vacancy-card:visible")).to_contain_text("Кладовщик")
    vacancy_search.fill("Москва")
    expect(page.locator("#employer-vacancy-results .employer-vacancy-card:visible")).to_have_count(2)
    vacancy_search.fill("нет такой вакансии")
    expect(page.locator("#employer-vacancy-results .employer-vacancy-card:visible")).to_have_count(0)
    expect(page.locator("#employer-vacancy-empty")).to_be_visible()
    page.locator("[data-action='clear-employer-job-search']").click()
    expect(vacancy_search).to_be_focused()
    expect(vacancy_search).to_have_value("")
    expect(page.locator("#employer-vacancy-results .employer-vacancy-card:visible")).to_have_count(4)
    attention_filter = page.locator(
        "#dashboard-main [data-action='filter-employer-jobs'][data-filter='attention']"
    )
    expect(attention_filter).to_contain_text("Требуют внимания (1)")
    attention_filter.click()
    expect(attention_filter).to_have_attribute("aria-pressed","true")
    expect(attention_filter).to_be_focused()
    expect(page.locator("#employer-vacancy-results .employer-vacancy-card:visible")).to_have_count(1)
    expect(page.locator("#employer-vacancy-results .employer-vacancy-card:visible")).to_contain_text("Кладовщик")
    # Search survives changing a status filter and remains usable at 390px.
    vacancy_search.fill("Кладовщик")
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("""() => {
      const content = document.querySelector('#dashboard-main');
      return content.scrollWidth <= content.clientWidth + 3;
    }"""), "Employer vacancy search must fit mobile width"
    expect(page.locator("#employer-vacancy-results .employer-vacancy-card:visible")).to_have_count(1)
    page.locator("[data-action='filter-employer-jobs'][data-filter='all']").click()
    expect(page.locator("#employer-vacancy-search")).to_have_value("Кладовщик")
    page.locator("[data-action='clear-employer-job-search']").click()
    page.set_viewport_size({"width": 1280, "height": 800})
    page.locator("#dashboard-main [data-action='filter-employer-jobs'][data-filter='closed']").click()
    expect(page.locator("#dashboard-main [data-action='filter-employer-jobs'][data-filter='closed']")).to_have_attribute("aria-pressed", "true")
    page.locator("#dashboard-main [data-action='filter-employer-jobs'][data-filter='all']").click()
    page.locator("#dashboard-main .item-card").filter(has_text="Кладовщик").locator("[data-action='vacancy-applications']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Отклики соискателей")
    expect(page.locator("#employer-applications-vacancy")).not_to_have_value("all")
    expect(page.locator("#dashboard-main")).to_contain_text("Кладовщик")
    expect(page.locator("#dashboard-main .application-review-card").first.locator(".application-profile-strip span")).to_have_count(1)
    # Release 0.5.18: local search reads only the current employer's
    # already loaded profiles. Typing does not query the API or reveal contacts.
    application_search = page.locator("#employer-application-search")
    expect(application_search).to_be_visible()
    employer_application_reads = []
    page.on("request", lambda request: employer_application_reads.append(request)
            if request.method == "GET" and request.url.endswith("/api/employer/applications")
            else None)
    expect(page.locator("#employer-application-results .application-review-card:visible")).to_have_count(1)
    application_search.fill("пОДОльСК")
    expect(page.locator("#employer-application-results .application-review-card:visible")).to_have_count(1)
    application_search.fill("1С")
    expect(page.locator("#employer-application-results .application-review-card:visible")).to_have_count(1)
    application_search.fill("точно-нет-такой-профессии")
    expect(page.locator("#employer-application-results .application-review-card:visible")).to_have_count(0)
    expect(page.locator("#employer-application-search-empty")).to_be_visible()
    expect(page.locator("#employer-application-visible-count")).to_have_text("0")
    assert not employer_application_reads, "Search typing must not make API requests"
    page.locator("#employer-application-search-empty [data-v02-action='clear-employer-application-search']").click()
    expect(application_search).to_have_value("")
    expect(application_search).to_be_focused()
    expect(page.locator("#employer-application-results .application-review-card:visible")).to_have_count(1)
    application_search.fill("Кладовщик")
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("""() => {
      const root = document.querySelector('#dashboard-main');
      const input = document.querySelector('#employer-application-search');
      const grid = document.querySelector('.employer-application-stage-filter');
      return root.scrollWidth <= root.clientWidth + 3 &&
        input.getBoundingClientRect().height >= 44 &&
        getComputedStyle(grid).gridTemplateColumns.trim().split(/\\s+/).length === 2;
    }"""), "Application triage should fit 390px with two-column stage filters"
    page.set_viewport_size({"width": 1280, "height": 800})
    # Release 0.5.19: page through 45 fictional applications, without losing
    # search matches beyond the first 20. The real backend stays untouched.
    application_search.fill("")
    original_applications = page.request.get(URL + "/api/employer/applications").json()
    sample_application = original_applications["applications"][0]
    generated_applications = []
    for idx in range(45):
        item = dict(sample_application)
        item["id"] = 50000 + idx
        item["profession"] = f"Тестовый специалист {idx:02d}"
        item["skills"] = "уникальный-навык-44" if idx == 44 else "1С"
        item["timeline"] = []
        generated_applications.append(item)
    def fake_many_applications(route):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"applications": generated_applications}, ensure_ascii=False))
    page.route("**/api/employer/applications", fake_many_applications)
    page.locator("[data-v02-action='employer-application-filter'][data-filter='all']").click()
    expect(page.locator("#employer-application-results .application-review-card:visible")).to_have_count(20)
    expect(page.locator("#employer-application-visible-count")).to_have_text("20")
    expect(page.locator("#employer-application-matched-count")).to_have_text("45")
    pager = page.locator("[data-v02-action='more-employer-applications']")
    expect(pager).to_contain_text("20")
    pager.click()
    expect(page.locator("#employer-application-results .application-review-card:visible")).to_have_count(40)
    expect(page.locator(".application-review-card[data-application-id='50024']")).to_be_focused()
    expect(pager).to_contain_text("5")
    pager.click()
    expect(page.locator("#employer-application-results .application-review-card:visible")).to_have_count(45)
    expect(page.locator("#employer-application-pagination")).to_be_hidden()
    application_search = page.locator("#employer-application-search")
    application_search.fill("уникальный-навык-44")
    expect(page.locator("#employer-application-results .application-review-card:visible")).to_have_count(1)
    expect(page.locator(".application-review-card[data-application-id='50044']")).to_be_visible()
    expect(page.locator("#employer-application-visible-count")).to_have_text("1")
    expect(page.locator("#employer-application-pagination")).to_be_hidden()
    application_search.fill("")
    expect(page.locator("#employer-application-results .application-review-card:visible")).to_have_count(20)
    page.unroute("**/api/employer/applications", fake_many_applications)
    # Restore the pre-existing search and a neutral stage before the legacy
    # filter assertions; the pagination scenario intentionally changed both.
    page.locator("[data-v02-action='employer-application-filter'][data-filter='all']").click()
    page.locator("#employer-application-search").fill("Кладовщик")
    expect(page.locator("#employer-application-results .application-review-card:visible")).to_have_count(1)
    expect(page.locator("#dashboard-main [data-v02-action='employer-application-filter']")).to_have_count(6)
    attention_filter = page.locator("#dashboard-main [data-v02-action='employer-application-filter'][data-filter='attention']")
    expect(attention_filter).to_contain_text("Требуют внимания")
    expect(attention_filter).to_have_attribute("aria-pressed", "false")
    attention_filter.click()
    expect(attention_filter).to_have_attribute("aria-pressed", "true")
    expect(page.locator("[data-v02-action='employer-application-filter'][data-filter='attention']")).to_be_focused()
    expect(page.locator("#employer-application-search")).to_have_value("Кладовщик")
    expect(page.locator("#dashboard-main .employer-application-result-line")).to_contain_text("Показываем 1 из 1")
    page.locator("#employer-applications-vacancy").select_option("all")
    expect(page.locator("#employer-applications-vacancy")).to_have_value("all")
    expect(page.locator("#dashboard-main")).to_contain_text("Отклики соискателей")
    expect(page.locator("#dashboard-main")).to_contain_text("Кладовщик")
    # A mistaken tap on refusal must not update the candidate's status.
    before_refusal = page.request.get(URL + "/api/employer/applications").json()["applications"][0]
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.locator("#dashboard-main [data-v02-action='application-status'][data-status='rejected']").click()
    after_refusal = page.request.get(URL + "/api/employer/applications").json()["applications"][0]
    assert before_refusal["status"] == after_refusal["status"] == "applied"
    page.locator("#dashboard-main [data-v02-action='application-status'][data-status='reviewing']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("На рассмотрении")
    expect(page.locator("#dashboard-main [data-v02-action='application-status'][data-status='reviewing']")).to_have_count(0)
    # Fast double clicks should generate only one request and one invitation.
    interest_requests = []
    page.on("request", lambda request: interest_requests.append(request)
            if request.method == "POST" and request.url.endswith("/interest")
            and "/api/employer/applications/" in request.url else None)
    page.locator("#dashboard-main [data-v02-action='express-interest']").evaluate(
        "(button) => { button.click(); button.click(); }"
    )
    expect(page.locator("#account-action-count")).to_be_hidden()
    expect(page.locator("#dashboard-main")).to_contain_text("Запрос отправлен")
    assert len(interest_requests) == 1, f"Expected one interest POST, got {len(interest_requests)}"
    expect(page.locator("#dashboard-main")).to_contain_text("Ждём решения кандидата")
    expect(page.locator("#dashboard-main [data-v02-action='express-interest']")).to_have_count(0)
    expect(page.locator("#dashboard-main [data-v02-action='open-introductions']")).to_have_count(0)
    consent_filter = page.locator("#dashboard-main [data-v02-action='employer-application-filter'][data-filter='consent']")
    expect(consent_filter).to_contain_text("Ждём решения кандидата")
    consent_filter.click()
    expect(consent_filter).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#dashboard-main")).to_contain_text("Запрос отправлен")
    page.locator("#dashboard-main [data-v02-action='reset-application-filters']").first.click()
    expect(page.locator("#employer-applications-vacancy")).to_have_value("all")
    expect(page.locator("#dashboard-main [data-v02-action='employer-application-filter'][data-filter='all']")).to_have_attribute("aria-pressed", "true")
    page.locator(".dashboard-tabs [data-tab='vacancies']").click()
    expect(page.locator("#dashboard-main .employer-next")).to_contain_text("Ждём решения кандидата")
    expect(page.locator("#dashboard-main .item-card").filter(has_text="Кладовщик").locator(".card-eyebrow")).to_contain_text("Ждём решения кандидата")
    page.locator("#logout").click()

    login(page, "kladovshik@demo.example")
    expect(page.locator("#account-action-count")).to_have_text("1")
    expect(page.locator(".dashboard-tabs [data-tab='invitations'] .dashboard-action-count")).to_have_text("1")
    expect(page.locator("[data-dashboard-tab-select] option[value='invitations']")).to_have_text("Знакомства · 1")
    expect(page.locator("#dashboard-main")).to_contain_text("Требует вашего ответа")
    page.locator(".dashboard-tabs [data-tab='applications']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Требует вашего ответа")
    expect(page.locator("#dashboard-main")).to_contain_text("Работодатель предлагает знакомство")
    expect(page.locator(".dashboard-tabs [data-tab='security']")).to_be_visible()
    # Release 0.5.24: a candidate's specific application takes them straight
    # to the correct invitation, even when 44 other fictional cases precede it.
    real_candidate_invites = page.request.get(URL + "/api/candidate/invitations").json()["invitations"]
    real_candidate_invite = next(item for item in real_candidate_invites if item["status"] == "sent")
    candidate_intro_link = page.locator("#dashboard-main [data-v02-action='open-introductions']")
    expect(candidate_intro_link).to_have_attribute("data-invitation-id", str(real_candidate_invite["id"]))
    fictional_candidate_invites = []
    for idx in range(44):
        item = dict(real_candidate_invite)
        item["id"] = 97000 + idx
        item["title"] = f"Учебное приглашение {idx:02d}"
        item["status"] = "sent"
        item["contact_shared"] = False
        item["application_status"] = "interview"
        item["timeline"] = []
        fictional_candidate_invites.append(item)
    fictional_candidate_invites.append(real_candidate_invite)

    def fake_many_candidate_invitations(route):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"invitations": fictional_candidate_invites}, ensure_ascii=False))

    page.route("**/api/candidate/invitations", fake_many_candidate_invitations)
    candidate_intro_link.click()
    expect(page.locator("#dashboard-main")).to_contain_text("Знакомства с компаниями")
    invited_cards = page.locator("#candidate-invitation-results .candidate-introduction-card")
    expect(invited_cards).to_have_count(20)
    expect(invited_cards.first).to_have_attribute("data-invitation-id", str(real_candidate_invite["id"]))
    expect(invited_cards.first).to_be_focused()
    expect(page.locator(".candidate-introduction-result-line")).to_contain_text("Показываем 20 из 45")
    candidate_intro_next = page.locator("[data-action='more-candidate-invitations']")
    expect(candidate_intro_next).to_contain_text("20")
    candidate_intro_next.click()
    expect(invited_cards).to_have_count(40)
    # The selected introduction stays first when later pages become visible.
    expect(invited_cards.first).to_have_attribute("data-invitation-id", str(real_candidate_invite["id"]))
    expect(invited_cards.nth(20)).to_be_focused()
    expect(candidate_intro_next).to_contain_text("5")
    candidate_intro_next.click()
    expect(invited_cards).to_have_count(45)
    expect(candidate_intro_next).to_have_count(0)
    page.locator("[data-action='filter-candidate-invitations'][data-filter='all']").click()
    expect(invited_cards).to_have_count(20)
    candidate_intro_reads = []
    page.on("request", lambda request: candidate_intro_reads.append(request)
            if request.method == "GET" and request.url.endswith("/api/candidate/invitations")
            else None)
    page.locator("[data-candidate-introduction-search]").fill("учебное приглашение 43")
    expect(invited_cards).to_have_count(1)
    expect(invited_cards).to_contain_text("Учебное приглашение 43")
    assert not candidate_intro_reads, "Candidate invitation search must use cached records"
    page.locator("[data-candidate-introduction-search]").fill("несуществующее-приглашение")
    expect(invited_cards).to_have_count(0)
    expect(page.locator("#dashboard-main")).to_contain_text("По этому запросу знакомств нет")
    page.locator("[data-action='reset-candidate-invitation-filters']").click()
    expect(invited_cards).to_have_count(20)
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("""() => {
      const root = document.querySelector('#dashboard-main');
      const pager = document.querySelector('.candidate-introduction-pagination');
      return root.scrollWidth <= root.clientWidth + 3 &&
        (!pager || pager.scrollWidth <= pager.clientWidth + 3);
    }"""), "Candidate invitation queue must fit 390px"
    page.set_viewport_size({"width": 1280, "height": 800})
    page.unroute("**/api/candidate/invitations", fake_many_candidate_invitations)
    page.locator(".dashboard-tabs [data-tab='applications']").click()
    page.locator("#dashboard-main [data-v02-action='open-introductions']").click()
    expect(invited_cards).to_have_count(1)
    expect(invited_cards.first).to_be_focused()
    expect(page.locator("#dashboard-main .candidate-introduction-stage-filter [data-action='filter-candidate-invitations']")).to_have_count(5)
    expect(page.locator("#dashboard-main [data-action='filter-candidate-invitations'][data-filter='decision']")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#dashboard-main")).to_contain_text("Требует ответа")
    # Release 0.5.23: the consent POST succeeds, but the subsequent GET
    # fails once. The UI must show a confirmed receipt, not another consent CTA.
    def fail_candidate_list_once(route):
        route.fulfill(status=503, content_type="application/json",
                      body='{"detail":"Test-only read failure"}')

    candidate_responses = []
    page.on("request", lambda request: candidate_responses.append(request)
            if request.method == "POST" and "/api/candidate/invitations/" in request.url
            and request.url.endswith("/respond") else None)
    page.route("**/api/candidate/invitations", fail_candidate_list_once, times=1)
    original_candidate_intro_id = page.locator(
        "#dashboard-main .candidate-introduction-card[data-invitation-id]"
    ).first.get_attribute("data-invitation-id")
    page.locator("#dashboard-main [id^='consent-']").check()
    page.locator("#dashboard-main [data-action='accept']").click()
    saved_consent = page.locator("#dashboard-main .candidate-introduction-saved-receipt")
    expect(saved_consent).to_contain_text("Согласие отправлено")
    expect(page.locator("#dashboard-main [data-action='accept']")).to_have_count(0)
    expect(page.locator("#dashboard-main [data-action='decline']")).to_have_count(0)
    assert len(candidate_responses) == 1, "Consent response must not be posted twice"
    persisted_consent = page.request.get(URL + "/api/candidate/invitations").json()["invitations"]
    assert any(item["status"] == "accepted" for item in persisted_consent), "Consent must be saved by server"
    saved_consent.locator("[data-action='refresh-candidate-introductions']").click()
    expect(page.locator("#account-action-count")).to_be_hidden()
    expect(page.locator("#dashboard-main")).to_contain_text("Согласие отправлено")
    expect(page.locator("#dashboard-main .candidate-introduction-card[data-invitation-id='" +
                        original_candidate_intro_id + "']")).to_be_focused()
    expect(page.locator("#dashboard-main")).to_contain_text("Теперь ждём работодателя")
    expect(page.locator("#dashboard-main [data-action='filter-candidate-invitations'][data-filter='waiting']")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#dashboard-main [data-action='accept']")).to_have_count(0)
    # Separately check the declined path on a fictional invitation. Never
    # mutate real consent or personal data for this test.
    fictional_invitation = dict(persisted_consent[0])
    fictional_invitation["id"] = 96001
    fictional_invitation["status"] = "sent"
    fictional_invitation["application_status"] = "interview"
    fictional_invitation["contact_shared"] = False
    fictional_invitation["timeline"] = []
    fictional_state = {"status": "sent"}
    def fictional_candidate_list(route):
        item = dict(fictional_invitation)
        item["status"] = fictional_state["status"]
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"invitations": [item]}, ensure_ascii=False))
    def fictional_decline(route):
        fictional_state["status"] = "declined"
        route.fulfill(status=200, content_type="application/json",
                      body='{"status":"declined"}')

    page.route("**/api/candidate/invitations", fictional_candidate_list)
    page.route("**/api/candidate/invitations/96001/respond", fictional_decline)
    page.locator(".dashboard-tabs [data-tab='applications']").click()
    page.locator(".dashboard-tabs [data-tab='invitations']").click()
    expect(page.locator("#dashboard-main [data-action='decline']")).to_be_visible()
    page.route("**/api/candidate/invitations", fail_candidate_list_once, times=1)
    page.locator("#dashboard-main [data-action='decline']").evaluate(
        "(button) => { button.click(); button.click(); }"
    )
    saved_decline = page.locator("#dashboard-main .candidate-introduction-saved-receipt")
    expect(saved_decline).to_contain_text("Отказ сохранён")
    expect(saved_decline).to_contain_text("Контакты компании не переданы")
    expect(page.locator("#dashboard-main [data-action='accept']")).to_have_count(0)
    expect(page.locator("#dashboard-main [data-action='decline']")).to_have_count(0)
    assert len(candidate_responses) == 2, "Fictional decline must POST once despite double click"
    saved_decline.locator("[data-action='refresh-candidate-introductions']").click()
    expect(page.locator("#dashboard-main [data-action='filter-candidate-invitations'][data-filter='closed']")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#dashboard-main .candidate-introduction-card[data-invitation-id='96001']")).to_be_focused()
    expect(page.locator("#dashboard-main")).to_contain_text("Вы отказались")
    page.unroute("**/api/candidate/invitations", fictional_candidate_list)
    page.unroute("**/api/candidate/invitations/96001/respond", fictional_decline)
    # Return to actual API state without submitting another decision.
    page.locator(".dashboard-tabs [data-tab='applications']").click()
    expect(page.locator("#dashboard-main [data-v02-action='open-introductions']")).to_contain_text("Посмотреть знакомство")
    page.locator("#dashboard-main [data-v02-action='open-introductions']").click()
    expect(page.locator("#dashboard-main [data-action='filter-candidate-invitations'][data-filter='waiting']")).to_have_attribute("aria-pressed", "true")
    page.locator(".dashboard-tabs [data-tab='overview']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Ждём работодателя: 1")
    expect(page.locator("#dashboard-main .overview-stat-card").filter(has_text="Активные отклики").locator("strong")).to_have_text("0")
    expect(page.locator("#dashboard-main .overview-stat-card").filter(has_text="Знакомства")).to_contain_text("1")
    page.locator("#logout").click()

    login(page, "company@demo.example")
    expect(page.locator("#account-action-count")).to_have_text("1")
    expect(page.locator(".dashboard-tabs [data-tab='invitations'] .dashboard-action-count")).to_have_text("1")
    expect(page.locator("#dashboard-main")).to_contain_text("Есть согласие кандидата")
    page.locator(".dashboard-tabs [data-tab='applications']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Согласие получено")
    expect(page.locator(".dashboard-tabs [data-tab='security']")).to_be_visible()
    expect(page.locator("#dashboard-main [data-v02-action='open-introductions']")).to_contain_text("Продолжить знакомство")
    # Release 0.5.21: the link from an application opens exactly its own
    # invitation even among many fictional cases. No POST/PATCH in fixtures.
    real_invites = page.request.get(URL + "/api/employer/invitations").json()["invitations"]
    assert real_invites, "Expected an accepted invitation in the seeded flow"
    real_invite = real_invites[0]
    deep_link = page.locator("#dashboard-main [data-v02-action='open-introductions']")
    expect(deep_link).to_have_attribute("data-invitation-id", str(real_invite["id"]))
    many_invites = []
    for idx in range(44):
        item = dict(real_invite)
        item["id"] = 60000 + idx
        item["application_id"] = 61000 + idx
        item["candidate_profession"] = f"Тестовый кандидат {idx:02d}"
        item["status"] = "accepted"
        item["contact"] = None
        item["contact_shared"] = False
        item["timeline"] = []
        many_invites.append(item)
    many_invites.append(real_invite)

    def fake_employer_invitations(route):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"invitations": many_invites}, ensure_ascii=False))

    page.route("**/api/employer/invitations", fake_employer_invitations)
    deep_link.click()
    expect(page.locator("#dashboard-main [data-action='filter-employer-invitations'][data-filter='action']")).to_have_attribute("aria-pressed", "true")
    intro_cards = page.locator("#employer-invitation-results .employer-invitation-card")
    expect(intro_cards).to_have_count(20)
    expect(intro_cards.first).to_have_attribute("data-invitation-id", str(real_invite["id"]))
    expect(intro_cards.first).to_be_focused()
    expect(page.locator(".employer-invitation-result-line")).to_contain_text("Показываем 20 из 45")
    next_intro = page.locator("[data-action='more-employer-invitations']")
    expect(next_intro).to_contain_text("20")
    next_intro.click()
    expect(intro_cards).to_have_count(40)
    expect(intro_cards.nth(20)).to_be_focused()
    expect(next_intro).to_contain_text("5")
    next_intro.click()
    expect(intro_cards).to_have_count(45)
    expect(page.locator("[data-action='more-employer-invitations']")).to_have_count(0)
    page.locator("[data-action='filter-employer-invitations'][data-filter='all']").click()
    expect(intro_cards).to_have_count(20)
    employer_intro_reads = []
    page.on("request", lambda request: employer_intro_reads.append(request)
            if request.method == "GET" and request.url.endswith("/api/employer/invitations")
            else None)
    page.locator("[data-employer-introduction-search]").fill("тестовый кандидат 43")
    expect(intro_cards).to_have_count(1)
    expect(intro_cards).to_contain_text("Тестовый кандидат 43")
    assert not employer_intro_reads, "Invitation search must use already loaded records"
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("""() => {
      const root = document.querySelector('#dashboard-main');
      return root.scrollWidth <= root.clientWidth + 3;
    }"""), "Employer invitation pagination must fit 390px"
    page.set_viewport_size({"width": 1280, "height": 800})
    page.unroute("**/api/employer/invitations", fake_employer_invitations)
    # Reopen from the original application to discard fictional cached cases.
    page.locator(".dashboard-tabs [data-tab='applications']").click()
    page.locator("#dashboard-main [data-v02-action='open-introductions']").click()
    expect(page.locator("#dashboard-main [data-action='filter-employer-invitations'][data-filter='action']")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#dashboard-main")).to_contain_text("Знакомства и контакты")
    expect(page.locator("#dashboard-main")).to_contain_text("Открыть контакт кандидата")
    expect(intro_cards).to_have_count(1)
    expect(intro_cards.first).to_be_focused()
    page.locator(".dashboard-tabs [data-tab='vacancies']").click()
    page.locator("#dashboard-main .item-card").filter(has_text="Кладовщик").locator("[data-action='matches']").click()
    expect(page.locator("#employer-matches .candidate-match-card")).to_be_visible()
    expect(page.locator("#employer-matches")).to_contain_text("Согласие получено")
    expect(page.locator("#employer-matches")).to_contain_text("%")
    employer_match = page.locator("#employer-matches .candidate-match-card").first
    expect(employer_match.locator(".candidate-match-explanation")).to_be_visible()
    employer_match.locator(".candidate-resume-details summary").click()
    expect(employer_match.locator(".candidate-resume-details")).to_contain_text("Старший кладовщик")
    expect(employer_match.locator(".candidate-resume-details")).to_contain_text("Среднее профессиональное")
    expect(employer_match.locator(".candidate-resume-details")).to_contain_text("Управление складом в 1С")
    expect(employer_match.locator(".candidate-resume-details")).to_contain_text("не проверен")
    expect(employer_match.locator(".candidate-resume-details")).not_to_contain_text("kladovshik@demo.example")
    employer_match.locator(".candidate-match-explanation summary").click()
    expect(employer_match.locator(".match-factor-row")).to_have_count(6)
    expect(employer_match).to_contain_text("Возраст не используется")
    page.locator(".dashboard-tabs [data-tab='invitations']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Есть согласие")
    expect(page.locator("#dashboard-main [data-action='filter-employer-invitations']")).to_have_count(5)
    expect(page.locator("#dashboard-main [data-action='filter-employer-invitations'][data-filter='all']")).to_have_attribute("aria-pressed", "true")
    action_filter = page.locator("#dashboard-main [data-action='filter-employer-invitations'][data-filter='action']")
    expect(action_filter).to_contain_text("Есть согласие")
    expect(page.locator("#dashboard-main .employer-invitation-result-line")).to_contain_text("Показываем")
    expect(page.locator("#dashboard-main")).to_contain_text("Открыть контакт кандидата")
    # Release 0.5.22: POST succeeds, but the *following GET* fails once.
    # Show a durable server-confirmed receipt, never offer the POST again.
    def fail_introduction_refresh_once(route):
        route.fulfill(status=503, content_type="application/json",
                      body='{"detail":"Test-only temporary refresh failure"}')
    payment_posts = []
    page.on("request", lambda request: payment_posts.append(request)
            if request.method == "POST" and request.url.endswith("/demo-pay") else None)
    page.route("**/api/employer/invitations", fail_introduction_refresh_once, times=1)
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#dashboard-main [data-action='demo-pay']").click()
    receipt = page.locator("#dashboard-main .employer-introduction-saved-receipt")
    expect(receipt).to_contain_text("Контакт открыт (демо)")
    expect(page.locator("#dashboard-main [data-action='demo-pay']")).to_have_count(0)
    assert len(payment_posts) == 1, "Confirmed demo action must not be sent twice"
    persisted_introductions = page.request.get(URL + "/api/employer/invitations").json()["invitations"]
    assert any(item.get("contact_shared") for item in persisted_introductions), "Server must retain opened contact"
    receipt.locator("[data-action='refresh-employer-introductions']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("КОНТАКТ ОТКРЫТ · ДЕМО")
    expect(page.locator("#dashboard-main")).to_contain_text("Знакомство состоялось")
    expect(page.locator("#dashboard-main .employer-invitation-card").first).to_be_focused()
    expect(page.locator("#dashboard-main")).to_contain_text("Следующий шаг — свяжитесь с кандидатом")
    expect(page.locator("#dashboard-main .invitation-vacancy-context")).to_contain_text("Кладовщик")
    expect(page.locator("#dashboard-main .invitation-last-activity")).to_contain_text("Последнее действие")
    expect(page.locator("#dashboard-main .invitation-last-activity")).to_contain_text("Знакомство состоялось")
    last_activity_time = page.locator("#dashboard-main .invitation-last-activity small").inner_text()
    assert re.search(r"\d{2}\.\d{2}\.\d{4} · \d{2}:\d{2}", last_activity_time), last_activity_time
    page.locator(".dashboard-tabs [data-tab='overview']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Зафиксируйте итог знакомства")
    expect(page.locator("#dashboard-main .overview-stat-card").filter(has_text="Ждут итога").locator("strong")).to_have_text("1")
    page.locator("#dashboard-main .overview-priority [data-action='open-employer-invitations'][data-filter='introduced']").click()
    expect(page.locator("#dashboard-main [data-action='filter-employer-invitations'][data-filter='introduced']")).to_have_attribute("aria-pressed", "true")
    page.locator(".dashboard-tabs [data-tab='vacancies']").click()
    expect(page.locator("#dashboard-main .employer-next")).to_contain_text("Зафиксируйте итог знакомства")
    vacancy_card = page.locator("#dashboard-main .employer-vacancy-card").filter(has_text="Кладовщик")
    expect(vacancy_card).to_contain_text("Нужно зафиксировать итог")
    expect(vacancy_card.locator(".vacancy-pipeline-mini")).to_contain_text("Ждут итога")
    expect(vacancy_card.locator(".vacancy-pipeline-mini")).to_contain_text("Выбраны")
    expect(vacancy_card.locator(".vacancy-pipeline-mini")).to_contain_text("Не договорились")
    outcome_from_vacancy = vacancy_card.locator("[data-action='open-employer-invitations'][data-filter='introduced']")
    expect(outcome_from_vacancy).to_contain_text("Зафиксировать итог")
    vacancy_id = outcome_from_vacancy.get_attribute("data-vacancy-id")
    assert vacancy_id
    outcome_from_vacancy.click()
    expect(page.locator("#dashboard-main [data-action='filter-employer-invitations'][data-filter='introduced']")).to_have_attribute("aria-pressed", "true")
    introduction_vacancy_filter = page.locator("#dashboard-main [data-employer-introduction-vacancy-filter]")
    expect(introduction_vacancy_filter).to_have_value(vacancy_id)
    expect(introduction_vacancy_filter.locator("option:checked")).to_have_text("Кладовщик")
    reset_intro_filters = page.locator("#dashboard-main [data-action='reset-employer-invitation-filters']")
    expect(reset_intro_filters).to_be_visible()
    reset_intro_filters.click()
    expect(page.locator("#dashboard-main [data-employer-introduction-vacancy-filter]")).to_have_value("all")
    expect(page.locator("#dashboard-main [data-action='filter-employer-invitations'][data-filter='all']")).to_have_attribute("aria-pressed", "true")
    page.locator("#dashboard-main [data-employer-introduction-vacancy-filter]").select_option(vacancy_id)
    page.locator("#dashboard-main [data-action='filter-employer-invitations'][data-filter='introduced']").click()
    expect(page.locator("#dashboard-main [data-employer-introduction-vacancy-filter]")).to_have_value(vacancy_id)
    expect(page.locator("#dashboard-main [data-action='filter-employer-invitations'][data-filter='introduced']")).to_have_attribute("aria-pressed", "true")
    intro_search = page.locator("#dashboard-main [data-employer-introduction-search]")
    expect(intro_search).to_be_visible()
    intro_search.fill("клад")
    expect(page.locator("#dashboard-main .employer-invitation-card")).to_have_count(1)
    expect(page.locator("#dashboard-main .employer-invitation-card")).to_contain_text("Кладовщик")
    expect(intro_search).to_be_focused()
    intro_search.fill("точно-нет-такого-кандидата")
    expect(page.locator("#dashboard-main")).to_contain_text("По этому запросу знакомств нет")
    expect(page.locator("#dashboard-main [data-action='reset-employer-invitation-filters']")).to_have_count(1)
    page.locator("#dashboard-main [data-action='reset-employer-invitation-filters']").click()
    expect(page.locator("#dashboard-main [data-employer-introduction-search]")).to_have_value("")
    expect(page.locator("#dashboard-main [data-employer-introduction-vacancy-filter]")).to_have_value("all")
    page.locator("#dashboard-main [data-employer-introduction-vacancy-filter]").select_option(vacancy_id)
    page.locator("#dashboard-main [data-action='filter-employer-invitations'][data-filter='introduced']").click()
    expect(page.locator("#dashboard-main .contact-card-actions a[href^='mailto:']")).to_have_count(1)
    expect(page.locator("#dashboard-main [data-action='introduction-outcome'][data-status='hired']")).to_be_visible()
    expect(page.locator("#dashboard-main [data-action='introduction-outcome'][data-status='rejected']")).to_be_visible()
    introduced_filter = page.locator("#dashboard-main [data-action='filter-employer-invitations'][data-filter='introduced']")
    expect(introduced_filter).to_contain_text("Ждут итога")
    expect(introduced_filter).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#dashboard-main")).to_contain_text("История взаимодействия")
    outcome_dialog_messages = []
    page.route("**/api/employer/invitations", fail_introduction_refresh_once, times=1)
    outcome_posts = []
    page.on("request", lambda request: outcome_posts.append(request)
            if request.method == "PATCH" and "/api/employer/applications/" in request.url
            and request.url.endswith("/status") else None)
    page.once("dialog", lambda dialog: (outcome_dialog_messages.append(dialog.message), dialog.accept()))
    page.locator("#dashboard-main [data-action='introduction-outcome'][data-status='hired']").click()
    assert outcome_dialog_messages and "не подтверждение трудоустройства" in outcome_dialog_messages[0], outcome_dialog_messages
    outcome_receipt = page.locator("#dashboard-main .employer-introduction-saved-receipt")
    expect(outcome_receipt).to_contain_text("Положительный итог сохранён")
    expect(page.locator("#dashboard-main [data-action='introduction-outcome']")).to_have_count(0)
    assert len(outcome_posts) == 1, "Final result must be saved once only"
    persisted_final = page.request.get(URL + "/api/employer/applications").json()["applications"]
    assert any(item.get("status") == "hired" for item in persisted_final), "Server must keep final outcome"
    outcome_receipt.locator("[data-action='refresh-employer-introductions']").click()
    expect(page.locator("#dashboard-main [data-action='filter-employer-invitations'][data-filter='closed']")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#dashboard-main")).to_contain_text("Положительный итог")
    focused_completed_card = page.locator("#dashboard-main .employer-invitation-card[data-application-id]")
    expect(focused_completed_card.first).to_be_focused()
    completed_summary = page.locator("#dashboard-main .completed-introduction-summary")
    expect(completed_summary).to_contain_text("Выбраны")
    expect(completed_summary).to_contain_text("Не договорились")
    expect(completed_summary.locator("span").filter(has_text="Выбраны").locator("strong")).to_have_text("1")
    expect(completed_summary.locator("span").filter(has_text="Не договорились").locator("strong")).to_have_text("0")
    expect(page.locator("#dashboard-main")).to_contain_text("КОНТАКТ СОХРАНЁН · ДЕМО")
    expect(page.locator("#dashboard-main .contact-card-actions a[href^='mailto:']")).to_have_count(1)
    expect(page.locator("#dashboard-main [data-action='introduction-outcome']")).to_have_count(0)
    expect(page.locator("#dashboard-main .interaction-stage span")).to_have_count(4)
    expect(page.locator("#dashboard-main .interaction-stage span").last).to_contain_text("Итог")
    page.locator(".dashboard-tabs [data-tab='overview']").click()
    expect(page.locator("#dashboard-main .overview-stat-card").filter(has_text="Ждут итога").locator("strong")).to_have_text("0")
    outcome_step = page.locator("#dashboard-main .overview-funnel-steps > div").filter(has_text="Итоги")
    expect(outcome_step.locator("strong")).to_have_text("1")
    hired_summary = page.locator("#dashboard-main .employer-outcome-summary > div").filter(has_text="Положительные итоги")
    rejected_summary = page.locator("#dashboard-main .employer-outcome-summary > div").filter(has_text="Не договорились")
    waiting_summary = page.locator("#dashboard-main .employer-outcome-summary > div").filter(has_text="Ждут итога")
    expect(hired_summary.locator("strong")).to_have_text("1")
    expect(rejected_summary.locator("strong")).to_have_text("0")
    expect(waiting_summary.locator("strong")).to_have_text("0")
    expect(page.locator("#dashboard-main .employer-outcome-rate")).to_contain_text("100%")
    page.locator(".dashboard-tabs [data-tab='vacancies']").click()
    expect(page.locator("#dashboard-main .employer-next")).not_to_contain_text("Зафиксируйте итог знакомства")
    completed_vacancy_card = page.locator("#dashboard-main .employer-vacancy-card").filter(has_text="Кладовщик")
    expect(completed_vacancy_card).not_to_contain_text("Нужно зафиксировать итог")
    completed_outcome_stat = completed_vacancy_card.locator(".vacancy-pipeline-mini > span").filter(has_text="Ждут итога")
    completed_hired_stat = completed_vacancy_card.locator(".vacancy-pipeline-mini > span").filter(has_text="Выбраны")
    completed_rejected_stat = completed_vacancy_card.locator(".vacancy-pipeline-mini > span").filter(has_text="Не договорились")
    expect(completed_outcome_stat.locator("strong")).to_have_text("0")
    expect(completed_hired_stat.locator("strong")).to_have_text("1")
    expect(completed_rejected_stat.locator("strong")).to_have_text("0")
    page.locator(".dashboard-tabs [data-tab='applications']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Положительный итог")
    expect(page.locator("#dashboard-main .application-flow-legend")).to_contain_text("5. Итог")
    expect(page.locator("#dashboard-main [data-v02-action='open-introductions']")).to_contain_text("Открыть завершённое знакомство")
    expect(page.locator("#dashboard-main")).to_contain_text("Приглашение отправлено")
    expect(page.locator("#dashboard-main")).to_contain_text("Согласие получено")
    expect(page.locator("#dashboard-main")).to_contain_text("Знакомство состоялось (демо)")
    expect(page.locator("#dashboard-main")).to_contain_text("Положительный итог")
    expect(page.locator("#dashboard-main [data-v02-action='application-status']")).to_have_count(0)

    # Final employer outcome flow must remain usable on a narrow phone viewport.
    page.set_viewport_size({"width": 390, "height": 844})
    employer_mobile_section = page.locator("[data-dashboard-tab-select]")
    expect(employer_mobile_section).to_be_visible()
    expect(page.locator(".dashboard-tabs")).to_be_hidden()
    employer_mobile_section.select_option("invitations")
    expect(page.locator("#dashboard-main")).to_contain_text("Положительный итог")
    expect(page.locator("#dashboard-main [data-employer-introduction-vacancy-filter]")).to_be_visible()
    expect(page.locator("#dashboard-main [data-employer-introduction-search]")).to_be_visible()
    expect(page.locator("#dashboard-main")).to_contain_text("КОНТАКТ СОХРАНЁН · ДЕМО")
    expect(page.locator("#dashboard-main .invitation-last-activity")).to_be_visible()
    assert page.evaluate("""() => {
      const grid = document.querySelector('.employer-invitation-stage-filter');
      return grid && getComputedStyle(grid).gridTemplateColumns.trim().split(/\\s+/).length === 2;
    }"""), "Employer introduction filters should remain two columns at 390px"
    assert page.evaluate("""() => {
      const element = document.querySelector('#dashboard-main');
      return element.scrollWidth <= element.clientWidth + 3;
    }"""), "Completed introduction must fit mobile width"
    employer_mobile_section = page.locator("[data-dashboard-tab-select]")
    employer_mobile_section.select_option("vacancies")
    mobile_vacancy = page.locator("#dashboard-main .employer-vacancy-card").filter(has_text="Кладовщик")
    expect(mobile_vacancy.locator(".vacancy-pipeline-mini > span")).to_have_count(4)
    assert page.evaluate("""() => {
      const element = document.querySelector('#dashboard-main');
      return element.scrollWidth <= element.clientWidth + 3;
    }"""), "Employer vacancy outcome analytics must fit mobile width"
    page.set_viewport_size({"width": 1280, "height": 800})
    page.locator("#logout").click()

    login(page, "kladovshik@demo.example")
    expect(page.locator("#dashboard-main .candidate-outcome-alert")).to_contain_text("Положительный итог знакомства")
    outcome_button = page.locator("#dashboard-main .candidate-outcome-alert [data-action='open-candidate-invitations'][data-filter='closed']")
    expect(outcome_button).to_contain_text("Посмотреть итог")
    outcome_button.click()
    expect(page.locator("#dashboard-main [data-action='filter-candidate-invitations'][data-filter='closed']")).to_have_attribute("aria-pressed", "true")
    page.locator(".dashboard-tabs [data-tab='applications']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Положительный итог знакомства")
    expect(page.locator("#dashboard-main .interaction-stage span")).to_have_count(5)
    expect(page.locator("#dashboard-main .interaction-stage span").last).to_contain_text("Итог")
    expect(page.locator("#dashboard-main [data-v02-action='withdraw']")).to_have_count(0)
    expect(page.locator(".dashboard-tabs [data-tab='security']")).to_be_visible()
    expect(page.locator("#dashboard-main [data-v02-action='open-introductions']")).to_contain_text("Открыть завершённое знакомство")
    page.locator("#dashboard-main [data-v02-action='open-introductions']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Знакомства с компаниями")
    expect(page.locator("#dashboard-main [data-action='filter-candidate-invitations'][data-filter='closed']")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#dashboard-main")).to_contain_text("Положительный итог знакомства")
    expect(page.locator("#dashboard-main")).to_contain_text("Это не подтверждение трудоустройства")
    candidate_intro_search = page.locator("#dashboard-main [data-candidate-introduction-search]")
    expect(candidate_intro_search).to_be_visible()
    candidate_intro_search.fill("клад")
    expect(page.locator("#dashboard-main .candidate-introduction-card")).to_have_count(1)
    expect(page.locator("#dashboard-main .candidate-introduction-card")).to_contain_text("Кладовщик")
    expect(candidate_intro_search).to_be_focused()
    candidate_intro_search.fill("точно-нет-такой-компании")
    expect(page.locator("#dashboard-main")).to_contain_text("По этому запросу знакомств нет")
    expect(page.locator("#dashboard-main [data-action='reset-candidate-invitation-filters']")).to_have_count(1)
    page.locator("#dashboard-main [data-action='reset-candidate-invitation-filters']").click()
    expect(page.locator("#dashboard-main [data-candidate-introduction-search]")).to_have_value("")
    expect(page.locator("#dashboard-main [data-action='filter-candidate-invitations'][data-filter='all']")).to_have_attribute("aria-pressed", "true")
    page.locator("#dashboard-main [data-action='filter-candidate-invitations'][data-filter='closed']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Положительный итог знакомства")
    page.set_viewport_size({"width": 390, "height": 844})
    expect(page.locator("#dashboard-main [data-candidate-introduction-search]")).to_be_visible()
    assert page.evaluate("""() => {
      const grid = document.querySelector('.candidate-introduction-stage-filter');
      return grid && getComputedStyle(grid).gridTemplateColumns.trim().split(/\\s+/).length === 2;
    }"""), "Candidate introduction filters should remain two columns at 390px"
    assert page.evaluate("""() => {
      const element = document.querySelector('#dashboard-main');
      return element.scrollWidth <= element.clientWidth + 3;
    }"""), "Candidate completed introduction must fit mobile width"
    page.set_viewport_size({"width": 1280, "height": 800})
    page.locator("#logout").click()

    # Accountant must not receive an engineer recommendation merely
    # because both profiles mention Excel.
    login(page, "buhgalter@demo.example")
    page.locator(".dashboard-tabs [data-tab='offers']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Бухгалтер")
    expect(page.locator("#dashboard-main > .panel:first-child .dashboard-list")).not_to_contain_text("Инженер по эксплуатации")
    expect(page.locator("#dashboard-main [data-v02-action='apply']")).to_have_count(1)
    page.locator("#dashboard-main [data-v02-action='apply']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Отклик: Отправлен")
    expect(page.locator("#dashboard-main [data-v02-action='apply']")).to_have_count(0)
    # Reproduce the real screenshot: account has an existing application
    # before reloading the website and opening recommended jobs again.
    page.reload(wait_until="networkidle")
    expect(page.locator(".product-strip")).to_contain_text("СТАЖНО")
    page.locator(".dashboard-tabs [data-tab='offers']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Отклик: Отправлен")
    expect(page.locator("#dashboard-main [data-v02-action='apply']")).to_have_count(0)
    page.locator("#dashboard-main [data-v02-action='see-applications']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("История откликов")
    page.locator("#logout").click()

    login(page, "admin@demo.example")
    expect(page.locator("#admin-stats")).to_contain_text("Активные отклики")
    expect(page.locator("#admin-stats")).to_contain_text("Отозванные отклики")
    expect(page.locator("#admin-growth-stats")).to_contain_text("Переходы к вакансиям")
    expect(page.locator("#admin-growth-articles tbody tr")).to_have_count(4)

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
    expect(page.locator(".mobile-quick-nav")).to_be_hidden()
    expect(page.locator("#mobile-member-actions")).to_be_visible()
    expect(page.locator("#admin-v02-results")).to_be_visible()
    page.locator("#logout").click()
    login(page, "kladovshik@demo.example")
    mobile_section = page.locator("[data-dashboard-tab-select]")
    expect(mobile_section).to_be_visible()
    expect(mobile_section.locator("option")).to_have_count(9)
    expect(mobile_section).to_have_value("overview")
    expect(page.locator(".dashboard-tabs")).to_be_hidden()
    assert mobile_section.bounding_box()["height"] >= 44
    expect(page.locator("#dashboard-main .overview-stat-card")).to_have_count(4)
    expect(page.locator("#dashboard-main .candidate-outcome-alert")).to_contain_text("Положительный итог знакомства")
    assert page.evaluate("""() => {
      const element = document.querySelector('#dashboard-main');
      return element.scrollWidth <= element.clientWidth + 3;
    }"""), "Candidate final outcome alert must fit mobile width"
    mobile_section.select_option("profile")
    expect(page.locator("#profile-form")).to_be_visible()
    page.locator("[data-dashboard-tab-select]").select_option("applications")
    expect(page.locator("#dashboard-main")).to_contain_text("Положительный итог знакомства")

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
    jobs_after_edit_response = page.request.get(URL + "/api/employer/vacancies")
    assert jobs_after_edit_response.status == 200, f"After editing, vacancy listing returned HTTP {jobs_after_edit_response.status}: {jobs_after_edit_response.text()[:700]}"
    jobs_after_edit = jobs_after_edit_response.json()["jobs"]
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
    expect(page.locator("#vacancy-form")).to_be_visible()
    expect(page.locator("#vacancy-form")).to_have_attribute("data-revision", stale["revision"])
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
    expect(page.locator("#vacancy-form")).to_have_attribute("data-revision", stale["revision"])
    page.locator("#vacancy-show-preview").click()
    with page.expect_response(lambda response: (
        response.url.endswith(f"/api/employer/vacancies/{stale['id']}") and
        response.request.method == "PATCH"
    )) as conflict:
        page.locator("#vacancy-publish").click()
    assert conflict.value.status == 409, conflict.value.text()
    comparison = page.locator("[data-published-conflict-panel]")
    expect(comparison).to_be_visible()
    expect(comparison).to_contain_text("Зарплата от")
    expect(comparison).to_contain_text(str(competing["salary_min"]))
    expect(comparison.locator('[data-published-conflict-choice="salary_min"]')).to_have_value("server")
    expect(page.locator("#vacancy-publish")).to_be_disabled()
    # Applying a selection does NOT change the published vacancy or notify
    # candidates; it stages the server values for a new explicit preview.
    comparison.locator('[data-action="apply-published-conflict"]').click()
    expect(page.locator("[data-published-conflict-panel]")).to_have_count(0)
    expect(page.locator("#vacancy-salary-min")).to_have_value(str(competing["salary_min"]))
    expect(page.locator("#vacancy-publish")).to_be_disabled()
    assert next(job for job in page.request.get(
        URL + "/api/employer/vacancies").json()["jobs"]
        if job["id"] == stale["id"])["salary_min"] == competing["salary_min"]
    # Discarding the staged edit is a deliberate action.
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("[data-action='cancel-job-edit']").click()
    expect(page.locator("#dashboard-main")).to_contain_text("Мои вакансии")
    # The employer can inspect the exact history of the same vacancy, without
    # seeing candidate identities or individual read receipts.
    vacancy_card = page.locator(
        f".employer-vacancy-card[data-employer-vacancy-id='{old_job['id']}']"
    )
    history_button = vacancy_card.locator("[data-action='vacancy-history']")
    expect(history_button).to_have_attribute("aria-expanded", "false")
    history_button.click()
    history_section = vacancy_card.locator(".employer-vacancy-history")
    expect(history_section).to_be_visible()
    expect(history_button).to_have_attribute("aria-expanded", "true")
    expect(history_section).to_contain_text("Всего изменений: 2")
    expect(history_section).to_contain_text("Получателей в личных кабинетах")
    expect(history_section).to_contain_text("Зарплата от")
    assert page.evaluate("""() => {
      const element = document.querySelector('.employer-vacancy-history');
      return element.scrollWidth <= element.clientWidth + 3;
    }"""), "Change timeline must fit mobile viewport"
    # More than twenty events remain accessible without navigating away.
    sample_history = page.request.get(
        URL + f"/api/employer/vacancies/{old_job['id']}/updates"
    ).json()
    history_template = sample_history["updates"][0]
    first_history = dict(sample_history, total_count=21, has_more=True,
                         next_cursor=2000, updates=[
                             dict(history_template, id=2020-i) for i in range(20)])
    second_history = dict(sample_history, total_count=21, has_more=False,
                          next_cursor=None, updates=[dict(history_template,id=1999)])
    def paginated_employer_history(route):
        result = second_history if "before_id=2000" in route.request.url else first_history
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(result, ensure_ascii=False))
    page.route(
        f"**/api/employer/vacancies/{old_job['id']}/updates*",
        paginated_employer_history
    )
    history_button.click()
    history_button.click()
    expect(history_section.locator(".employer-vacancy-history-entry")).to_have_count(20)
    expect(history_section.locator("[data-action='more-vacancy-history']")).to_be_visible()
    history_section.locator("[data-action='more-vacancy-history']").click()
    expect(history_section.locator(".employer-vacancy-history-entry")).to_have_count(21)
    expect(history_section.locator("[data-action='more-vacancy-history']")).to_have_count(0)
    ids = history_section.locator("[data-history-update-id]").evaluate_all(
        "(items) => items.map(item => item.dataset.historyUpdateId)"
    )
    assert len(ids) == len(set(ids)) == 21
    page.unroute(
        f"**/api/employer/vacancies/{old_job['id']}/updates*",
        paginated_employer_history
    )
    history_button.click()
    expect(history_section).to_be_hidden()
    expect(history_button).to_have_attribute("aria-expanded", "false")

    # A candidate who had already applied sees changes to the older vacancy.
    page.locator("#logout").click()
    login(page, "kladovshik@demo.example")
    page.locator("[data-dashboard-tab-select]").select_option("applications")
    expect(page.locator(".vacancy-update-banner")).to_be_visible()
    page.locator("[data-dashboard-tab-select]").select_option("changes")
    expect(page.locator(".vacancy-change-item")).to_have_count(2)
    expect(page.locator(".vacancy-changes-list").first).to_contain_text("Зарплата от")
    expect(page.locator(".vacancy-change-next").first).to_contain_text("Следующий шаг")
    expect(page.locator(".vacancy-change-item").first.locator(
        "[data-tab='applications']"
    )).to_be_visible()
    # Structured descriptions are compared section by section; legacy free
    # text is kept whole rather than lost or silently truncated.
    assert page.evaluate("""() => {
      const before = 'Обязанности:\\nУчёт\\n\\nТребования:\\n1С\\n\\nУсловия работы:\\n2/2';
      const after = before.replace('2/2','3/3');
      const details = window.StazhnoVacancyChanges.details({
        description:{before,after}
      });
      return details.length === 1 && details[0].label === 'Условия работы'
        && details[0].before === '2/2' && details[0].after === '3/3';
    }"""), "Structured vacancy change details should compare only modified fields"
    assert page.evaluate("""() => {
      const element = document.querySelector('#dashboard-main');
      return element.scrollWidth <= element.clientWidth + 3;
    }"""), "Changes list must fit mobile width"
    notices = page.request.get(URL + "/api/candidate/vacancy-updates").json()
    assert notices["unread_count"] == 2
    # Visiting the changes page does not mark notices as read.
    expect(page.locator("#account-action-count")).to_have_text("2")
    expect(page.locator(".dashboard-tabs [data-tab='changes'] .dashboard-action-count")).to_have_text("2")
    with page.expect_response(lambda response: (
        "/api/candidate/vacancy-updates/" in response.url and
        response.url.endswith("/read") and response.request.method == "POST"
    )) as read_reply:
        page.locator("[data-v02-action='mark-vacancy-update-read']").first.click()
    assert read_reply.value.status == 200, read_reply.value.text()
    expect(page.locator(".vacancy-change-item")).to_have_count(2)
    expect(page.locator(".vacancy-change-item").first).to_contain_text("Прочитано")
    refreshed = page.request.get(URL + "/api/candidate/vacancy-updates").json()
    assert refreshed["unread_count"] == 1
    expect(page.locator("#account-action-count")).to_have_text("1")
    expect(page.locator(".dashboard-tabs [data-tab='changes'] .dashboard-action-count")).to_have_text("1")
    # Read/unread filters use the server and never mark items read by viewing.
    page.locator('[data-v02-action="filter-vacancy-updates"][data-filter="unread"]').click()
    expect(page.locator(".vacancy-change-item")).to_have_count(1)
    expect(page.locator('[data-v02-action="filter-vacancy-updates"][data-filter="unread"]')).to_have_attribute("aria-pressed","true")
    page.locator('[data-v02-action="filter-vacancy-updates"][data-filter="read"]').click()
    expect(page.locator(".vacancy-change-item")).to_have_count(1)
    expect(page.locator(".vacancy-change-item").first).to_contain_text("Прочитано")
    page.locator('[data-v02-action="filter-vacancy-updates"][data-filter="all"]').click()
    expect(page.locator(".vacancy-change-item")).to_have_count(2)
    assert page.request.get(URL + "/api/candidate/vacancy-updates").json()["unread_count"] == 1

    # Stub only the visual pagination window: backend pagination and ownership
    # are covered independently by the 125-event API regression.
    samples = page.request.get(URL + "/api/candidate/vacancy-updates").json()
    template = samples["updates"][0]
    fake_first = dict(samples, total_count=21, read_count=20, unread_count=1,
                      has_more=True, next_cursor=2000,
                      updates=[dict(template, id=2020-i) for i in range(20)])
    fake_second = dict(samples, total_count=21, read_count=20, unread_count=1,
                       has_more=False, next_cursor=None,
                       updates=[dict(template, id=1999)])
    def paginated_changes(route):
        if "filter=all" not in route.request.url:
            route.continue_()
            return
        result = fake_second if "before_id=2000" in route.request.url else fake_first
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(result, ensure_ascii=False))
    page.route("**/api/candidate/vacancy-updates?*", paginated_changes)
    page.locator('[data-v02-action="filter-vacancy-updates"][data-filter="all"]').click()
    expect(page.locator(".vacancy-change-item")).to_have_count(20)
    page.locator('[data-v02-action="more-vacancy-updates"]').click()
    expect(page.locator(".vacancy-change-item")).to_have_count(21)
    expect(page.locator('[data-v02-action="more-vacancy-updates"]')).to_have_count(0)
    ids = page.locator(".vacancy-change-item").evaluate_all(
        "(items) => items.map(item => item.dataset.vacancyUpdateId)"
    )
    assert len(ids) == len(set(ids)) == 21
    page.unroute("**/api/candidate/vacancy-updates?*", paginated_changes)

    if console_errors:
        raise AssertionError("Uncaught browser errors: " + " | ".join(console_errors))


def main():
    with tempfile.TemporaryDirectory(prefix="opytno-smoke-") as tmp:
        env = dict(os.environ, OPYT50_DB_PATH=str(Path(tmp) / "demo.db"),
                   OPYT50_PREVIEW_SEED_DEMO="0", OPYT50_COOKIE_SECURE="0")
        subprocess.run([sys.executable, "scripts/seed_demo.py", "--db", env["OPYT50_DB_PATH"]],
                       cwd=ROOT, env=env, check=True, capture_output=True)
        server_log_path = Path(tmp) / "uvicorn.log"
        server_log = server_log_path.open("w", encoding="utf-8")
        server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app",
                                   "--host", "127.0.0.1", "--port", "8765"],
                                  cwd=ROOT, env=env, stdout=server_log, stderr=subprocess.STDOUT)
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
                        server_log.flush()
                        print("Uvicorn server error log:\n" + server_log_path.read_text(encoding="utf-8")[-12000:],
                              file=sys.stderr)
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
            finally:
                server_log.close()
    print("Browser smoke: 0.3 vacancy preview/edit, legacy preservation, conflict guard and 0.2 regression PASSED")


if __name__ == "__main__":
    main()
