"""Стартовый сидинг продуктов, шаблонов и FAQ — запускается из main при старте.

Данные взяты из .business/products/overview.md, pricing.md и плана партнёрки.
EN-поля (*_en) рендерятся при lang=en; пусто → шаблон откатывается на русское поле.
"""
from sqlalchemy.orm import Session

from app.models import Course, FaqItem, MessageTemplate, ProductBlock


PRICE_RU = "https://drive.google.com/file/d/1q9shmtKtsNWSgl0DoH0bkEBq-Rjk9e8w/view?usp=drive_link"
PRICE_EN = "https://drive.google.com/file/d/1fs1vJi5X6AgARmv7B0NOtaYE5Y69wqOs/view?usp=drive_link"


def _meta(commission: str, price: str) -> str:
    """Две строки под названием карточки: Комиссия + Цена."""
    return (
        f"<div class=\"meta-row\"><span class=\"meta-label\">Вознаграждение:</span> "
        f"<strong>{commission}</strong></div>"
        f"<div class=\"meta-row\"><span class=\"meta-label\">Цена:</span> "
        f"<strong>{price}</strong></div>"
    )


def _meta_en(commission: str, price: str) -> str:
    """EN-вариант блока «Комиссия + Цена»."""
    return (
        f"<div class=\"meta-row\"><span class=\"meta-label\">Reward:</span> "
        f"<strong>{commission}</strong></div>"
        f"<div class=\"meta-row\"><span class=\"meta-label\">Price:</span> "
        f"<strong>{price}</strong></div>"
    )


