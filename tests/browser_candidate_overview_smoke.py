"""Browser smoke for the candidate career overview."""
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect


ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8767"
HEADERS = {"X-Requested-With": "OPYT50"}


def seed_readiness_profiles(db_file):
    # Registration may leave a partial profile. Keep optional fields complete
    # so the old percentage gate cannot accidentally pass these required fields.
    with sqlite3.connect(db_file) as db:
        for email, profession, city in (
            ("buhgalter@demo.example", "", "Москва"),
            ("inzhen@demo.example", "Инженер", ""),
        ):
            user_id = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()[0]
            db.execute(
                "UPDATE candidate_profiles SET profession=?,city=?,about=? WHERE user_id=?",
                (profession, city, "Демонстрационный опыт для проверки кабинета.", user_id),
            )
            db.execute(
                "INSERT INTO account_controls(user_id,email_verified) VALUES(?,1) "
                "ON CONFLICT(user_id) DO UPDATE SET email_verified=1", (user_id,),
            )


def exercise_application_destinations(page, jobs):
    # Two real applications make the older target distinguishable from the
    # default newest-first queue. They use this test's existing temporary DB.
    applications = []
    for title in ("Бухгалтер", "Инженер по эксплуатации"):
        vacancy_id = next(job["id"] for job in jobs if job["title"] == title)
        response = page.request.post(
            URL + "/api/candidate/applications", headers=HEADERS,
            data={"vacancy_id": vacancy_id},
        )
        assert response.status == 201, response.text()
        applications.append(response.json()["id"])
    target_id = applications[0]
    before = page.request.get(URL + "/api/candidate/applications").json()["applications"]
    stages = page.locator("#dashboard-main .candidate-stage-overview")
    expect(stages).to_be_visible()
    assert sum(int(card.locator("strong").inner_text()) for card in
               stages.locator(".candidate-stage-card").all()) == len({row["id"] for row in before})
    stages.locator('[data-filter="active"]').click()
    expect(page.locator(".candidate-application-toolbar")).to_be_visible()
    expect(page.locator('[data-candidate-app-action="filter"][data-filter="active"]')).to_have_attribute("aria-pressed","true")
    selector = page.locator("[data-dashboard-tab-select]")
    selector.select_option("overview")
    expect(page.locator(".candidate-stage-overview")).to_be_visible()
    selector.select_option("applications")
    expect(page.locator(".candidate-application-card:visible").first).to_have_attribute(
        "data-application-id", str(applications[1])
    )
    page.locator("#candidate-application-search").fill("несуществующая вакансия")
    page.locator("[data-candidate-app-action='filter'][data-filter='closed']").click()
    expect(page.locator(".candidate-application-card:visible")).to_have_count(0)
    selector.select_option("overview")
    page.locator(
        f"[data-v02-action='open-candidate-applications'][data-application-id='{target_id}']"
    ).click()
    expect(page.locator("#candidate-application-search")).to_have_value("")
    expect(page.locator("[data-candidate-app-action='filter'][data-filter='all']")).to_have_attribute(
        "aria-pressed", "true"
    )
    target = page.locator(f".candidate-application-card[data-application-id='{target_id}']")
    expect(target).to_be_visible()
    expect(target).to_be_focused()
    expect(page.locator(".candidate-application-card:visible").first).to_have_attribute(
        "data-application-id", str(target_id)
    )
    assert page.request.get(URL + "/api/candidate/applications").json()["applications"] == before

    assert page.request.post(URL + "/api/logout", headers=HEADERS).status == 200
    login(page, "company@demo.example")
    selector.select_option("applications")
    stale_vacancy = next(job["id"] for job in jobs if job["title"] == "Кладовщик")
    page.locator("#employer-applications-vacancy").select_option(str(stale_vacancy))
    page.locator("[data-v02-action='employer-application-filter'][data-filter='closed']").click()
    page.locator("#employer-application-search").fill("нет такого кандидата")
    expect(page.locator(".application-review-card:visible")).to_have_count(0)
    selector.select_option("overview")
    page.locator(".overview-priority [data-v02-action='open-employer-applications']").click()
    expect(page.locator("#employer-applications-vacancy")).to_have_value("all")
    expect(page.locator("#employer-application-search")).to_have_value("")
    expect(page.locator("[data-v02-action='employer-application-filter'][data-filter='attention']")).to_have_attribute(
        "aria-pressed", "true"
    )
    expect(page.locator(".application-review-card:visible")).to_have_count(2)
    for application_id in applications:
        expect(page.locator(f".application-review-card[data-application-id='{application_id}']")).to_be_visible()
    # These overview links only navigate; application decisions remain explicit.
    result = page.request.get(URL + "/api/employer/applications")
    assert result.status == 200, result.text()
    assert all(item["status"] == "applied" for item in result.json()["applications"])


