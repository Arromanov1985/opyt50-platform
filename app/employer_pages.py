"""Read-only public employer presentation, restricted to existing public API data."""
from __future__ import annotations

import hashlib
from html import escape
from pathlib import Path

from fastapi.responses import HTMLResponse

from .vacancy_pages import _pay


def _e(value) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def _asset(name: str) -> str:
    revision = hashlib.sha256((Path(__file__).parent / "static" / name).read_bytes()).hexdigest()[:12]
    return f"/static/{name}?v={revision}"


def employer_page(data: dict) -> HTMLResponse:
    company = data["company"]
    jobs = data["jobs"]
    employer_id = int(company["id"])
    company_name = _e(company["company_name"])
    about = _e(company.get("about") or "Компания пока не добавила описание.")
    trust = company.get("trust") or {}
    status = (
        "Компания проверена администрацией СТАЖНО" if trust.get("verified")
        else "Отметка проверки СТАЖНО пока не получена"
    )
    badges = []
    if trust.get("verified"):
        badges.append("Проверена СТАЖНО")
    if trust.get("email_verified"):
        badges.append("Email подтверждён")
    if trust.get("inn_provided"):
        badges.append("Реквизиты указаны")
    badge_html = "".join(f"<span>{_e(x)}</span>" for x in badges)
    locations = list(dict.fromkeys(str(job.get("city") or "Город не указан") for job in jobs))
    locations_text = ", ".join(locations[:3])
    if len(locations) > 3:
        locations_text += f" и ещё {len(locations) - 3}"
    summary = (
        f'<p class="employer-hero-summary">Открытых вакансий на странице: <strong>{len(jobs)}</strong>.</p>'
        f'<p class="employer-locations"><span>Где есть предложения:</span> {_e(locations_text)}</p>'
        if jobs else '<p class="employer-hero-summary">Открытых вакансий сейчас нет.</p>'
    )
    primary_action = (
        '<a class="employer-button primary" href="#company-jobs">Смотреть вакансии компании ↓</a>'
        if jobs else '<a class="employer-button primary" href="/#jobs">Посмотреть другие вакансии</a>'
    )
    cards = "".join(
        '<article class="public-employer-job">'
        f'<h3><a href="/vacancies/{int(job["id"])}" data-growth-action="vacancy_click">{_e(job["title"])}</a></h3>'
        '<dl class="employer-job-facts">'
        f'<div><dt>Оплата</dt><dd class="job-pay">{_e(_pay(job.get("salary_min"), job.get("salary_max")))}</dd></div>'
        f'<div><dt>Город</dt><dd>{_e(job.get("city") or "Не указан")}</dd></div>'
        f'<div><dt>График</dt><dd>{_e(job.get("schedule") or "Уточняется")}</dd></div>'
        f'<div><dt>Занятость</dt><dd>{_e(job.get("employment") or "Уточняется")}</dd></div>'
        '</dl>'
        f'<a class="employer-job-link" href="/vacancies/{int(job["id"])}" data-growth-action="vacancy_click">Посмотреть вакансию</a>'
        '</article>'
        for job in jobs
    )
    if not cards:
        cards = (
            '<div class="public-employer-empty"><h3>Пока нет открытых предложений</h3>'
            '<p>У этой компании сейчас нет опубликованных вакансий. '
            'Сравните предложения других работодателей или вернитесь на эту страницу позже.</p>'
            '<a class="employer-button secondary" href="/#jobs" data-growth-action="jobs_click">Все вакансии СТАЖНО</a>'
            '<a class="employer-job-link" href="/employers">Компании с открытыми вакансиями →</a></div>'
        )
    description = _e((str(company.get("about") or "").strip()[:150]) or
                     "Описание работодателя и актуальные вакансии на СТАЖНО.")
    canonical = f"https://stazhno.ru/companies/{employer_id}"
    html = f"""<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{company_name} — вакансии и информация | СТАЖНО</title>
<meta name="description" content="{description}">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="website"><meta property="og:site_name" content="СТАЖНО">
<meta property="og:title" content="{company_name} — вакансии и информация">
<meta property="og:description" content="{description}">
<meta property="og:url" content="{canonical}">
<link rel="stylesheet" href="{_asset('employer-share.css')}">
<script src="{_asset('journal.js')}" defer></script>
</head><body>
<a class="skip-link" href="#main">Перейти к содержимому</a>
<header class="employer-top"><div class="employer-wrap employer-top-inner">
<a class="employer-brand" href="/">стажно<span>.</span>ру</a>
<nav aria-label="Основное меню"><a href="/#jobs">Вакансии</a><a href="/employers">Работодатели</a><a href="/journal">Журнал</a></nav>
<button id="reading-mode-toggle" class="employer-reading-toggle" type="button" aria-pressed="false" aria-label="Включить крупный текст">Аа <span>Крупный текст</span></button>
</div></header>
<main id="main" class="employer-wrap">
<nav class="employer-crumbs" aria-label="Навигация"><a href="/">Главная</a><span aria-hidden="true">/</span><a href="/employers">Работодатели</a><span aria-hidden="true">/</span><span>Компания</span></nav>
<section class="employer-hero"><span class="employer-kicker">РАБОТОДАТЕЛЬ НА СТАЖНО</span>
<h1>{company_name}</h1>{summary}
<p class="employer-status">{_e(status)}</p>
{f'<div class="employer-badges" aria-label="Отметки компании">{badge_html}</div>' if badges else ''}
<div class="employer-hero-actions">{primary_action}<a class="employer-about-link" href="#company-about">О компании и проверках</a></div>
</section>
<section class="employer-jobs" id="company-jobs" aria-labelledby="company-jobs-title"><div class="employer-section-heading"><h2 id="company-jobs-title">Открытые вакансии <span>{len(jobs)}</span></h2><a href="/#jobs" data-growth-action="jobs_click">Все вакансии СТАЖНО →</a></div><p class="employer-section-note">Сравните основные условия. Обязанности и требования — на странице выбранной вакансии.</p><div class="employer-jobs-grid">{cards}</div></section>
<section class="employer-body" id="company-about" aria-labelledby="company-about-title">
<div><h2 id="company-about-title">О компании</h2><p class="employer-description">{about}</p></div>
<aside class="employer-summary"><h3>Что означают отметки</h3>
<dl class="employer-trust-facts"><div><dt>Проверка СТАЖНО</dt><dd>{'Пройдена' if trust.get('verified') else 'Нет отметки проверки'}</dd></div><div><dt>Email компании</dt><dd>{'Подтверждён' if trust.get('email_verified') else 'Нет отметки подтверждения'}</dd></div><div><dt>Реквизиты компании</dt><dd>{'Указаны' if trust.get('inn_provided') else 'Нет отметки об указании'}</dd></div></dl>
<p class="employer-trust-note">Подтверждение email означает доступ к почте, а указание реквизитов — их наличие в профиле. Эти отметки не гарантируют условия работы. Обязанности, оплату и оформление обсудите с работодателем.</p></aside>
</section>
<aside class="employer-bottom"><h2>Следующий шаг — изучить вакансию</h2><p>Условия можно прочитать без регистрации. Доступные действия показаны на странице вакансии. Контакты соискателя не раскрываются автоматически: для знакомства предусмотрено отдельное согласие.</p><a href="/journal/kak-proverit-vakansiyu">Как проверить работодателя и вакансию</a></aside>
</main><footer class="employer-wrap employer-footer">СТАЖНО · Ваш опыт работает на вас</footer>
</body></html>"""
    return HTMLResponse(html, headers={"Cache-Control": "public, max-age=60"})
