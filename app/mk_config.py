"""Контент мини-лендинга регистрации на мастер-класс с главбухом ONCOUNT.

План: plans/2026-06-02-mk-buh-registraciya-lending.md. Правило репо №1 — дата и
тексты живут здесь, не в вёрстке (меняются одной строкой при переносе МК).
Переиспользуем 3 квалифицирующих вопроса из quiz_config (один источник правды:
тот же белый список вариантов и заголовки). Дискриминатор EVENT_SLUG отделяет
регистрации МК от заявок /consultation в общей таблице quiz_submissions.
"""

from app import quiz_config

# Меняется одной строкой при переносе даты МК (правило репо №1 — не хардкод в вёрстке).
EVENT_SLUG = "mk-buh-2026-07-30"
EVENT_DATE_HUMAN = "30 июля, 18:00 (по Дубаю)"
EVENT_DATE_HUMAN_EN = "July 30, 6:00 PM (Dubai time)"

# Экран-обложка (шаг 0) — оффер мастер-класса (с Marquiz-референса).
COVER = {
    "image": "/static/img/mk-hero.jpg",  # баннер мастер-класса (сжат: 1000px, ~62КБ)
    "title": "Закрытая встреча с главным бухгалтером ONCOUNT",
    "date": EVENT_DATE_HUMAN,
    "place": "ZOOM",
    "lead": (
        "За 90 минут — ответы по налогам, за которые консультанты берут тысячи "
        "дирхам. Corporate Tax, VAT, структура бизнеса, вывод денег — честно, "
        "о чём обычно молчат."
    ),
    "bullets": [
        "0% Corporate Tax: кто реально может и до когда",
        "Freezone vs Mainland: где 0% работает, а где маркетинг",
        "Как выводить деньги без проблем с FTA",
    ],
    "cta": "Зарегистрироваться",
    "note": "Участие бесплатное, количество мест ограничено",
}

# EN-версия обложки (та же структура, дата из EVENT_DATE_HUMAN_EN).
COVER_EN = {
    "image": "/static/img/mk-hero.jpg",
    "title": "Private meeting with the Chief Accountant of ONCOUNT",
    "date": EVENT_DATE_HUMAN_EN,
    "place": "ZOOM",
    "lead": (
        "In 90 minutes — the tax answers consultants charge thousands of "
        "dirhams for. Corporate Tax, VAT, business structure, withdrawing "
        "money — an honest talk about what usually stays unsaid."
    ),
    "bullets": [
        "0% Corporate Tax: who really qualifies and until when",
        "Freezone vs Mainland: where 0% works and where it is just marketing",
        "How to withdraw money without problems with the FTA",
    ],
    "cta": "Register",
    "note": "Free to attend, seats are limited",
}

# Интро над шагами-вопросами (после обложки).
INTRO = (
    "Чтобы встреча была полезной именно вам — ответьте на три коротких вопроса. "
    "Мы подготовимся под вашу ситуацию."
)

# EN-версия интро.
INTRO_EN = (
    "To make the meeting useful for you — answer three short questions. "
    "We will prepare for your situation."
)

# Те же 3 вопроса, что и в /consultation — один источник правды (не дублируем).
QUESTIONS = quiz_config.QUESTIONS
QUESTIONS_EN = quiz_config.QUESTIONS_EN
VALID_OPTIONS = quiz_config.VALID_OPTIONS  # белый список RU ∪ EN (собран в quiz_config)
QUESTION_TITLES = quiz_config.QUESTION_TITLES  # русские — идут в примечание Kommo

# Финальный экран (имя + телефон).
FINAL = {
    "title": "Куда прислать ссылку на встречу?",
    "subtitle": (
        "Оставьте номер телефона WhatsApp — ссылку на встречу пришлём на этот номер."
    ),
    "consent": (
        "Нажимая кнопку, вы соглашаетесь на обработку своих данных для связи "
        "по регистрации."
    ),
    "submit": "Получить ссылку на встречу",
}

