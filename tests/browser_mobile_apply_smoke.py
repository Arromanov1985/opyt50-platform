"""Real-browser smoke for the mobile vacancy -> apply route (fictional users only)."""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8770"


def no_auto_submit(page):
    posts = []
    page.on("request", lambda request: posts.append(request.url) if (
        request.url.endswith("/api/candidate/applications") and request.method == "POST"
    ) else None)
    return posts


def open_kladovshik(page):
    page.goto(URL, wait_until="networkidle")
    card = page.locator("#public-jobs .job-card").filter(has_text="Кладовщик")
    expect(card).to_be_visible()
    expect(card.locator("[data-v02-action='apply']")).to_be_visible()
    card.locator("[data-v02-action='details']").click()
    expect(page.locator("#job-dialog")).to_be_visible()
    expect(page.locator("#job-dialog-title")).to_have_text("Кладовщик")
    expect(page.locator("#job-dialog .job-detail-privacy")).to_contain_text("отдельное согласие")
    expect(page.locator("#job-dialog [data-v02-action='apply']")).to_be_visible()
    assert page.evaluate("""() => {
      const action = document.querySelector('#job-dialog .job-detail-action');
      const description = document.querySelector('#job-dialog .job-detail-description');
      return action && description &&
        action.getBoundingClientRect().top < description.getBoundingClientRect().top;
    }"""), "The vacancy apply CTA must be before the long job description"


def login_resumes_vacancy(page):
    posts = no_auto_submit(page)
    open_kladovshik(page)
    page.locator("#job-dialog [data-v02-action='apply']").click()
    expect(page.locator("#auth-dialog")).to_be_visible()
    expect(page.locator("#auth-guidance")).to_contain_text("снова покажем выбранную вакансию")
    page.locator("#auth-email").fill("kladovshik@demo.example")
    page.locator("#auth-password").fill("DemoPass2026!")
    page.locator("#auth-submit").click()
    expect(page.locator("#job-dialog")).to_be_visible()
    expect(page.locator("#job-dialog-title")).to_have_text("Кладовщик")
    assert posts == [], "The login must never submit an application automatically"

    # The same vacancy exists in the background list and inside the dialog.
    # Two synchronous click events must result in exactly one POST, even when
    # the second event targets the other representation of the same job.
    with page.expect_response(lambda r: r.url.endswith("/api/candidate/applications")
                              and r.request.method == "POST") as reply:
        busy = page.evaluate("""() => {
          const modal = document.querySelector('#job-dialog [data-v02-action="apply"]');
          const card = Array.from(document.querySelectorAll('#public-jobs .job-card'))
            .find(node => node.textContent.includes('Кладовщик'))
            ?.querySelector('[data-v02-action="apply"]');
          if (!modal || !card) throw new Error('Expected two CTAs for same vacancy');
          modal.dispatchEvent(new MouseEvent('click', {bubbles:true,cancelable:true}));
          const firstBusy = modal.disabled && modal.getAttribute('aria-busy') === 'true';
          const otherBusy = card.disabled && card.getAttribute('aria-busy') === 'true';
          card.dispatchEvent(new MouseEvent('click', {bubbles:true,cancelable:true}));
          return {firstBusy, otherBusy};
        }""")
    assert busy["firstBusy"] and busy["otherBusy"], busy
    assert reply.value.status == 201, reply.value.text()
    expect(page.locator("#job-dialog")).to_be_visible()
    receipt = page.locator("#job-dialog .job-application-receipt")
    expect(receipt).to_be_visible()
    expect(receipt).to_be_focused()
    expect(receipt).to_contain_text("Отклик отправлен")
    expect(receipt).to_contain_text("контакты остаются скрытыми")
    expect(page.locator("#job-dialog [data-v02-action='apply']")).to_have_count(0)
    assert len(posts) == 1
    # Cards already on screen must reflect the saved result without a reload.
    visible_card = page.locator("#public-jobs .job-card").filter(has_text="Кладовщик")
    expect(visible_card.locator("[data-v02-action='apply']")).to_have_count(0)
    expect(visible_card.locator("[data-v02-action='see-applications']")).to_be_visible()
    expect(visible_card.locator(".job-application-receipt")).to_be_visible()

    page.locator("#job-dialog [data-v02-action='see-applications']").click()
    expect(page.locator("#job-dialog")).not_to_be_visible()
    expect(page.locator("#dashboard-main")).to_contain_text("История откликов")

    # The receipt and the no-duplicate-action state survive a full page reload.
    page.reload(wait_until="networkidle")
    public_card = page.locator("#public-jobs .job-card").filter(has_text="Кладовщик")
    expect(public_card.locator(".job-application-receipt")).to_be_visible()
    expect(public_card.locator("[data-v02-action='apply']")).to_have_count(0)