PRODUCTS = [
    {
        "slug": "accounting",
        "title": "Бухгалтерское обслуживание",
        "title_en": "Accounting services",
        "price_aed": _meta("100% за 1й месяц", "от 550 AED/мес"),
        "price_aed_en": _meta_en("100% for the 1st month", "from 550 AED/mo"),
        "summary_md": (
            "Основная услуга ONCOUNT. Бухгалтерия полного цикла для компаний в ОАЭ. "
            "В тариф всё включено: от регистрации на налоги и консультаций — "
            "до ведения бухгалтерского учёта и сдачи всех налоговых и финансовых отчётов."
        ),
        "summary_md_en": (
            "ONCOUNT's core service. Full-cycle accounting for UAE companies. "
            "Everything is included in the plan: from tax registration and consultations "
            "to bookkeeping and filing all tax and financial reports."
        ),
        "full_md": (
            "<h4>Чем отличается бухгалтерия ONCOUNT</h4>"
            "<ul>"
            "<li><strong>Личный кабинет — веб и мобильное приложение.</strong> "
            "Все ваши документы, отчёты, счета и статусы — в одном месте, 24/7. "
            "Не нужно писать «а где мой VAT?» — вы видите всё сами в реальном времени.</li>"
            "<li><strong>Страхование профессиональных рисков 1 000 000 AED.</strong> "
            "Если бухгалтер ошибается — штрафы FTA и финансовые потери покрывает ONCOUNT, "
            "а не клиент. Это наша юридическая ответственность, зафиксированная в договоре.</li>"
            "<li><strong>Слаженная команда профессионалов.</strong> "
            "За каждым клиентом — не один «универсальный» бухгалтер, а команда: "
            "главбух, помощник, налоговый специалист, payroll-менеджер. "
            "Опыт каждого — от 8 лет именно в UAE-юрисдикции.</li>"
            "<li><strong>Фиксированная цена «всё включено» — без сюрпризов.</strong> "
            "Никаких внезапных доплат за консультацию, отчёт или правку прошлого периода. "
            "Что в тарифе — то и платите, точка.</li>"
            "</ul>"
            "<h4>Прайс</h4>"
            "<ul>"
            f"<li><a href=\"{PRICE_RU}\" target=\"_blank\" rel=\"noopener\">Price RU</a></li>"
            f"<li><a href=\"{PRICE_EN}\" target=\"_blank\" rel=\"noopener\">Price EN</a></li>"
            "</ul>"
        ),
        "full_md_en": (
            "<h4>What makes ONCOUNT accounting different</h4>"
            "<ul>"
            "<li><strong>Client portal — web and mobile app.</strong> "
            "All your documents, reports, invoices and statuses in one place, 24/7. "
            "No need to ask “where's my VAT?” — you see everything yourself in real time.</li>"
            "<li><strong>Professional indemnity insurance of 1,000,000 AED.</strong> "
            "If the accountant makes a mistake, ONCOUNT covers the FTA fines and financial "
            "losses, not the client. It's our legal liability, fixed in the contract.</li>"
            "<li><strong>A coordinated team of professionals.</strong> "
            "Behind every client is not a single “universal” accountant but a team: "
            "chief accountant, assistant, tax specialist, payroll manager. "
            "Each has 8+ years specifically in the UAE jurisdiction.</li>"
            "<li><strong>Fixed all-inclusive price — no surprises.</strong> "
            "No sudden charges for a consultation, a report or fixing a past period. "
            "What's in the plan is what you pay, period.</li>"
            "</ul>"
            "<h4>Pricing</h4>"
            "<ul>"
            f"<li><a href=\"{PRICE_RU}\" target=\"_blank\" rel=\"noopener\">Price RU</a></li>"
            f"<li><a href=\"{PRICE_EN}\" target=\"_blank\" rel=\"noopener\">Price EN</a></li>"
            "</ul>"
        ),
        "order_index": 1,
    },
    {
        "slug": "audit",
        "title": "Аудит",
        "title_en": "Audit",
        "price_aed": _meta("$300", "от $1 500"),
        "price_aed_en": _meta_en("$300", "from $1,500"),
        "summary_md": "Независимая проверка финансовой отчётности компании лицензированным аудитором в ОАЭ.",
        "summary_md_en": "Independent review of a company's financial statements by a licensed auditor in the UAE.",
        "full_md": (
            "<p>Независимая проверка финансовой отчётности компании лицензированным аудитором в ОАЭ.</p>"
        ),
        "full_md_en": (
            "<p>Independent review of a company's financial statements by a licensed auditor in the UAE.</p>"
        ),
        "order_index": 2,
    },
    {
        "slug": "accounting-restore",
        "title": "Восстановление бухгалтерского учёта",
        "title_en": "Accounting restoration",
        "price_aed": _meta("по запросу", "по запросу"),
        "price_aed_en": _meta_en("on request", "on request"),
        "summary_md": "Восстановление учёта за прошлые периоды, когда бухгалтерия не велась или велась с ошибками.",
        "summary_md_en": "Restoring records for past periods when accounting wasn't kept or was kept with errors.",
        "full_md": (
            "<p>Восстановление учёта за прошлые периоды, когда бухгалтерия не велась или велась с ошибками. "
            "Готовим корректную отчётность под VAT, корпоративный налог, аудит или передачу нового бухгалтера.</p>"
        ),
        "full_md_en": (
            "<p>Restoring records for past periods when accounting wasn't kept or was kept with errors. "
            "We prepare correct statements for VAT, corporate tax, an audit or handover to a new accountant.</p>"
        ),
        "order_index": 3,
    },
    {
        "slug": "tax-reports",
        "title": "Сдача налоговых отчётов",
        "title_en": "Filing tax reports",
        "price_aed": _meta("по запросу", "по запросу"),
        "price_aed_en": _meta_en("on request", "on request"),
        "summary_md": "Подготовка и сдача VAT, корпоративного налога и прочей обязательной отчётности.",
        "summary_md_en": "Preparing and filing VAT, corporate tax and other mandatory reporting.",
        "full_md": (
            "<p>Подготовка и сдача VAT, корпоративного налога и прочей обязательной отчётности FTA. "
            "Берёмся, даже если основное обслуживание ведётся не у нас.</p>"
        ),
        "full_md_en": (
            "<p>Preparing and filing VAT, corporate tax and other mandatory FTA reporting. "
            "We take it on even if the main service isn't with us.</p>"
        ),
        "order_index": 4,
    },
    {
        "slug": "consultation",
        "title": "Консультация бухгалтера",
        "title_en": "Accountant consultation",
        "price_aed": _meta("$100", "от $350"),
        "price_aed_en": _meta_en("$100", "from $350"),
        "summary_md": "Подробный глубокий разбор ситуации клиента по налогам, учёту и оптимизации в ОАЭ.",
        "summary_md_en": "A detailed, in-depth review of the client's situation on taxes, accounting and optimisation in the UAE.",
        "full_md": (
            "<p>Подробный глубокий разбор ситуации клиента по налогам, учёту и оптимизации в ОАЭ.</p>"
        ),
        "full_md_en": (
            "<p>A detailed, in-depth review of the client's situation on taxes, accounting and optimisation in the UAE.</p>"
        ),
        "order_index": 5,
    },
    {
        "slug": "company-setup",
        "title": "Открытие компании в UAE",
        "title_en": "Company setup in the UAE",
        "price_aed": _meta("$1 000", "по запросу"),
        "price_aed_en": _meta_en("$1,000", "on request"),
        "summary_md": "Открытие или закрытие компании фри зона или мейнленд.",
        "summary_md_en": "Opening or closing a free-zone or mainland company.",
        "full_md": (
            "<p>Открытие или закрытие компании фри зона или мейнленд.</p>"
        ),
        "full_md_en": (
            "<p>Opening or closing a free-zone or mainland company.</p>"
        ),
        "order_index": 6,
    },
    {
        "slug": "bank-account",
        "title": "Банковский счёт",
        "title_en": "Bank account",
        "price_aed": _meta("$1 000", "по запросу"),
        "price_aed_en": _meta_en("$1,000", "on request"),
        "summary_md": "Открытие корпоративного или личного счёта НЕ резидента в банке ОАЭ.",
        "summary_md_en": "Opening a corporate or personal non-resident account at a UAE bank.",
        "full_md": (
            "<p>Открытие корпоративного или личного счёта НЕ резидента в банке ОАЭ.</p>"
        ),
        "full_md_en": (
            "<p>Opening a corporate or personal non-resident account at a UAE bank.</p>"
        ),
        "order_index": 7,
    },
    {
        "slug": "uae-visa",
        "title": "Виза резидента ОАЭ",
        "title_en": "UAE resident visa",
        "price_aed": _meta("$300–1 000", "по запросу"),
        "price_aed_en": _meta_en("$300–1,000", "on request"),
        "summary_md": "Оформление резидентской визы ОАЭ, включая золотую визу на 10 лет.",
        "summary_md_en": "Arranging a UAE residence visa, including the 10-year Golden Visa.",
        "full_md": (
            "<p>Оформление резидентской визы ОАЭ, включая золотую визу на 10 лет.</p>"
        ),
        "full_md_en": (
            "<p>Arranging a UAE residence visa, including the 10-year Golden Visa.</p>"
        ),
        "order_index": 8,
    },
]


