"""Professional community acceptance on an isolated, fictional local database.

Exercises the rendered desktop/mobile UI and the protected API boundary. No live
accounts, external email, Timeweb data, or existing applications are involved.
"""
from __future__ import annotations

import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
HEADERS = {"X-Requested-With": "OPYT50"}
OUTPUT = Path(os.getenv("STAZHNO_COMMUNITY_REVIEW_DIR", "community-review"))
PASSWORD = "DemoPass2026!"


def checked(response, statuses=(200, 201)):
    assert response.status in statuses, f"{response.status}: {response.text()}"
    return response.json()


def profile_payload(name, headline, *, version=0, about="Делюсь практическим опытом."):
    return {
        "expected_version": version,
        "public_name": name,
        "headline": headline,
        "city": "Москва",
        "skills": "Организация работы, наставничество, обучение",
        "about": about,
        "goal": "mentoring",
    }


def api_profile(page, base, admin, name, headline):
    profile = checked(page.request.put(
        base + "/api/community/profile", headers=HEADERS,
        data=profile_payload(name, headline),
    ))["profile"]
    profile = checked(page.request.post(
        base + "/api/community/profile/submit", headers=HEADERS,
        data={"expected_version": profile["version"], "publish_consent": True},
    ))["profile"]
    return checked(admin.request.patch(
        base + "/api/admin/community/profiles/" + profile["public_id"],
        headers=HEADERS,
        data={"expected_version": profile["version"], "decision": "approve", "reason": ""},
    ))["profile"]


def no_overflow(page):
    assert page.evaluate("""() => {
      const root = document.documentElement;
      return root.scrollWidth <= root.clientWidth + 2;
    }"""), "Community page must fit the viewport without horizontal scrolling"


def capture(page, filename):
    no_overflow(page)
    page.evaluate("window.scrollTo(0, 0)")
    page.screenshot(path=str(OUTPUT / filename), full_page=True)


def assert_private_values_absent(text):
    for value in (
        "Александр Демонстрационный", "Наталья Демонстрационная",
        "kladovshik@demo.example", "buhgalter@demo.example",
        "+70000000001", "+70000000002", "password_hash", "salary_min",
    ):
        assert value not in text, f"Private account/resume value leaked: {value}"


