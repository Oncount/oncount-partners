"""Контент квиз-лендинга /consultation (план 2026-06-02).

Правило репо №1: тексты/варианты — не хардкод в шаблоне, а здесь (один источник
правды, легко править без вёрстки). Вопросы и варианты сняты со скринов
Marquiz-референса oncount.co/consultation15; заголовки шагов 1–2 подтверждены
Николь 2026-06-02. Ключи вопросов (`id`) стабильны — по ним пишем `answers`
в БД и собираем примечание лида, поэтому их НЕ меняем задним числом.
"""

# Экран-обложка (шаг 0) — оффер консультации с бухгалтером (макет Николь 2026-06-02).
# Поля badge/team/bullets_title рендерятся в quiz.html только если заданы (у /mk их нет).
COVER = {
    "image": "/static/img/consultation-hero.jpg",  # переговоры на фоне Бурдж-Халифа (Николь, 2026-06-02)
    "image_side": "right",  # десктоп — фото справа; мобайл — под кнопкой (см. .cover-split)
    "badge": "БЕСПЛАТНО",
    "title": "Личная 15-минутная консультация по налогам и бухгалтерии в ОАЭ",
    "lead": (
        "Для тех, кто планирует открыть компанию в ОАЭ или уже ведёт бизнес и "
        "хочет понять, как выстроить структуру, налоги и бухгалтерию без хаоса "
        "и лишних рисков."
    ),
    "team": [
        "Команда ONCOUNT",
        "200+ клиентов на сопровождении",
        "Работаем с международными компаниями и предпринимателями",
    ],
    "bullets_title": "После консультации у вас будет ясность:",
    "bullets": [
        "Какие налоги и отчёты обязательны для вашей компании",
        "Сколько реально должна стоить бухгалтерия — и за что вы переплачиваете сейчас",
        "Что включить в ежемесячное обслуживание, чтобы не было доплат",
    ],
    "cta": "Разобрать мою ситуацию",
    "note": None,
}

# EN-версия обложки (та же структура, отдаётся через page('en')).
COVER_EN = {
    "image": "/static/img/consultation-hero.jpg",
    "image_side": "right",
    "badge": "FREE",
    "title": "Personal 15-minute consultation on taxes and accounting in the UAE",
    "lead": (
        "For those who plan to open a company in the UAE or already run a "
        "business and want to understand how to set up their structure, taxes "
        "and accounting without chaos and extra risks."
    ),
    "team": [
        "ONCOUNT team",
        "200+ clients on ongoing support",
        "We work with international companies and entrepreneurs",
    ],
    "bullets_title": "After the consultation you will know:",
    "bullets": [
        "Which taxes and reports are mandatory for your company",
        "What accounting should really cost — and where you are overpaying now",
        "What to include in your monthly service so there are no extra charges",
    ],
    "cta": "Review my situation",
    "note": None,
}

# Соцсети на экране «спасибо» (как у /mk). type ∈ {instagram, telegram, site}.
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

# Постоянный интро-текст (показывается над каждым шагом, после обложки).
INTRO = (
    "Чтобы созвон был полезным, а не ознакомительным — ответьте на несколько "
    "вопросов. Мы заранее посмотрим вашу ситуацию и придём с конкретными "
    "цифрами, а не общими."
)

# EN-версия интро.
INTRO_EN = (
    "To make the call useful, not just introductory — answer a few questions. "
    "We will review your case in advance and come with specific numbers, "
    "not general ones."
)

# 3 вопроса. options — список строк (один выбор). hint — необязательный
# поясняющий абзац под заголовком.
QUESTIONS = [
    {
        "id": "service",
        "title": "С каким вопросом вам нужна помощь?",
        "hint": None,
        "options": [
            "Бухгалтерия и учёт",
            "Регистрация на корпоративный налог и НДС",
            "Аудит",
            "Подключение эквайринга",
            "Пока не уверен(а)",
        ],
    },
    {
        "id": "company",
        "title": "У вас уже есть компания в ОАЭ?",
        "hint": None,
        "options": [
            "Да",
            "В процессе",
            "Только планируется",
            "Неизвестно",
        ],
    },
    {
        "id": "timing",
        "title": "Когда вам нужна помощь с решением вашего вопроса?",
        "hint": None,
        "options": [
            "Прямо сейчас",
            "В этом месяце",
            "В течение 1–3 месяцев",
            "Позже / пока не знаю",
        ],
    },
]

