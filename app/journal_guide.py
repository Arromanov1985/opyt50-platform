"""Editorial navigator: only published material, no inferred visitor interests.

Events are announcements from editors, not bookings or automatically scraped
listings. Dates are displayed as supplied by the editor; no imaginary events.
"""
from __future__ import annotations

from datetime import date
from html import escape
from urllib.parse import urlsplit

from fastapi import HTTPException
from fastapi.responses import HTMLResponse

SECTIONS = {
    "overview": ("Профессиональный навигатор", "Материалы, обучение и профессиональные мероприятия"),
    "news": ("Отраслевые новости", "Редакционные новости с указанием источников"),
    "learning": ("Обучение и практические материалы", "Развивайте навыки в удобном темпе"),
    "events": ("Мероприятия и вебинары", "Редакционные анонсы с датой, форматом и организатором"),
    "personal": ("Моя подборка", "Ваш выбор профессиональных тем и материалов для чтения"),
}
GUIDE_PATHS = tuple("/journal/guide/" + slug for slug in SECTIONS)
FORMATS = {"online": "Онлайн", "offline": "Очно", "hybrid": "Гибридный формат"}
LEARNING_SEEDS = {"cifrovye-navyki-dlya-raboty", "nastavnichestvo-peredacha-opyta",
                  "perehod-v-novuyu-professiyu", "proektnaya-rabota-posle-50"}


TOPICS = {
    "career": "Карьера и поиск работы",
    "management": "Управление и предпринимательство",
    "sales": "Продажи и работа с клиентами",
    "engineering": "Инженерия и производство",
    "technology": "ИТ и цифровые навыки",
    "finance": "Финансы и бухгалтерия",
    "operations": "Логистика и операционная работа",
    "education": "Образование и наставничество",
    "safety": "Безопасность и защита данных",
}
SEED_TOPICS = {
    "kak-pokazat-opyt-v-profile": ("career",),
    "kak-proverit-vakansiyu": ("career", "safety"),
    "proektnaya-rabota-posle-50": ("career", "management", "education"),
    "sobesedovanie-posle-50": ("career",),
    "cifrovye-navyki-dlya-raboty": ("technology", "education"),
    "rabotodatelyu-ocenit-opyt": ("management", "career"),
    "perehod-v-novuyu-professiyu": ("career", "education"),
    "kak-obsuzhdat-zarplatu": ("career",),
    "nastavnichestvo-peredacha-opyta": ("education", "management"),
    "udalyonnaya-rabota-bez-riskov": ("technology", "safety", "career"),
}
KINDS = {"article": "Статьи", "news": "Новости", "learning": "Обучение", "event": "Мероприятия"}


def article_topics(article: dict) -> list[str]:
    raw = article.get("topics", SEED_TOPICS.get(article["slug"], ()))
    return [key for key in TOPICS if key in raw] if isinstance(raw, (list, tuple)) else []


def selection_kind(article: dict) -> str:
    kind = article_type(article)
    return "learning" if kind == "article" and article["slug"] in LEARNING_SEEDS else kind


def save_button(slug: str) -> str:
    return ('<button type="button" class="jr-save-button" data-jr-save="' + _e(slug) +
            '" aria-pressed="false" hidden>Сохранить для чтения</button>')


def _event_card(item: dict) -> str:
    return ('<a class="jr-card" data-jr-event-date="' + _e(item.get("event_date")) +
            '" data-jr-event-format="' + _e(item.get("event_format")) +
            '" href="/journal/' + _e(item["slug"]) + '">'
            '<span class="jr-tag">' + _e(date_label(item.get("event_date"))) +
            ' · ' + _e(FORMATS.get(item.get("event_format"), "")) + '</span>'
            '<h2>' + _e(item["title"]) + '</h2><p>' + _e(item["description"]) +
            '</p><p>Организатор: ' + _e(item.get("source_name")) +
            '</p><span class="jr-card-link">Подробнее →</span></a>')