def run_browser(browser, base, database):
    errors = []
    contexts = []

    def page_for(email=None):
        context = browser.new_context(viewport={"width": 1366, "height": 900}, locale="ru-RU")
        contexts.append(context)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        if email:
            checked(page.request.post(
                base + "/api/login", headers=HEADERS,
                data={"email": email, "password": PASSWORD},
            ))
        return page

    visitor = page_for()
    anna = page_for("kladovshik@demo.example")
    boris = page_for("buhgalter@demo.example")
    outsider = page_for("inzhen@demo.example")
    employer = page_for("company@demo.example")
    admin = page_for("admin@demo.example")
    try:
        login_probe = page_for()
        login_probe.goto(base + "/community/connections", wait_until="networkidle")
        login_form = login_probe.locator("#community-login-form")
        expect(login_form).to_be_visible()
        login_form.locator('[name="email"]').fill("manager@demo.example")
        login_form.locator('[name="password"]').fill(PASSWORD)
        login_form.locator('[type="submit"]').click()
        expect(login_probe.locator("#community-connections-list")).to_be_visible()
        with sqlite3.connect(database) as db:
            initial_notices = db.execute("SELECT COUNT(*) FROM email_outbox").fetchone()[0]

        # Existing resumes must never automatically become discoverable people.
        assert checked(visitor.request.get(base + "/api/community/people"))["total"] == 0
        visitor.goto(base + "/community", wait_until="networkidle")
        expect(visitor.locator("#community-people")).to_be_visible()
        capture(visitor, "community-empty-desktop.png")

        anna.goto(base + "/community/profile", wait_until="networkidle")
        form = anna.locator("#professional-profile-form")
        expect(form).to_be_visible()
        assert form.locator('[name="public_name"]').input_value() == ""
        payload = profile_payload("Анна «Опыт»", "Наставник складской команды")
        for field in ("public_name", "headline", "city", "skills", "about"):
            form.locator(f'[name="{field}"]').fill(payload[field])
        form.locator('[name="goal"]').select_option(payload["goal"])
        with anna.expect_response(lambda r: r.url.endswith("/api/community/profile") and r.request.method == "PUT") as saved:
            anna.locator("#save-professional-profile").click()
        profile = checked(saved.value)["profile"]
        assert profile["status"] == "draft"
        person_id = profile["public_id"]
        assert visitor.request.get(base + "/api/community/people/" + person_id).status == 404
        expect(anna.locator("#publish-consent")).not_to_be_checked()
        refused = anna.request.post(
            base + "/api/community/profile/submit", headers=HEADERS,
            data={"expected_version": profile["version"], "publish_consent": False},
        )
        assert refused.status in (400, 422)

        # A failed save preserves input, and a double-click cannot submit twice.
        about = "Обучаю коллег работе со складом. <svg onload=window.communityXss=1>"
        form.locator('[name="about"]').fill(about)
        anna.context.set_offline(True)
        anna.locator("#save-professional-profile").click()
        expect(anna.locator("#save-professional-profile")).to_be_enabled()
        expect(form.locator('[name="about"]')).to_have_value(about)
        anna.context.set_offline(False)
        writes = []
        anna.on("request", lambda r: writes.append(r) if r.url.endswith("/api/community/profile") and r.method == "PUT" else None)
        with anna.expect_response(lambda r: r.url.endswith("/api/community/profile") and r.request.method == "PUT") as retried:
            anna.locator("#save-professional-profile").evaluate("button => { button.click(); button.click(); }")
        profile = checked(retried.value)["profile"]
        assert len(writes) == 1, "A double click must send one profile save"
        assert profile["about"] == about
        assert anna.evaluate("window.communityXss || 0") == 0
        capture(anna, "community-profile-desktop.png")
        anna.set_viewport_size({"width": 390, "height": 844})
        anna.locator("#reading-mode-toggle").click()
        expect(anna.locator("body")).to_have_class(re.compile(r".*comfortable-view.*"))
        capture(anna, "community-profile-mobile-large.png")
        anna.locator("#reading-mode-toggle").click()

        anna.locator("#publish-consent").check()
        with anna.expect_response(lambda r: r.url.endswith("/profile/submit") and r.request.method == "POST") as submitted:
            anna.locator("#submit-profile-review").click()
        pending = checked(submitted.value)["profile"]
        assert pending["status"] == "pending"
        assert visitor.request.get(base + "/api/community/people/" + person_id).status == 404
        admin.goto(base + "/community/moderation", wait_until="networkidle")
        candidate = admin.locator(f'#moderation-list [data-profile-id="{person_id}"]')
        expect(candidate).to_be_visible()
        capture(admin, "community-moderation-pending-desktop.png")
        candidate.locator('[data-action="approve-profile"]').click()
        with admin.expect_response(lambda r: r.url.endswith("/profiles/" + person_id) and r.request.method == "PATCH") as approved:
            admin.locator("#confirm-community-action").click()
        published = checked(approved.value)["profile"]
        assert published["status"] == "published"

        public_response = visitor.request.get(base + "/people/" + person_id)
        assert public_response.status == 200, public_response.text()
        assert "no-store" in public_response.headers.get("cache-control", "")
        assert_private_values_absent(public_response.text())
        public_api = visitor.request.get(base + "/api/community/people/" + person_id)
        assert_private_values_absent(public_api.text())
        visitor.goto(base + "/people/" + person_id, wait_until="networkidle")
        assert visitor.evaluate("window.communityXss || 0") == 0
        expect(visitor.locator(".person-facts dt")).to_have_text(["Город", "Цель знакомства"])
        expect(visitor.locator(".person-skills")).to_contain_text("Организация работы")
        assert_private_values_absent(visitor.locator("body").inner_text())
        capture(visitor, "community-person-desktop.png")
        visitor.locator("#reading-mode-toggle").click()
        for width in (390, 320):
            visitor.set_viewport_size({"width": width, "height": 844})
            expect(visitor.locator("#reading-mode-toggle")).to_have_attribute("aria-pressed", "true")
            assert visitor.evaluate("""() => {
              const facts = document.querySelector('.person-facts').getBoundingClientRect();
              const skills = document.querySelector('.person-skills').getBoundingClientRect();
              const next = document.querySelector('#person-next-step').getBoundingClientRect();
              const story = document.querySelector('.person-story').getBoundingClientRect();
              return facts.bottom <= next.top + 2 && skills.bottom <= next.top + 2
                && next.bottom <= story.top + 2;
            }"""), "Mobile profile should explain facts and interests before the request, then show the detailed story"
            capture(visitor, f"community-person-{width}-large.png")
        visitor.locator("#reading-mode-toggle").click()
        visitor.set_viewport_size({"width": 390, "height": 844})

        # Portfolio drafts are independently consented and moderated.
        anna.goto(base + "/community/portfolio", wait_until="networkidle")
        anna.locator("#portfolio-add").click()
        editor = anna.locator("#portfolio-form")
        editor.locator('[name="kind"]').select_option("project")
        editor.locator('[name="title"]').fill("Внедрение складского учёта")
        editor.locator('[name="period"]').fill("2020–2024")
        editor.locator('[name="contribution"]').fill("Обучила коллег. <img src=x onerror=window.portfolioXss=1>")
        editor.locator('[name="result"]').fill("Снизили количество ошибок.")
        anna.context.set_offline(True)
        editor.locator('[type="submit"]').click()
        expect(editor.locator(".form-error")).to_be_visible()
        expect(editor.locator('[name="title"]')).to_have_value("Внедрение складского учёта")
        anna.context.set_offline(False)
        with anna.expect_response(lambda r: r.url.endswith("/api/community/portfolio") and r.request.method == "POST") as portfolio_saved:
            editor.locator('[type="submit"]').click()
        portfolio = checked(portfolio_saved.value)["entry"]
        portfolio_id = portfolio["id"]
        card = anna.locator(f'#portfolio-list [data-portfolio-id="{portfolio_id}"]')
        expect(card).to_contain_text("Черновик")
        assert checked(visitor.request.get(base + "/api/community/people/" + person_id + "/portfolio"))["entries"] == []
        card.locator('[data-action="submit-portfolio"]').click()
        consent = anna.locator("#portfolio-submit-form")
        consent.locator('[name="publish_consent"]').check()
        with anna.expect_response(lambda r: r.url.endswith("/portfolio/" + portfolio_id + "/submit")) as portfolio_submitted:
            consent.locator('[type="submit"]').click()
        assert checked(portfolio_submitted.value)["entry"]["status"] == "pending"
        expect(card).to_contain_text("На проверке")
        capture(anna, "community-portfolio-owner-mobile.png")
        admin.goto(base + "/community/portfolio", wait_until="networkidle")
        admin.locator(f'#portfolio-review-list [data-portfolio-id="{portfolio_id}"] [data-action="approve-portfolio"]').click()
        with admin.expect_response(lambda r: r.url.endswith("/api/admin/community/portfolio/" + portfolio_id) and r.request.method == "PATCH") as portfolio_approved:
            admin.locator('#portfolio-review-form [type="submit"]').click()
        assert checked(portfolio_approved.value)["entry"]["status"] == "published"
        visitor.goto(base + "/people/" + person_id, wait_until="networkidle")
        expect(visitor.locator(f'.person-portfolio [data-portfolio-id="{portfolio_id}"]')).to_contain_text("Внедрение складского учёта")
        assert visitor.evaluate("window.portfolioXss || 0") == 0
        visitor.locator("#share-person").click()
        expect(visitor.locator("#share-profile-url")).to_have_value(base + "/people/" + person_id)
        visitor.keyboard.press("Escape")
        capture(visitor, "community-public-portfolio-mobile.png")
        anna.reload(wait_until="networkidle")
        card.locator('[data-action="edit-portfolio"]').click()
        editor.locator('[name="result"]').fill("Уточнённый результат работы.")
        with anna.expect_response(lambda r: r.url.endswith("/api/community/portfolio/" + portfolio_id) and r.request.method == "PUT") as portfolio_edited:
            editor.locator('[type="submit"]').click()
        assert checked(portfolio_edited.value)["entry"]["status"] == "draft"
        assert checked(visitor.request.get(base + "/api/community/people/" + person_id + "/portfolio"))["entries"] == []
        assert visitor.request.get(base + "/people/" + person_id).status == 200

        boris_profile = api_profile(boris, base, admin, "Борис Проекты", "Координатор проектов")
        outsider_profile = api_profile(outsider, base, admin, "Виктор Мастер", "Мастер производственного обучения")
        # Curated groups: private membership, scoped moderation and safe exit.
        anna.set_viewport_size({"width": 390, "height": 844})
        anna.goto(base + "/community/groups", wait_until="networkidle")
        group_card = anna.locator('[data-group-slug="engineering"]')
        expect(group_card).to_contain_text("Инженерия и производство")
        with anna.expect_response(lambda r: r.url.endswith("/groups/engineering/membership") and r.request.method == "PUT") as group_joined:
            group_card.locator('[data-action="join-group"]').click()
        assert checked(group_joined.value)["group"]["joined"] is True
        expect(group_card).to_contain_text("Вы участник")
        anna.locator("#groups-filter").select_option("mine")
        expect(anna.locator("#groups-list [data-group-slug]")).to_have_count(1)
        capture(anna, "community-groups-mobile.png")
        group_card.locator('a[href*="group=engineering"]').click()
        group_form = anna.locator("#feed-compose-form")
        expect(group_form).to_be_visible()
        group_form.locator('[name="title"]').fill("Технический обмен опытом")
        group_form.locator('[name="body"]').fill("Практические вопросы организации производства")
        group_form.locator('[name="publish_consent"]').check()
        with anna.expect_response(lambda r: r.url.endswith("/api/community/feed") and r.request.method == "POST") as group_sent:
            group_form.locator('[type="submit"]').click()
        group_entry = checked(group_sent.value)["entry"]
        group_id = group_entry["id"]
        assert group_entry["group_slug"] == "engineering"
        assert checked(boris.request.get(base + "/api/community/feed?group_slug=engineering"))["entries"] == []
        admin.goto(base + "/community/feed", wait_until="networkidle")
        group_review = admin.locator(f'#feed-review-list [data-feed-id="{group_id}"]')
        expect(group_review).to_contain_text("Инженерия и производство")
        group_review.locator('[data-action="approve-feed"]').click()
        with admin.expect_response(lambda r: r.url.endswith("/api/admin/community/feed/" + group_id) and r.request.method == "PATCH") as group_approved:
            admin.locator('#feed-review-form [type="submit"]').click()
        group_entry = checked(group_approved.value)["entry"]
        boris.goto(base + "/community/feed?group=engineering", wait_until="networkidle")
        expect(boris.locator("#feed-compose-form")).to_have_count(0)
        group_post = boris.locator(f'#feed-list [data-feed-id="{group_id}"]')
        expect(group_post).to_contain_text("Технический обмен опытом")
        group_post.locator('[data-action="open-feed-thread"]').click()
        expect(boris.locator("#feed-discussion")).to_contain_text("вступите в группу")
        expect(boris.locator("#feed-comment-form")).to_have_count(0)
        assert checked(boris.request.get(base + "/api/community/feed?group_slug=sales"))["entries"] == []
        anna.goto(base + "/community/groups", wait_until="networkidle")
        group_card = anna.locator('[data-group-slug="engineering"]')
        with anna.expect_response(lambda r: r.url.endswith("/groups/engineering/membership") and r.request.method == "DELETE") as group_left:
            group_card.locator('[data-action="leave-group"]').click()
        assert checked(group_left.value)["group"]["joined"] is False
        assert checked(boris.request.get(base + "/api/community/feed?group_slug=engineering"))["entries"][0]["id"] == group_id
        checked(anna.request.delete(base + "/api/community/feed/" + group_id, headers=HEADERS,
                                    data={"expected_version": group_entry["version"]}))
        assert checked(boris.request.get(base + "/api/community/feed?group_slug=engineering"))["entries"] == []

        # Professional feed: an explicit, moderated submission and discussion.
        anna.set_viewport_size({"width": 390, "height": 844})
        anna.goto(base + "/community/feed", wait_until="networkidle")
        composer = anna.locator("#feed-compose-form")
        expect(composer).to_be_visible()
        composer.locator('[name="kind"]').select_option("mentoring")
        composer.locator('[name="title"]').fill("Как передавать опыт")
        feed_body = "Начинаю с учебного плана. <img src=x onerror=window.communityXss=1>"
        composer.locator('[name="body"]').fill(feed_body)
        composer.locator('[name="publish_consent"]').check()
        anna.context.set_offline(True)
        composer.locator('[type="submit"]').click()
        expect(composer.locator(".form-error")).to_be_visible()
        expect(composer.locator('[name="body"]')).to_have_value(feed_body)
        anna.context.set_offline(False)
        with anna.expect_response(lambda r: r.url.endswith("/api/community/feed") and r.request.method == "POST") as feed_sent:
            composer.locator('[type="submit"]').click()
        feed_entry = checked(feed_sent.value)["entry"]
        feed_id = feed_entry["id"]
        expect(anna.locator(f'#feed-mine-list [data-feed-id="{feed_id}"]')).to_contain_text("На проверке")
        assert checked(boris.request.get(base + "/api/community/feed"))["entries"] == []
        admin.goto(base + "/community/feed", wait_until="networkidle")
        admin.locator(f'#feed-review-list [data-feed-id="{feed_id}"] [data-action="approve-feed"]').click()
        with admin.expect_response(lambda r: r.url.endswith("/api/admin/community/feed/" + feed_id) and r.request.method == "PATCH") as feed_approved:
            admin.locator('#feed-review-form [type="submit"]').click()
        assert checked(feed_approved.value)["entry"]["status"] == "published"
        boris.set_viewport_size({"width": 390, "height": 844})
        boris.goto(base + "/community/feed", wait_until="networkidle")
        post = boris.locator(f'#feed-list [data-feed-id="{feed_id}"]')
        expect(post).to_contain_text(feed_body)
        assert boris.evaluate("window.communityXss || 0") == 0
        with boris.expect_response(lambda r: r.url.endswith("/api/community/feed/follows") and r.request.method == "POST") as followed:
            post.locator('[data-action="follow-author"]').click()
        assert checked(followed.value)["following"] is True
        expect(boris.locator("#feed-follows-list")).to_contain_text("Анна")
        boris.locator("#feed-following").select_option("true")
        boris.locator('#feed-filter [type="submit"]').click()
        expect(post.locator('[data-action="unfollow-author"]')).to_be_visible()
        post.locator('[data-action="open-feed-thread"]').click()
        reply_form = boris.locator("#feed-comment-form")
        expect(reply_form).to_be_visible()
        reply_form.locator('[name="body"]').fill("Полезный подход к обучению.")
        reply_form.locator('[name="publish_consent"]').check()
        with boris.expect_response(lambda r: r.url.endswith("/api/community/feed") and r.request.method == "POST") as reply_sent:
            reply_form.locator('[type="submit"]').click()
        reply = checked(reply_sent.value)["entry"]
        expect(boris.locator(f'#feed-mine-list [data-feed-id="{reply["id"]}"]')).to_contain_text("На проверке")
        assert checked(anna.request.get(base + "/api/community/feed/" + feed_id + "/comments"))["entries"] == []
        admin.reload(wait_until="networkidle")
        admin.locator(f'#feed-review-list [data-feed-id="{reply["id"]}"] [data-action="approve-feed"]').click()
        with admin.expect_response(lambda r: r.url.endswith("/api/admin/community/feed/" + reply["id"]) and r.request.method == "PATCH") as reply_approved:
            admin.locator('#feed-review-form [type="submit"]').click()
        assert checked(reply_approved.value)["entry"]["status"] == "published"
        boris.reload(wait_until="networkidle")
        boris.locator(f'#feed-list [data-feed-id="{feed_id}"] [data-action="open-feed-thread"]').click()
        expect(boris.locator("#feed-comments")).to_contain_text("Полезный подход к обучению.")
        anna.reload(wait_until="networkidle")
        expect(anna.locator("#feed-alert-badge")).to_have_text("1")
        expect(anna.locator("#feed-alerts-list")).to_contain_text("Полезный подход к обучению.")
        anna.locator('#feed-alerts-list [data-action="open-feed-thread"]').click()
        expect(anna.locator("#feed-comments")).to_contain_text("Полезный подход к обучению.")
        expect(anna.locator("#feed-alert-badge")).to_have_text("1")
        with anna.expect_response(lambda r: r.url.endswith("/alerts/" + reply["id"] + "/read")) as read_alert:
            anna.locator('#feed-alerts-list [data-action="read-feed-alert"]').click()
        assert checked(read_alert.value)["read"] is True
        expect(anna.locator("#feed-alert-badge")).to_be_hidden()
        capture(anna, "community-feed-notifications-mobile.png")

        anna.locator(f'#feed-comments [data-feed-id="{reply["id"]}"] [data-action="report-feed"]').click()
        anna.locator('#feed-report-form [name="details"]').fill("Проверка обработки жалобы")
        with anna.expect_response(lambda r: r.url.endswith("/" + reply["id"] + "/reports") and r.request.method == "POST") as reported:
            anna.locator('#feed-report-form [type="submit"]').click()
        report_id = checked(reported.value)["report"]["id"]
        admin.reload(wait_until="networkidle")
        report_card = admin.locator(f'[data-feed-report-id="{report_id}"]')
        expect(report_card).to_contain_text("Проверка обработки жалобы")
        report_card.locator('[data-action="dismiss-feed-report"]').click()
        with admin.expect_response(lambda r: r.url.endswith("/reports/" + report_id) and r.request.method == "PATCH") as decided:
            admin.locator('#feed-report-review-form [type="submit"]').click()
        assert checked(decided.value)["report"]["status"] == "dismissed"
        capture(boris, "community-feed-mobile.png")
        # Dedicated opportunity pages reuse moderation and show structured filters.
        anna.goto(base + "/community/mentoring", wait_until="networkidle")
        expect(anna.locator("h1")).to_have_text("Наставничество")
        opportunity = anna.locator("#feed-compose-form")
        opportunity.locator('[name="intent"]').select_option("offer")
        opportunity.locator('[name="meeting_format"]').select_option("online")
        opportunity.locator('[name="commitment"]').select_option("regular")
        opportunity.locator('[name="title"]').fill("Обучение учёту на складе")
        opportunity.locator('[name="body"]').fill("Готов помочь коллеге освоить учёт.")
        opportunity.locator('[name="publish_consent"]').check()
        with anna.expect_response(lambda r: r.url.endswith("/api/community/feed") and r.request.method == "POST") as opportunity_sent:
            opportunity.locator('[type="submit"]').click()
        offer = checked(opportunity_sent.value)["entry"]
        offer_id = offer["id"]
        expect(anna.locator(f'#feed-mine-list [data-feed-id="{offer_id}"]')).to_contain_text("На проверке")
        admin.goto(base + "/community/feed", wait_until="networkidle")
        offer_review = admin.locator(f'#feed-review-list [data-feed-id="{offer_id}"]')
        expect(offer_review).to_contain_text("Готов быть наставником")
        offer_review.locator('[data-action="approve-feed"]').click()
        with admin.expect_response(lambda r: r.url.endswith("/api/admin/community/feed/" + offer_id) and r.request.method == "PATCH") as offer_approved:
            admin.locator('#feed-review-form [type="submit"]').click()
        assert checked(offer_approved.value)["entry"]["status"] == "published"
        boris.goto(base + "/community/mentoring", wait_until="networkidle")
        offer_card = boris.locator(f'#feed-list [data-feed-id="{offer_id}"]')
        expect(offer_card).to_contain_text("Онлайн")
        expect(boris.locator(f'#feed-list [data-feed-id="{feed_id}"]')).to_have_count(0)
        boris.locator("#opp-filter-format").select_option("offline")
        boris.locator('#feed-filter [type="submit"]').click()
        expect(offer_card).to_have_count(0)
        boris.locator("#opp-filter-format").select_option("online")
        boris.locator('#feed-filter [type="submit"]').click()
        expect(offer_card).to_be_visible()
        offer_card.locator('[data-action="respond-opportunity"]').click()
        offer_request = boris.locator("#connection-request-form")
        expect(offer_request.locator('[name="purpose"]')).to_have_value("mentoring")
        expect(offer_request.locator('[name="purpose"]')).to_be_disabled()
        assert "Обучение" in offer_request.locator('[name="note"]').input_value()
        boris.keyboard.press("Escape")
        capture(boris, "community-mentoring-mobile.png")
        with boris.expect_response(lambda r: r.url.endswith("/saved/" + offer_id) and r.request.method == "PUT") as bookmark:
            offer_card.locator('[data-action="save-entry"]').click()
        assert checked(bookmark.value)["saved"] is True
        expect(offer_card.locator('[data-action="remove-saved"]')).to_have_attribute("aria-pressed", "true")
        boris.goto(base + "/community/saved", wait_until="networkidle")
        expect(boris.locator(f'#saved-list [data-feed-id="{offer_id}"]')).to_contain_text("Обучение учёту")
        capture(boris, "community-saved-mobile.png")
        boris.goto(base + "/community/recommendations", wait_until="networkidle")
        expect(boris.locator("#discovery-results")).to_be_hidden()
        preferences = boris.locator("#discovery-preferences")
        preferences.locator('[name="keyword"]').fill("склад")
        preferences.locator('[name="focus"]').select_option("mentoring")
        with boris.expect_response(lambda r: r.url.endswith("/recommendations/preferences") and r.request.method == "PUT") as discovery_saved:
            preferences.locator('[type="submit"]').click()
        assert checked(discovery_saved.value)["settings"]["focus"] == "mentoring"
        expect(boris.locator("#discovery-people")).to_contain_text("Анна")
        expect(boris.locator(f'#discovery-feed [data-feed-id="{offer_id}"]')).to_contain_text("Обучение учёту")
        expect(boris.locator(f'#discovery-feed [data-feed-id="{offer_id}"] [data-action="remove-saved"]')).to_be_visible()
        capture(boris, "community-recommendations-mobile.png")
        boris.reload(wait_until="networkidle")
        expect(boris.locator("#discovery-keyword")).to_have_value("склад")
        expect(boris.locator(f'#discovery-feed [data-feed-id="{offer_id}"]')).to_be_visible()
        boris.goto(base + "/community/projects", wait_until="networkidle")
        expect(boris.locator("h1")).to_have_text("Совместные проекты")
        expect(boris.locator("#opp-intent")).to_contain_text("Собираю команду")
        capture(boris, "community-projects-mobile.png")
        boris.set_viewport_size({"width": 1366, "height": 900})
        boris.goto(base + "/community/feed", wait_until="networkidle")
        capture(boris, "community-feed-desktop.png")
        anna.set_viewport_size({"width": 1366, "height": 900})

        visitor.goto(base + "/community", wait_until="networkidle")
        expect(visitor.locator("#community-people [data-person-id]")).to_have_count(3)
        capture(visitor, "community-directory-mobile.png")
        boris.goto(base + "/people/" + person_id, wait_until="networkidle")
        boris.locator("#request-connection").click()
        request_form = boris.locator("#connection-request-form")
        expect(request_form).to_be_visible()
        request_form.locator('[name="purpose"]').select_option("mentoring")
        request_form.locator('[name="note"]').fill("Хочу обсудить обучение коллег работе на складе.")
        with boris.expect_response(lambda r: r.url.endswith("/api/community/connections") and r.request.method == "POST") as requested:
            request_form.locator('[type="submit"]').click()
        connection = checked(requested.value)["connection"]
        connection_id = connection["id"]
        assert connection["status"] == "pending"
        assert_private_values_absent(requested.value.text())
        for path in ("", "/messages"):
            assert outsider.request.get(base + "/api/community/connections/" + connection_id + path).status in (403, 404)
        assert boris.request.post(
            base + "/api/community/connections/" + connection_id + "/messages", headers=HEADERS,
            data={"body": "Не должно отправиться до согласия", "client_key": str(uuid4())},
        ).status in (403, 409)

        anna.goto(base + "/community/connections", wait_until="networkidle")
        incoming = anna.locator(f'#community-connections-list [data-connection-id="{connection_id}"]')
        expect(incoming).to_contain_text("Борис Проекты")
        with anna.expect_response(lambda r: r.url.endswith(connection_id + "/respond") and r.request.method == "POST") as accepted:
            incoming.locator('[data-action="accept-connection"]').click()
        assert checked(accepted.value)["connection"]["status"] == "accepted"

        # Colleague recommendation: accepted relationship, offline draft,
        # separate recipient consent, independent moderation, public rendering.
        anna.goto(base + "/community/connections", wait_until="networkidle")
        anna.locator(f'[data-connection-id="{connection_id}"] a[href*="/community/reputation?connection="]').click()
        recommendation_form = anna.locator("#recommendation-form")
        expect(recommendation_form).to_be_visible()
        recommendation_form.locator('[name="skill"]').fill("Организация обучения")
        recommendation_form.locator('[name="context"]').fill("Вместе организовывали учебный проект")
        recommendation_form.locator('[name="body"]').fill("Коллега понятно объясняет задачи. <img src=x onerror=window.reputationXss=1>")
        recommendation_form.locator('[name="publish_consent"]').check()
        anna.context.set_offline(True)
        recommendation_form.locator('[type="submit"]').click()
        expect(recommendation_form.locator(".form-error")).to_be_visible()
        expect(recommendation_form.locator('[name="skill"]')).to_have_value("Организация обучения")
        anna.context.set_offline(False)
        with anna.expect_response(lambda r: r.url.endswith("/api/community/reputation") and r.request.method == "POST") as recommendation_sent:
            recommendation_form.locator('[type="submit"]').click()
        recommendation = checked(recommendation_sent.value)["entry"]
        recommendation_id = recommendation["id"]
        assert checked(visitor.request.get(base + "/api/community/people/" + boris_profile["public_id"] + "/reputation"))["entries"] == []
        boris.goto(base + "/community/reputation", wait_until="networkidle")
        recommendation_card = boris.locator(f'#reputation-list [data-recommendation-id="{recommendation_id}"]')
        expect(recommendation_card).to_contain_text("Ожидает согласия")
        recommendation_card.locator('[data-action="accept-reputation"]').click()
        recommendation_consent = boris.locator("#reputation-consent-form")
        recommendation_consent.locator('[name="publish_consent"]').check()
        with boris.expect_response(lambda r: r.url.endswith("/reputation/" + recommendation_id + "/respond")) as recommendation_accepted:
            recommendation_consent.locator('[type="submit"]').click()
        assert checked(recommendation_accepted.value)["entry"]["status"] == "pending"
        expect(recommendation_card).to_contain_text("На проверке")
        capture(boris, "community-recommendations-mobile.png")
        admin.goto(base + "/community/reputation", wait_until="networkidle")
        admin.locator(f'#reputation-list [data-recommendation-id="{recommendation_id}"] [data-action="approve-reputation"]').click()
        with admin.expect_response(lambda r: r.url.endswith("/api/admin/community/reputation/" + recommendation_id) and r.request.method == "PATCH") as recommendation_approved:
            admin.locator('#reputation-review-form [type="submit"]').click()
        assert checked(recommendation_approved.value)["entry"]["status"] == "published"
        visitor.goto(base + "/people/" + boris_profile["public_id"], wait_until="networkidle")
        expect(visitor.locator(f'[data-recommendation-id="{recommendation_id}"]')).to_contain_text("Организация обучения")
        assert visitor.evaluate("window.reputationXss || 0") == 0
        capture(visitor, "community-public-recommendation-mobile.png")
        anna.goto(base + "/community/profile", wait_until="networkidle")
        anna.locator('[data-action="invite-colleague"]').click()
        expect(anna.locator("#share-profile-url")).to_have_value(base + "/people/" + person_id)
        anna.keyboard.press("Escape")
        boris.reload(wait_until="networkidle")
        recommendation_card.locator('[data-action="withdraw-reputation"]').click()
        with boris.expect_response(lambda r: r.url.endswith("/reputation/" + recommendation_id + "/publication") and r.request.method == "DELETE") as recommendation_withdrawn:
            boris.locator("#confirm-community-action").click()
        assert checked(recommendation_withdrawn.value)["entry"]["status"] == "hidden"
        assert checked(visitor.request.get(base + "/api/community/people/" + boris_profile["public_id"] + "/reputation"))["entries"] == []

        boris.goto(base + "/community/connections", wait_until="networkidle")
        outgoing = boris.locator(f'#community-connections-list [data-connection-id="{connection_id}"]')
        outgoing.locator('[data-action="open-thread"]').click()
        message_form = boris.locator("#community-message-form")
        expect(message_form).to_be_visible()
        message_body = "Предлагаю начать с учебного плана. <img src=x onerror=window.communityXss=1>"
        message_form.locator('[name="body"]').fill(message_body)
        outgoing.locator('[data-action="open-thread"]').click()
        expect(message_form.locator('[name="body"]')).to_have_value(message_body)
        boris.context.set_offline(True)
        message_form.locator('[type="submit"]').click()
        expect(message_form.locator('[type="submit"]')).to_be_enabled()
        expect(message_form.locator('[name="body"]')).to_have_value(message_body)
        boris.context.set_offline(False)
        sends = []
        boris.on("request", lambda r: sends.append(r) if r.url.endswith(connection_id + "/messages") and r.method == "POST" else None)
        with boris.expect_response(lambda r: r.url.endswith(connection_id + "/messages") and r.request.method == "POST") as sent:
            message_form.locator('[type="submit"]').evaluate("button => { button.click(); button.click(); }")
        message = checked(sent.value)["message"]
        assert len(sends) == 1
        expect(boris.locator(f'#thread-history [data-message-id="{message["id"]}"]')).to_contain_text(message_body)
        expect(boris.locator("#community-notice")).to_have_text("Сообщение отправлено.")
        expect(boris.locator("#community-notice")).not_to_have_class(re.compile(r".*\berror\b.*"))
        assert boris.evaluate("window.communityXss || 0") == 0
        replay = checked(boris.request.post(
            base + "/api/community/connections/" + connection_id + "/messages", headers=HEADERS,
            data=sends[0].post_data_json,
        ))["message"]
        assert replay["id"] == message["id"]
        thread = checked(anna.request.get(base + "/api/community/connections/" + connection_id + "/messages"))
        assert [item["body"] for item in thread["messages"]].count(message_body) == 1
        assert_private_values_absent(str(thread))

        # Account overview opens the actual actionable community inbox.
        anna.set_viewport_size({"width": 390, "height": 844})
        anna.goto(base + "/", wait_until="networkidle")
        overview = anna.locator("#community-attention-overview")
        expect(overview).to_be_visible()
        expect(overview).to_contain_text("Непрочитанные сообщения: 1")
        overview.locator("a").click()
        expect(anna.locator("#connection-filter")).to_have_value("attention")
        incoming = anna.locator(f'[data-connection-id="{connection_id}"]')
        expect(incoming).to_contain_text("Непрочитанных: 1")
        incoming.locator('[data-action="open-thread"]').click()
        expect(anna.locator("#community-mark-read")).to_be_visible()
        capture(anna, "community-attention-mobile.png")
        with anna.expect_response(lambda r: r.url.endswith(connection_id + "/read") and r.request.method == "POST") as read:
            anna.locator("#community-mark-read").click()
        assert checked(read.value)["unread_count"] == 0
        expect(anna.locator("#community-notice")).to_have_text("Разговор отмечен прочитанным.")
        expect(anna.locator("#community-connections-list")).to_contain_text("Новых действий нет")
        expect(anna.locator("#community-mark-read")).to_be_hidden()
        anna.set_viewport_size({"width": 1366, "height": 900})
        boris.set_viewport_size({"width": 390, "height": 844})
        capture(boris, "community-chat-mobile.png")

        # A failed details refresh leaves the current composer fully usable.
        # Failed selection must not invalidate its active send/history token.
        detail_url = base + "/api/community/connections/" + connection_id

        def abort_details(route):
            route.abort("failed")

        boris.route(detail_url, abort_details)
        with boris.expect_event("requestfailed", predicate=lambda request: request.url == detail_url):
            boris.locator('#community-thread [data-action="refresh-thread"]').click()
        boris.unroute(detail_url, abort_details)
        expect(boris.locator("#community-notice")).to_have_class(re.compile(r".*\berror\b.*"))
        after_refresh_message = "Продолжаю разговор после временной ошибки обновления."
        boris.locator('#community-message-form [name="body"]').fill(after_refresh_message)
        with boris.expect_response(lambda response: response.url == detail_url + "/messages" and response.request.method == "POST") as after_refresh_send:
            boris.locator('#community-message-form [type="submit"]').click()
        checked(after_refresh_send.value)
        expect(boris.locator("#thread-history")).to_contain_text(after_refresh_message)
        expect(boris.locator('#community-message-form [name="body"]')).to_have_value("")
        expect(boris.locator("#community-notice")).to_have_text("Сообщение отправлено.")
        expect(boris.locator("#community-notice")).not_to_have_class(re.compile(r".*\berror\b.*"))

        # A late history response from thread A must neither replace thread B
        # nor attach A's submit handler to B's composer.
        second_connection = checked(outsider.request.post(
            base + "/api/community/connections", headers=HEADERS,
            data={"public_id": boris_profile["public_id"], "purpose": "exchange", "note": "Обсудим обучение мастеров"},
        ))["connection"]
        second_id = second_connection["id"]
        checked(boris.request.post(
            base + "/api/community/connections/" + second_id + "/respond", headers=HEADERS,
            data={"decision": "accept"},
        ))
        first_history = checked(boris.request.get(base + "/api/community/connections/" + connection_id + "/messages"))
        boris.goto(base + "/community/connections", wait_until="networkidle")
        held_routes = []
        first_url = base + "/api/community/connections/" + connection_id + "/messages"

        def hold_first_history(route):
            held_routes.append(route)

        boris.route(first_url, hold_first_history)
        with boris.expect_request(lambda request: request.url == first_url and request.method == "GET"):
            boris.locator(f'[data-connection-id="{connection_id}"] [data-action="open-thread"]').click()
        expect(boris.locator("#community-thread h2")).to_have_text("Анна «Опыт»")
        assert len(held_routes) == 1
        second_url = base + "/api/community/connections/" + second_id + "/messages"
        with boris.expect_response(lambda response: response.url == second_url and response.request.method == "GET") as second_history:
            boris.locator(f'[data-connection-id="{second_id}"] [data-action="open-thread"]').click()
        checked(second_history.value)
        expect(boris.locator("#community-thread h2")).to_have_text("Виктор Мастер")
        with boris.expect_response(lambda response: response.url == first_url):
            held_routes[0].fulfill(status=200, content_type="application/json", body=json.dumps(first_history))
        boris.unroute(first_url, hold_first_history)
        # Allow the fulfilled response's microtasks to complete before the next
        # actual user action, without a timing-dependent sleep.
        boris.evaluate("() => new Promise(resolve => requestAnimationFrame(resolve))")
        expect(boris.locator("#community-thread h2")).to_have_text("Виктор Мастер")
        race_posts = []

        def record_thread_post(request):
            if request.url.endswith("/messages") and request.method == "POST":
                race_posts.append(request.url)

        boris.on("request", record_thread_post)
        race_message = "Сообщение только для Виктора, а не для Анны."
        boris.locator('#community-message-form [name="body"]').fill(race_message)
        with boris.expect_response(lambda response: response.url == second_url and response.request.method == "POST") as raced_send:
            boris.locator('#community-message-form [type="submit"]').click()
        checked(raced_send.value)
        expect(boris.locator("#thread-history")).to_contain_text(race_message)
        boris.remove_listener("request", record_thread_post)
        assert race_posts == [second_url], "A late response must not send thread B's text to thread A"
        unchanged_history = checked(boris.request.get(first_url))
        assert [item["id"] for item in unchanged_history["messages"]] == [item["id"] for item in first_history["messages"]]
        capture(boris, "community-multiple-conversations-mobile.png")

        # Recipient controls continuation; blocking makes both write directions fail.
        anna.reload(wait_until="networkidle")
        incoming = anna.locator(f'#community-connections-list [data-connection-id="{connection_id}"]')
        incoming.locator('[data-action="open-thread"]').click()
        anna.locator('#community-thread [data-action="block-connection"]').click()
        with anna.expect_response(lambda r: r.url.endswith(connection_id + "/block") and r.request.method == "POST") as blocked:
            anna.locator("#confirm-community-action").click()
        assert checked(blocked.value)["connection"]["status"] == "blocked"
        for participant in (anna, boris):
            assert participant.request.post(
                base + "/api/community/connections/" + connection_id + "/messages", headers=HEADERS,
                data={"body": "После блокировки", "client_key": str(uuid4())},
            ).status in (403, 409)
        assert boris.request.post(
            base + "/api/community/connections", headers=HEADERS,
            data={"public_id": person_id, "purpose": "exchange", "note": "Повторный запрос"},
        ).status == 409

        # Decline and sender cancellation must remain terminal, too.
        employer_request = checked(employer.request.post(
            base + "/api/community/connections", headers=HEADERS,
            data={"public_id": boris_profile["public_id"], "purpose": "projects", "note": "Обсудим учебный проект"},
        ))["connection"]
        boris.goto(base + "/community/connections", wait_until="networkidle")
        employer_card = boris.locator(f'[data-connection-id="{employer_request["id"]}"]')
        employer_card.locator('[data-action="decline-connection"]').click()
        with boris.expect_response(lambda r: r.url.endswith(employer_request["id"] + "/respond") and r.request.method == "POST") as declined:
            boris.locator("#confirm-community-action").click()
        assert checked(declined.value)["connection"]["status"] == "declined"
        cancel_request = checked(employer.request.post(
            base + "/api/community/connections", headers=HEADERS,
            data={"public_id": outsider_profile["public_id"], "purpose": "projects", "note": "Пробный запрос"},
        ))["connection"]
        cancelled = checked(employer.request.post(
            base + "/api/community/connections/" + cancel_request["id"] + "/cancel", headers=HEADERS,
        ))["connection"]
        assert cancelled["status"] == "cancelled"

        report = checked(outsider.request.post(
            base + "/api/community/reports", headers=HEADERS,
            data={"public_id": boris_profile["public_id"], "reason": "other", "details": "Учебная проверка жалоб"},
        ))["report"]
        admin.goto(base + "/community/moderation", wait_until="networkidle")
        expect(admin.locator("#moderation-reports")).to_contain_text("Учебная проверка жалоб")
        capture(admin, "community-moderation-desktop.png")
        with admin.expect_response(lambda r: r.url.endswith("/reports/" + report["id"]) and r.request.method == "PATCH") as resolved:
            admin.locator(f'[data-action="resolve-report"][data-id="{report["id"]}"]').click()
        checked(resolved.value)

        anna.goto(base + "/community/profile", wait_until="networkidle")
        anna.locator("#withdraw-profile").click()
        with anna.expect_response(lambda r: r.url.endswith("/profile/publication") and r.request.method == "DELETE") as withdrawn:
            anna.locator("#confirm-community-action").click()
        hidden = checked(withdrawn.value)["profile"]
        assert hidden["status"] == "hidden"
        assert hidden["consent_at"] is None
        assert visitor.request.get(base + "/people/" + person_id).status == 404
        assert visitor.request.get(base + "/api/community/people/" + person_id).status == 404
        assert anna.request.post(
            base + "/api/community/profile/submit", headers=HEADERS,
            data={"expected_version": published["version"], "publish_consent": True},
        ).status == 409, "A stale tab must not republish after withdrawal"
        with sqlite3.connect(database) as db:
            assert db.execute("SELECT COUNT(*) FROM email_outbox").fetchone()[0] == initial_notices
        # A stored published status is not permission to share an inaccessible profile.
        outsider.goto(base + "/community/profile", wait_until="networkidle")
        expect(outsider.locator('[data-action="share-profile"]')).to_be_visible()
        privacy_request = outsider.request.post(base + "/api/account/privacy-requests", headers=HEADERS,
                                               data={"kind": "stop_processing"})
        assert privacy_request.status == 201, privacy_request.text()
        assert visitor.request.get(base + "/people/" + outsider_profile["public_id"]).status == 404
        outsider.locator('[data-action="invite-colleague"]').click()
        expect(outsider.locator("#share-profile-url")).to_have_value(base + "/community")
        outsider.keyboard.press("Escape")
        outsider.locator('[data-action="share-profile"]').click()
        expect(outsider.locator("#community-notice")).to_contain_text("Профиль сейчас недоступен")
        expect(outsider.locator("#community-dialog")).to_be_hidden()
        expect(outsider.locator("#share-profile-url")).to_be_hidden()
        outsider.reload(wait_until="networkidle")
        expect(outsider.locator('[data-action="share-profile"]')).to_have_count(0)
        outsider.goto(base + "/community/reputation", wait_until="networkidle")
        outsider.locator('[data-action="invite-colleague"]').click()
        expect(outsider.locator("#share-profile-url")).to_have_value(base + "/community")
        outsider.keyboard.press("Escape")
        assert not errors, "Uncaught browser errors: " + " | ".join(errors)
    except Exception:
        for index, context in enumerate(contexts):
            for page in context.pages:
                if not page.is_closed():
                    page.screenshot(path=str(OUTPUT / f"failure-{index}.png"), full_page=True)
        raise
    finally:
        for context in contexts:
            context.close()


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with socket.socket() as port_socket:
        port_socket.bind(("127.0.0.1", 0))
        port = port_socket.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="stazhno-community-smoke-") as temporary:
        database = str(Path(temporary) / "community.db")
        env = dict(os.environ, OPYT50_DB_PATH=database, OPYT50_ENV="development",
                   OPYT50_PREVIEW_SEED_DEMO="0", OPYT50_COOKIE_SECURE="0",
                   OPYT50_MAIL_WORKER_ENABLED="0", OPYT50_ADMIN_MFA_MODE="off",
                   OPYT50_SMTP_HOST="", OPYT50_MAIL_FROM="", OPYT50_PUBLIC_URL="",
                   OPYT50_PREVIEW_PASSWORD="", OPYT50_ALLOWED_HOSTS="")
        env.pop("DATABASE_URL", None)
        subprocess.run([sys.executable, "scripts/seed_demo.py", "--db", database],
                       cwd=ROOT, env=env, check=True, capture_output=True)
        log_path = Path(temporary) / "uvicorn.log"
        with log_path.open("w", encoding="utf-8") as log:
            server = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
            )
            try:
                for _ in range(80):
                    try:
                        with urlopen(base + "/api/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(.25)
                else:
                    raise RuntimeError("Local community server did not become ready")
                with sync_playwright() as playwright:
                    launch_options = {"headless": True, "args": ["--no-sandbox"]}
                    if os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"):
                        launch_options["executable_path"] = os.environ["PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"]
                    browser = playwright.chromium.launch(**launch_options)
                    try:
                        run_browser(browser, base, database)
                    finally:
                        browser.close()
            except Exception:
                log.flush()
                print(log_path.read_text(encoding="utf-8")[-10000:], file=sys.stderr)
                raise
            finally:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)
    print("Community browser smoke PASSED: opt-in, moderation, mobile/large text, consent, chat, privacy, blocking and withdrawal")


if __name__ == "__main__":
    main()