# EN-версия финального экрана.
FINAL_EN = {
    "title": "Where should we send the meeting link?",
    "subtitle": (
        "Leave your WhatsApp number — we will send the meeting link to it."
    ),
    "consent": (
        "By clicking the button, you agree to the processing of your data "
        "so we can contact you about your registration."
    ),
    "submit": "Get the meeting link",
}

# Экран после успешной регистрации (Zoom-ссылку публично НЕ показываем).
THANKS = {
    "title": "Вы зарегистрированы!",
    "subtitle": (
        "Ссылку на Zoom пришлём в WhatsApp перед встречей 30 июля. До встречи!"
    ),
}

# EN-версия экрана после регистрации (дата из EVENT_DATE_HUMAN_EN).
THANKS_EN = {
    "title": "You are registered!",
    "subtitle": (
        "We will send the Zoom link to your WhatsApp before the meeting — "
        f"{EVENT_DATE_HUMAN_EN}. See you there!"
    ),
}

# Соцсети на экране «спасибо» — три квадрата-ссылки (правило репо №1: URL здесь,
# не в вёрстке). type ∈ {instagram, telegram, site} → иконка в quiz.html.
SOCIALS = [
    {"type": "instagram", "label": "Instagram Николь", "url": "https://www.instagram.com/nikol_hillton"},
    {"type": "telegram",  "label": "Telegram-канал ONCOUNT", "url": "https://t.me/oncountt"},
    {"type": "site",      "label": "Сайт ONCOUNT", "url": "https://oncount.com"},
]

# EN-версия — те же url/type, переведены только label.
SOCIALS_EN = [
    {"type": "instagram", "label": "Nikole's Instagram", "url": "https://www.instagram.com/nikol_hillton"},
    {"type": "telegram",  "label": "ONCOUNT Telegram channel", "url": "https://t.me/oncountt"},
    {"type": "site",      "label": "ONCOUNT website", "url": "https://oncount.com"},
]

# Параметры лида в Kommo воронку 1.1 (под предохранителем QUIZ_KOMMO_LIVE).
KOMMO_LEAD_PREFIX = "Мастер-класс 30 июля"
KOMMO_LEAD_TAG = "masterclass"
KOMMO_NOTE_INTRO = (
    "Регистрация на мастер-класс с главбухом ONCOUNT (30 июля, 18:00 Дубай)."
)

# Авто-подтверждение участнику в WhatsApp сразу после регистрации (решение Николь
# 2026-07-21). Дата подставляется из EVENT_DATE_HUMAN — при переносе МК меняется
# одной строкой сверху. Уходит с канала WAZZUP_CLIENT_CHANNEL_ID, best-effort.
CONFIRM_WA_TEXT = (
    "Здравствуйте! Это ONCOUNT. Вы записаны на закрытую встречу с главным "
    f"бухгалтером — {EVENT_DATE_HUMAN}, ZOOM ✅\n\n"
    "Ссылку на Zoom пришлём сюда перед встречей.\n\n"
    "Если появятся вопросы — просто ответьте на это сообщение."
)

# EN-версия WhatsApp-подтверждения (дата из EVENT_DATE_HUMAN_EN).
CONFIRM_WA_TEXT_EN = (
    "Hello! This is ONCOUNT. You are registered for the private meeting with "
    f"our Chief Accountant — {EVENT_DATE_HUMAN_EN}, ZOOM ✅\n\n"
    "We will send the Zoom link here before the meeting.\n\n"
    "If you have any questions — just reply to this message."
)


def page(lang: str) -> dict:
    """Контекст quiz.html для языка ('en' → EN-тексты, иначе RU)."""
    en = lang == "en"
    return {
        "cover": COVER_EN if en else COVER,
        "intro": INTRO_EN if en else INTRO,
        "questions": QUESTIONS_EN if en else QUESTIONS,
        "final": FINAL_EN if en else FINAL,
        "thanks": THANKS_EN if en else THANKS,
        "socials": SOCIALS_EN if en else SOCIALS,
    }
