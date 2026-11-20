"""Real-browser smoke for the mobile vacancy -> apply route (fictional users only)."""
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8770"
OUTPUT = Path(os.environ.get("STAZHNO_VISUAL_REVIEW_DIR", "visual-review"))


def no_auto_submit(page):
    posts = []
    page.on("request", lambda request: posts.append(request.url) if (
        request.url.endswith("/api/candidate/applications") and request.method == "POST"
    ) else None)
    return posts


def open_kladovshik(page):
    page.goto(URL, wait_until="networkidle")
    if page.locator("#reading-mode-toggle").get_attribute("aria-pressed") != "true":
        page.locator("#reading-mode-toggle").click()
    card = page.locator("#public-jobs .job-card").filter(has_text="Кладовщик")
    expect(card).to_be_visible()
    expect(card.locator("[data-v02-action='apply']")).to_have_count(0)
    expect(card.locator("[data-v02-action='details']")).to_contain_text("Условия и отклик")
    expect(card.locator(".job-essential-facts dt")).to_have_text(["Город", "График", "Занятость"])
    expect(card.locator(".job-share-link")).to_be_visible()
    # Seeded edge cases must be understandable without inventing a zero salary.
    pay_negotiated = page.locator("#public-jobs .job-card").filter(has_text="Бухгалтер").locator(".job-salary")
    expect(pay_negotiated).to_have_text("По договорённости")
    pay_upper = page.locator("#public-jobs .job-card").filter(has_text="Инженер по эксплуатации").locator(".job-salary")
    expect(pay_upper).to_have_text(re.compile(r"до\s+110\s*000\s*₽"))
    card.locator("[data-v02-action='details']").click()
    expect(page.locator("#job-dialog")).to_be_visible()
    expect(page.locator("#job-dialog-title")).to_have_text("Кладовщик")
    expect(page.locator("#job-dialog .job-detail-privacy")).to_contain_text("отдельное согласие")
    expect(page.locator("#job-dialog [data-v02-action='apply']")).to_be_visible()
    expect(page.locator("#job-dialog [data-v02-action='apply']")).to_contain_text("Войти и откликнуться")
    assert page.evaluate("""() => {
      const action = document.querySelector('#job-dialog .job-detail-action');
      const description = document.querySelector('#job-dialog .job-detail-description');
      return action && description &&
        action.getBoundingClientRect().top < description.getBoundingClientRect().top;
    }"""), "The vacancy apply CTA must be before the long job description"
    dimensions = page.evaluate("""() => {
      const dialog = document.querySelector('#job-dialog');
      return {document: document.documentElement.scrollWidth,
        viewport: document.documentElement.clientWidth,
        dialogScroll: dialog.scrollWidth, dialogClient: dialog.clientWidth};
    }""")
    if (dimensions['document'] > dimensions['viewport'] + 3
            or dimensions['dialogScroll'] > dimensions['dialogClient'] + 3):
        dimensions['offenders'] = page.evaluate("""() => {
          const dialog = document.querySelector('#job-dialog');
          const bounds = dialog.getBoundingClientRect();
          const describe = el => {
            const rect = el.getBoundingClientRect(), style = getComputedStyle(el);
            return {selector: el.tagName.toLowerCase() + (el.id ? '#' + el.id : '')
                + [...el.classList].map(name => '.' + name).join(''),
              left: rect.left, right: rect.right, width: rect.width,
              client: el.clientWidth, scroll: el.scrollWidth,
              display: style.display, minWidth: style.minWidth,
              fontSize: style.fontSize, whiteSpace: style.whiteSpace,
              columns: style.gridTemplateColumns, flexWrap: style.flexWrap};
          };
          return [...dialog.querySelectorAll('*')].filter(el => {
            const rect = el.getBoundingClientRect();
            return rect.width && rect.height && (rect.right > bounds.right + 3
              || rect.left < bounds.left - 3 || el.scrollWidth > el.clientWidth + 3);
          }).slice(0, 12).map(el => ({...describe(el), parent: describe(el.parentElement)}));
        }""")
        raise AssertionError(f'Vacancy facts and actions overflow with large text: {dimensions}')