# EN-версия вопросов. id те же, что в QUESTIONS — по ним пишутся answers в БД.
QUESTIONS_EN = [
    {
        "id": "service",
        "title": "What do you need help with?",
        "hint": None,
        "options": [
            "Accounting and bookkeeping",
            "Corporate Tax and VAT registration",
            "Audit",
            "Setting up payment acquiring",
            "Not sure yet",
        ],
    },
    {
        "id": "company",
        "title": "Do you already have a company in the UAE?",
        "hint": None,
        "options": [
            "Yes",
            "In progress",
            "Just planning",
            "Not sure",
        ],
    },
    {
        "id": "timing",
        "title": "When do you need help with your question?",
        "hint": None,
        "options": [
            "Right now",
            "This month",
            "Within 1–3 months",
            "Later / not sure yet",
        ],
    },
]

# Финальный экран (имя + телефон).
FINAL = {
    "title": "Спасибо, что заполнили анкету!",
    "subtitle": None,  # текст «Она нужна, чтобы созвон…» убран по просьбе Николь 2026-06-02
    "consent": (
        "Нажимая кнопку, вы соглашаетесь на обработку своих данных для связи "
        "по заявке."
    ),
    "submit": "Отправить заявку",
}

# EN-версия финального экрана.
FINAL_EN = {
    "title": "Thank you for completing the form!",
    "subtitle": None,
    "consent": (
        "By clicking the button, you agree to the processing of your data "
        "so we can contact you about your request."
    ),
    "submit": "Send request",
}

# Экран после успешной отправки.
THANKS = {
    "title": "Заявка принята!",
    "subtitle": "Мы свяжемся с вами в ближайшее время и подберём удобное время созвона.",
}

# EN-версия экрана после отправки.
THANKS_EN = {
    "title": "Request received!",
    "subtitle": "We will contact you shortly and arrange a convenient time for the call.",
}

# Авто-подтверждение клиенту в WhatsApp сразу после заявки (решение Николь
# 2026-07-21: каждый оставивший контакты получает подтверждение с номера 84).
# Уходит с канала WAZZUP_CLIENT_CHANNEL_ID (config.py), best-effort.
CONFIRM_WA_TEXT = (
    "Здравствуйте! Это ONCOUNT. Ваша заявка на бесплатную консультацию "
    "принята ✅\n\n"
    "Менеджер свяжется с вами в течение часа в рабочее время "
    "(9:00–18:00 по Дубаю, пн–пт).\n\n"
    "Если удобнее написать самим — просто ответьте на это сообщение."
)

# EN-версия WhatsApp-подтверждения.
CONFIRM_WA_TEXT_EN = (
    "Hello! This is ONCOUNT. Your request for a free consultation has been "
    "received ✅\n\n"
    "Our manager will contact you within an hour during business hours "
    "(9:00–18:00 Dubai time, Mon–Fri).\n\n"
    "If it is easier for you to write to us — just reply to this message."
)

# Множества допустимых ответов (белый список RU ∪ EN) — на приёме отбрасываем
# всё, чего нет в вариантах (анти-инъекция произвольных строк в БД/CRM).
VALID_OPTIONS = {q["id"]: set(q["options"]) for q in QUESTIONS}
for _q in QUESTIONS_EN:
    VALID_OPTIONS[_q["id"]] |= set(_q["options"])
# Заголовки — русские: идут в примечание Kommo для менеджера.
QUESTION_TITLES = {q["id"]: q["title"] for q in QUESTIONS}


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
