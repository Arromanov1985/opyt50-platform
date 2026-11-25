"""Public professional presence and private community workspace shells.

Public profiles use the same allowlisted service as the API. Account names,
resumes and contact fields are never used by this renderer.
"""
from __future__ import annotations

import hashlib
from html import escape
from pathlib import Path

from fastapi import Depends
from fastapi.responses import HTMLResponse

STATIC = Path(__file__).resolve().parent / "static"
GOALS = {
    "work": "Работа и подработка",
    "projects": "Совместные проекты",
    "mentoring": "Наставничество",
    "exchange": "Обмен опытом",
}


def _e(value) -> str:
    return escape(str(value or ""), quote=True)


def _asset(name: str) -> str:
    revision = hashlib.sha256((STATIC / name).read_bytes()).hexdigest()[:12]
    return f"/static/{name}?v={revision}"


def _public_content(person: dict) -> str:
    return f"""<nav class="breadcrumbs" aria-label="Путь к странице"><a href="/community">Профессиональное сообщество</a><span aria-hidden="true">/</span><span>Профиль</span></nav>
<section class="person-layout">
  <article class="panel public-person" data-person-id="{_e(person['public_id'])}">
    <span class="eyebrow">ПРОФЕССИОНАЛЬНЫЙ ПРОФИЛЬ</span>
    <div class="person-identity"><div class="person-avatar" aria-hidden="true">{_e(person['public_name'][:1])}</div><div><h1>{_e(person['public_name'])}</h1><p class="person-role-label">Профессиональное направление</p><p class="person-headline">{_e(person['headline'])}</p></div></div>
    <dl class="person-facts"><div><dt>Город</dt><dd>{_e(person.get('city') or 'Не указан')}</dd></div><div><dt>Цель знакомства</dt><dd>{_e(GOALS.get(person.get('goal'), 'Не указана'))}</dd></div></dl>
    <section class="person-section person-skills"><h2>Навыки и темы</h2><p class="multiline">{_e(person.get('skills') or 'Участник пока не добавил навыки.')}</p></section>
    <p class="person-summary-note">Направление, цель и опыт указаны самим участником.</p>
  </article>
  <aside class="panel person-action" id="person-next-step" aria-labelledby="person-next-step-title">
    <span class="eyebrow">СЛЕДУЮЩИЙ ШАГ</span><h2 id="person-next-step-title">Начните с общего интереса</h2><p>Предложите обсудить проект, работу или обменяться опытом. В запросе коротко расскажите о задаче и о том, чем можете быть полезны.</p>
    <button class="button primary full" id="request-connection" type="button">Предложить знакомство</button><p id="person-action-hint" class="help" role="status"></p><div id="person-follow-slot"></div>
    <p class="help">Для запроса нужно войти в аккаунт. Переписка откроется только после принятия запроса участником.</p>
    <p class="help person-contact-note">Имя и контакты из аккаунта не передаются. Здесь показаны только сведения, выбранные самим участником.</p>
  </aside>
  <section class="panel person-story" aria-labelledby="person-story-title"><h2 id="person-story-title">Чем могу быть полезен</h2><p class="multiline">{_e(person.get('about') or 'Участник пока не добавил описание опыта.')}</p></section>
  <aside class="panel safety-note person-safety"><h2>Как оценить профиль</h2><p>Модерация проверяет содержание профиля, но не подтверждает квалификацию и не гарантирует результат знакомства.</p><p>Обсудите конкретную задачу и ожидания до начала совместной работы.</p><button class="text-button" id="report-person" type="button">Сообщить о проблеме</button>
  </aside>
</section>"""


def community_page(mode: str = "directory", person: dict | None = None) -> HTMLResponse:
    titles = {
        "directory": "Профессиональное сообщество",
        "profile": "Мой профессиональный профиль",
        "feed": "Профессиональная лента",
        "connections": "Профессиональные связи",
        "moderation": "Модерация сообщества",
        "person": str((person or {}).get("public_name", "Профессиональный профиль")),
    }
    title = titles[mode]
    content = _public_content(person) if mode == "person" and person else '<div class="loading" role="status">Загружаем сообщество…</div>'
    intro = """<section class="community-hero"><div><span class="eyebrow">ПРОФЕССИОНАЛЬНОЕ СООБЩЕСТВО</span><h1>Опыт становится ценнее,<br> когда им делятся.</h1><p>Найдите коллег для проекта, передайте знания или начните новое профессиональное знакомство.</p><a class="button light" href="/community/profile">Создать свой профиль <span aria-hidden="true">↗</span></a></div><aside class="hero-note"><span class="note-symbol" aria-hidden="true">↗</span><h2>Есть что предложить.<br> Есть чему научиться.</h2><p>Работа, наставничество, совместные проекты и разговор по делу.</p></aside></section>""" if mode == "directory" else ""
    markup = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)} | СТАЖНО</title>
