"""Public employer discovery using ONLY active companies with approved open jobs.

This is deliberately read-only. No user accounts, contacts, private profiles,
payments or applicant records are used to build these pages.
"""
from __future__ import annotations

from html import escape
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from .vacancy_pages import _pay

ORIGIN = "https://stazhno.ru"
CSS = "/static/employer-directory.css?v=1"


def _e(value) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def _layout(title: str, description: str, canonical_path: str, content: str) -> HTMLResponse:
    canonical = ORIGIN + canonical_path
    markup = f"""<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)} | СТАЖНО</title>
<meta name="description" content="{_e(description)}">
<link rel="canonical" href="{_e(canonical)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="СТАЖНО">
<meta property="og:title" content="{_e(title)}">
<meta property="og:description" content="{_e(description)}">
<meta property="og:url" content="{_e(canonical)}">
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{CSS}">
</head><body>
<a class="skip-link" href="#main">Перейти к содержанию</a>
<header class="directory-header"><div class="wrap header-row">
<a class="brand" href="/" aria-label="СТАЖНО — на главную">
<img src="/static/brand-symbol.svg" width="34" height="34" alt="">
стажно<span>.</span>ру</a>
<nav aria-label="Основное меню">
<a href="/employers" aria-current="{"page" if canonical_path == "/employers" else "false"}">Работодатели</a>
<a href="/#jobs">Вакансии</a><a href="/journal">Журнал</a>
</nav></div></header>
<main class="wrap" id="main">{content}</main>
<footer class="wrap directory-footer">
<span>СТАЖНО — ваш опыт работает на вас</span>
<a href="/journal/kak-proverit-vakansiyu">Как проверить работодателя</a>
</footer></body></html>"""
    return HTMLResponse(markup, headers={"Cache-Control": "public, max-age=30"})


def _company_rows(db, query: str, city: str):
    """Discoverability is scoped to existing, moderated public vacancies."""
    sql = """SELECT e.user_id AS id, e.company_name,e.verified,
                    COUNT(v.id) AS vacancy_count,
                    MAX(v.id) AS latest_vacancy_id
             FROM employer_profiles e
             JOIN users u ON u.id=e.user_id AND u.role='employer'
             JOIN vacancies v ON v.employer_id=e.user_id AND v.status='open'
             LEFT JOIN account_controls c ON c.user_id=e.user_id
             LEFT JOIN vacancy_moderation vm ON vm.vacancy_id=v.id
             LEFT JOIN employer_public_profiles p ON p.employer_id=e.user_id
             WHERE COALESCE(c.status,'active')='active'
               AND COALESCE(vm.status,'approved')='approved'"""
    args = []
    if query:
        sql += " AND (instr(unicode_fold(e.company_name),?)>0 OR instr(unicode_fold(COALESCE(p.about,'')),?)>0)"
        args.extend([query.casefold(), query.casefold()])
    if city:
        sql += (" AND (unicode_fold(v.city)=? OR unicode_fold(v.city)='удалённо'"
                " OR unicode_fold(v.city)='любой город')")
        args.append(city.casefold())
    sql += """ GROUP BY e.user_id,e.company_name,e.verified
               ORDER BY COUNT(v.id) DESC,e.user_id DESC LIMIT 100"""
    return [dict(row) for row in db.execute(sql, args).fetchall()]


def employer_directory(query: str, city: str, db) -> HTMLResponse:
    query, city = query.strip(), city.strip()
    if len(query) > 100 or len(city) > 100:
        raise HTTPException(422, "Слишком длинный запрос. Уточните условия поиска.")
    rows = _company_rows(db, query, city)
    cards = "".join(
        f'<article class="employer-card"><span class="card-kicker">КОМПАНИЯ</span>'
        f'<h2><a href="/employers/{int(row["id"])}">{_e(row["company_name"])}</a></h2>'
        f'<p class="verification">{("Данные компании подтверждены" if row["verified"] else "Данные компании пока не проверены")}</p>'
        f'<p class="vacancy-counter"><strong>{int(row["vacancy_count"])}</strong> '
        f'открытых вакансий по текущему поиску</p>'
        f'<a class="card-link" href="/employers/{int(row["id"])}">Вакансии компании →</a></article>'
        for row in rows
    )
    filter_query = urlencode({"q": query, "city": city})
    clear_href = "/employers"
    empty = (
        '<div class="empty-list" role="status"><h2>Компаний по этим условиям не найдено</h2>'
        '<p>Расширьте поиск: проверьте название, город или посмотрите всех работодателей.</p>'
        f'<a class="button secondary" href="{clear_href}">Показать все компании</a></div>'
    )
    body = (
        '<nav class="breadcrumbs" aria-label="Навигация"><a href="/">Главная</a>'
        '<span aria-hidden="true">/</span>Работодатели</nav>'
        '<section class="intro"><span class="kicker">РАБОТОДАТЕЛИ СТАЖНО</span>'
        '<h1>Узнайте больше о компаниях</h1>'
        '<p>Здесь собраны работодатели с открытыми опубликованными вакансиями.'
        ' Сравнивайте предложения и условия, прежде чем откликаться.</p></section>'
        '<form class="employer-search" method="get" action="/employers" role="search">'
        '<label>Название или направление<input type="search" name="q" maxlength="100"'
        f' value="{_e(query)}" placeholder="Например, склад или производство"></label>'
        '<label>Город<input type="search" name="city" maxlength="100"'
        f' value="{_e(city)}" placeholder="Например, Москва"></label>'
        '<button type="submit" class="button primary">Найти компании</button>'
        '<a class="reset-link" href="/employers">Сбросить</a></form>'
        f'<p class="results-count" aria-live="polite">Найдено компаний: {len(rows)}</p>'
        + (f'<section class="employer-grid" id="employer-cards" aria-label="Компании">{cards}</section>'
           if rows else empty)
        + '<aside class="disclaimer"><strong>Проверяйте условия самостоятельно.</strong>'
        '<p>Публикация вакансии не означает гарантию добросовестности компании.'
        ' Личные контакты кандидатов остаются защищены правилами знакомства на СТАЖНО.</p></aside>'
    )
    # Directory query pages are noindexed by template, but the main directory
    # is canonical. Do not put arbitrary user search strings in canonical URLs.
    return _layout(
        "Работодатели и открытые вакансии",
        "Компании с опубликованными вакансиями на СТАЖНО: поиск по названию и городу.",
        "/employers", body,
    )


