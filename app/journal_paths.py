"""Curated reading journeys built exclusively from currently published Journal articles.

Guides are editorial navigation, not user profiling. They have no personal
data, cookies, visitor tracking or independent publication state.
"""
from __future__ import annotations

from html import escape

from fastapi import HTTPException
from fastapi.responses import HTMLResponse

PATHS = (
    {
        "slug": "nayti-rabotu",
        "title": "Найти работу с опорой на опыт",
        "description": "Подготовьте профиль, проверьте условия вакансии и уверенно пройдите собеседование.",
        "action": "Смотреть вакансии",
        "href": "/#jobs",
        "steps": (
            ("kak-pokazat-opyt-v-profile", "Расскажите о своём опыте"),
            ("kak-proverit-vakansiyu", "Проверьте работодателя"),
            ("sobesedovanie-posle-50", "Подготовьтесь к разговору"),
            ("kak-obsuzhdat-zarplatu", "Обсудите условия"),
        ),
    },
    {
        "slug": "novye-navyki",
        "title": "Освоить новые навыки",
        "description": "Выберите практическую цель и сделайте первые шаги к новым рабочим задачам.",
        "action": "Смотреть вакансии",
        "href": "/#jobs",
        "steps": (
            ("perehod-v-novuyu-professiyu", "Выберите направление"),
            ("cifrovye-navyki-dlya-raboty", "Освойте полезные инструменты"),
            ("udalyonnaya-rabota-bez-riskov", "Проверьте удалённые предложения"),
        ),
    },
    {
        "slug": "delitsya-opytom",
        "title": "Делиться опытом и находить коллег",
        "description": "Изучите проектную работу, наставничество и профессиональные знакомства.",
        "action": "Открыть сообщество",
        "href": "/community",
        "steps": (
            ("proektnaya-rabota-posle-50", "Выберите формат проекта"),
            ("nastavnichestvo-peredacha-opyta", "Подготовьтесь к наставничеству"),
            ("rabotodatelyu-ocenit-opyt", "Посмотрите на запрос работодателя"),
        ),
    },
)


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def visible_paths(articles: list[dict]) -> list[dict]:
    """Only published CMS articles are allowed in a visitor-facing journey."""
    by_slug = {article["slug"]: article for article in articles}
    result = []
    for entry in PATHS:
        steps = [
            {"label": label, "article": by_slug[slug]}
            for slug, label in entry["steps"] if slug in by_slug
        ]
        if steps:
            result.append({**entry, "steps": steps})
    return result


def _shell(title: str, description: str, canonical: str, body: str) -> HTMLResponse:
    from .journal import _layout
    return HTMLResponse(
        _layout(title, description, canonical, body),
        headers={"Cache-Control": "public, max-age=300"},
    )


def paths_index(articles: list[dict]) -> HTMLResponse:
    paths = visible_paths(articles)
    cards = "".join(
        '<article class="jr-path-card">'
        f'<span class="jr-kicker">МАРШРУТ · {len(path["steps"])} ШАГА</span>'
        f'<h2><a href="/journal/paths/{_e(path["slug"])}">{_e(path["title"])}</a></h2>'
        f'<p>{_e(path["description"])}</p>'
        f'<a class="jr-primary" href="/journal/paths/{_e(path["slug"])}">Выбрать маршрут →</a>'
        '</article>'
        for path in paths
    )
    body = (
        '<div class="jr-breadcrumb"><a href="/">Главная</a> / <a href="/journal">Журнал</a> / Маршруты</div>'
        '<section class="jr-hero"><span class="jr-kicker">ПОЛЕЗНЫЕ МАРШРУТЫ</span>'
        '<h1>С чего начать?</h1><p>Выберите свою цель. Материалы расположены по шагам, '
        'а личные данные для чтения не нужны.</p></section>'
        f'<section class="jr-path-grid" aria-label="Маршруты чтения">{cards}</section>'
        '<p class="jr-back"><a href="/journal">← Все статьи журнала</a></p>'
    )
    return _shell("Маршруты по работе и навыкам | СТАЖНО",
                  "Тематические подборки статей о работе, новых навыках и наставничестве.",
                  "/journal/paths", body)


def path_detail(slug: str, articles: list[dict]) -> HTMLResponse:
    path = next((item for item in visible_paths(articles) if item["slug"] == slug), None)
    if path is None:
        raise HTTPException(404, "Маршрут не найден")
    steps = "".join(
        '<li class="jr-path-step">'
        f'<span class="jr-path-number" aria-hidden="true">{index}</span>'
        '<div>'
        f'<span class="jr-tag">{_e(step["article"]["category"])}</span>'
        f'<h2><a href="/journal/{_e(step["article"]["slug"])}">{_e(step["label"])}</a></h2>'
        f'<p>{_e(step["article"]["description"])}</p>'
        f'<a href="/journal/{_e(step["article"]["slug"])}">Читать статью →</a>'
        '</div></li>'
        for index, step in enumerate(path["steps"], start=1)
    )
    body = (
        '<div class="jr-breadcrumb"><a href="/">Главная</a> / '
        '<a href="/journal">Журнал</a> / <a href="/journal/paths">Маршруты</a></div>'
        '<section class="jr-hero"><span class="jr-kicker">ПЛАН ДЕЙСТВИЙ</span>'
        f'<h1>{_e(path["title"])}</h1><p>{_e(path["description"])}</p></section>'
        f'<ol class="jr-path-steps">{steps}</ol>'
        '<aside class="jr-bottom"><h2>Готовы к следующему шагу?</h2>'
        '<p>Выберите подходящее действие, когда закончите чтение.</p>'
        f'<a class="jr-primary" href="{_e(path["href"])}">{_e(path["action"])} →</a>'
        '<a class="jr-secondary" href="/journal/paths">Другие маршруты</a></aside>'
    )
    return _shell(path["title"] + " | СТАЖНО", path["description"],
                  "/journal/paths/" + path["slug"], body)
