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
}
GUIDE_PATHS = tuple("/journal/guide/" + slug for slug in SECTIONS)
FORMATS = {"online": "Онлайн", "offline": "Очно", "hybrid": "Гибридный формат"}
LEARNING_SEEDS = {"cifrovye-navyki-dlya-raboty", "nastavnichestvo-peredacha-opyta",
                  "perehod-v-novuyu-professiyu", "proektnaya-rabota-posle-50"}


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
    if kind == "article":
        return ""
    labels = {"news": "Отраслевая новость", "learning": "Учебный материал", "event": "Анонс мероприятия"}
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
        cards.append('<a class="jr-card" href="/journal/' + _e(item["slug"]) + '">'
                     '<span class="jr-tag">' + _e(date_label(item.get("event_date"))) +
                     ' · ' + _e(FORMATS.get(item.get("event_format"), "")) + '</span>'
                     '<h2>' + _e(item["title"]) + '</h2><p>' + _e(item["description"]) +
                     '</p><p>Организатор: ' + _e(item.get("source_name")) +
                     '</p><span class="jr-card-link">Подробнее →</span></a>')
    return '<div class="jr-grid">' + "".join(cards) + '</div>'


def guide_page(section: str, articles: list[dict]) -> HTMLResponse:
    from .journal import _layout, _prelaunch_note
    if section not in SECTIONS:
        raise HTTPException(404, "Раздел не найден")
    title, description = SECTIONS[section]
    nav = '<nav class="jr-category-filters" aria-label="Разделы навигатора">' + "".join(
        '<a class="jr-secondary" href="/journal/guide/' + slug + '"' +
        (' aria-current="page"' if slug == section else '') + '>' + _e(info[0]) + '</a>'
        for slug, info in SECTIONS.items()) + '</nav>'
    body = ('<div class="jr-breadcrumb"><a href="/">Главная</a> / <a href="/journal">Журнал</a> / '
            + _e(title) + '</div><section class="jr-hero"><span class="jr-kicker">ПРОФЕССИОНАЛЬНОЕ РАЗВИТИЕ</span><h1>'
            + _e(title) + '</h1><p>' + _e(description) + '</p></section>' + _prelaunch_note() + nav)
    if section == "overview":
        for key in ("news", "learning", "events"):
            name, desc = SECTIONS[key]
            body += ('<section class="jr-list"><h2 class="jr-list-title">' + _e(name) +
                     '</h2><p>' + _e(desc) + '</p>' + _cards(materials(key, articles)[:3], key) +
                     '<p><a class="jr-secondary" href="/journal/guide/' + key + '">Все материалы раздела →</a></p></section>')
    else:
        if section == "events":
            body += ('<p class="jr-analytics-note">Анонсы упорядочены по дате. Уточняйте актуальность, время, '
                     'стоимость и условия участия у организатора. СТАЖНО не принимает заявки и оплату.</p>')
        body += '<section class="jr-list">' + _cards(materials(section, articles), section) + '</section>'
    body += ('<aside class="jr-bottom"><h2>Продолжите профессиональное развитие</h2>'
             '<p>Выберите учебный маршрут или найдите коллег для обмена практическим опытом.</p>'
             '<a class="jr-primary" href="/journal/paths">Маршруты чтения →</a>'
             '<a class="jr-secondary" href="/community/groups">Профессиональные группы</a></aside>')
    return HTMLResponse(_layout(title, description, "/journal/guide/" + section, body),
                        headers={"Cache-Control": "no-store"})
