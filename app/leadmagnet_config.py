"""Контент лид-магнита /guide/corp-tax — квиз → PDF чек-листа в WhatsApp.

План: plans/2026-06-02-lead-magnit-kviz-pdf-whatsapp.md. Канал партнёра (способ #9
из .business/marketing/partner-lead-channels.md): агент даёт короткий тизер +
персональную ссылку `?ref={код}`; клиент проходит 3 вопроса, оставляет WhatsApp —
ему приходит ССЫЛКА на PDF (не файл: проще и надёжнее, решение Николь 2026-06-02),
а лид с привязкой к агенту падает в воронку 1.1.

Правило репо №1 — тексты/варианты/ссылка живут здесь, не в вёрстке. Свои 3 вопроса
(не из quiz_config): у лид-магнита другая квалификация. Ключи вопросов (`id`)
стабильны — по ним пишем answers и собираем примечание лида, задним числом не меняем.
"""

# Дискриминатор события в общей таблице quiz_submissions (как mk_config.EVENT_SLUG).
EVENT_SLUG = "guide-corp-tax"

# Ссылка на чек-лист — публичный Google Drive (решение Николь 2026-06-02: не хостим
# у себя — статика partner-platform не в git, и Drive надёжнее). Файл открыт «всем по
# ссылке» (reader/anyone, проверено). Меняется одной строкой при замене PDF.
GUIDE_PDF_URL = "https://drive.google.com/file/d/1zVUZRk0QIurSkPVMlK1Mgyu-CB02ZvCo/view"

# Текст WhatsApp-сообщения с чек-листом. {link} подставляется в роуте. Сообщение
# уходит С нашего номера → клиент может просто ответить = живой диалог с менеджером.
WA_TEXT = (
    "Здравствуйте! Это ONCOUNT 👋\n\n"
    "Ваш чек-лист «0% Corporate Tax в ОАЭ» — по ссылке:\n{link}\n\n"
    "Если захотите разобрать именно вашу ситуацию — просто ответьте на это "
    "сообщение, и наш бухгалтер поможет."
)

# EN-версия WA-сообщения. {link} тот же; PDF пока только на русском — честно
# помечаем это в скобках.
WA_TEXT_EN = (
    "Hello! This is ONCOUNT 👋\n\n"
    "Here is your checklist \"0% Corporate Tax in the UAE\" "
    "(the guide is in Russian):\n{link}\n\n"
    "If you would like us to look at your specific situation, just reply to "
    "this message and our accountant will help."
)

# Экран-обложка (шаг 0) — оффер чек-листа.
COVER = {
    "image": None,  # отдельного hero пока нет; обложка работает на тексте (Николь добавит позже)
    "badge": "БЕСПЛАТНЫЙ ЧЕК-ЛИСТ",
    "title": "0% Corporate Tax в ОАЭ: вы под ним — или рискуете попасть на 9%?",
    "lead": (
        "Короткий разбор: какие free zone и виды дохода реально дают 0%, а за что "
        "FTA доначисляет 9%. Ответьте на 3 вопроса — пришлём PDF прямо в WhatsApp."
    ),
    "bullets": [
        "Какие зоны и виды деятельности дают qualifying income",
        "5 ситуаций, в которых ожидаемый 0% превращается в 9%",
        "Что нужно, чтобы получить и удержать 0%",
    ],
    "cta": "Получить чек-лист",
    "note": "Бесплатно. PDF придёт в WhatsApp сразу после ответов.",
}

# EN-версия обложки.
COVER_EN = {
    "image": None,  # как в RU: hero пока нет
    "badge": "FREE CHECKLIST",
    "title": "0% Corporate Tax in the UAE: do you qualify — or risk paying 9%?",
    "lead": (
        "A short guide: which Freezones and income types really give 0%, and "
        "where the FTA charges 9% instead. Answer 3 questions — we will send "
        "the PDF straight to your WhatsApp."
    ),
    "bullets": [
        "Which zones and activities give qualifying income",
        "5 situations where the expected 0% turns into 9%",
        "What you need to get and keep the 0% rate",
    ],
    "cta": "Get the checklist",
    "note": "Free. The PDF arrives in WhatsApp right after your answers.",
}

# Интро над шагами-вопросами (после обложки).
INTRO = (
    "Чтобы чек-лист был полезен именно вам — ответьте на три коротких вопроса. "
    "PDF пришлём в WhatsApp на указанный номер."
)

# EN-версия интро.
INTRO_EN = (
    "To make the checklist useful for you, please answer three short questions. "
    "We will send the PDF to the WhatsApp number you leave."
)