def _personal_section(articles: list[dict]) -> str:
    from .journal import _article_card
    choices = "".join(
        '<label class="jr-topic-choice"><input type="checkbox" data-jr-topic value="' + key +
        '"><span>' + _e(label) + '</span></label>' for key, label in TOPICS.items())
    options = "".join('<option value="' + key + '">' + _e(label) + '</option>'
                      for key, label in KINDS.items())
    cards = []
    for item in articles:
        topics = article_topics(item)
        kind = selection_kind(item)
        cards.append(
            '<article class="jr-personal-card" data-jr-material="' + _e(item["slug"]) +
            '" data-jr-kind="' + _e(kind) + '" data-jr-topics="' + _e(" ".join(topics)) + '">' +
            (_event_card(item) if kind == "event" else _article_card(item)) +
            ('<p class="jr-topic-labels">' + _e(" · ".join(TOPICS[key] for key in topics)) + '</p>' if topics else '') +
            save_button(item["slug"]) + '</article>')
    return (
        '<section class="jr-list"><h2 class="jr-list-title">Подберите материалы по своим интересам</h2>'
        '<p>Выберите одно или несколько направлений. Если ничего не выбрано, показаны материалы текущей страницы. '
        'Отбор идёт по редакционным темам на текущей странице. Закладки сохраняются при переходах между страницами. </p>'
        '<section class="jr-discovery jr-personal-controls" id="jr-personal-controls" hidden>'
        '<fieldset class="jr-topic-fieldset"><legend>Профессиональные интересы</legend>'
        '<div class="jr-topic-grid">' + choices + '</div></fieldset>'
        '<div class="jr-personal-filters"><label for="jr-personal-kind">Тип материала'
        '<select id="jr-personal-kind"><option value="all">Все типы</option>' + options + '</select></label>'
        '<label class="jr-topic-choice"><input type="checkbox" id="jr-personal-saved"><span>Только сохранённое</span></label></div>'
        '<div class="jr-local-actions"><button type="button" id="jr-remember-topics" class="jr-save-button">Запомнить интересы</button>'
        '<button type="button" id="jr-reset-topics" class="jr-save-button">Сбросить фильтры</button>'
        '<button type="button" id="jr-clear-reading" class="jr-save-button">Очистить интересы и закладки</button></div>'
        '<p class="jr-analytics-note">Интересы запоминаются только по вашей команде. Закладки и настройки хранятся в этом браузере, '
        'не привязаны к аккаунту и не синхронизируются между устройствами. На общем устройстве их могут увидеть другие пользователи браузера. '
        'Сервер не получает эти настройки. Скрытые редакцией материалы не показываются даже в закладках.</p>'
        '<p id="jr-personal-count" class="jr-results-count" role="status" aria-live="polite"></p>'
        '</section><noscript><p>Для фильтров и закладок включите JavaScript. Все материалы доступны и без него.</p></noscript>'
        '<p id="jr-reading-status" class="jr-results-count" role="status" aria-live="polite"></p>'
        '<div id="jr-personal-grid" class="jr-grid">' + "".join(cards) + '</div>'
        '<p id="jr-personal-empty" class="jr-no-results" hidden>Подходящих материалов нет. Измените фильтры или откройте все материалы.</p>'
        '</section>')


def _events_section(items: list[dict]) -> str:
    if not items:
        return _cards(items, "events")
    options = "".join('<option value="' + key + '">' + _e(label) + '</option>'
                      for key, label in FORMATS.items())
    return (
        '<section class="jr-discovery jr-event-controls" id="jr-event-controls" hidden>'
        '<div class="jr-personal-filters"><label for="jr-event-period">Период'
        '<select id="jr-event-period"><option value="upcoming">Предстоящие и сегодня</option>'
        '<option value="past">Прошедшие</option><option value="all">Все даты</option></select></label>'
        '<label for="jr-event-format">Формат<select id="jr-event-format"><option value="all">Все форматы</option>' +
        options + '</select></label></div>'
        '<p class="jr-analytics-note">Период определяется по календарной дате на вашем устройстве. Фильтр действует на текущей странице.</p>'
        '<p class="jr-results-count" id="jr-event-count" role="status" aria-live="polite"></p></section>'
        '<div class="jr-grid" id="jr-events-grid">' + "".join(_event_card(item) for item in items) + '</div>'
        '<p id="jr-event-empty" class="jr-no-results" hidden>Нет мероприятий по выбранным условиям.</p>')


def _e(value) -> str:
    return escape(str(value or ""), quote=True)


def source_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if any(ch.isspace() or ord(ch) < 32 for ch in value) or "\\" in value:
        raise HTTPException(422, "Укажите корректную HTTPS-ссылку на источник")
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname or "." not in parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443)):
            raise ValueError("invalid source")
    except ValueError:
        raise HTTPException(422, "Укажите корректную HTTPS-ссылку без логина и пароля") from None
    return value


def date_label(value) -> str:
    try:
        parsed = date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return ""
    return parsed.strftime("%d.%m.%Y")


def article_type(article: dict) -> str:
    return article.get("content_type", "article")


def editorial_facts(article: dict) -> str:
    kind = article_type(article)
    if kind == "article" and not (article.get("source_name") or article.get("source_url")):
        return ""
    labels = {"article": "Экспертная статья", "news": "Отраслевая новость", "learning": "Учебный материал", "event": "Анонс мероприятия"}
    if kind not in labels:
        return ""
    facts = ['<p><strong>' + labels[kind] + '</strong></p>']
    if kind == "event":
        facts.append('<p>Дата: <time datetime="' + _e(article.get("event_date")) + '">' +
                     _e(date_label(article.get("event_date"))) + '</time> · ' +
                     _e(FORMATS.get(article.get("event_format"), "")) + '</p>')
    name = article.get("source_name")
    if name:
        facts.append('<p>' + ('Организатор: ' if kind == "event" else 'Источник: ') + _e(name) + '</p>')
    try:
        url = source_url(article.get("source_url") or "")
    except HTTPException:
        url = ""
    if url:
        facts.append('<p><a href="' + _e(url) + '" rel="noopener noreferrer" target="_blank">'
                     'Открыть первоисточник ↗</a></p>')
    return '<aside class="jr-path-promo" aria-label="Сведения о материале">' + "".join(facts) + '</aside>'