def employer_profile(employer_id: int, db, email_pattern, phone_pattern) -> HTMLResponse:
    if employer_id <= 0:
        raise HTTPException(404, "Компания не найдена")
    company = db.execute(
        """SELECT e.user_id AS id,e.company_name,e.verified,
                  COALESCE(p.about,'') AS about
           FROM employer_profiles e
           JOIN users u ON u.id=e.user_id AND u.role='employer'
           LEFT JOIN employer_public_profiles p ON p.employer_id=e.user_id
           LEFT JOIN account_controls c ON c.user_id=e.user_id
           WHERE e.user_id=? AND COALESCE(c.status,'active')='active'
             AND EXISTS (
               SELECT 1 FROM vacancies v
               LEFT JOIN vacancy_moderation vm ON vm.vacancy_id=v.id
               WHERE v.employer_id=e.user_id AND v.status='open'
                 AND COALESCE(vm.status,'approved')='approved'
             )""",
        (employer_id,),
    ).fetchone()
    if company is None:
        raise HTTPException(404, "Компания не найдена")
    rows = db.execute(
        """SELECT v.id,v.title,v.city,v.salary_min,v.salary_max,
                  v.schedule,v.employment
           FROM vacancies v
           LEFT JOIN vacancy_moderation vm ON vm.vacancy_id=v.id
           WHERE v.employer_id=? AND v.status='open'
             AND COALESCE(vm.status,'approved')='approved'
           ORDER BY v.id DESC LIMIT 50""",
        (employer_id,),
    ).fetchall()
    # Old free-text descriptions can predate current account-side validation.
    # Don't amplify accidentally embedded email/phone information in directory.
    about = str(company["about"] or "").strip()
    if email_pattern.search(about) or phone_pattern.search(about):
        about = ""
    about_markup = (
        f'<p class="company-about">{_e(about)}</p>' if about
        else '<p class="company-about">Компания пока не добавила публичное описание.</p>'
    )
    jobs = "".join(
        f'<article class="company-job"><div><h3>{_e(job["title"])}</h3>'
        f'<p>{_e(job["city"])} · {_e(job["schedule"] or "График уточняется")}'
        f' · {_e(job["employment"] or "Занятость уточняется")}</p>'
        f'<strong>{_e(_pay(job["salary_min"],job["salary_max"]))}</strong></div>'
        f'<a class="button secondary" href="/vacancies/{int(job["id"])}">Условия и отклик</a></article>'
        for job in rows
    )
    body = (
        '<nav class="breadcrumbs" aria-label="Навигация"><a href="/">Главная</a>'
        '<span aria-hidden="true">/</span><a href="/employers">Работодатели</a>'
        '<span aria-hidden="true">/</span>Компания</nav>'
        '<section class="intro company-hero"><span class="kicker">ПРОФИЛЬ РАБОТОДАТЕЛЯ</span>'
        f'<h1>{_e(company["company_name"])}</h1>'
        f'<p class="verification">{("Данные компании подтверждены" if company["verified"] else "Данные компании пока не проверены")}</p>'
        f'{about_markup}</section>'
        '<section class="company-vacancies" aria-label="Открытые вакансии компании">'
        f'<h2>Открытые вакансии <span>{len(rows)}</span></h2>{jobs}</section>'
        '<aside class="disclaimer"><strong>Что важно знать о контактах</strong>'
        '<p>Вы можете прочитать условия каждой вакансии без регистрации. Отклик и знакомство'
        ' проходят через СТАЖНО, личные контакты соискателя не публикуются автоматически.</p></aside>'
        '<p class="back-link"><a href="/employers">← Все работодатели</a></p>'
    )
    return _layout(
        str(company["company_name"]),
        f"Открытые вакансии компании {company['company_name']} на СТАЖНО.",
        f"/employers/{int(employer_id)}", body,
    )


def install_employer_directory(app: FastAPI) -> None:
    from .main import CONTACT_EMAIL_PATTERN, CONTACT_PHONE_PATTERN, get_connection

    @app.get("/employers", include_in_schema=False)
    def employer_directory_route(
        q: str = "", city: str = "", db=Depends(get_connection),
    ):
        return employer_directory(q, city, db)

    @app.get("/employers/{employer_id}", include_in_schema=False)
    def employer_profile_route(employer_id: int, db=Depends(get_connection)):
        return employer_profile(employer_id, db, CONTACT_EMAIL_PATTERN, CONTACT_PHONE_PATTERN)