# 3 вопроса — заодно квалифицируют лида (бухгалтер видит ситуацию до звонка).
QUESTIONS = [
    {
        "id": "company",
        "title": "Компания в ОАЭ у вас уже есть?",
        "hint": None,
        "options": [
            "Да, уже работает",
            "В процессе открытия",
            "Только планирую",
            "Пока не знаю",
        ],
    },
    {
        "id": "field",
        "title": "Чем занимается (или будет заниматься) бизнес?",
        "hint": None,
        "options": [
            "Торговля / импорт-экспорт",
            "Услуги (IT, консалтинг, маркетинг)",
            "Холдинг / инвестиции",
            "Другое",
        ],
    },
    {
        "id": "priority",
        "title": "Что для вас сейчас важнее всего?",
        "hint": None,
        "options": [
            "Открыть структуру правильно с нуля",
            "Проверить, попадаю ли я под 0%",
            "Навести порядок в бухгалтерии и отчётности",
        ],
    },
]

# EN-версии вопросов — те же `id`, переведены только тексты.
QUESTIONS_EN = [
    {
        "id": "company",
        "title": "Do you already have a company in the UAE?",
        "hint": None,
        "options": [
            "Yes, it is already running",
            "In the process of opening",
            "Just planning",
            "Not sure yet",
        ],
    },
    {
        "id": "field",
        "title": "What does (or will) your business do?",
        "hint": None,
        "options": [
            "Trading / import-export",
            "Services (IT, consulting, marketing)",
            "Holding / investments",
            "Other",
        ],
    },
    {
        "id": "priority",
        "title": "What matters most to you right now?",
        "hint": None,
        "options": [
            "Set up the structure correctly from scratch",
            "Check if I qualify for the 0% rate",
            "Put my accounting and reporting in order",
        ],
    },
]

# Финальный экран (имя + телефон).
FINAL = {
    "title": "Куда прислать чек-лист?",
    "subtitle": "Оставьте номер WhatsApp — PDF придёт на него сразу.",
    "consent": (
        "Нажимая кнопку, вы соглашаетесь на обработку своих данных для связи "
        "по заявке."
    ),
    "submit": "Получить чек-лист в WhatsApp",
}

# EN-версия финального экрана.
FINAL_EN = {
    "title": "Where should we send the checklist?",
    "subtitle": "Leave your WhatsApp number — the PDF will arrive right away.",
    "consent": (
        "By clicking the button, you agree to the processing of your data so "
        "we can contact you about your request."
    ),
    "submit": "Get the checklist in WhatsApp",
}

# Экран после успешной отправки. Фоллбэк мягкой проверки телефона: если PDF не
# пришёл (неверный номер) — клиент видит, что делать.
THANKS = {
    "title": "Готово! Чек-лист уже в пути",
    "subtitle": (
        "Мы отправили PDF в WhatsApp на указанный номер. Не пришло за пару минут — "
        "проверьте номер или напишите нам."
    ),
}

# EN-версия «спасибо» — с пометкой, что PDF пока на русском.
THANKS_EN = {
    "title": "Done! Your checklist is on its way",
    "subtitle": (
        "We have sent the PDF to your WhatsApp number. The checklist PDF is in "
        "Russian. If it does not arrive within a couple of minutes, check the "
        "number or message us."
    ),
}

# Соцсети на экране «спасибо» (как у /mk и /consultation).
SOCIALS = [
    {"type": "instagram", "label": "Instagram Николь", "url": "https://www.instagram.com/nikol_hillton"},
    {"type": "telegram",  "label": "Telegram-канал ONCOUNT", "url": "https://t.me/oncountt"},
    {"type": "site",      "label": "Сайт ONCOUNT", "url": "https://oncount.com"},
]

# EN-версии соцсетей — url/type те же, переведены только label.
SOCIALS_EN = [
    {"type": "instagram", "label": "Nikole's Instagram", "url": "https://www.instagram.com/nikol_hillton"},
    {"type": "telegram",  "label": "ONCOUNT Telegram channel", "url": "https://t.me/oncountt"},
    {"type": "site",      "label": "ONCOUNT website", "url": "https://oncount.com"},
]

# Параметры лида в Kommo воронку 1.1 (под предохранителем QUIZ_KOMMO_LIVE).
KOMMO_LEAD_PREFIX = "Лид-магнит: 0% Corporate Tax"
KOMMO_LEAD_TAG = "guide-corp-tax"
KOMMO_NOTE_INTRO = "Заявка с лид-магнита «0% Corporate Tax» (чек-лист отправлен в WhatsApp)."

# Белый список вариантов — как в quiz_config (анти-инъекция + примечание),
# но объединённый по обоим языкам: принимаем и RU-, и EN-варианты.
VALID_OPTIONS = {q["id"]: set(q["options"]) for q in QUESTIONS}
for _q in QUESTIONS_EN:
    VALID_OPTIONS[_q["id"]] |= set(_q["options"])
# Заголовки для примечания лида — остаются русскими (примечание читает бухгалтер).
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
