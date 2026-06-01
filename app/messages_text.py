"""Тексты сообщений бота — RU + EN. Формат: Telegram HTML.

В HTML экранировать нужно только &, <, >. Подчёркивания и URL — без проблем.

Структура: TEXTS[KEY][lang]. Доступ — через t(KEY, lang): язык, которого нет,
откатывается на русский. Так новый ключ не уронит бот, даже если EN забыли.
"""
from __future__ import annotations

TEXTS: dict[str, dict[str, str]] = {
    "WELCOME_NEW": {
        "ru": (
            "Привет, {first_name}! 👋\n\n"
            "Я — бот ONCOUNT: лицензированной бухгалтерии полного цикла в ОАЭ.\n\n"
            "С чего хотите начать?\n\n"
            "🎓 <b>Практикум «Настройка AI-сотрудников»</b> — за ~2 часа настроишь "
            "2 AI-сотрудников, которые делают сайты и презентации. Бесплатно.\n"
            "🤝 <b>Партнёрская программа</b> — приводите клиентов, получайте вознаграждение.\n\n"
            "Выберите внизу 👇"
        ),
        "en": (
            "Hi, {first_name}! 👋\n\n"
            "I'm the ONCOUNT bot — a licensed full-cycle accounting firm in the UAE.\n\n"
            "Where would you like to start?\n\n"
            "🎓 <b>«Setting up AI employees» practicum</b> — in ~2 hours set up "
            "2 AI employees that build websites and presentations. Free.\n"
            "🤝 <b>Partner program</b> — introduce clients, earn rewards.\n\n"
            "Pick an option below 👇"
        ),
    },
    "PRACTICUM_INTRO": {
        "ru": (
            "🎓 <b>Практикум «Настройка AI-сотрудников»</b>\n\n"
            "За ~2 часа в 3 шага настроите 2 AI-сотрудников, которые сами делают "
            "сайты и презентации для вашего бизнеса.\n\n"
            "Что внутри:\n"
            "• Пошаговые уроки: День 1 — настройка, День 2 — практика\n"
            "• Готовые промпты и тайм-коды\n"
            "• Всё в вашем личном кабинете, проходите в своём темпе\n\n"
            "Жмите на кнопку — вход в кабинет откроется сразу на практикуме:"
        ),
        "en": (
            "🎓 <b>«Setting up AI employees» practicum</b>\n\n"
            "In ~2 hours and 3 steps you'll set up 2 AI employees that build "
            "websites and presentations for your business.\n\n"
            "What's inside:\n"
            "• Step-by-step lessons: Day 1 — setup, Day 2 — practice\n"
            "• Ready-made prompts and timecodes\n"
            "• Everything in your cabinet, go at your own pace\n\n"
            "Tap the button — your cabinet opens straight on the practicum:"
        ),
    },
    "WELCOME_PARTNER": {
        "ru": (
            "С возвращением, {first_name}! 🤝\n\n"
            "Что хотите сделать?"
        ),
        "en": (
            "Welcome back, {first_name}! 🤝\n\n"
            "What would you like to do?"
        ),
    },
    "PARTNER_ONBOARDING_INTRO": {
        "ru": (
            "🤝 <b>Партнёрская программа ONCOUNT</b>\n\n"
            "ONCOUNT — ведущая лицензированная бухгалтерия в ОАЭ: страховка ответственности "
            "1 млн AED, чёткие регламенты, бухгалтеры с опытом 8+ лет и сотни довольных клиентов. "
            "Рекомендуйте уверенно — ваша репутация с нами только растёт.\n\n"
            "<b>Как работает:</b> вы передаёте контакт клиента в один клик → наш менеджер свяжется "
            "в рабочие часы в течение часа, подберёт тариф, и мы качественно выполним работу. "
            "Вы видите статусы и отчёты, а довольный клиент благодарит именно вас.\n\n"
            "<b>Выплаты до 10 числа, чётко и вовремя:</b>\n"
            "   ▸ <b>100%</b> от первого месяца бухгалтерского обслуживания;\n"
            "   ▸ <b>30%</b> от разовых услуг (банки, аудит, отчёты) — обычно $500–1 000;\n"
            "   ▸ от <b>10 клиентов/мес</b> — индивидуальные тарифы.\n"
            "В среднем — <b>$2 000–25 000</b> в месяц.\n\n"
            "Тексты, посты, чек-листы и сайты с UTM-метками уже ждут вас."
        ),
        "en": (
            "🤝 <b>ONCOUNT Partner Program</b>\n\n"
            "ONCOUNT is a leading licensed accounting firm in the UAE: 1M AED liability insurance, "
            "clear procedures, accountants with 8+ years of experience, and hundreds of satisfied clients. "
            "Recommend us with confidence — your reputation only grows with us.\n\n"
            "<b>How it works:</b> you pass the client's contact in one click → our manager reaches out "
            "within the hour during working hours, suggests the right plan, and we do the job properly. "
            "You see statuses and reports, and the happy client thanks you.\n\n"
            "<b>Payouts by the 10th, clear and on time:</b>\n"
            "   ▸ <b>100%</b> of the client's first month of accounting service;\n"
            "   ▸ <b>30%</b> of one-off services (banking, audit, reports) — usually $500–1,000;\n"
            "   ▸ from <b>10 clients/mo</b> — individual rates.\n"
            "On average — <b>$2,000–25,000</b> a month.\n\n"
            "Copy, posts, checklists, and landing pages with UTM tags are already waiting for you."
        ),
    },
    "PARTNER_LINKS": {
        "ru": (
            "🔗 <b>Ваши партнёрские ссылки</b>\n"
            "Код партнёра: <code>{ref_slug}</code>\n\n"
            "💼 <b>Бесплатная консультация с бухгалтером</b>\n"
            "Telegram: <code>{link_consult_tg}</code>\n"
            "WhatsApp: <code>{link_consult_wa}</code>\n\n"
            "🎓 <b>Мастер-класс с бухгалтером</b>\n"
            "Telegram: <code>{link_mclass_tg}</code>\n"
            "WhatsApp: <code>{link_mclass_wa}</code>\n\n"
            "🤝 <b>Партнёрская ссылка в бот ONCOUNT Community</b>\n"
            "10% от вознаграждений приглашённых партнёров.\n"
            "<code>{link_partner_bot}</code>\n\n"
            "Открыть со всеми кнопками «Скопировать» и QR-кодами: {webapp_url}/links"
        ),
        "en": (
            "🔗 <b>Your partner links</b>\n"
            "Partner code: <code>{ref_slug}</code>\n\n"
            "💼 <b>Free consultation with an accountant</b>\n"
            "Telegram: <code>{link_consult_tg}</code>\n"
            "WhatsApp: <code>{link_consult_wa}</code>\n\n"
            "🎓 <b>Masterclass with an accountant</b>\n"
            "Telegram: <code>{link_mclass_tg}</code>\n"
            "WhatsApp: <code>{link_mclass_wa}</code>\n\n"
            "🤝 <b>Partner link to the ONCOUNT Community bot</b>\n"
            "10% of the rewards earned by partners you invite.\n"
            "<code>{link_partner_bot}</code>\n\n"
            "Open it with all the «Copy» buttons and QR codes: {webapp_url}/links"
        ),
    },
    "TRANSFER_INTRO": {
        "ru": (
            "💰 <b>Передать клиента</b>\n\n"
            "Введите имя клиента:"
        ),
        "en": (
            "💰 <b>Introduce a client</b>\n\n"
            "Enter the client's name:"
        ),
    },
    "TRANSFER_ASK_PHONE": {
        "ru": "Телефон, Telegram или WhatsApp клиента:",
        "en": "Client's phone, Telegram, or WhatsApp:",
    },
    "TRANSFER_ASK_TASK": {
        "ru": "Опишите задачу клиента в одном сообщении:",
        "en": "Describe the client's request in one message:",
    },
    "TRANSFER_DONE": {
        "ru": (
            "✅ Клиент <b>{name}</b> передан в работу.\n\n"
            "Спасибо за доверие. Менеджер ONCOUNT свяжется с ним в рабочее время "
            "в течение часа и проведёт полную консультацию. Статус сделки и вознаграждение — "
            "в вашем личном кабинете."
        ),
        "en": (
            "✅ Client <b>{name}</b> has been handed over.\n\n"
            "Thanks for your trust. An ONCOUNT manager will reach out during working hours "
            "within the hour and give a full consultation. The deal status and your partner reward "
            "are in your personal cabinet."
        ),
    },
    "ONBOARDING_PARTNER_OK": {
        "ru": "\n\n✅ Жмите на кнопку для входа в кабинет.",
        "en": "\n\n✅ Tap the button to enter your cabinet.",
    },
    "LOGIN_READY": {
        "ru": "Готово! Жмите на кнопку — откроется кабинет партнёра.",
        "en": "Done! Tap the button — your partner cabinet will open.",
    },
    "LOGIN_EXPIRED": {
        "ru": (
            "Ссылка для входа истекла или уже использована.\n"
            "Откройте /login на сайте ещё раз."
        ),
        "en": (
            "The login link has expired or was already used.\n"
            "Open /login on the website again."
        ),
    },
    "OPEN_CABINET_PROMPT": {
        "ru": "Жмите на кнопку — откроется ваш кабинет:",
        "en": "Tap the button — your cabinet will open:",
    },
    "MENU_PARTNER_TITLE": {
        "ru": "Меню партнёра:",
        "en": "Partner menu:",
    },
    "NEED_START": {
        "ru": "Сначала /start.",
        "en": "Please /start first.",
    },
    "STATS_BODY": {
        "ru": (
            "📊 <b>Ваша статистика:</b>\n\n"
            "• Передано клиентов: <b>{total}</b>\n"
            "• Успешных: <b>{won}</b>\n"
            "• В работе: <b>{in_progress}</b>\n"
            "• Конверсия: <b>{conversion}%</b>\n\n"
            "Полный дашборд: {dashboard_url}"
        ),
        "en": (
            "📊 <b>Your stats:</b>\n\n"
            "• Clients referred: <b>{total}</b>\n"
            "• Won: <b>{won}</b>\n"
            "• In progress: <b>{in_progress}</b>\n"
            "• Conversion: <b>{conversion}%</b>\n\n"
            "Full dashboard: {dashboard_url}"
        ),
    },
    "PRODUCTS_HEADER": {
        "ru": "📦 <b>Тарифы и сервисы ONCOUNT</b>\n\n",
        "en": "📦 <b>ONCOUNT plans and services</b>\n\n",
    },
    "PRODUCTS_FOOTER": {
        "ru": "Подробности — в ЛК: {products_url}",
        "en": "Details in your cabinet: {products_url}",
    },
    "FAQ_HEADER": {
        "ru": "❓ <b>Частые вопросы</b>\n\n",
        "en": "❓ <b>Frequently asked questions</b>\n\n",
    },
    "FAQ_FOOTER": {
        "ru": "\nПолный FAQ: {faq_url}",
        "en": "\nFull FAQ: {faq_url}",
    },
    "MESSAGES_BODY": {
        "ru": (
            "📨 <b>Тексты рассылок</b> — 5 готовых шаблонов под разные сегменты.\n\n"
            "Полный список с кнопкой «Скопировать» — в ЛК:\n{messages_url}"
        ),
        "en": (
            "📨 <b>Outreach copy</b> — 5 ready-made templates for different segments.\n\n"
            "The full list with a «Copy» button is in your cabinet:\n{messages_url}"
        ),
    },
    "LANG_SWITCHED": {
        "ru": "Язык переключён на русский 🇷🇺",
        "en": "Language switched to English 🇬🇧",
    },
    # Экран выбора языка показывается до того, как язык известен — поэтому он
    # двуязычный сразу (одинаков для ru/en).
    "LANG_PICK": {
        "ru": "Выберите язык / Choose your language 👇",
        "en": "Выберите язык / Choose your language 👇",
    },
}


def t(key: str, lang: str = "ru", **kwargs) -> str:
    """Текст по ключу и языку. Неизвестный язык/ключ → русский fallback.

    kwargs прокидываются в .format(), если переданы (удобно для шаблонов).
    """
    variants = TEXTS.get(key, {})
    text = variants.get(lang) or variants.get("ru", "")
    return text.format(**kwargs) if kwargs else text
