"""Public, editorial-only journal for STAZHNO release 0.5.34.

No profile data, DB access, comments, external tracking or user-generated HTML.
This is intentionally small: editorial content is reviewed and deployed as code.
"""
from __future__ import annotations

import json
from html import escape

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

ARTICLES = json.loads(r'''[{"slug":"kak-pokazat-opyt-v-profile","title":"Как показать свой опыт в профессиональном профиле","description":"Пошаговая инструкция: какую профессию указать, как описать навыки и результаты работы и что проверить перед публикацией профиля.","category":"Карьера","read":"5 минут","sections":[{"title":"Начните не с возраста, а с того, какую задачу решаете","paragraphs":["Работодателю и заказчику важно быстро понять, чем вы полезны. Вместо длинной биографии начните с профессии и направления: «Бухгалтер по участкам», «Мастер смены», «Менеджер по работе с корпоративными клиентами». Если вариантов несколько, выберите основной — его легче найти через поиск.","Опишите свою специализацию двумя-тремя понятными предложениями. Избегайте общих фраз вроде «ответственный, коммуникабельный». Лучше написать, с какими задачами и инструментами вы работаете."]},{"title":"Соберите доказательства опыта","paragraphs":["Вспомните три случая, когда благодаря вашей работе что-то стало лучше: сократились ошибки, ускорились поставки, удалось обучить сотрудников, наладить учёт или удержать клиента. Укажите конкретный результат, если можете его подтвердить.","Если точных цифр нет, не придумывайте их. Назовите масштаб задач: команда, участок, ассортимент, тип клиентов или проект. Хорошее описание показывает действие и результат, а не просто перечень должностных обязанностей."],"bullets":["Работал с учётом товаров и инвентаризацией нескольких складских зон.","Обучил новых сотрудников работе с 1С и внутренними регламентами.","Наладил обработку обращений корпоративных клиентов."]},{"title":"Укажите условия, при которых готовы работать","paragraphs":["Город, формат занятости, график и желаемая оплата помогают сразу отсечь неподходящие варианты. Обновляйте их, если ваши планы изменились. Для проектной работы отдельно отметьте, какие задачи готовы брать на ограниченный срок.","Не обязательно заполнять сразу все дополнительные поля: начните с профессии, навыков, города и условий; остальное можно уточнить позднее."]},{"title":"Защитите личные контакты","paragraphs":["Не размещайте номер телефона, почту и ссылки на личные мессенджеры в открытом описании опыта. На СТАЖНО контакты скрыты по умолчанию и передаются работодателю в установленном сценарии только после вашего согласия.","После сохранения профиля используйте предпросмотр «Печать / сохранить PDF». По умолчанию контактные данные в печатной версии тоже скрыты. Перед отправкой файла внимательно проверьте его содержимое."]}]},{"slug":"kak-proverit-vakansiyu","title":"Как проверить вакансию и сохранить свои данные","description":"Практический список проверок перед откликом и собеседованием: работодатель, условия, подозрительные требования и безопасность контактов.","category":"Безопасность","read":"4 минуты","sections":[{"title":"Сначала проверьте, кто предлагает работу","paragraphs":["Название компании, сфера деятельности, адрес и корпоративные каналы связи должны складываться в понятную картину. Поищите официальный сайт организации и убедитесь, что вакансия действительно относится к ней. Если объявление размещено от имени посредника, попросите прямо назвать его роль.","Отсутствие сайта само по себе не доказывает мошенничество, особенно у небольшого бизнеса. Оценивайте сразу несколько признаков и задавайте уточняющие вопросы."]},{"title":"Уточните условия до передачи документов","paragraphs":["Узнайте, какие задачи входят в обязанности, как устроен график, где находится рабочее место, как определяется оплата и кто будет руководителем. Попросите объяснить, из чего состоит обещанный доход, особенно если в объявлении указан широкий диапазон.","Не отправляйте фото паспорта, банковские реквизиты, коды из SMS или доступы к аккаунтам на этапе обычного знакомства с вакансией. Для законного оформления документов нужен отдельный понятный процесс."]},{"title":"Сигналы, при которых стоит остановиться","paragraphs":["Насторожиться стоит, если вас торопят, просят заплатить за трудоустройство, обучение или «резервирование места», предлагают получать чужие деньги на личную карту либо скрывают название компании и обязанности.","Если общение вызывает сомнения, не переходите по неизвестным ссылкам и не устанавливайте программы удалённого доступа по просьбе незнакомого собеседника."],"bullets":["До оплаты или передачи документов попросите письменное описание условий.","Уточните ФИО и должность контактного лица в компании.","При подозрениях завершите общение и сообщите администрации площадки."]},{"title":"Используйте согласие на открытие контактов","paragraphs":["На СТАЖНО работодателю доступен профессиональный профиль, а ваши личные контакты защищены до предусмотренного согласия. Это не отменяет собственной проверки работодателя, но помогает не публиковать телефон и почту для всех посетителей.","Никакой сервис не может гарантировать отсутствие мошенников. Осторожность и проверка условий важны на каждом этапе."]}]},{"slug":"proektnaya-rabota-posle-50","title":"Подработка, проекты и наставничество: как начать","description":"Как превратить профессиональные навыки в понятное предложение для заказчика: формат, результат, объём работы и первые шаги.","category":"Новые возможности","read":"5 минут","sections":[{"title":"Выберите конкретную услугу, а не абстрактную «подработку»","paragraphs":["Многолетний опыт можно использовать не только в штатной должности. Предпринимателю может понадобиться временный бухгалтер, производству — наставник для новой смены, отделу продаж — специалист для настройки клиентской базы.","Начните с одной услуги, которую вы можете объяснить за минуту: «проведу инвентаризацию», «настрою отчётность», «обучу сотрудников правилам приёмки товара». Чем конкретнее обещанный результат, тем проще обсудить работу."]},{"title":"Определите границы работы","paragraphs":["До начала договоритесь об объёме задач, сроках, способе связи, критериях приёмки результата и вознаграждении. Если заказчик ожидает постоянной доступности, это уже другое условие — его нужно обсуждать отдельно.","Не обещайте то, что зависит от недоступной информации или решений третьих лиц. Лучше начать с небольшого понятного проекта, чем брать слишком большой и неопределённый объём."]},{"title":"Подготовьте короткую профессиональную презентацию","paragraphs":["Понадобятся несколько строк о квалификации, два примера выполненных задач и перечень инструментов, которыми владеете. Не раскрывайте конфиденциальные данные бывших работодателей. Рабочие кейсы можно описать обобщённо, без названий клиентов и коммерческих секретов.","Обновите профиль СТАЖНО, чтобы потенциальный работодатель или заказчик понимал вашу специализацию. Для личной встречи можно сохранить печатную версию резюме в PDF."]},{"title":"Измеряйте реальный результат","paragraphs":["Первым успехом может стать не большая выручка, а конкретный разговор с заинтересованным заказчиком. Записывайте, какие предложения вызывают отклик, что чаще уточняют и где остаются вопросы.","Перед началом оплачиваемой деятельности отдельно выясните применимые правила оформления договоров и налогов. Не полагайтесь на универсальные советы без учёта вашей ситуации."]}]}]''')
BY_SLUG = {entry["slug"]: entry for entry in ARTICLES}
PUBLISHED = "2026-11-19"
ORIGIN = "https://stazhno.ru"