def exercise_profile_readiness(page):
    for email, field, heading in (
        ("buhgalter@demo.example", "profession", "Укажите профессию"),
        ("inzhen@demo.example", "city", "Укажите город"),
    ):
        assert page.request.post(URL + "/api/logout", headers=HEADERS).status == 200
        login(page, email)
        expect(page.locator(".overview-health")).to_contain_text("Основные сведения")
        expect(page.locator(".overview-health > strong")).to_have_text("50%")
        expect(page.locator(".overview-priority h3")).to_have_text(heading)
        profile_before = page.request.get(URL + "/api/me").json()["user"]["profile"]
        assert profile_before[field] == ""
        page.locator(
            f".overview-priority [data-action='open-candidate-profile'][data-profile-field='{field}']"
        ).click()
        expect(page.locator(f"#profile-{field}")).to_be_focused()
        expect(page.locator(f"#profile-{field}")).to_have_value("")
        assert page.request.get(URL + "/api/me").json()["user"]["profile"] == profile_before

    user = page.request.get(URL + "/api/me").json()["user"]
    profile = {key: user["profile"][key] for key in (
        "profession", "city", "skills", "salary_min", "schedule", "employment", "about",
    )}
    profile.update(city="Москва", is_active=False, phone=user["phone"],
                   skills="", about="", salary_min=0)
    response = page.request.put(URL + "/api/candidate/profile", headers=HEADERS, data=profile)
    assert response.status == 200, response.text()
    page.goto(URL, wait_until="networkidle")
    expect(page.locator(".overview-health > strong")).to_have_text("100%")
    expect(page.locator(".overview-priority h3")).to_have_text("Подбор на паузе")
    page.locator(
        ".overview-priority [data-action='open-candidate-profile'][data-profile-field='is_active']"
    ).click()
    expect(page.locator("#profile-active")).to_be_focused()
    expect(page.locator("#profile-active")).not_to_be_checked()
    assert page.request.get(URL + "/api/me").json()["user"]["profile"]["is_active"] == 0

    # Turning search back on with only profession/city must prioritize jobs,
    # not pressure the candidate to write optional experience a second time.
    profile["is_active"] = True
    response = page.request.put(URL + "/api/candidate/profile", headers=HEADERS, data=profile)
    assert response.status == 200, response.text()
    page.goto(URL, wait_until="networkidle")
    expect(page.locator(".overview-health > strong")).to_have_text("100%")
    first_task = page.locator(".overview-action-center .overview-action-item").first
    expect(first_task).to_contain_text("ваканси")


def login(page, email, password="DemoPass2026!"):
    response = page.request.post(
        URL + "/api/login",
        headers=HEADERS,
        data={"email": email, "password": password},
    )
    assert response.status == 200, response.text()
    page.goto(URL, wait_until="networkidle")