TEMPLATES = [
    {
        "slug": "corp-tax-registration",
        "segment": "Открыл компанию",
        "segment_en": "Just opened a company",
        "title": "Регистрация на корпоративный налог",
        "title_en": "Corporate tax registration",
        "body_md": (
            "Привет! Только открыл компанию в ОАЭ? Тебе обязательно нужна "
            "регистрация на корпоративный налог.\n\n"
            "ONCOUNT регистрирует бесплатно — это уже входит в стоимость "
            "обслуживания. Цены приятные, всё включено: бухгалтерия, отчёты, "
            "консультации. №1 в Дубае по бухгалтерии на русском языке.\n\n"
            "Пиши, расскажу подробнее."
        ),
        "body_md_en": (
            "Hi! Just opened a company in the UAE? You'll definitely need "
            "corporate tax registration.\n\n"
            "ONCOUNT registers you for free — it's already included in the "
            "service. Friendly pricing, all-inclusive: accounting, reports, "
            "consultations. A top accounting firm in Dubai.\n\n"
            "Message me, I'll tell you more."
        ),
        "order_index": 1,
    },
    {
        "slug": "vat-registration",
        "segment": "Пошли обороты",
        "segment_en": "Revenue picking up",
        "title": "Регистрация на VAT (НДС)",
        "title_en": "VAT registration",
        "body_md": (
            "Привет! У компании пошли обороты — значит, пора регистрироваться "
            "на VAT.\n\n"
            "ONCOUNT: бесплатная регистрация на VAT и сдача отчётов каждый "
            "квартал. Всё входит в стоимость ежемесячного обслуживания. "
            "Цены приятные, всё включено, никаких скрытых доплат.\n\n"
            "Обратись в ONCOUNT."
        ),
        "body_md_en": (
            "Hi! Your company's revenue is picking up — so it's time to "
            "register for VAT.\n\n"
            "ONCOUNT: free VAT registration and quarterly report filing. "
            "It's all included in the monthly service. Friendly pricing, "
            "all-inclusive, no hidden charges.\n\n"
            "Get in touch with ONCOUNT."
        ),
        "order_index": 2,
    },
    {
        "slug": "free-consultation",
        "segment": "Бесит бухгалтер",
        "segment_en": "Fed up with their accountant",
        "title": "Бесплатная консультация по бухгалтерии",
        "title_en": "Free accounting consultation",
        "body_md": (
            "Задолбали и...ы, которые говорят не понятно, вовремя не "
            "отвечают, отчёты не сдают и вообще бесят?\n\n"
            "Запишись на бесплатную консультацию ONCOUNT. Эксперты за "
            "15–20 минут ответят на твои вопросы, подберут тариф и расскажут, "
            "как лучше всё устроить."
        ),
        "body_md_en": (
            "Fed up with people who talk in riddles, don't reply on time, "
            "don't file reports and just drive you crazy?\n\n"
            "Book a free ONCOUNT consultation. In 15–20 minutes the experts "
            "will answer your questions, suggest a plan and explain how best "
            "to set everything up."
        ),
        "order_index": 3,
    },
    {
        "slug": "masterclass-invite",
        "segment": "Мастер-класс",
        "segment_en": "Masterclass",
        "title": "Приглашение на мастер-класс",
        "title_en": "Masterclass invitation",
        "body_md": (
            "Помню, ты говорил, что у тебя проблемы с бухгалтером.\n\n"
            "Бухгалтер ONCOUNT проводит бесплатный мастер-класс — там можно "
            "задать любые вопросы, получить консультацию от специалиста и "
            "познакомиться с другими предпринимателями в Дубае.\n\n"
            "Регистрируйся, скину детали."
        ),
        "body_md_en": (
            "I remember you said you were having trouble with your "
            "accountant.\n\n"
            "An ONCOUNT accountant runs a free masterclass — you can ask any "
            "questions, get advice from a specialist and meet other "
            "entrepreneurs in Dubai.\n\n"
            "Sign up and I'll send the details."
        ),
        "order_index": 4,
    },
    {
        "slug": "vat-checklist",
        "segment": "Чек-лист VAT",
        "segment_en": "VAT checklist",
        "title": "Чек-лист по регистрации на VAT",
        "title_en": "VAT registration checklist",
        "body_md": (
            "Ты спрашивал, как зарегистрироваться на VAT — держи чек-лист.\n\n"
            "Делал ONCOUNT — №1 в Дубае на русском: всё технологично, "
            "личный кабинет, страховка профрисков 1 000 000 AED. Штрафы — "
            "больше не твоя проблема.\n\n"
            "Пиши, пришлю чек-лист."
        ),
        "body_md_en": (
            "You asked how to register for VAT — here's a checklist.\n\n"
            "Made by ONCOUNT — a top firm in Dubai: fully tech-driven, a "
            "client portal, 1,000,000 AED professional indemnity insurance. "
            "Fines are no longer your problem.\n\n"
            "Message me, I'll send the checklist."
        ),
        "order_index": 5,
    },
    {
        "slug": "accountant-check-checklist",
        "segment": "Сомнения в бухгалтере",
        "segment_en": "Doubts about their accountant",
        "title": "Чек-лист: как проверить своего бухгалтера",
        "title_en": "Checklist: how to vet your accountant",
        "body_md": (
            "Ты говорил, что сомневаешься в своём бухгалтере — фрилансер, без "
            "лицензии, не живёт в Дубае, непонятно, всё ли точно сдаёт.\n\n"
            "Держи чек-лист — как проверить бухгалтера и не словить штраф.\n\n"
            "Пиши, пришлю."
        ),
        "body_md_en": (
            "You said you have doubts about your accountant — a freelancer, "
            "no licence, not based in Dubai, unclear whether everything is "
            "filed correctly.\n\n"
            "Here's a checklist — how to vet an accountant and avoid a "
            "fine.\n\n"
            "Message me, I'll send it."
        ),
        "order_index": 6,
    },
]