def _e(value: str) -> str:
    return escape(str(value), quote=True)


def _layout(title: str, description: str, path: str, body: str) -> str:
    canonical = ORIGIN + path
    return (
        "<!doctype html>\n<html lang=\"ru\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{_e(title)} — СТАЖНО.РУ</title>"
        f"<meta name=\"description\" content=\"{_e(description)}\">"
        f"<link rel=\"canonical\" href=\"{_e(canonical)}\">"
        "<meta name=\"theme-color\" content=\"#0B2D26\">"
        "<link rel=\"icon\" href=\"/static/favicon.svg\" type=\"image/svg+xml\">"
        "<meta property=\"og:site_name\" content=\"СТАЖНО.РУ\">"
        f"<meta property=\"og:title\" content=\"{_e(title)}\">"
        f"<meta property=\"og:description\" content=\"{_e(description)}\">"
        f"<meta property=\"og:url\" content=\"{_e(canonical)}\">"
        "<link rel=\"stylesheet\" href=\"/static/journal.css?v=1\">"
        "<script src=\"/static/journal.js?v=2\" defer></script>"
        "</head><body class=\"jr-page\">"
        "<a class=\"jr-skip\" href=\"#jr-content\">К основному содержанию</a>"
        "<header class=\"jr-header\"><div class=\"jr-wrap jr-top\">"
        "<a class=\"jr-brand\" href=\"/\" aria-label=\"СТАЖНО.РУ — на главную\">"
        "<img src=\"/static/brand-symbol.svg\" alt=\"\" width=\"36\" height=\"36\">"
        "стажно<span>.</span>ру</a>"
        "<nav class=\"jr-nav\" aria-label=\"Основное меню\">"
        "<a href=\"/journal\">Журнал</a><a href=\"/#jobs\">Вакансии</a>"
        "<a href=\"/#candidate-path\">Соискателям</a></nav>"
        "<button class=\"jr-text-toggle\" id=\"reading-mode-toggle\" aria-pressed=\"false\" "
        "type=\"button\" aria-label=\"Включить крупный текст\">Аа <span>Крупный текст</span></button>"
        "</div></header>"
        f"<main id=\"jr-content\" class=\"jr-wrap\">{body}</main>"
        "<footer class=\"jr-footer\"><div class=\"jr-wrap jr-footer-row\">"
        "<span>СТАЖНО.РУ — ваш опыт работает на вас</span>"
        "<a href=\"/\">На главную</a></div></footer>"
        "</body></html>"
    )


def _article_card(article: dict) -> str:
    return (
        f'<a class="jr-card" href="/journal/{_e(article["slug"])}">'
        f'<span class="jr-tag">{_e(article["category"])}</span>'
        f'<h2>{_e(article["title"])}</h2>'
        f'<p>{_e(article["description"])}</p>'
        f'<span class="jr-card-link">Читать · {_e(article["read"])} →</span></a>'
    )