def run_overview(page):
    browser_errors = []
    page.on("pageerror", lambda error: browser_errors.append(str(error)))
    navigation_writes = []
    page.on("request", lambda request: navigation_writes.append((request.method, request.url))
            if "/api/" in request.url and request.method not in {"GET", "HEAD", "OPTIONS"}
            else None)

    # A real pending invitation must beat an unverified email in the main CTA.
    # These are isolated fictional demo accounts in a temporary local database.
    employer = page.request.post(
        URL + "/api/login", headers=HEADERS,
        data={"email": "company@demo.example", "password": "DemoPass2026!"},
    )
    assert employer.status == 200, employer.text()
    vacancy_list = page.request.get(URL + "/api/employer/vacancies")
    assert vacancy_list.status == 200
    vacancy_id = next(
        job["id"] for job in vacancy_list.json()["jobs"] if job["title"] == "Кладовщик"
    )
    matches = page.request.get(URL + f"/api/employer/vacancies/{vacancy_id}/matches")
    assert matches.status == 200
    candidate_id = next(
        candidate["candidate_id"]
        for candidate in matches.json()["matches"]
        if candidate["profession"] == "Кладовщик"
    )
    invite = page.request.post(
        URL + "/api/employer/invitations", headers=HEADERS,
        data={"vacancy_id": vacancy_id, "candidate_id": candidate_id},
    )
    assert invite.status == 201, invite.text()
    assert page.request.post(URL + "/api/logout", headers=HEADERS).status == 200

    login(page, "kladovshik@demo.example")
    email_status = page.request.get(URL + "/api/account/email/status")
    assert email_status.status == 200
    assert email_status.json()["email_verified"] is False
    dashboard = page.locator("#dashboard-main")
    expect(dashboard.locator(".overview-priority h3")).to_have_text(
        "Ответьте на приглашение работодателя"
    )
    expect(dashboard.locator(".overview-priority [data-action='open-candidate-invitations']")).to_be_visible()
    expect(dashboard.locator(".candidate-status-row")).to_contain_text("Подтвердите email")
    expect(dashboard).to_contain_text("ВАШ СЛЕДУЮЩИЙ ШАГ")
    expect(dashboard.locator(".overview-stat-card")).to_have_count(4)
    expect(dashboard.locator(".candidate-status-row")).to_be_visible()
    expect(dashboard.locator(".candidate-status-chip")).to_have_count(3)
    expect(dashboard.locator(".candidate-overview-grid")).to_be_visible()
    expect(dashboard).to_contain_text("Вакансии для вас")
    expect(dashboard).to_contain_text("Сейчас в процессе")
    expect(dashboard.locator(".candidate-overview-section")).to_have_count(3)
    expect(dashboard.locator(".candidate-invitations-preview")).to_be_visible()
    tasks = dashboard.locator(".overview-action-center")
    expect(tasks).to_be_visible()
    expect(tasks).to_contain_text("Приглашения, ожидающие ответа")
    expect(tasks).to_contain_text("Подтвердить электронную почту")
    assert tasks.locator(".overview-action-item").count() >= 2
    expect(tasks.locator("[data-action='open-candidate-invitations']")).to_be_visible()
    expect(dashboard.locator(".candidate-stage-overview")).to_be_visible()
    expect(dashboard.locator(".candidate-stage-card")).to_have_count(3)

    # The overview must remain usable at the core mobile width.
    page.set_viewport_size({"width": 390, "height": 844})
    expect(dashboard.locator(".candidate-overview-grid")).to_be_visible()
    assert page.evaluate("""() => {
      const center = document.querySelector('#dashboard-main .overview-action-center');
      return center && center.scrollWidth <= center.clientWidth + 3;
    }"""), "Candidate action center must fit a 390px viewport"
    expect(dashboard.locator(".candidate-status-row")).to_be_visible()
    expect(dashboard.locator(".candidate-status-chip").first).to_be_visible()
    mobile_section = page.locator("[data-dashboard-tab-select]")
    expect(mobile_section).to_be_visible()
    expect(mobile_section.locator("option")).to_have_count(9)
    expect(page.locator(".dashboard-tabs")).to_be_hidden()
    expect(page.locator(".mobile-quick-nav")).to_be_hidden()
    expect(page.locator("#mobile-member-actions")).to_be_visible()

    # Primary overview actions stay direct; section navigation uses the compact mobile switcher.
    dashboard.locator("[data-tab='offers']").first.click()
    expect(dashboard).to_contain_text("Подходящие вакансии")
    recommendation = dashboard.locator(".job-card").first
    expect(recommendation.locator(".match-score")).to_be_visible()
    expect(recommendation.locator(".match-score")).to_contain_text("%")
    explanation = recommendation.locator("details.match-explanation")
    expect(explanation).to_be_visible()
    explanation.locator("summary").click()
    expect(explanation.locator(".match-factor-row")).to_have_count(6)
    expect(explanation).to_contain_text("Возраст и другие личные характеристики не используются")
    mobile_section.select_option("overview")
    expect(dashboard.locator(".candidate-overview-grid")).to_be_visible()
    expect(dashboard.locator(".candidate-invitations-preview")).to_be_visible()
    assert page.evaluate("""() => {
      const invitation = document.querySelector('#dashboard-main .candidate-invitations-preview');
      const regular = document.querySelector('#dashboard-main .candidate-overview-grid');
      return invitation && regular &&
        invitation.getBoundingClientRect().top < regular.getBoundingClientRect().top;
    }"""), "Unanswered invitations must precede routine recommendations"
    assert page.evaluate("""() => {
      const stats = document.querySelector('#dashboard-main .overview-stat-grid');
      return stats && getComputedStyle(stats).gridTemplateColumns.trim().split(/\\s+/).length === 2;
    }"""), "Candidate KPIs must use two readable columns at 390px"
    assert page.evaluate("""() => {
      const chips = document.querySelector('#dashboard-main .candidate-status-row');
      return chips && getComputedStyle(chips).gridTemplateColumns.trim().split(/\\s+/).length === 2;
    }"""), "Candidate trust indicators must fit two columns at 390px"
    page.locator("#reading-mode-toggle").click()
    assert page.evaluate("""() => {
      const stats = document.querySelector('#dashboard-main .overview-stat-grid');
      return stats && getComputedStyle(stats).gridTemplateColumns.trim().split(/\\s+/).length === 1;
    }"""), "Large-text mode must retain full-width candidate KPI cards"
    page.locator("#reading-mode-toggle").click()

    # Account-security controls are available without leaving the dashboard.
    mobile_section.focus()
    mobile_section.select_option("security")
    expect(page.locator("[data-dashboard-tab-select]")).to_be_focused()
    expect(page.locator("[data-dashboard-tab-select]")).to_have_value("security")
    expect(dashboard).to_contain_text("БЕЗОПАСНОСТЬ АККАУНТА")
    expect(dashboard.locator("#security-password-form")).to_be_visible()
    expect(dashboard.locator("[data-action='revoke-other-sessions']")).to_be_visible()
    expect(dashboard.locator(".account-security-summary")).to_be_visible()

    exercise_application_destinations(page, vacancy_list.json()["jobs"])
    exercise_profile_readiness(page)
    assert not navigation_writes, "Overview navigation must not mutate account or application state: " + str(navigation_writes)

    if browser_errors:
        raise AssertionError("Uncaught browser errors: " + " | ".join(browser_errors))


