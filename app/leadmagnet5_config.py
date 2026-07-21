"""Контент лид-магнита /guide/5-mistakes — квиз → PDF чек-листа в WhatsApp.

Второй лид-магнит по образцу `leadmagnet_config.py` (тема «0% Corporate Tax»),
но с темой «5 ошибок при открытии бизнеса в ОАЭ» и улучшениями (решение Николь
2026-06-03 «сделай такой же с новой темой и лучше»):

  • более сильная обложка (конкретные деньги: 50 000–200 000 AED/год);
  • 3 вопроса, которые квалифицируют лида И сопоставляют его с конкретной ошибкой;
  • ПЕРСОНАЛИЗИРОВАННОЕ WhatsApp-сообщение: помимо ссылки на PDF — строка, какая
    из 5 ошибок вероятнее всего про этого клиента (по ответу на вопрос `worry`).
    Это второе касание сразу зовёт в живой диалог → выше конверсия в консультацию.

Правило репо №1 — тексты/варианты/ссылка живут здесь, не в вёрстке. Ключи
вопросов (`id`) стабильны: по ним пишем answers, собираем примечание лида и
строим персональную подсказку — задним числом не меняем.
"""

# Дискриминатор события в общей таблице quiz_submissions (как leadmagnet_config).
EVENT_SLUG = "guide-5-mistakes"

# Ссылка на чек-лист — публичный Google Drive (PDF «5 ошибок при открытии бизнеса
# в ОАЭ», открыт «всем по ссылке» — проверено get_file_permissions 2026-06-03).
# Меняется одной строкой при замене PDF.
GUIDE_PDF_URL = "https://drive.google.com/file/d/1FcfR_M2fjt8pWDy0-dcgWElaAblObRzo/view"

# Базовый текст WhatsApp (фоллбэк, если персонализация не сработала). {link}
# подставляется в роуте. Сообщение уходит С нашего номера → клиент может ответить.
WA_TEXT = (
    "Здравствуйте! Это ONCOUNT 👋\n\n"
    "Ваш чек-лист «5 ошибок при открытии бизнеса в ОАЭ» — по ссылке:\n{link}\n\n"
    "Если захотите разобрать именно вашу ситуацию — просто ответьте на это "
    "сообщение, и наш бухгалтер поможет."
)

# EN-версия базового WA-сообщения. {link} тот же; PDF пока только на русском —
# честно помечаем это в скобках.
WA_TEXT_EN = (
    "Hello! This is ONCOUNT 👋\n\n"
    "Here is your checklist \"5 mistakes when opening a business in the UAE\" "
    "(the guide is in Russian):\n{link}\n\n"
    "If you would like us to look at your specific situation, just reply to "
    "this message and our accountant will help."
)

# Персональная подсказка по ответу на вопрос `worry` — какая из 5 ошибок ближе
# всего к зоне риска клиента. Ключи = варианты вопроса `worry` (белый список).
_RISK_HINT = {
    "Выбор фризоны и структуры": (
        "Судя по ответам, вам особенно важны ошибки №1 и №3: выбирать юрисдикцию "
        "под бизнес-модель, а не под цену лицензии — иначе ожидаемый 0% легко "
        "превращается в 9%."
    ),
    "Открытие банковского счёта": (
        "Судя по ответам, ваша зона риска — ошибка №2: банк в ОАЭ это фильтр. "
        "Структуру и документы лучше готовить под банк заранее, до открытия счёта."
    ),
    "Налоги и регистрация Corporate Tax": (
        "Судя по ответам, обратите внимание на ошибку №4: регистрироваться на "
        "Corporate Tax нужно по срокам лицензии, а не по факту прибыли — иначе "
        "автоматические штрафы FTA."
    ),
    "Бухгалтерия и отчётность": (
        "Судя по ответам, ваша зона риска — ошибка №5: FTA смотрит логику бизнеса, "
        "а не просто цифры. Бухгалтерия и софт — это система защиты, а не "
        "формальность."
    ),
}

# EN-версия подсказок. Ключи = EN-варианты вопроса `worry` (из QUESTIONS_EN).
_RISK_HINT_EN = {
    "Choosing a Freezone and structure": (
        "Judging by your answers, mistakes #1 and #3 matter most for you: choose "
        "the jurisdiction to fit your business model, not the licence price — "
        "otherwise the expected 0% easily turns into 9%."
    ),
    "Opening a bank account": (
        "Judging by your answers, your risk zone is mistake #2: a UAE bank is a "
        "filter. It is better to prepare your structure and documents for the "
        "bank in advance, before opening the account."
    ),
    "Taxes and Corporate Tax registration": (
        "Judging by your answers, pay attention to mistake #4: you must register "
        "for Corporate Tax based on your licence dates, not on when you start "
        "making a profit — otherwise the FTA issues automatic fines."
    ),
    "Accounting and reporting": (
        "Judging by your answers, your risk zone is mistake #5: the FTA looks at "
        "the logic of your business, not just the numbers. Accounting and "
        "software are a protection system, not a formality."
    ),
}


def wa_text(answers: dict | None) -> str:
    """Собрать персональное WA-сообщение по ответам квиза. Возвращает текст со
    ссылкой на PDF и подсказкой про релевантную ошибку. Безопасно при пустых
    answers — тогда отдаём базовый WA_TEXT. Используется как deliver_wa_text_builder
    в _handle_quiz_submit (best-effort; ошибка → фоллбэк на статичный WA_TEXT)."""
    hint = _RISK_HINT.get((answers or {}).get("worry"))
    if not hint:
        return WA_TEXT.format(link=GUIDE_PDF_URL)
    return (
        "Здравствуйте! Это ONCOUNT 👋\n\n"
        "Ваш чек-лист «5 ошибок при открытии бизнеса в ОАЭ» — по ссылке:\n"
        + GUIDE_PDF_URL + "\n\n"
        + hint + "\n\n"
        "Хотите — разберём вашу ситуацию с бухгалтером бесплатно. "
        "Просто ответьте на это сообщение."
    )