def prelaunch_guest_navigation(page):
    posts = []
    page.on("request", lambda request: posts.append(request.url) if (
        request.method == "POST" and request.url.rsplit("/", 1)[-1] in {"applications", "register"}
    ) else None)
    open_kladovshik(page)
    expect(page.locator('meta[name="prelaunch-signup-closed"]')).to_have_attribute("content", "yes")
    expect(page.locator("#job-dialog .job-entry-note")).to_contain_text("Регистрация пока закрыта")
    guide = page.locator('#job-dialog .job-preparation-link[href="/journal/paths/nayti-rabotu"]')
    expect(guide).to_be_visible()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    page.locator("#job-dialog").screenshot(path=str(OUTPUT / "prelaunch-vacancy-modal-large.png"))
    page.locator("#job-dialog [data-v02-action='apply']").click()
    expect(page.locator("#auth-dialog")).to_be_visible()
    expect(page.locator("#auth-title")).to_have_text("Войти в аккаунт")
    expect(page.locator("#auth-switch [data-switch='register']")).to_have_count(0)
    expect(page.locator("#auth-switch")).to_contain_text("регистрация временно закрыта")
    page.locator("#modal-close").click()
    # Sharing still leads to the same vacancy and never submits an application.
    card = page.locator("#public-jobs .job-card").filter(has_text="Кладовщик")
    vacancy_id = int(card.get_attribute("data-job-id"))
    page.goto(URL + f"/vacancies/{vacancy_id}", wait_until="networkidle")
    expect(page.locator("h1")).to_have_text("Кладовщик")
    expect(page.locator(".share-entry-note")).to_contain_text("Регистрация пока закрыта")
    expect(page.locator("#reading-mode-toggle")).to_have_attribute("aria-pressed", "true")
    for width in (320, 390):
        page.set_viewport_size({"width": width, "height": 844})
        assert page.evaluate("""() => document.documentElement.scrollWidth
          <= document.documentElement.clientWidth + 3"""), "Public vacancy overflows with large text"
    page.screenshot(path=str(OUTPUT / "prelaunch-vacancy-page-large.png"), full_page=True)
    start = page.locator(f'a[href="/?vacancy={vacancy_id}#jobs"]')
    expect(start).to_have_count(1)
    start.click()
    expect(page.locator("#job-dialog-title")).to_have_text("Кладовщик")
    expect(page.locator("#job-dialog .job-entry-note")).to_contain_text("Регистрация пока закрыта")
    assert not posts, "Prelaunch reading and login entry must never register or apply"


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


def run_fixture(browser, env, log_path, cases):
    with log_path.open("w", encoding="utf-8") as log_file:
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
            for run, width in cases:
                context = browser.new_context(
                    viewport={"width": width, "height": 844}, locale="ru-RU"
                )
                try:
                    page = context.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    run(page)
                    assert not errors, errors
                    print(f"{run.__name__}: PASSED")
                except Exception:
                    OUTPUT.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(OUTPUT / (run.__name__ + "-failure.png")), full_page=True)
                    log_file.flush()
                    print(log_path.read_text(encoding="utf-8")[-8000:], file=sys.stderr)
                    raise
                finally:
                    context.close()
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


def main():
    with tempfile.TemporaryDirectory(prefix="stazhno-mobile-apply-") as temp:
        env = dict(
            os.environ, OPYT50_DB_PATH=str(Path(temp) / "demo.db"),
            OPYT50_ENV="development", OPYT50_PUBLIC_URL="", OPYT50_ALLOWED_HOSTS="",
            OPYT50_PREVIEW_PASSWORD="", OPYT50_ADMIN_MFA_MODE="off",
            OPYT50_PREVIEW_SEED_DEMO="0", OPYT50_COOKIE_SECURE="0",
            OPYT50_MAIL_WORKER_ENABLED="0", OPYT50_SMTP_HOST="", OPYT50_MAIL_FROM="",
        )
        env.pop("DATABASE_URL", None)
        subprocess.run(
            [sys.executable, "scripts/seed_demo.py", "--db", env["OPYT50_DB_PATH"]],
            cwd=ROOT, env=env, capture_output=True, check=True,
        )
        with sqlite3.connect(env["OPYT50_DB_PATH"]) as db:
            db.execute("UPDATE vacancies SET salary_min=0,salary_max=0 WHERE title='Бухгалтер'")
            db.execute("UPDATE vacancies SET salary_min=0,salary_max=110000 WHERE title='Инженер по эксплуатации'")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            try:
                run_fixture(browser, env, Path(temp) / "normal.log", (
                    (login_resumes_vacancy, 320), (registration_resumes_after_profile, 390),
                ))
                # The HTTPS setting activates the actual prelaunch render gate.
                # The server and all browsing remain on loopback with fictional
                # records; this phase performs no registration or login POSTs.
                prelaunch = dict(env, OPYT50_PUBLIC_URL="https://preview.example.invalid")
                run_fixture(browser, prelaunch, Path(temp) / "prelaunch.log", (
                    (prelaunch_guest_navigation, 320),
                ))
            finally:
                browser.close()


if __name__ == "__main__":
    main()