def journal_index() -> HTMLResponse:
    cards = "".join(_article_card(item) for item in ARTICLES)
    body = (
        '<div class="jr-breadcrumb"><a href="/">Главная</a><span aria-hidden="true">/</span>Журнал</div>'
        '<section class="jr-hero"><span class="jr-kicker">ЖУРНАЛ СТАЖНО</span>'
        '<h1>Опыт открывает новые возможности</h1>'
        '<p>Понятные практические материалы о работе, профессиональном опыте и безопасности.'
        ' Без лишних обещаний и возрастных стереотипов.</p></section>'
        '<section class="jr-list" aria-label="Статьи"><h2 class="jr-list-title">Начните с полезного</h2>'
        f'<div class="jr-grid">{cards}</div></section>'
        '<aside class="jr-bottom"><h2>Готовы использовать свой опыт?</h2>'
        '<p>Посмотрите вакансии или начните с профессионального профиля. Контакты защищены.</p>'
        '<a class="jr-primary" href="/#jobs" data-growth-action="jobs_click">Посмотреть вакансии →</a></aside>'
    )
    return HTMLResponse(_layout("Журнал: работа и новые возможности после 50", 
                               "Практические статьи СТАЖНО о профессиональном опыте, работе, проектах и безопасности.",
                               "/journal", body), headers={"Cache-Control": "public, max-age=300"})


def journal_article(slug: str) -> HTMLResponse:
    article = BY_SLUG.get(slug)
    if article is None:
        raise HTTPException(status_code=404, detail="Статья не найдена")
    sections = []
    for section in article["sections"]:
        content = f'<h2>{_e(section["title"])}</h2>'
        content += "".join(f'<p>{_e(p)}</p>' for p in section["paragraphs"])
        if section.get("bullets"):
            content += '<ul>' + "".join(f'<li>{_e(b)}</li>' for b in section["bullets"]) + '</ul>'
        sections.append('<section>' + content + '</section>')
    article_body = (
        '<div class="jr-breadcrumb"><a href="/">Главная</a>'
        '<span aria-hidden="true">/</span><a href="/journal">Журнал</a>'
        f'<span aria-hidden="true">/</span>{_e(article["category"])}</div>'
        '<div class="jr-article-layout"><article class="jr-article">'
        f'<header><span class="jr-kicker">{_e(article["category"])}</span>'
        f'<h1>{_e(article["title"])}</h1>'
        f'<p class="jr-lead">{_e(article["description"])}</p>'
        f'<p class="jr-meta">Редакция СТАЖНО · <time datetime="{PUBLISHED}">19 ноября 2026</time>'
        f' · {_e(article["read"])} чтения</p></header>'
        + "".join(sections) + '</article>'
        '<aside class="jr-aside"><h2>Следующий шаг</h2>'
        '<p>Профессиональный профиль помогает показать навыки и условия работы.'
        ' Контакты не публикуются автоматически.</p>'
        '<a class="jr-primary" href="/#candidate-path" data-growth-action="profile_click">Создать профиль →</a>'
        '<a class="jr-secondary" href="/#jobs" data-growth-action="jobs_click">Посмотреть вакансии</a></aside></div>'
        '<p class="jr-back"><a href="/journal">← Все статьи журнала</a></p>'
    )
    return HTMLResponse(_layout(article["title"], article["description"],
                               "/journal/" + slug, article_body),
                        headers={"Cache-Control": "public, max-age=300"})



def journal_sitemap() -> Response:
    """Only public, editorial destinations; no account, profile or API URLs."""
    paths = ["/", "/journal"] + ["/journal/" + article["slug"] for article in ARTICLES]
    urls = "".join(
        "<url><loc>" + _e(ORIGIN + path) + "</loc>"
        "<lastmod>" + PUBLISHED + "</lastmod></url>"
        for path in paths
    )
    xml = '<?xml version="1.0" encoding="UTF-8"?>' + (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + urls + "</urlset>"
    )
    return Response(content=xml, media_type="application/xml",
                    headers={"Cache-Control": "public, max-age=300"})


def journal_robots(request: Request) -> PlainTextResponse:
    """Preview and unknown hosts are not search-indexable."""
    canonical_hosts = {"stazhno.ru", "www.stazhno.ru"}
    if request.url.hostname in canonical_hosts:
        policy = (
            "User-agent: *\n"
            "Disallow: /api/\n"
            "Sitemap: https://stazhno.ru/sitemap.xml\n"
        )
    else:
        policy = "User-agent: *\nDisallow: /\n"
    return PlainTextResponse(policy, headers={"Cache-Control": "public, max-age=300"})


def install_journal_routes(app: FastAPI) -> None:
    app.add_api_route("/robots.txt", journal_robots, methods=["GET"], include_in_schema=False)
    app.add_api_route("/sitemap.xml", journal_sitemap, methods=["GET"], include_in_schema=False)
    app.add_api_route("/journal", journal_index, methods=["GET"], include_in_schema=False)
    app.add_api_route("/journal/{slug}", journal_article, methods=["GET"], include_in_schema=False)
