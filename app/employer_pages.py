"""Read-only public employer presentation, restricted to existing public API data."""
from __future__ import annotations

from html import escape

from fastapi.responses import HTMLResponse


def _e(value) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def _pay(low, high) -> str:
    a, b = max(0, int(low or 0)), max(0, int(high or 0))
    if a and b > a:
        return f"от {a:,} до {b:,} ₽".replace(",", " ")
    if a:
        return f"от {a:,} ₽".replace(",", " ")
    if b:
        return f"до {b:,} ₽".replace(",", " ")
    return "По договорённости"


def employer_page(data: dict) -> HTMLResponse:
    company = data["company"]
    jobs = data["jobs"]
    employer_id = int(company["id"])
    company_name = _e(company["company_name"])
    about = _e(company.get("about") or "Компания пока не добавила описание.")
    trust = company.get("trust") or {}
    status = (
        "Компания проверена администрацией СТАЖНО" if trust.get("verified")
        else "Статус проверки компании не подтверждён"
    )
    badges = []
    if trust.get("verified"):
        badges.append("Проверена СТАЖНО")
    if trust.get("email_verified"):
        badges.append("Email подтверждён")
    if trust.get("inn_provided"):
        badges.append("Реквизиты указаны")
    badge_html = "".join(f"<span>{_e(x)}</span>" for x in badges)
    cards = "".join(
        '<article class="public-employer-job">'
        f'<h3><a href="/vacancies/{int(job["id"])}">{_e(job["title"])}</a></h3>'
        f'<p>{_e(job.get("city") or "Город не указан")} · {_e(_pay(job.get("salary_min"), job.get("salary_max")))}</p>'
        f'<p>{_e(job.get("schedule") or "График не указан")} · {_e(job.get("employment") or "Формат не указан")}</p>'
        f'<a class="employer-job-link" href="/vacancies/{int(job["id"])}">Посмотреть вакансию</a>'
        '</article>'
        for job in jobs
    )
    if not cards:
        cards = '<p class="public-employer-empty">У этой компании пока нет опубликованных вакансий. Можно посмотреть другие предложения.</p>'
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
<link rel="stylesheet" href="/static/employer-share.css?v=1">
</head><body>
<a class="skip-link" href="#main">Перейти к содержимому</a>
<header class="employer-top"><div class="employer-wrap employer-top-inner">
<a class="employer-brand" href="/">стажно<span>.</span>ру</a>
<nav aria-label="Основное меню"><a href="/#jobs">Вакансии</a><a href="/journal">Журнал</a></nav>
</div></header>
<main id="main" class="employer-wrap">
<nav class="employer-crumbs" aria-label="Навигация"><a href="/">Главная</a><span>/</span><span>Работодатель</span></nav>
<section class="employer-hero"><span class="employer-kicker">РАБОТОДАТЕЛЬ НА СТАЖНО</span>
<h1>{company_name}</h1><p>{_e(status)}</p>
<div class="employer-badges" aria-label="Подтверждённые признаки">{badge_html}</div>
</section>
<section class="employer-body">
<div><h2>О компании</h2><p class="employer-description">{about}</p>
<p class="employer-trust-note">Статусы показывают только факты проверок на платформе, а не являются гарантией условий работы. Перед откликом изучите обязанности и договорённости.</p></div>
<aside class="employer-summary"><strong>{len(jobs)}</strong><span>открытых вакансий на странице</span><a href="/#jobs">Смотреть все вакансии</a></aside>
</section>
<section class="employer-jobs"><h2>Открытые вакансии</h2><div class="employer-jobs-grid">{cards}</div></section>
<aside class="employer-bottom"><h2>Нашли интересную работу?</h2><p>Отклик происходит на странице вакансии. Контакты соискателя не раскрываются автоматически: потребуется отдельное согласие на знакомство.</p><a href="/journal/kak-proverit-vakansiyu">Как проверить работодателя и вакансию</a></aside>
</main><footer class="employer-wrap employer-footer">СТАЖНО · Ваш опыт работает на вас</footer>
</body></html>"""
    return HTMLResponse(html, headers={"Cache-Control": "public, max-age=60"})