FAQ = [
    {
        "category": "Передача клиента",
        "category_en": "Introducing a client",
        "question": "Что происходит после того, как я передал клиента?",
        "question_en": "What happens after I introduce a client?",
        "answer_md": (
            "1. Карточка создаётся в нашей CRM Kommo с твоим именем как партнёра.\n"
            "2. Менеджер связывается с клиентом в рабочее время в течение часа.\n"
            "3. Вы получаете отчёт о всех клиентах и партнёрское вознаграждение до 10-го числа каждого месяца."
        ),
        "answer_md_en": (
            "1. A card is created in our Kommo CRM with your name as the partner.\n"
            "2. A manager contacts the client during business hours within an hour.\n"
            "3. You get a report on all clients and your partner reward by the 10th of each month."
        ),
        "order_index": 1,
    },
    {
        "category": "Выплаты",
        "category_en": "Payouts",
        "question": "Сколько и когда я получу за приведённого клиента?",
        "question_en": "How much and when do I get for a client you've introduced?",
        "answer_md": (
            "Размер партнёрского вознаграждения зависит от тарифа клиента — обычно от $300 до $1 000. "
            "Партнёрское вознаграждение всегда включено в тарифы ONCOUNT. "
            "Выплаты и отчёты отправляем раз в месяц по итогам месяца, "
            "до 10-го числа каждого месяца, на удобные реквизиты."
        ),
        "answer_md_en": (
            "The partner reward depends on the client's plan — usually from $300 to $1,000. "
            "The partner reward is always included in ONCOUNT's pricing. "
            "We send payouts and reports once a month, by the 10th of each month, "
            "to your preferred payment details."
        ),
        "order_index": 2,
    },
    {
        "category": "Партнёрские ссылки",
        "category_en": "Partner links",
        "question": "Где взять партнёрскую ссылку?",
        "question_en": "Where do I get my partner link?",
        "answer_md": (
            "Раздел «Партнёрские ссылки» в личном кабинете — там твоя личная ссылка "
            "на Telegram и WhatsApp ONCOUNT и кнопка «Скопировать»."
        ),
        "answer_md_en": (
            "The “Partner links” section in your dashboard — there you'll find "
            "your personal link to ONCOUNT's Telegram and WhatsApp and a “Copy” button."
        ),
        "order_index": 3,
    },
    {
        "category": "Ошибки",
        "category_en": "Errors",
        "question": "Не приходит код подтверждения / не могу войти в ЛК",
        "question_en": "The confirmation code isn't arriving / I can't log in",
        "answer_md": (
            "Авторизация в ЛК — через Telegram Login Widget, кодов нет. Просто нажми "
            "кнопку «Login with Telegram» на странице /login и подтверди в Telegram. "
            "Если кнопка не работает — напиши Николь в WhatsApp: wa.me/971589217784."
        ),
        "answer_md_en": (
            "Login uses the Telegram Login Widget — there are no codes. Just click "
            "“Login with Telegram” on the /login page and confirm in Telegram. "
            "If the button doesn't work, message Nicole on WhatsApp: wa.me/971589217784."
        ),
        "order_index": 5,
    },
]