def materials(section: str, articles: list[dict]) -> list[dict]:
    if section == "news":
        return sorted((a for a in articles if article_type(a) == "news"),
                      key=lambda a: (a.get("published_at") or "", a["slug"]), reverse=True)
    if section == "learning":
        return [a for a in articles if article_type(a) == "learning"
                or (article_type(a) == "article" and a["slug"] in LEARNING_SEEDS)]
    if section == "events":
        return sorted((a for a in articles if article_type(a) == "event"),
                      key=lambda a: (a.get("event_date") or "", a["slug"]))
    return []


def _cards(items: list[dict], section: str) -> str:
    from .journal import _article_card
    if not items:
        note = ("Подтверждённых анонсов пока нет. Редакция добавит мероприятия после проверки сведений."
                if section == "events" else "Материалов в этой рубрике пока нет.")
        return '<p class="jr-no-results" role="status">' + _e(note) + '</p>'
    cards = []
    for item in items:
        if section != "events":
            cards.append(_article_card(item))
            continue
        cards.append(_event_card(item))
    return '<div class="jr-grid">' + "".join(cards) + '</div>'


def guide_page_count(section: str, articles: list[dict]) -> int:
    from .journal import catalog_page_count
    if section == "overview":
        return 1
    return catalog_page_count(len(articles if section == "personal" else materials(section, articles)))


def guide_page(section: str, articles: list[dict], page: int = 1) -> HTMLResponse:
    from .journal import _layout, _prelaunch_note, catalog_slice, catalog_navigation, catalog_page_path
    if section not in SECTIONS:
        raise HTTPException(404, "Раздел не найден")
    if not 1 <= page <= guide_page_count(section, articles):
        raise HTTPException(404, "Страница каталога не найдена")
    title, description = SECTIONS[section]
    base = "/journal/guide/" + section
    nav = '<nav class="jr-category-filters" aria-label="Разделы навигатора">' + "".join(
        '<a class="jr-secondary" href="/journal/guide/' + slug + '"' +
        (' aria-current="page"' if slug == section else '') + '>' + _e(info[0]) + '</a>'
        for slug, info in SECTIONS.items()) + '</nav>'
    body = ('<div class="jr-breadcrumb"><a href="/">Главная</a> / <a href="/journal">Журнал</a> / '
            + _e(title) + '</div><section class="jr-hero"><span class="jr-kicker">ПРОФЕССИОНАЛЬНОЕ РАЗВИТИЕ</span><h1>'
            + _e(title) + '</h1><p>' + _e(description) + '</p></section>' + _prelaunch_note() + nav)
    if section == "overview":
        body += ('<aside class="jr-path-promo"><h2>Моя подборка</h2><p>Выберите профессиональные темы и сохраняйте полезные материалы в своём браузере.</p>'
                 '<a class="jr-primary" href="/journal/guide/personal">Открыть свою подборку →</a></aside>')
        for key in ("news", "learning", "events"):
            name, desc = SECTIONS[key]
            items = materials(key, articles)
            if key == "events":
                items = sorted(items, key=lambda item: (item.get("published_at") or "", item["slug"]), reverse=True)
            body += ('<section class="jr-list"><h2 class="jr-list-title">' + _e(name) +
                     '</h2><p>' + _e(desc) + '</p>' + _cards(items[:3], key) +
                     '<p><a class="jr-secondary" href="/journal/guide/' + key + '">Все материалы раздела →</a></p></section>')
    elif section == "personal":
        body += _personal_section(catalog_slice(articles, page))
        body += catalog_navigation(base, page, len(articles))
    else:
        if section == "events":
            body += ('<p class="jr-analytics-note">Анонсы упорядочены по дате. Уточняйте актуальность, время, '
                     'стоимость и условия участия у организатора. СТАЖНО не принимает заявки и оплату.</p>')
        items = materials(section, articles)
        page_items = catalog_slice(items, page)
        body += '<section class="jr-list">' + (_events_section(page_items) if section == 'events' else _cards(page_items, section)) + '</section>'
        body += catalog_navigation(base, page, len(items))
    body += ('<aside class="jr-bottom"><h2>Продолжите профессиональное развитие</h2>'
             '<p>Выберите учебный маршрут или найдите коллег для обмена практическим опытом.</p>'
             '<a class="jr-primary" href="/journal/paths">Маршруты чтения →</a>'
             '<a class="jr-secondary" href="/community/groups">Профессиональные группы</a></aside>')
    return HTMLResponse(_layout(title, description, catalog_page_path(base, page), body),
                        headers={"Cache-Control": "no-store"})
