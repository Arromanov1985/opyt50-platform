"""Curated reading journeys built exclusively from currently published Journal articles.

Guides are editorial navigation, not user profiling. They have no personal
data, cookies, visitor tracking or independent publication state.
"""
from __future__ import annotations

from html import escape
import hashlib
import json

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


# Practical editorial tasks complement the existing reading routes. They are
# intentionally small, actionable, and never ask visitors to enter personal data.
STEP_TASKS = {
    "kak-pokazat-opyt-v-profile": "Сформулируйте свою специализацию одной фразой и запишите три реальных профессиональных достижения для себя.",
    "kak-proverit-vakansiyu": "Выберите интересную вакансию, проверьте сведения о компании и составьте список вопросов об условиях.",
    "sobesedovanie-posle-50": "Подготовьте короткий рассказ о своём опыте и один пример решения рабочей задачи. Потренируйтесь произнести их вслух.",
    "kak-obsuzhdat-zarplatu": "Определите приемлемый график, минимальный доход и условия, которые нужно уточнить до решения.",
    "perehod-v-novuyu-professiyu": "Выберите одну интересующую профессию и сравните требования двух-трёх вакансий со своими навыками.",
    "cifrovye-navyki-dlya-raboty": "Выберите один цифровой навык и выполните небольшое упражнение на вымышленных данных.",
    "udalyonnaya-rabota-bez-riskov": "Проверьте оборудование и связь, составьте вопросы о графике, оплате и безопасности удалённой работы.",
    "proektnaya-rabota-posle-50": "Опишите для себя одну рабочую задачу, которую могли бы выполнить как отдельный проект, и ожидаемый результат.",
    "nastavnichestvo-peredacha-opyta": "Выберите тему, которой можете научить коллегу, и подготовьте короткий практический пример без закрытых данных.",
    "rabotodatelyu-ocenit-opyt": "Подготовьте два проверяемых примера того, как ваш опыт помогает решить конкретные задачи работодателя.",
}


def step_key(article: dict, label: str, task: str) -> str:
    # Revision changes invalidate the corresponding check mark, not unrelated
    # steps. Only published editorial content is used; no visitor data.
    content = {key: article.get(key) for key in ("title", "description", "category", "sections")}
    content.update(label=label, task=task)
    digest = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":")).encode("utf-8")).hexdigest()[:24]
    return article["slug"] + ":" + digest


def _journey_attrs(path: dict) -> str:
    keys = " ".join(step["key"] for step in path["steps"])
    return f'data-jr-journey="{_e(path["slug"])}" data-jr-journey-steps="{_e(keys)}"'


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def visible_paths(articles: list[dict]) -> list[dict]:
    """Only published CMS articles are allowed in a visitor-facing journey."""
    by_slug = {article["slug"]: article for article in articles}
    result = []
    for entry in PATHS:
        steps = [
            {"label": label, "article": by_slug[slug], "task": STEP_TASKS[slug],
             "key": step_key(by_slug[slug], label, STEP_TASKS[slug])}
            for slug, label in entry["steps"] if slug in by_slug
        ]
        if steps:
            result.append({**entry, "steps": steps})
    return result


def _shell(title: str, description: str, canonical: str, body: str) -> HTMLResponse:
    from .journal import _layout
    return HTMLResponse(
        _layout(title, description, canonical, body),
        headers={"Cache-Control": "no-store"},
    )


def _prelaunch_note() -> str:
    from .journal import _prelaunch_note as notice
    return notice()


