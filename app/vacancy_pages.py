"""Shareable public vacancy pages. Renders only approved public job fields.

The owning API endpoint applies availability, moderation and account checks.
Never include applicant, employer contact, token or invitation fields here.
"""
from __future__ import annotations

import hashlib
from html import escape
from pathlib import Path
from urllib.parse import quote

from fastapi.responses import HTMLResponse


def _e(value) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def _pay(minimum, maximum) -> str:
    low, high = max(int(minimum or 0), 0), max(int(maximum or 0), 0)
    if low > 0 and low == high:
        return f"{low:,} ₽".replace(",", " ")
    if low > 0 and high > low:
        return f"от {low:,} до {high:,} ₽".replace(",", " ")
    if low > 0:
        return f"от {low:,} ₽".replace(",", " ")
    if high > 0:
        return f"до {high:,} ₽".replace(",", " ")
    return "По договорённости"


def _asset(name: str) -> str:
    revision = hashlib.sha256((Path(__file__).parent / "static" / name).read_bytes()).hexdigest()[:12]
    return f"/static/{name}?v={revision}"


def vacancy_page(job: dict) -> HTMLResponse:
    from .legal_config import legal_approved
    from .main import production_runtime

    job_id = int(job["id"])
    title = _e(job.get("title") or "Вакансия")
    company = _e(job.get("company_name") or "Работодатель")
    city = _e(job.get("city") or "Город не указан")
    schedule = _e(job.get("schedule") or "Уточняется")
    employment = _e(job.get("employment") or "Уточняется")
    pay = _e(_pay(job.get("salary_min"), job.get("salary_max")))
    description = _e(job.get("description") or "Уточните условия у работодателя.")
    teaser = _e(" ".join(str(job.get("description") or "").split())[:155] or
                f"{job.get('title') or 'Вакансия'} — условия и отклик на СТАЖНО.")
    skills = [
        _e(token.strip()) for token in str(job.get("skills") or "").split(",")
        if token.strip()
    ][:10]
    url = f"https://stazhno.ru/vacancies/{job_id}"
    start_url = "/?vacancy=" + quote(str(job_id)) + "#jobs"
    prelaunch = production_runtime() and not legal_approved()
    entry_note = (
        "Регистрация пока закрыта. Отклик доступен соискателям с существующим аккаунтом. "
        "Условия вакансии можно прочитать без входа."
        if prelaunch else
        "Для отклика нужен профиль соискателя. На следующем шаге откроется эта же вакансия. "
        "Переход по ссылке не отправляет отклик."
    )
    preparation = (
        '<a class="preparation-link" href="/journal/paths/nayti-rabotu">Подготовиться к поиску работы</a>'
        if prelaunch else ""
    )
    markup = f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} — {company} | СТАЖНО</title>
  <meta name="description" content="{teaser}">
  <link rel="canonical" href="{url}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="СТАЖНО">
  <meta property="og:title" content="{title} — {company}">
  <meta property="og:description" content="{teaser}">
  <meta property="og:url" content="{url}">
  <link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="{_asset('vacancy-share.css')}">
  <script src="{_asset('journal.js')}" defer></script>
</head>
<body>
  <a class="skip-link" href="#content">Перейти к вакансии</a>
  <header class="share-header"><div class="wrap">
    <a class="brand" href="/" aria-label="СТАЖНО — на главную">
      <img src="/static/brand-symbol.svg" alt="" width="32" height="32">
      стажно<span>.</span>ру</a>
    <nav aria-label="Разделы сайта"><a href="/#jobs">Все вакансии</a><a href="/employers">Работодатели</a><a href="/journal">Журнал</a></nav>
    <button class="reading-toggle" id="reading-mode-toggle" type="button" aria-pressed="false" aria-label="Включить крупный текст">Аа <span>Крупный текст</span></button>
  </div></header>
  <main class="wrap" id="content">
    <nav class="breadcrumbs" aria-label="Навигация">
      <a href="/">Главная</a><span aria-hidden="true">/</span>
      <a href="/#jobs">Вакансии</a><span aria-hidden="true">/</span>
      <span>Описание вакансии</span>
    </nav>
    <article class="vacancy-sheet">
      <span class="kicker">ОТКРЫТАЯ ВАКАНСИЯ</span>
      <h1>{title}</h1><p class="company"><a href="/companies/{int(job['employer_id'])}" data-growth-action="company_click">{company}</a> · {city}</p>
      <p class="salary"><span>Оплата</span><strong>{pay}</strong></p>
      <dl class="facts" aria-label="Основные условия">
        <div><dt>Город</dt><dd>{city}</dd></div>
        <div><dt>График</dt><dd>{schedule}</dd></div>
        <div><dt>Занятость</dt><dd>{employment}</dd></div>
      </dl>
      {f'<div class="skills" aria-label="Навыки">{ "".join("<span>"+skill+"</span>" for skill in skills) }</div>' if skills else ''}
      <section class="share-next-step" aria-labelledby="next-step-title">
        <h2 id="next-step-title">Как откликнуться</h2>
        <p class="share-entry-note">{entry_note}</p>
        <div class="share-actions">
          <a class="button primary" href="{start_url}" data-growth-action="apply_click">Перейти к отклику</a>
          <a class="button secondary" href="/#jobs" data-growth-action="jobs_click">Другие вакансии</a>
        </div>
        {preparation}
      </section>
      <section class="details"><h2>Условия и описание</h2>
        <p class="description">{description}</p></section>
      <aside class="share-privacy"><strong>Как связаться с работодателем?</strong>
        <p>Отклик отправляется через СТАЖНО. Личные контакты кандидата не передаются автоматически — для знакомства предусмотрено отдельное согласие.</p>
      </aside>
    </article>
    <section class="tips"><h2>Перед откликом</h2>
      <p>Проверьте описание обязанностей, оплату и график. Никому не передавайте пароли или коды подтверждения.</p>
      <a href="/journal/kak-proverit-vakansiyu">Как проверить вакансию →</a>
    </section>
  </main>
  <footer class="wrap share-footer"><span>СТАЖНО · Ваш опыт работает на вас</span><a href="/journal">Практические материалы</a></footer>
</body></html>"""
    return HTMLResponse(markup, headers={"Cache-Control": "public, max-age=60"})