def registration_resumes_after_profile(page):
    posts = no_auto_submit(page)
    open_kladovshik(page)
    page.locator("#job-dialog [data-v02-action='apply']").click()
    expect(page.locator("#auth-dialog")).to_be_visible()
    page.locator("#auth-switch [data-switch='register']").click()
    page.locator("#auth-name").fill("Тестовый Новый Соискатель")
    page.locator("#auth-email").fill("mobile-apply-regression@demo.example")
    page.locator("#auth-password").fill("NewApplicantPass2026!")
    page.locator("#auth-submit").click()
    expect(page.locator("#profile-form")).to_be_visible()
    expect(page.locator("#job-dialog")).not_to_be_visible()
    assert posts == [], "Registration must not submit an application"

    page.locator("#profile-profession").fill("Кладовщик")
    page.locator("#profile-city").fill("Подольск")
    page.locator("#profile-skills").fill("склад, 1С, инвентаризация")
    page.locator("#profile-salary").fill("65000")
    page.locator("#profile-schedule").select_option("Сменный")
    with page.expect_response(lambda r: r.url.endswith("/api/candidate/profile")
                              and r.request.method == "PUT") as profile_reply:
        page.locator("#profile-form button[type='submit']").click()
    assert profile_reply.value.status == 200, profile_reply.value.text()
    expect(page.locator("#job-dialog")).to_be_visible()
    expect(page.locator("#job-dialog-title")).to_have_text("Кладовщик")
    assert posts == [], "Profile save must not submit the vacancy application"
    expect(page.locator("#job-dialog [data-v02-action='apply']")).to_be_visible()
    # A transient network failure must release the in-flight guard and allow
    # an explicit retry (without forcing the user to reload or lose the job).
    def fail_once(route):
        route.fulfill(status=503, content_type="application/json",
                      body='{"detail":"Временная ошибка отправки"}')
    page.route("**/api/candidate/applications", fail_once)
    page.locator("#job-dialog [data-v02-action='apply']").click()
    expect(page.locator("#toast")).to_contain_text("Временная ошибка отправки")
    expect(page.locator("#job-dialog [data-v02-action='apply']")).to_be_enabled()
    expect(page.locator("#job-dialog [data-v02-action='apply']")).not_to_have_attribute(
        "aria-busy", "true"
    )
    page.unroute("**/api/candidate/applications", fail_once)
    with page.expect_response(lambda r: r.url.endswith("/api/candidate/applications")
                              and r.request.method == "POST") as sent:
        page.locator("#job-dialog [data-v02-action='apply']").click()
    assert sent.value.status == 201, sent.value.text()
    expect(page.locator("#job-dialog .job-application-receipt")).to_be_visible()
    assert page.evaluate("""() => document.documentElement.scrollWidth
      <= document.documentElement.clientWidth + 3"""), "Mobile resume introduces overflow"


def main():
    with tempfile.TemporaryDirectory(prefix="stazhno-mobile-apply-") as temp:
        env = dict(
            os.environ, OPYT50_DB_PATH=str(Path(temp) / "demo.db"),
            OPYT50_PREVIEW_SEED_DEMO="0", OPYT50_COOKIE_SECURE="0",
        )
        subprocess.run(
            [sys.executable, "scripts/seed_demo.py", "--db", env["OPYT50_DB_PATH"]],
            cwd=ROOT, env=env, capture_output=True, check=True,
        )
        log_file = (Path(temp) / "uvicorn.log").open("w", encoding="utf-8")
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", "8770"],
            cwd=ROOT, env=env, stdout=log_file, stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(80):
                try:
                    with urlopen(URL + "/api/health", timeout=1) as reply:
                        if reply.status == 200:
                            break
                except Exception:
                    time.sleep(.25)
            else:
                raise RuntimeError("Mobile apply smoke server did not start")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True, args=["--no-sandbox"]
                )
                try:
                    for run in (login_resumes_vacancy, registration_resumes_after_profile):
                        context = browser.new_context(
                            viewport={"width": 390, "height": 844}, locale="ru-RU"
                        )
                        try:
                            page = context.new_page()
                            errors = []
                            page.on("pageerror", lambda error: errors.append(str(error)))
                            run(page)
                            assert not errors, errors
                            print(f"{run.__name__}: PASSED")
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
            log_file.close()


if __name__ == "__main__":
    main()