def paths_index(articles: list[dict]) -> HTMLResponse:
    paths = visible_paths(articles)
    cards = "".join(
        f'<article class="jr-path-card" {_journey_attrs(path)}>'
        f'<span class="jr-kicker">МАРШРУТ · {len(path["steps"])} ШАГА</span>'
        f'<h2><a href="/journal/paths/{_e(path["slug"])}">{_e(path["title"])}</a></h2>'
        f'<p>{_e(path["description"])}</p>'
        '<div class="jr-journey-card-progress" data-jr-journey-progress hidden>'
        '<p data-jr-journey-count role="status"></p>'
        f'<progress max="{len(path["steps"])}" value="0" aria-label="Выполненные шаги"></progress>'
        '<p class="jr-journey-warning" data-jr-journey-warning hidden>Отметки в этом браузере недоступны.</p></div>'
        f'<a class="jr-primary" data-jr-journey-resume href="/journal/paths/{_e(path["slug"])}">Выбрать маршрут →</a>'
        '</article>'
        for path in paths
    )
    body = (
        '<div class="jr-breadcrumb"><a href="/">Главная</a> / <a href="/journal">Журнал</a> / Маршруты</div>'
        '<section class="jr-hero"><span class="jr-kicker">ПОЛЕЗНЫЕ МАРШРУТЫ</span>'
        '<h1>С чего начать?</h1><p>Выберите цель и двигайтесь по небольшим практическим шагам. '
        'Отмечайте выполненное и возвращайтесь к плану в этом браузере. Регистрация не нужна.</p></section>'
        + _prelaunch_note() +
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
    action = "community_click" if path["href"] == "/community" else "jobs_click"
    steps = "".join(
        f'<li class="jr-path-step" id="step-{_e(step["article"]["slug"])}" tabindex="-1" data-jr-journey-step="{_e(step["key"])}">'
        f'<span class="jr-path-number" aria-hidden="true">{index}</span>'
        '<div>'
        f'<span class="jr-tag">{_e(step["article"]["category"])}</span>'
        f'<h2><a href="/journal/{_e(step["article"]["slug"])}">{_e(step["label"])}</a></h2>'
        f'<p>{_e(step["article"]["description"])}</p>'
        f'<a href="/journal/{_e(step["article"]["slug"])}">Читать статью →</a>'
        f'<p class="jr-journey-task"><strong>Что сделать:</strong> {_e(step["task"])}</p>'
        '<label class="jr-journey-check" data-jr-journey-control hidden>'
        f'<input type="checkbox" data-jr-journey-check="{_e(step["key"])}">'
        f'<span>Шаг выполнен: {_e(step["label"])}</span></label>'
        '</div></li>'
        for index, step in enumerate(path["steps"], start=1)
    )
    body = (
        '<div class="jr-breadcrumb"><a href="/">Главная</a> / '
        '<a href="/journal">Журнал</a> / <a href="/journal/paths">Маршруты</a></div>'
        '<section class="jr-hero"><span class="jr-kicker">ПЛАН ДЕЙСТВИЙ</span>'
        f'<h1>{_e(path["title"])}</h1><p>{_e(path["description"])}</p></section>'
        + _prelaunch_note() +
        f'<section class="jr-journey-plan" {_journey_attrs(path)}>'
        '<div class="jr-journey-summary" data-jr-journey-progress hidden>'
        '<h2>Мой план действий</h2><p data-jr-journey-count role="status"></p>'
        f'<progress max="{len(path["steps"])}" value="0" aria-label="Выполненные шаги"></progress>'
        '<p>Отметки хранятся только в этом браузере, не связаны с аккаунтом и не передаются серверу. '
        'На общем устройстве их могут увидеть другие пользователи браузера.</p>'
        '<p class="jr-journey-warning" data-jr-journey-warning role="status" hidden></p>'
        '<div class="jr-journey-actions"><a class="jr-primary" data-jr-journey-resume href="#step-' +
        _e(path["steps"][0]["article"]["slug"]) + '">Начать с первого шага →</a>'
        '<button type="button" class="jr-save-button" data-jr-journey-reset>Сбросить отметки</button></div></div>'
        f'<ol class="jr-path-steps">{steps}</ol></section>'
        '<aside class="jr-bottom" id="jr-journey-next"><h2>Готовы к следующему шагу?</h2>'
        '<p>Выберите подходящее действие, когда закончите чтение.</p>'
        f'<a class="jr-primary" href="{_e(path["href"])}" data-growth-action="{action}">'
        f'{_e(path["action"])} →</a>'
        '<a class="jr-secondary" href="/journal/paths">Другие маршруты</a></aside>'
    )
    return _shell(path["title"] + " | СТАЖНО", path["description"],
                  "/journal/paths/" + path["slug"], body)