def wa_text_en(answers: dict | None) -> str:
    """EN-версия wa_text: та же логика — подсказка по EN-варианту `worry`,
    пустые/неизвестные answers → базовый WA_TEXT_EN. Ссылка и фоллбэк те же."""
    hint = _RISK_HINT_EN.get((answers or {}).get("worry"))
    if not hint:
        return WA_TEXT_EN.format(link=GUIDE_PDF_URL)
    return (
        "Hello! This is ONCOUNT 👋\n\n"
        "Here is your checklist \"5 mistakes when opening a business in the UAE\" "
        "(the guide is in Russian):\n"
        + GUIDE_PDF_URL + "\n\n"
        + hint + "\n\n"
        "If you want, we can go through your situation with an accountant for "
        "free. Just reply to this message."
    )


# Экран-обложка (шаг 0) — оффер чек-листа с конкретной ценой ошибки.
COVER = {
    "image": None,  # отдельного hero пока нет (Николь добавит позже)
    "badge": "БЕСПЛАТНЫЙ ЧЕК-ЛИСТ",
    "title": "5 ошибок при открытии бизнеса в ОАЭ, которые стоят 50 000–200 000 AED в год",
    "lead": (
        "Их допускают почти все на старте — и узнают, только когда приходит штраф "
        "FTA или банк замораживает счёт. Ответьте на 3 вопроса — пришлём PDF прямо "
        "в WhatsApp."
    ),
    "bullets_title": "Что внутри:",
    "bullets": [
        "5 типичных ошибок — и как обойти каждую",
        "Почему ожидаемый 0% налог превращается в 9%",
        "Как сразу выстроить структуру под банк и FTA",
    ],
    "cta": "Получить чек-лист",
    "note": "Бесплатно. PDF придёт в WhatsApp сразу после ответов.",
}

# EN-версия обложки.
COVER_EN = {
    "image": None,  # как в RU: hero пока нет
    "badge": "FREE CHECKLIST",
    "title": "5 mistakes when opening a business in the UAE that cost 50,000–200,000 AED a year",
    "lead": (
        "Almost everyone makes them at the start — and finds out only when an "
        "FTA fine arrives or the bank freezes the account. Answer 3 questions — "
        "we will send the PDF straight to your WhatsApp."
    ),
    "bullets_title": "What is inside:",
    "bullets": [
        "5 typical mistakes — and how to avoid each one",
        "Why the expected 0% tax turns into 9%",
        "How to build your structure for the bank and the FTA from day one",
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

# 3 вопроса — квалифицируют лида и задают персональную подсказку (по `worry`).
QUESTIONS = [
    {
        "id": "stage",
        "title": "На каком вы этапе?",
        "hint": None,
        "options": [
            "Только планирую открыть компанию",
            "Открыл недавно (до года)",
            "Компания работает больше года",
            "Пока изучаю рынок ОАЭ",
        ],
    },
    {
        "id": "worry",
        "title": "Что сейчас вызывает больше всего вопросов?",
        "hint": None,
        "options": [
            "Выбор фризоны и структуры",
            "Открытие банковского счёта",
            "Налоги и регистрация Corporate Tax",
            "Бухгалтерия и отчётность",
        ],
    },
    {
        "id": "accounting",
        "title": "Кто сейчас ведёт вашу бухгалтерию?",
        "hint": None,
        "options": [
            "Штатный бухгалтер",
            "Аутсорс-компания",
            "Веду сам / пока никто",
            "Не уверен, что всё правильно",
        ],
    },
]

# EN-версии вопросов — те же `id`, переведены только тексты. Варианты `worry`
# должны совпадать с ключами _RISK_HINT_EN.
QUESTIONS_EN = [
    {
        "id": "stage",
        "title": "What stage are you at?",
        "hint": None,
        "options": [
            "Just planning to open a company",
            "Opened recently (less than a year ago)",
            "The company has been running for over a year",
            "Still exploring the UAE market",
        ],
    },
    {
        "id": "worry",
        "title": "What raises the most questions for you right now?",
        "hint": None,
        "options": [
            "Choosing a Freezone and structure",
            "Opening a bank account",
            "Taxes and Corporate Tax registration",
            "Accounting and reporting",
        ],
    },
    {
        "id": "accounting",
        "title": "Who handles your accounting now?",
        "hint": None,
        "options": [
            "In-house accountant",
            "An outsourcing company",
            "I do it myself / no one yet",
            "Not sure everything is correct",
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

# Экран после успешной отправки. Мягкий фоллбэк проверки телефона.
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

# Соцсети на экране «спасибо» (как у /mk, /consultation, /guide/corp-tax).
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
KOMMO_LEAD_PREFIX = "Лид-магнит: 5 ошибок при открытии бизнеса"
KOMMO_LEAD_TAG = "guide-5-mistakes"
KOMMO_NOTE_INTRO = (
    "Заявка с лид-магнита «5 ошибок при открытии бизнеса в ОАЭ» "
    "(чек-лист отправлен в WhatsApp)."
)

# Белый список вариантов — как в leadmagnet_config (анти-инъекция), но
# объединённый по обоим языкам: принимаем и RU-, и EN-варианты.
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