# progress_steps — «только вид» (фиксированный прогресс из данных), не пер-партнёрский
# трекинг. 0 = кнопка «Начать». Поменяй число, чтобы показать «Продолжить»/done.
COURSES = [
    {
        "slug": "ai-employees-setup",
        "title": "Настройка 2 АИ-сотрудников",
        "subtitle": "⏱ 2 часа · 3 шага",
        "outcome": "сайты и презентации делают AI-сотрудники",
        "title_en": "Setting up 2 AI employees",
        "subtitle_en": "⏱ 2 hours · 3 steps",
        "outcome_en": "AI employees build your websites and presentations",
        "done_label_en": "Completed",
        "total_steps": 3,
        "progress_steps": 0,
        "done_label": "Завершено",
        "order_index": 1,
    },
    {
        "slug": "partner-course",
        "title": "Курс партнёра ONCOUNT",
        "subtitle": "5 шагов к первым $2 500 вознаграждения",
        "outcome": None,
        "title_en": "ONCOUNT Partner Course",
        "subtitle_en": "5 steps to your first $2,500 reward",
        "outcome_en": None,
        "done_label_en": "Program materials",
        "total_steps": 5,
        "progress_steps": 0,
        "done_label": "Материалы программы",
        "order_index": 2,
    },
]


def seed_if_empty(session: Session) -> None:
    # ProductBlock и MessageTemplate — force-reseed на каждом старте, чтобы правки
    # в коде гарантированно доехали до прода. FK на эти таблицы нет, удаление безопасно.
    session.query(ProductBlock).delete()
    session.add_all([ProductBlock(**p) for p in PRODUCTS])
    session.query(MessageTemplate).delete()
    session.add_all([MessageTemplate(**t) for t in TEMPLATES])
    session.query(FaqItem).delete()
    session.add_all([FaqItem(**f) for f in FAQ])
    # Course — тоже force-reseed: прогресс хранится отдельно (course_progress) по slug,
    # без FK на courses.id, поэтому пересоздание строк Course его не затрагивает.
    session.query(Course).delete()
    session.add_all([Course(**c) for c in COURSES])
    session.commit()