def main():
    with tempfile.TemporaryDirectory(prefix="stazhno-candidate-overview-") as tmp:
        env = dict(
            os.environ,
            OPYT50_DB_PATH=str(Path(tmp) / "demo.db"),
            OPYT50_PREVIEW_SEED_DEMO="0",
            OPYT50_COOKIE_SECURE="0",
        )
        subprocess.run(
            [sys.executable, "scripts/seed_demo.py", "--db", env["OPYT50_DB_PATH"]],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
        )
        server_log_path = Path(tmp) / "uvicorn.log"
        server_log = server_log_path.open("w", encoding="utf-8")
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8767",
            ],
            cwd=ROOT,
            env=env,
            stdout=server_log,
            stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(80):
                try:
                    with urlopen(URL + "/api/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except Exception:
                    time.sleep(.25)
            else:
                raise RuntimeError("Local server did not become ready")

            seed_readiness_profiles(env["OPYT50_DB_PATH"])
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                try:
                    context = browser.new_context(viewport={"width": 1280, "height": 820}, locale="ru-RU")
                    page = context.new_page()
                    try:
                        run_overview(page)
                    except Exception:
                        page.screenshot(path=str(Path(tmp) / "failure.png"), full_page=True)
                        server_log.flush()
                        print(
                            "Uvicorn server error log:\n"
                            + server_log_path.read_text(encoding="utf-8")[-12000:],
                            file=sys.stderr,
                        )
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

    print("Browser candidate overview smoke: desktop, mobile and tab navigation PASSED")


if __name__ == "__main__":
    main()
