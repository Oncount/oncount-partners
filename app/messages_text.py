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
            "С чего хочешь начать?\n\n"
            "📅 <b>Мастер-класс «AI 2-й мозг»</b> — 21 мая, 18:00 (Дубай). Бесплатно.\n"
            "🤝 <b>Партнёрская программа</b> — приводи клиентов, получай комиссию.\n\n"
            "Выбери внизу 👇"
        ),
        "en": (
            "Hi, {first_name}! 👋\n\n"
            "I'm the ONCOUNT bot — a licensed full-cycle accounting firm in the UAE.\n\n"
            "Where would you like to start?\n\n"
            "📅 <b>«AI Second Brain» masterclass</b> — May 21, 6:00 PM (Dubai). Free.\n"
            "🤝 <b>Partner program</b> — refer clients, earn commission.\n\n"
            "Pick an option below 👇"
        ),
    },
    "WELCOME_REGISTERED_FOR_EVENT": {
        "ru": (
            "Привет, {first_name}! 👋\n\n"
            "Ты уже зарегистрирован/-а на мастер-класс <b>«AI 2-й мозг»</b> 21 мая в 18:00 (Дубай).\n\n"
            "🎥 Zoom: https://us06web.zoom.us/j/81890945980\n\n"
            "Хочешь параллельно стать партнёром ONCOUNT? Жми кнопку ниже."
        ),
        "en": (
            "Hi, {first_name}! 👋\n\n"
            "You're already registered for the <b>«AI Second Brain»</b> masterclass on May 21 at 6:00 PM (Dubai).\n\n"
            "🎥 Zoom: https://us06web.zoom.us/j/81890945980\n\n"
            "Want to become an ONCOUNT partner too? Tap the button below."
        ),
    },
    "WELCOME_PARTNER": {
        "ru": (
            "С возвращением, {first_name}! 🤝\n\n"
            "Что хочешь сделать?"
        ),
        "en": (
            "Welcome back, {first_name}! 🤝\n\n"
            "What would you like to do?"
        ),
    },
    "EVENT_REGISTERED": {
        "ru": (
            "Готово, {first_name}! 🎉\n\n"
            "Ты зарегистрирован/-а на бесплатный AI-мастер-класс <b>«AI 2-й мозг»</b> от ONCOUNT.\n\n"
            "📅 <b>21 мая 2026, четверг, 18:00 (Дубай / GST)</b>\n"
            "🎥 Онлайн в Zoom — ссылку пришлю в день мероприятия.\n\n"
            "---\n\n"
            "<b>Подготовка к мастер-классу — 6 этапов. Делай по порядку:</b>\n\n"
            "🖥 Этап 1. Устанавливаем VS Code — ~5 мин\n"
            "🔐 Этап 2. Регистрируемся в Claude — ~20–30 мин\n"
            "💳 Этап 3. Оплачиваем подписку — ~10 мин\n"
            "⚙️ Этап 4. Ставим Claude Code и настраиваем — ~15 мин\n"
            "🎤 Этап 5. Голосовой ввод + скриншоты — ~10 мин\n"
            "🤖 Этап 6. Запускаем агента — ~10–20 мин\n\n"
            "📄 <a href=\"https://docs.google.com/document/d/18rpKrqfDK1dIBIz5Psf7W8aRF3aW2_vuW2KBG3FsTcs/edit?usp=sharing\">Пошаговая инструкция</a>\n\n"
            "Если не настроишь, не страшно, сделаешь позже."
        ),
        "en": (
            "Done, {first_name}! 🎉\n\n"
            "You're registered for the free AI masterclass <b>«AI Second Brain»</b> by ONCOUNT.\n\n"
            "📅 <b>Thursday, May 21, 2026, 6:00 PM (Dubai / GST)</b>\n"
            "🎥 Online via Zoom — I'll send the link on the event day.\n\n"
            "---\n\n"
            "<b>Getting ready — 6 steps. Do them in order:</b>\n\n"
            "🖥 Step 1. Install VS Code — ~5 min\n"
            "🔐 Step 2. Sign up for Claude — ~20–30 min\n"
            "💳 Step 3. Pay for the subscription — ~10 min\n"
            "⚙️ Step 4. Install and set up Claude Code — ~15 min\n"
            "🎤 Step 5. Voice input + screenshots — ~10 min\n"
            "🤖 Step 6. Launch your agent — ~10–20 min\n\n"
            "📄 <a href=\"https://docs.google.com/document/d/18rpKrqfDK1dIBIz5Psf7W8aRF3aW2_vuW2KBG3FsTcs/edit?usp=sharing\">Step-by-step guide</a>\n\n"
            "If you don't finish the setup, no worries — you can do it later."
        ),
    },
    "EVENT_REMINDER_24H": {
        "ru": (
            "Напоминаю: <b>завтра, 21 мая, в 18:00</b> (Дубай) — мастер-класс «AI 2-й мозг».\n\n"
            "✅ Проверь по чек-листу, что всё установлено.\n"
            "✅ Подготовь блокнот и наушники.\n"
            "✅ Заложи 3 часа — будет много практики.\n\n"
            "До завтра!"
        ),
        "en": (
            "Reminder: <b>tomorrow, May 21, at 6:00 PM</b> (Dubai) — the «AI Second Brain» masterclass.\n\n"
            "✅ Use the checklist to confirm everything is installed.\n"
            "✅ Get a notebook and headphones ready.\n"
            "✅ Set aside 3 hours — lots of hands-on practice.\n\n"
            "See you tomorrow!"
        ),
    },
    "EVENT_REMINDER_ZOOM": {
        "ru": (
            "Сегодня в <b>18:00</b> (Дубай) встречаемся на мастер-классе — "
            "<b>AI-автоматизация в B2B-бизнесе</b>.\n\n"
            "Что будем делать:\n"
            "1️⃣ Настроим Claude, который будет помнить всё о твоём бизнесе и "
            "предлагать лучшие решения на основе анализа конкурентов.\n"
            "2️⃣ Настроим 5 AI-сотрудников — для аналитики, маркетинговых текстов, "
            "лидогенерации, подготовки презентаций и напоминаний клиентам — и "
            "подключим их через API к соцсетям и CRM.\n"
            "3️⃣ Нетворкинг с участниками комьюнити B2B-эдвайзеров в Дубае.\n\n"
            "<a href=\"https://nikolhillton.github.io/ai_masterclass/\">Подробнее</a>\n\n"
            "🎥 <b>Ссылка на Zoom:</b> https://us06web.zoom.us/j/81890945980\n\n"
            "Сохрани, чтобы не искать. До вечера!"
        ),
        "en": (
            "Today at <b>6:00 PM</b> (Dubai) we meet at the masterclass — "
            "<b>AI automation for B2B business</b>.\n\n"
            "What we'll do:\n"
            "1️⃣ Set up Claude to remember everything about your business and "
            "suggest the best moves based on competitor analysis.\n"
            "2️⃣ Set up 5 AI employees — for analytics, marketing copy, "
            "lead generation, presentations, and client reminders — and "
            "connect them via API to social media and CRM.\n"
            "3️⃣ Networking with the B2B advisor community in Dubai.\n\n"
            "<a href=\"https://nikolhillton.github.io/ai_masterclass/\">Learn more</a>\n\n"
            "🎥 <b>Zoom link:</b> https://us06web.zoom.us/j/81890945980\n\n"
            "Save it so you don't have to search. See you tonight!"
        ),
    },
    "EVENT_REMINDER_1H": {
        "ru": (
            "Через час начинаем — <b>заходи</b> 🚀\n\n"
            "🎥 https://us06web.zoom.us/j/81890945980"
        ),
        "en": (
            "We start in one hour — <b>join in</b> 🚀\n\n"
            "🎥 https://us06web.zoom.us/j/81890945980"
        ),
    },
    "PARTNER_ONBOARDING_INTRO": {
        "ru": (
            "🤝 <b>Партнёрская программа ONCOUNT</b>\n\n"
            "Зарабатывай вместе с лицензированной бухгалтерией №1 для русскоязычного бизнеса в ОАЭ "
            "<b>от $2 000 – 25 000 каждый месяц</b>\n\n"
            "<b>Почему это выгодно:</b>\n"
            "• 🛡 <b>Надёжный партнёр.</b> Лицензия ОАЭ, страхование 1 000 000 AED, бухгалтеры с опытом 8+ лет.\n"
            "• 💰 <b>Щедрая комиссия — и вовремя.</b>\n"
            "   ▸ <b>100%</b> от первого месяца бухгалтерского обслуживания клиента;\n"
            "   ▸ <b>30%</b> от разовых услуг (аудит, налоговые отчёты, открытие компании, визы) — обычно $500–1 000 с клиента;\n"
            "   ▸ <b>10%</b> от агентских вознаграждений партнёров, которых ты привёл;\n"
            "   ▸ <b>White Label — 30% ежемесячно</b> с каждой оплаты при 10+ клиентах.\n"
            "• 🔗 <b>Готовые инструменты.</b> Реф-ссылки и тексты под 5 сегментов клиентов.\n"
            "• 📊 <b>Прозрачный дашборд:</b> каждый клиент, статус, комиссия — в одном кабинете.\n"
            "• ⚡ <b>1 клик — передал клиента.</b> Менеджер свяжется в течение часа.\n\n"
            "Открой свой кабинет — там уже ждут твои ссылки, тексты и статистика:"
        ),
        "en": (
            "🤝 <b>ONCOUNT Partner Program</b>\n\n"
            "Earn alongside the #1 licensed accounting firm for Russian-speaking business in the UAE — "
            "<b>$2,000–25,000 every month</b>\n\n"
            "<b>Why it pays off:</b>\n"
            "• 🛡 <b>A reliable partner.</b> UAE license, 1,000,000 AED insurance, accountants with 8+ years of experience.\n"
            "• 💰 <b>Generous commission — paid on time.</b>\n"
            "   ▸ <b>100%</b> of the client's first month of accounting service;\n"
            "   ▸ <b>30%</b> of one-off services (audit, tax reports, company setup, visas) — usually $500–1,000 per client;\n"
            "   ▸ <b>10%</b> of the agent rewards of partners you bring in;\n"
            "   ▸ <b>White Label — 30% monthly</b> on every payment once you have 10+ clients.\n"
            "• 🔗 <b>Ready-made tools.</b> Referral links and copy for 5 client segments.\n"
            "• 📊 <b>Transparent dashboard:</b> every client, status, and commission in one place.\n"
            "• ⚡ <b>1 click to refer a client.</b> A manager reaches out within the hour.\n\n"
            "Open your cabinet — your links, copy, and stats are already waiting:"
        ),
    },
    "PARTNER_LINKS": {
        "ru": (
            "🔗 <b>Твои реферальные ссылки</b>\n"
            "Код партнёра: <code>{ref_slug}</code>\n\n"
            "💼 <b>Бесплатная консультация с бухгалтером</b>\n"
            "Telegram: <code>{link_consult_tg}</code>\n"
            "WhatsApp: <code>{link_consult_wa}</code>\n\n"
            "🎓 <b>Мастер-класс с бухгалтером</b>\n"
            "Telegram: <code>{link_mclass_tg}</code>\n"
            "WhatsApp: <code>{link_mclass_wa}</code>\n\n"
            "🤝 <b>Партнёрская ссылка в бот ONCOUNT Community</b>\n"
            "10% от агентских вознаграждений приглашённых партнёров.\n"
            "<code>{link_partner_bot}</code>\n\n"
            "Открыть со всеми кнопками «Скопировать» и QR-кодами: {webapp_url}/links"
        ),
        "en": (
            "🔗 <b>Your referral links</b>\n"
            "Partner code: <code>{ref_slug}</code>\n\n"
            "💼 <b>Free consultation with an accountant</b>\n"
            "Telegram: <code>{link_consult_tg}</code>\n"
            "WhatsApp: <code>{link_consult_wa}</code>\n\n"
            "🎓 <b>Masterclass with an accountant</b>\n"
            "Telegram: <code>{link_mclass_tg}</code>\n"
            "WhatsApp: <code>{link_mclass_wa}</code>\n\n"
            "🤝 <b>Referral link to the ONCOUNT Community bot</b>\n"
            "10% of the agent rewards of partners you invite.\n"
            "<code>{link_partner_bot}</code>\n\n"
            "Open it with all the «Copy» buttons and QR codes: {webapp_url}/links"
        ),
    },
    "TRANSFER_INTRO": {
        "ru": (
            "💰 <b>Передать клиента</b>\n\n"
            "Введи имя клиента:"
        ),
        "en": (
            "💰 <b>Refer a client</b>\n\n"
            "Enter the client's name:"
        ),
    },
    "TRANSFER_ASK_PHONE": {
        "ru": "Телефон, Telegram или WhatsApp клиента:",
        "en": "Client's phone, Telegram, or WhatsApp:",
    },
    "TRANSFER_ASK_TASK": {
        "ru": "Опиши задачу клиента в одном сообщении:",
        "en": "Describe the client's request in one message:",
    },
    "TRANSFER_DONE": {
        "ru": (
            "✅ Клиент <b>{name}</b> передан в работу.\n\n"
            "Спасибо за доверие. Менеджер ONCOUNT свяжется с ним в рабочее время "
            "в течение часа и проведёт полную консультацию. Статус сделки и комиссия — "
            "в твоём личном кабинете."
        ),
        "en": (
            "✅ Client <b>{name}</b> has been handed over.\n\n"
            "Thanks for your trust. An ONCOUNT manager will reach out during working hours "
            "within the hour and give a full consultation. The deal status and your commission "
            "are in your personal cabinet."
        ),
    },
    "ONBOARDING_PARTNER_OK": {
        "ru": "\n\n✅ Ты — партнёр ONCOUNT. Жми кнопку для входа в кабинет.",
        "en": "\n\n✅ You're an ONCOUNT partner. Tap the button to enter your cabinet.",
    },
    "LOGIN_READY": {
        "ru": "Готово! Жми кнопку — откроется кабинет партнёра в браузере.",
        "en": "Done! Tap the button — your partner cabinet will open in the browser.",
    },
    "LOGIN_EXPIRED": {
        "ru": (
            "Ссылка для входа истекла или уже использована.\n"
            "Открой /login на сайте ещё раз."
        ),
        "en": (
            "The login link has expired or was already used.\n"
            "Open /login on the website again."
        ),
    },
    "OPEN_CABINET_PROMPT": {
        "ru": "Жми кнопку — откроется твой кабинет:",
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
            "📊 <b>Твоя статистика:</b>\n\n"
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
    "EVENT_TOAST_ALREADY": {
        "ru": "Уже было записано",
        "en": "Already registered",
    },
    "EVENT_TOAST_DONE": {
        "ru": "Зарегистрирован/-а!",
        "en": "Registered!",
    },
}


def t(key: str, lang: str = "ru", **kwargs) -> str:
    """Текст по ключу и языку. Неизвестный язык/ключ → русский fallback.

    kwargs прокидываются в .format(), если переданы (удобно для шаблонов).
    """
    variants = TEXTS.get(key, {})
    text = variants.get(lang) or variants.get("ru", "")
    return text.format(**kwargs) if kwargs else text
