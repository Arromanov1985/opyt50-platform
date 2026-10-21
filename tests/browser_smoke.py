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
    print("Browser smoke: 0.3 guest browsing, readable UX, forms, mobile navigation and 0.2 regression PASSED")


if __name__ == "__main__":
    main()