<meta name="description" content="Профессиональные профили, обмен опытом и знакомства по взаимному согласию на СТАЖНО.">
<meta name="robots" content="noindex, nofollow"><meta name="theme-color" content="#0b2d26">
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{_asset('community.css')}"><script src="{_asset('community.js')}" defer></script>
</head><body data-community-page="{mode}" data-person-id="{_e((person or {}).get('public_id'))}">
<a class="skip-link" href="#community-main">К основному содержанию</a>
<header class="community-header"><div class="wrap header-row"><a class="brand" href="/" aria-label="СТАЖНО — на главную"><img src="/static/brand-symbol.svg" width="32" height="32" alt=""><span class="brand-word">стажно<span class="brand-dot">.</span>ру</span></a>
<nav aria-label="Основное меню"><a href="/#jobs">Вакансии</a><a href="/community" aria-current="page">Сообщество</a><a href="/journal">Журнал</a></nav>
<div class="header-actions"><button id="reading-mode-toggle" class="text-button reading-toggle" type="button" aria-pressed="false" aria-label="Включить крупный текст">Аа <span>Крупный текст</span></button><a class="button secondary compact" href="/#account">Мой кабинет</a></div></div></header>
<main id="community-main" class="wrap">{intro}
<nav class="community-tabs" aria-label="Разделы сообщества"><a href="/community"{' aria-current="page"' if mode == 'directory' else ''}>Участники</a><a href="/community/feed"{' aria-current="page"' if mode == 'feed' else ''}>Лента <span id="feed-alert-badge" class="count" hidden></span></a><a href="/community/profile"{' aria-current="page"' if mode == 'profile' else ''}>Мой профиль</a><a href="/community/connections"{' aria-current="page"' if mode == 'connections' else ''}>Мои связи <span id="community-unread" class="count" hidden></span></a><a href="/community/moderation" id="moderation-nav" hidden>Модерация</a></nav>
<p id="community-notice" class="notice" role="status" aria-live="polite" hidden></p>
<div id="community-content">{content}</div>
<noscript><div class="panel"><p>Для поиска участников и работы с профилем включите JavaScript. Публичный профиль можно прочитать без него.</p><a href="/journal">Перейти в журнал</a></div></noscript>
</main>
<footer class="community-footer wrap"><p><strong>СТАЖНО.</strong> Ваш опыт работает на вас.</p><div><a href="/journal/kak-proverit-vakansiyu">Безопасное знакомство</a><a href="/">На главную</a></div></footer>
<dialog id="community-dialog" aria-labelledby="community-dialog-title"><div class="dialog-top"><h2 id="community-dialog-title"></h2><button class="icon-button" type="button" id="close-community-dialog" aria-label="Закрыть окно">×</button></div><div id="community-dialog-content"></div></dialog>
</body></html>"""
    return HTMLResponse(markup, headers={
        "Cache-Control": "no-store", "Pragma": "no-cache", "X-Robots-Tag": "noindex, nofollow",
    })


def install_community_pages(app) -> None:
    from .main import get_connection
    from .community import public_person

    @app.get("/community", include_in_schema=False)
    def community_directory():
        return community_page()

    @app.get("/community/feed", include_in_schema=False)
    def professional_feed():
        return community_page("feed")

    @app.get("/community/profile", include_in_schema=False)
    def professional_profile():
        return community_page("profile")

    @app.get("/community/connections", include_in_schema=False)
    def professional_connections():
        return community_page("connections")

    @app.get("/community/moderation", include_in_schema=False)
    def community_moderation():
        return community_page("moderation")

    @app.get("/people/{public_id}", include_in_schema=False)
    def public_professional_profile(public_id: str, db=Depends(get_connection)):
        return community_page("person", public_person(db, public_id))
