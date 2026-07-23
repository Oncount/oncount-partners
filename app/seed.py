"""Стартовый сидинг продуктов, шаблонов и FAQ — запускается из main при старте.

Данные взяты из .business/products/overview.md, pricing.md и плана партнёрки.
EN-поля (*_en) рендерятся при lang=en; пусто → шаблон откатывается на русское поле.
"""
from sqlalchemy.orm import Session

from app.kit_validator import _kit_body_clean
from app.mk_config import EVENT_DATE_HUMAN, EVENT_DATE_HUMAN_EN
from app.models import Course, FaqItem, MessageTemplate, ProductBlock


PRICE_RU = "https://drive.google.com/file/d/1q9shmtKtsNWSgl0DoH0bkEBq-Rjk9e8w/view?usp=drive_link"
PRICE_EN = "https://drive.google.com/file/d/1fs1vJi5X6AgARmv7B0NOtaYE5Y69wqOs/view?usp=drive_link"


def _meta(commission: str, price: str) -> str:
    """Две строки под названием карточки: Комиссия + Цена."""
    return (
        f"<div class=\"meta-row\"><span class=\"meta-label\">Выплата:</span> "
        f"<strong>{commission}</strong></div>"
        f"<div class=\"meta-row\"><span class=\"meta-label\">Цена:</span> "
        f"<strong>{price}</strong></div>"
    )


def _meta_en(commission: str, price: str) -> str:
    """EN-вариант блока «Комиссия + Цена»."""
    return (
        f"<div class=\"meta-row\"><span class=\"meta-label\">Payout:</span> "
        f"<strong>{commission}</strong></div>"
        f"<div class=\"meta-row\"><span class=\"meta-label\">Price:</span> "
        f"<strong>{price}</strong></div>"
    )


PRODUCTS = [
    {
        "slug": "accounting",
        "title": "Бухгалтерское обслуживание",
        "title_en": "Accounting services",
        "price_aed": _meta("100% за 1й месяц", "от $149/мес"),
        "price_aed_en": _meta_en("100% for the 1st month", "from $149/mo"),
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
            "<p>Независимая проверка финансовой отчётности компании сертифицированным "
            "аудитором в ОАЭ.</p>"
            "<h4>Когда нужен аудит</h4>"
            "<ul>"
            "<li>Перед продлением лицензии — ряд фри-зон требует аудированную отчётность.</li>"
            "<li>При закрытии или ликвидации компании.</li>"
            "<li>Для получения кредита или иного финансирования в банке.</li>"
            "<li>При привлечении инвесторов, продаже доли или подготовке к сделке (due diligence).</li>"
            "<li>По требованию фри-зоны или регулятора — во многих юрисдикциях ОАЭ "
            "ежегодный аудит обязателен.</li>"
            "<li>Для подтверждения отчётности по корпоративному налогу перед FTA.</li>"
            "</ul>"
            "<h4>Как мы это делаем</h4>"
            "<p>Аудит проводят сертифицированные аудиторы, одобренные вашей фри-зоной и "
            "профильным регулятором. Мы работаем с проверенными партнёрами-аудиторами и "
            "берём процесс на себя под ключ: организуем сам аудит, готовим и прикрепляем "
            "аудиторские отчёты к нужным порталам фри-зоны и госорганов. От вас — документы, "
            "остальное доводим до результата.</p>"
        ),
        "full_md_en": (
            "<p>Independent review of a company's financial statements by a certified "
            "auditor in the UAE.</p>"
            "<h4>When an audit is needed</h4>"
            "<ul>"
            "<li>Before license renewal — several free zones require audited statements.</li>"
            "<li>When closing or liquidating a company.</li>"
            "<li>To obtain a bank loan or other financing.</li>"
            "<li>When raising investors, selling a stake or preparing for a deal (due diligence).</li>"
            "<li>At the request of a free zone or regulator — in many UAE jurisdictions an "
            "annual audit is mandatory.</li>"
            "<li>To support corporate tax reporting before the FTA.</li>"
            "</ul>"
            "<h4>How we do it</h4>"
            "<p>The audit is performed by certified auditors approved by your free zone and "
            "the relevant regulator. We work with trusted partner auditors and handle the "
            "whole process turnkey: we run the audit itself and prepare and attach the audit "
            "reports to the required free-zone and government portals. You provide the "
            "documents — we take care of the rest.</p>"
        ),
        "order_index": 4,
    },
    {
        "slug": "accounting-restore",
        "title": "Восстановление бухгалтерского учёта",
        "title_en": "Accounting restoration",
        "price_aed": _meta("от $300", "от $1 500"),
        "price_aed_en": _meta_en("from $300", "from $1,500"),
        "summary_md": "Восстановление учёта за прошлые периоды, когда бухгалтерия не велась или велась с ошибками.",
        "summary_md_en": "Restoring records for past periods when accounting wasn't kept or was kept with errors.",
        "full_md": (
            "<p>Восстановление учёта за прошлые периоды, когда бухгалтерия не велась или "
            "велась с ошибками. Готовим корректную отчётность под VAT, корпоративный налог, "
            "аудит или передачу нового бухгалтера.</p>"
            "<h4>Когда требуется</h4>"
            "<p>Восстановление необходимо, чтобы корректно сдать отчётность за прошлые "
            "периоды и пройти аудит: без полной и проверенной первичной документации сдать "
            "отчёты и подтвердить их аудитору невозможно.</p>"
            "<h4>Что входит в работу</h4>"
            "<p>Это полноценный процесс: мы собираем всю первичную документацию, вносим её "
            "в сертифицированную бухгалтерскую программу и отражаем каждую транзакцию. "
            "Договоры, инвойсы и прочие документы прикрепляются и проверяются — чтобы вся "
            "первичка была на месте и подтверждена.</p>"
            "<h4>Почему лучше не запускать</h4>"
            "<p>Восстановление не менее трудоёмко, чем ежемесячное бухгалтерское "
            "обслуживание, а нередко и сложнее: документы за два-три года теряются, и "
            "восстановить утерянные счета, инвойсы и договоры бывает непросто. Поэтому "
            "надёжнее вести учёт ежемесячно и не накапливать — тогда сдача отчётности "
            "проходит легко.</p>"
        ),
        "full_md_en": (
            "<p>Restoring records for past periods when accounting wasn't kept or was kept "
            "with errors. We prepare correct statements for VAT, corporate tax, an audit or "
            "handover to a new accountant.</p>"
            "<h4>When it's needed</h4>"
            "<p>Restoration is required to correctly file reporting for past periods and "
            "pass an audit: without complete and verified source documents, returns can't be "
            "filed or confirmed by the auditor.</p>"
            "<h4>What the work involves</h4>"
            "<p>It's a full process: we collect all source documents, enter them into "
            "certified accounting software and record every transaction. Contracts, invoices "
            "and other documents are attached and verified — so that all primary records are "
            "in place and confirmed.</p>"
            "<h4>Why not to let it pile up</h4>"
            "<p>Restoration is no less labour-intensive than monthly accounting — and often "
            "harder: documents from two or three years back get lost, and recovering missing "
            "invoices, statements and contracts can be difficult. It's safer to keep the "
            "books monthly and not accumulate — then filing is easy.</p>"
        ),
        "order_index": 3,
    },
    {
        "slug": "tax-reports",
        "title": "Регистрация и отчёты по CIT и VAT (корпоративный налог и НДС)",
        "title_en": "CIT & VAT registration and returns",
        "price_aed": _meta("по запросу", "по запросу"),
        "price_aed_en": _meta_en("on request", "on request"),
        "summary_md": "Подготовка и сдача отчётности по корпоративному налогу (CIT) и НДС (VAT), а также прочей обязательной отчётности.",
        "summary_md_en": "Preparing and filing corporate tax (CIT) and VAT returns, plus other mandatory reporting.",
        "full_md": (
            "<p>Подготовка и сдача VAT, корпоративного налога и прочей обязательной "
            "отчётности FTA. Берёмся, даже если основное обслуживание ведётся не у нас.</p>"
            "<h4>На бухгалтерском обслуживании — всё включено</h4>"
            "<p>При полном сопровождении регистрация на корпоративный налог (CIT) и VAT, "
            "а также своевременная сдача всех обязательных отчётов уже входят в стоимость "
            "бухгалтерского обслуживания — без отдельной оплаты.</p>"
            "<h4>Только отчётность — отдельной услугой</h4>"
            "<p>Если клиент ведёт учёт самостоятельно или у другого подрядчика, мы берём "
            "на себя подготовку и сдачу отчётности как отдельную услугу.</p>"
        ),
        "full_md_en": (
            "<p>Preparing and filing corporate tax (CIT) and VAT returns, plus other "
            "mandatory FTA reporting. We take it on even if the main service isn't with us.</p>"
            "<h4>On our accounting service — all included</h4>"
            "<p>With full support, registration for corporate tax (CIT) and VAT, as well as "
            "the timely filing of all mandatory returns, is already included in the accounting "
            "service fee — at no extra charge.</p>"
            "<h4>Reporting only — as a standalone service</h4>"
            "<p>If the client keeps the books themselves or with another provider, we handle "
            "the preparation and filing of the returns as a standalone service.</p>"
        ),
        "order_index": 2,
    },
    {
        "slug": "company-setup",
        "title": "Бизнес-лицензии",
        "title_en": "Business licenses",
        "price_aed": _meta("$1 000", "от $2 000"),
        "price_aed_en": _meta_en("$1,000", "from $2,000"),
        "summary_md": "Открытие или закрытие компании во фри-зоне или мейнленде: подбор и оформление бизнес-лицензии в ОАЭ.",
        "summary_md_en": "Opening or closing a free-zone or mainland company: selecting and obtaining a UAE business license.",
        "full_md": (
            "<p>Открытие или закрытие компании на мейнленде и во фри-зонах ОАЭ — под ключ, "
            "через проверенных партнёров.</p>"
            "<h4>Подбираем под ваш бизнес</h4>"
            "<p>Мы глубоко знаем специфику Дубая и подбираем правильную фри-зону под ваш "
            "запрос — и по цене, и по наполнению. Заранее закладываем корректные "
            "бизнес-активности, которые позволят открыть корпоративный счёт и вести "
            "деятельность правильно — чтобы ваш бизнес работал без штрафов.</p>"
            "<h4>Под ключ</h4>"
            "<p>Сопровождаем весь процесс: от выбора юрисдикции и формы компании до "
            "получения лицензии.</p>"
        ),
        "full_md_en": (
            "<p>Opening or closing a mainland or free-zone company in the UAE — turnkey, "
            "through trusted partners.</p>"
            "<h4>Tailored to your business</h4>"
            "<p>We know Dubai's specifics in depth and select the right free zone for your "
            "needs — on price and on scope. We set the correct business activities up front "
            "so you can open a corporate account and operate properly — so your business runs "
            "without fines.</p>"
            "<h4>Turnkey</h4>"
            "<p>We handle the whole process: from choosing the jurisdiction and company form "
            "to obtaining the license.</p>"
        ),
        "order_index": 5,
    },
    {
        "slug": "uae-visa",
        "title": "Визы резидента ОАЭ",
        "title_en": "UAE resident visas",
        "price_aed": _meta("$300–1 000", "от $1 500"),
        "price_aed_en": _meta_en("$300–1,000", "from $1,500"),
        "summary_md": "Оформление резидентской визы ОАЭ, включая золотую визу на 10 лет.",
        "summary_md_en": "Arranging a UAE residence visa, including the 10-year Golden Visa.",
        "full_md": (
            "<p>Оформление резидентских виз ОАЭ под ключ — через проверенных партнёров.</p>"
            "<h4>Какие визы открываем</h4>"
            "<ul>"
            "<li>Рабочие визы (инвесторские, партнёрские) на 2 года.</li>"
            "<li>Пятилетние резидентские визы.</li>"
            "<li>Десятилетние золотые визы — за 3 дня, на основании покупки недвижимости.</li>"
            "</ul>"
            "<h4>Полное сопровождение</h4>"
            "<p>Всё под ключ: встречаем, привозим и возим на автомобилях бизнес-класса, "
            "сопровождаем на всех этапах и помогаем на каждом шаге.</p>"
        ),
        "full_md_en": (
            "<p>Arranging UAE residence visas turnkey — through trusted partners.</p>"
            "<h4>Visas we arrange</h4>"
            "<ul>"
            "<li>Work visas (investor, partner) for 2 years.</li>"
            "<li>5-year residence visas.</li>"
            "<li>10-year Golden Visas — in 3 days, based on a property purchase.</li>"
            "</ul>"
            "<h4>Full support</h4>"
            "<p>Everything turnkey: we meet you, drive you in business-class cars, accompany "
            "you at every stage and help at every step.</p>"
        ),
        "order_index": 6,
    },
    {
        "slug": "acquiring",
        "title": "Эквайринг",
        "title_en": "Acquiring",
        "price_aed": _meta("по запросу", "от $300"),
        "price_aed_en": _meta_en("on request", "from $300"),
        "summary_md": "Подключение эквайринга и онлайн-приёма платежей для бизнеса в ОАЭ.",
        "summary_md_en": "Setting up acquiring and online payment acceptance for a business in the UAE.",
        "full_md": (
            "<p>Подключение эквайринга и онлайн-приёма платежей для бизнеса в ОАЭ — "
            "через проверенных партнёров.</p>"
            "<h4>Платежи со всего мира</h4>"
            "<p>Подключаем ведущие эквайринговые платёжные системы, которые позволяют "
            "принимать оплату со всего мира — с дебетовых и кредитных карт любых стран.</p>"
        ),
        "full_md_en": (
            "<p>Connecting acquiring and online payment acceptance for a UAE business — "
            "through trusted partners.</p>"
            "<h4>Payments from around the world</h4>"
            "<p>We connect leading acquiring payment systems that let you accept payments "
            "worldwide — from debit and credit cards in any country.</p>"
        ),
        "order_index": 8,
    },
    {
        "slug": "bank-account",
        "title": "Банковские счета",
        "title_en": "Bank accounts",
        "price_aed": _meta("$1 000", "от $2 500"),
        "price_aed_en": _meta_en("$1,000", "from $2,500"),
        "summary_md": "Открытие корпоративного или личного счёта НЕ резидента в банке ОАЭ.",
        "summary_md_en": "Opening a corporate or personal non-resident account at a UAE bank.",
        "full_md": (
            "<p>Открытие корпоративных счетов и счетов для нерезидентов в ОАЭ — полностью "
            "под ключ, через проверенных партнёров.</p>"
            "<h4>Что входит</h4>"
            "<p>Ведём весь процесс: от подготовки и подачи документов до подбора подходящего "
            "банка и полного открытия счёта в ведущих банках Эмиратов.</p>"
            "<h4>Условия</h4>"
            "<ul>"
            "<li>Счета в разных валютах, в том числе мультивалютные (current accounts).</li>"
            "<li>Без депозитов — не нужно вносить и замораживать деньги на счёте.</li>"
            "</ul>"
        ),
        "full_md_en": (
            "<p>Opening corporate and non-resident accounts in the UAE — fully turnkey, "
            "through trusted partners.</p>"
            "<h4>What's included</h4>"
            "<p>We run the whole process: from preparing and submitting documents to "
            "selecting the right bank and fully opening the account at leading UAE banks.</p>"
            "<h4>Terms</h4>"
            "<ul>"
            "<li>Accounts in multiple currencies, including multi-currency (current) accounts.</li>"
            "<li>No deposits — no need to place or freeze funds on the account.</li>"
            "</ul>"
        ),
        "order_index": 7,
    },
]


TEMPLATES = [
    # Пост о мастер-классе с главбухом: картинка + текст + персональная ссылка
    # (решение Николь 2026-07-23). Дата берётся из mk_config — при переносе МК
    # правится одной строкой там, а не здесь (правило репо №1). Картинка —
    # обложка карусели из Instagram, перевыпущенной под новую дату.
    {
        "slug": "post-mk-nalogi-oae",
        "segment": "Пост о встрече",
        "segment_en": "Masterclass post",
        "title": "Мастер-класс ОАЭ — картинка и текст поста",
        "title_en": "UAE masterclass — image and post text",
        "body_md": (
            "Как легально платить меньше налогов в ОАЭ — и спать спокойно, "
            "даже если придёт проверка\n"
            "\n"
            f"⏰ {EVENT_DATE_HUMAN} главный бухгалтер ONCOUNT проведёт закрытую "
            "встречу для предпринимателей в ОАЭ.\n"
            "\n"
            "ONCOUNT — это IT-бухгалтерия с 200+ клиентами на обслуживании в ОАЭ.\n"
            "\n"
            "За 45 минут вы получите ответы, за которые консультанты берут "
            "тысячи дирхам.\n"
            "\n"
            "Честно разберём то, о чём молчат:\n"
            "→ Как остаться на 0% Corporate Tax — и до какого момента действует "
            "Small Business Relief\n"
            "→ Freezone vs Mainland: где 0% работает, а где это маркетинг\n"
            "→ Как не пересечь порог VAT 375K раньше времени\n"
            "→ Можно ли платить себе зарплату, дивиденды, займы\n"
            "→ Что делать, если вы уже выводили деньги на личный счёт\n"
            "→ При каком соотношении расходов и доходов FTA начинает проверку\n"
            "→ Какие расходы примут, а какие вычеркнут\n"
            "→ Как максимально возмещать входящий VAT\n"
            "→ Holding + операционная компания: работает ли схема в ОАЭ\n"
            "→ Substance requirements — сколько это реально стоит\n"
            "\n"
            "После встречи вы сможете:\n"
            "✅ проверить свой статус по Corporate Tax и VAT\n"
            "✅ понять, нужен ли аудит или восстановление учёта\n"
            "✅ увидеть, где теряете деньги прямо сейчас\n"
            "✅ выстроить структуру, которую пройдёт любая проверка\n"
            "\n"
            "📍 ZOOM, участие бесплатное, мест ограничено.\n"
            "\n"
            "Регистрация: {link}\n"
            "\n"
            "P.S. «У меня маленький бизнес, меня не тронут» — именно с таких "
            "компаний FTA начала массовые проверки."
        ),
        "body_md_en": (
            "How to legally pay less tax in the UAE — and sleep well even if an "
            "audit lands\n"
            "\n"
            f"⏰ On {EVENT_DATE_HUMAN_EN} the Chief Accountant of ONCOUNT is running "
            "a private meeting for UAE entrepreneurs.\n"
            "\n"
            "ONCOUNT is an IT-driven accounting firm with 200+ clients in the UAE.\n"
            "\n"
            "In 45 minutes you get the answers consultants charge thousands of "
            "dirhams for.\n"
            "\n"
            "An honest talk about what usually stays unsaid:\n"
            "→ How to stay at 0% Corporate Tax — and until when Small Business "
            "Relief applies\n"
            "→ Freezone vs Mainland: where 0% works and where it is just marketing\n"
            "→ How not to cross the VAT 375K threshold too early\n"
            "→ Whether you can pay yourself a salary, dividends or loans\n"
            "→ What to do if you have already moved money to a personal account\n"
            "→ At what expense-to-income ratio the FTA starts an audit\n"
            "→ Which expenses are accepted and which get struck out\n"
            "→ How to reclaim input VAT in full\n"
            "→ Holding + operating company: does the structure work in the UAE\n"
            "→ Substance requirements — what they really cost\n"
            "\n"
            "After the meeting you will be able to:\n"
            "✅ check your Corporate Tax and VAT status\n"
            "✅ tell whether you need an audit or bookkeeping clean-up\n"
            "✅ see where you are losing money right now\n"
            "✅ build a structure that survives any audit\n"
            "\n"
            "📍 ZOOM, free to attend, seats are limited.\n"
            "\n"
            "Register: {link}\n"
            "\n"
            "P.S. \"My business is small, nobody will come after me\" — those are "
            "exactly the companies the FTA started with."
        ),
        "method": "social",
        "link_key": "mk_quiz",
        "image_path": "/static/img/mk-post-30july.jpg",
        "image_thumb": "/static/img/mk-post-30july-thumb.jpg",
        "order_index": 0,
    },
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
            "Пиши, расскажу подробнее.\n\n"
            "Записаться на бесплатную консультацию: {link}"
        ),
        "body_md_en": (
            "Hi! Just opened a company in the UAE? You'll definitely need "
            "corporate tax registration.\n\n"
            "ONCOUNT registers you for free — it's already included in the "
            "service. Friendly pricing, all-inclusive: accounting, reports, "
            "consultations. A top accounting firm in Dubai.\n\n"
            "Message me, I'll tell you more.\n\n"
            "Book a free consultation: {link}"
        ),
        "method": "broadcast",
        "link_key": "consult_wa",
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
            "Обратись в ONCOUNT.\n\n"
            "Записаться на бесплатную консультацию: {link}"
        ),
        "body_md_en": (
            "Hi! Your company's revenue is picking up — so it's time to "
            "register for VAT.\n\n"
            "ONCOUNT: free VAT registration and quarterly report filing. "
            "It's all included in the monthly service. Friendly pricing, "
            "all-inclusive, no hidden charges.\n\n"
            "Get in touch with ONCOUNT.\n\n"
            "Book a free consultation: {link}"
        ),
        "method": "broadcast",
        "link_key": "consult_wa",
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
            "как лучше всё устроить.\n\n"
            "Записаться (3 вопроса): {link}"
        ),
        "body_md_en": (
            "Fed up with people who talk in riddles, don't reply on time, "
            "don't file reports and just drive you crazy?\n\n"
            "Book a free ONCOUNT consultation. In 15–20 minutes the experts "
            "will answer your questions, suggest a plan and explain how best "
            "to set everything up.\n\n"
            "Sign up (3 questions): {link}"
        ),
        "method": "broadcast",
        "link_key": "consult_quiz",
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
            "Регистрируйся, скину детали.\n\n"
            "Регистрация на мастер-класс: {link}"
        ),
        "body_md_en": (
            "I remember you said you were having trouble with your "
            "accountant.\n\n"
            "An ONCOUNT accountant runs a free masterclass — you can ask any "
            "questions, get advice from a specialist and meet other "
            "entrepreneurs in Dubai.\n\n"
            "Sign up and I'll send the details.\n\n"
            "Register for the masterclass: {link}"
        ),
        "method": "broadcast",
        "link_key": "mk_quiz",
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
            "Пиши, пришлю чек-лист.\n\n"
            "Или сразу записаться на консультацию: {link}"
        ),
        "body_md_en": (
            "You asked how to register for VAT — here's a checklist.\n\n"
            "Made by ONCOUNT — a top firm in Dubai: fully tech-driven, a "
            "client portal, 1,000,000 AED professional indemnity insurance. "
            "Fines are no longer your problem.\n\n"
            "Message me, I'll send the checklist.\n\n"
            "Or book a consultation right away: {link}"
        ),
        "method": "leadmagnet",
        "link_key": "consult_wa",
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
            "Пиши, пришлю.\n\n"
            "Или сразу записаться на консультацию: {link}"
        ),
        "body_md_en": (
            "You said you have doubts about your accountant — a freelancer, "
            "no licence, not based in Dubai, unclear whether everything is "
            "filed correctly.\n\n"
            "Here's a checklist — how to vet an accountant and avoid a "
            "fine.\n\n"
            "Message me, I'll send it.\n\n"
            "Or book a consultation right away: {link}"
        ),
        "method": "leadmagnet",
        "link_key": "consult_wa",
        "order_index": 6,
    },
    # ── Лид-магниты-квизы с АВТО-выдачей PDF в WhatsApp (планы 2026-06-02 / -03).
    #    Клиент проходит 3 вопроса по персональной ?ref-ссылке → чек-лист
    #    приходит ему в WhatsApp автоматически, лид падает в воронку 1.1 на агента.
    #    link_key → main._personal_links (lm_corptax / lm_5mistakes). Ключи ≤16
    #    символов — ограничение колонки link_key VARCHAR(16).
    {
        "slug": "leadmagnet-quiz-corptax",
        "segment": "Лид-магнит · авто-выдача",
        "segment_en": "Lead magnet · auto-delivery",
        "title": "Чек-лист «0% Corporate Tax» (PDF придёт клиенту в WhatsApp)",
        "title_en": "Checklist “0% Corporate Tax” (PDF auto-sent to client's WhatsApp)",
        "body_md": (
            "Бесплатный чек-лист: попадает ли ваша компания под 0% налог в ОАЭ — "
            "или вы рискуете 9%.\n\n"
            "Ответьте на 3 коротких вопроса — и PDF придёт прямо к вам в "
            "WhatsApp 👇\n{link}"
        ),
        "body_md_en": (
            "Free checklist: does your company qualify for 0% tax in the UAE — or "
            "are you risking 9%?\n\n"
            "Answer 3 quick questions and the PDF will be sent straight to your "
            "WhatsApp 👇\n{link}"
        ),
        "method": "leadmagnet",
        "link_key": "lm_corptax",
        "order_index": 1,
    },
    {
        "slug": "leadmagnet-quiz-5mistakes",
        "segment": "Лид-магнит · авто-выдача",
        "segment_en": "Lead magnet · auto-delivery",
        "title": "Чек-лист «5 ошибок при открытии бизнеса» (PDF придёт клиенту в WhatsApp)",
        "title_en": "Checklist “5 mistakes opening a business” (PDF auto-sent to client's WhatsApp)",
        "body_md": (
            "Бесплатный чек-лист: 5 ошибок при открытии бизнеса в ОАЭ, которые "
            "стоят 50 000–200 000 AED в год.\n\n"
            "Ответьте на 3 вопроса — и PDF придёт вам в WhatsApp 👇\n{link}"
        ),
        "body_md_en": (
            "Free checklist: 5 mistakes when launching a business in the UAE that "
            "cost 50,000–200,000 AED a year.\n\n"
            "Answer 3 questions and the PDF will arrive in your WhatsApp 👇\n{link}"
        ),
        "method": "leadmagnet",
        "link_key": "lm_5mistakes",
        "order_index": 2,
    },
    # ── Квиз-крючки на бесплатную консультацию (перенесены из tools.html,
    #    план 2026-06-02). method=broadcast, ссылка — персональный квиз
    #    /consultation?ref= (наш домен, ?ref метит лида нативно). {link} в теле.
    {
        "slug": "quiz-hook-1",
        "segment": "Квиз-консультация",
        "segment_en": "Quiz consultation",
        "title": "Квиз: разбор ситуации (тёплым)",
        "title_en": "Quiz: situation review (warm)",
        "body_md": (
            "Привет! Если ведёшь бизнес в ОАЭ или только планируешь — у ONCOUNT "
            "можно бесплатно разобрать свою ситуацию с бухгалтером: налоги, VAT, "
            "открытие компании или счёта. Ответь на 3 коротких вопроса — и на "
            "созвон придут уже с конкретными цифрами:\n{link}"
        ),
        "body_md_en": (
            "Hi! If you run a business in the UAE — or are just planning one — "
            "ONCOUNT offers a free situation review with an accountant: taxes, "
            "VAT, opening a company or a bank account. Answer 3 quick questions "
            "and they'll come to the call with concrete numbers:\n{link}"
        ),
        "method": "broadcast",
        "link_key": "consult_quiz",
        "order_index": 7,
    },
    {
        "slug": "quiz-hook-2",
        "segment": "Квиз-консультация",
        "segment_en": "Quiz consultation",
        "title": "Квиз: не переплатить по налогам",
        "title_en": "Quiz: don't overpay on taxes",
        "body_md": (
            "Знаю, что бухгалтерия и налоги в ОАЭ — головная боль. ONCOUNT "
            "(200+ клиентов в Дубае) даёт бесплатную консультацию: подскажут, "
            "как не переплатить по VAT и Corporate Tax и навести порядок в "
            "учёте. Заполни анкету из 3 вопросов — подберут решение под тебя:\n{link}"
        ),
        "body_md_en": (
            "Accounting and taxes in the UAE can be a real headache. ONCOUNT "
            "(200+ clients in Dubai) gives a free consultation: how not to "
            "overpay on VAT and Corporate Tax and put your books in order. Fill "
            "a 3-question quiz — they'll tailor a solution for you:\n{link}"
        ),
        "method": "broadcast",
        "link_key": "consult_quiz",
        "order_index": 8,
    },
    {
        "slug": "quiz-hook-3",
        "segment": "Квиз-консультация",
        "segment_en": "Quiz consultation",
        "title": "Квиз: короткая рекомендация",
        "title_en": "Quiz: short recommendation",
        "body_md": (
            "Рекомендую ONCOUNT — бухгалтеры для бизнеса в ОАЭ. Бесплатная "
            "консультация, 3 вопроса и удобное время созвона:\n{link}"
        ),
        "body_md_en": (
            "I recommend ONCOUNT — accountants for businesses in the UAE. Free "
            "consultation, 3 questions and a convenient call time:\n{link}"
        ),
        "method": "broadcast",
        "link_key": "consult_quiz",
        "order_index": 9,
    },
]


# Партнёрский кит (Фаза C+G, план 2026-05-27). partner_type сохранён (тип, под
# который собран материал), но ось ГРУППИРОВКИ на /tools теперь method (способ
# привлечения, план 2026-06-02 «переборка по способам»): intro/social/…
# segment = тип ассета (чип над карточкой). Персональная ссылка вшивается через
# плейсхолдер {link} (link_key → main._personal_links). ⚠️ insider-киты намеренно
# БЕЗ {link} (link_key не задан): «голый» wa.me/971589217784 для полной
# дискретности — трекинг-ссылка раскрыла бы партнёрский мотив.
#
# Тексты УТВЕРЖДЕНЫ Николь 2026-06-02 (копилка финалов
# .business/marketing/partner-kits-final-2026-06-02.md). Это финальные сообщения,
# которые партнёр КОПИРУЕТ и шлёт клиенту — НЕ черновики. slug БЕЗ суффикса
# `-draft` → шаблон даёт копировать. Фаза J: тело прогоняется через
# _kit_body_clean при сидинге (на финальном ките money-word → ValueError, сидер
# падает явно). Плейсхолдеры в квадратных скобках ([имя]/[тема]/[событие]/
# [моё имя]/[URL мастеркласса + UTM]/…) партнёр подставляет сам. EN — параллельная
# локаль; insider-киты #8/#10 намеренно БЕЗ бренда ONCOUNT (полная дискретность).
KITS = [
    {
        "slug": "kit-employee-wa-intro",
        "partner_type": "employee",
        "segment": "Интро WhatsApp",
        "segment_en": "WhatsApp intro",
        "title": "Интро клиенту в WhatsApp",
        "title_en": "WhatsApp intro to a client",
        "body_md": (
            "Привет, [имя]!\n"
            "\n"
            "Ты как-то говорил, что нужен бухгалтер по адекватной цене и "
            "качеству в ОАЭ — хочу познакомить тебя с ONCOUNT. Они ведут "
            "бухучёт для бизнеса в Дубае, помогают с налогами, отчётами и "
            "зарплатой. Я с ними сам работаю.\n"
            "\n"
            "Если актуально, то напиши им напрямую: {link} "
            "(скажи, что от меня)."
        ),
        "body_md_en": (
            "Hi [name]!\n"
            "\n"
            "You once mentioned you needed a solid accountant in the UAE at a "
            "fair price — let me introduce you to ONCOUNT. They handle "
            "bookkeeping for businesses in Dubai, help with taxes, reports, and "
            "payroll. I work with them myself.\n"
            "\n"
            "If it's relevant, just message them directly: {link} "
            "(mention you're from me)."
        ),
        "method": "intro",
        "link_key": "consult_wa",
        "order_index": 1,
    },
    {
        "slug": "kit-solo-intro",
        "partner_type": "solo",
        "segment": "Интро / письмо",
        "segment_en": "Intro / email",
        "title": "Интро клиенту (WhatsApp или письмо)",
        "title_en": "Client intro (WhatsApp or email)",
        "body_md": (
            "Добрый день, [имя]!\n"
            "\n"
            "В нашей работе по [теме] вы упомянули, что нужна бухгалтерия в "
            "ОАЭ. Передаю вас команде ONCOUNT — они ведут бухучёт для бизнеса "
            "в Дубае, помогают с налогами, отчётами и зарплатой.\n"
            "\n"
            "Их менеджер свяжется с вами в течение часа в рабочее время. Если "
            "удобнее — напишите им сами: {link} (упомяните, что от "
            "[моё имя]).\n"
            "\n"
            "По нашим вопросам остаюсь на связи."
        ),
        "body_md_en": (
            "Hello [name]!\n"
            "\n"
            "In our work on [topic], you mentioned you needed accounting in the "
            "UAE. I'm handing this over to the ONCOUNT team — they handle "
            "bookkeeping for UAE businesses, help with taxes, reports, and "
            "payroll.\n"
            "\n"
            "Their manager will reach out within an hour during business hours. "
            "If it's easier, message them yourself: {link} (please "
            "mention I sent you — [my name]).\n"
            "\n"
            "I remain available on our matters."
        ),
        "method": "intro",
        "link_key": "consult_wa",
        "order_index": 1,
    },
    {
        "slug": "kit-events-lead-magnet",
        "partner_type": "events",
        "segment": "Lead-магнит (RU)",
        "segment_en": "Lead magnet (RU)",
        "title": "Lead-магнит для аудитории события",
        "title_en": "Lead magnet for an event audience",
        "body_md": (
            "🔶 Только для подписчиков моего канала [название вашего канала]\n"
            "\n"
            "В ОАЭ сейчас непростое время для бизнеса — корпоративный налог, "
            "новые правила отчётности, требования банков. Один промах в "
            "бухгалтерии = штраф или блокировка счёта.\n"
            "\n"
            "Команда ONCOUNT проводит закрытый мастеркласс для предпринимателей "
            "в ОАЭ: реальные кейсы клиентов, как платить меньше налогов "
            "легально и что налоговая сейчас спрашивает на проверках.\n"
            "\n"
            "Это не лекция — это разбор вашей ситуации с бухгалтером.\n"
            "\n"
            "Записаться можно по ссылке: {link}"
        ),
        "body_md_en": (
            "🔶 For subscribers of my channel [your channel name] only\n"
            "\n"
            "The UAE is a tricky place for business right now — corporate tax, "
            "new reporting rules, bank requirements. One slip in your accounting "
            "= a fine or a frozen account.\n"
            "\n"
            "The ONCOUNT team runs a closed masterclass for entrepreneurs in the "
            "UAE: real client cases, how to pay less tax legally, and what the "
            "tax authority is asking about in audits right now.\n"
            "\n"
            "This isn't a lecture — it's a review of your situation with an "
            "accountant.\n"
            "\n"
            "Register here: {link}"
        ),
        "method": "social",
        "link_key": "mk_quiz",
        "order_index": 1,
    },
    {
        "slug": "kit-insider-intro-script",
        "partner_type": "insider",
        "segment": "Скрипт интро",
        "segment_en": "Intro script",
        "title": "Дискретный скрипт интро",
        "title_en": "Discreet intro script",
        "body_md": (
            "────────────────────\n"
            "📌 ЧТО МОЖНО ГОВОРИТЬ\n"
            "────────────────────\n"
            "\n"
            "✅ «Я с ними сам сотрудничаю»\n"
            "✅ «Мне их рекомендовали»\n"
            "✅ «Это надёжная команда, знаю их давно»\n"
            "✅ «Я узнавал — у них хороший подход»\n"
            "✅ «По моему опыту с ними всё спокойно»\n"
            "\n"
            "────────────────────\n"
            "📌 ЧЕГО НЕ ГОВОРИТЬ НИКОГДА\n"
            "────────────────────\n"
            "\n"
            "❌ «За это мне платят»\n"
            "❌ «У нас с ними договорённость»\n"
            "❌ «Я получаю процент»\n"
            "❌ «Это специальная программа от меня»\n"
            "❌ «По специальной ссылке от меня»\n"
            "❌ «Они меня вознаграждают»\n"
            "\n"
            "────────────────────\n"
            "📌 ЕСЛИ КЛИЕНТ СПРОСИТ «А ВАМ ЧТО С ЭТОГО?»\n"
            "────────────────────\n"
            "\n"
            "✅ «Нет, я просто рекомендую тех, кому доверяю.»\n"
            "✅ «Сам пользуюсь — рад, когда у моих знакомых тоже хорошо "
            "складывается.»"
        ),
        "body_md_en": (
            "────────────────────\n"
            "📌 WHAT YOU CAN SAY\n"
            "────────────────────\n"
            "\n"
            "✅ \"I work with them myself\"\n"
            "✅ \"They came recommended to me\"\n"
            "✅ \"They're a reliable team, I've known them a long time\"\n"
            "✅ \"I looked into it — they have a good approach\"\n"
            "✅ \"In my experience everything's been smooth with them\"\n"
            "\n"
            "────────────────────\n"
            "📌 WHAT NEVER TO SAY\n"
            "────────────────────\n"
            "\n"
            "❌ \"I get paid for this\"\n"
            "❌ \"I have an arrangement with them\"\n"
            "❌ \"I get a percentage\"\n"
            "❌ \"It's a special program from me\"\n"
            "❌ \"Through a special link from me\"\n"
            "❌ \"They reward me for it\"\n"
            "\n"
            "────────────────────\n"
            "📌 IF THE CLIENT ASKS \"WHAT'S IN IT FOR YOU?\"\n"
            "────────────────────\n"
            "\n"
            "✅ \"Nothing, I just recommend people I trust.\"\n"
            "✅ \"I use them myself — I'm glad when things go well for people I "
            "know too.\""
        ),
        "method": "intro",
        "order_index": 1,
    },
    # Универсальный шаблон интро вынесен из «Дискретного скрипта» в отдельную
    # карточку 2026-07-21 (решение Николь): это готовый текст для отправки, у
    # него должна быть своя кнопка «Скопировать», а не тонуть внутри скрипта.
    # Блок «если клиент в 3-стороннем чате» убран там же.
    {
        "slug": "kit-insider-universal-intro",
        "partner_type": "insider",
        "segment": "Универсальный шаблон",
        "segment_en": "Universal template",
        "title": "Универсальный шаблон интро — любой канал",
        "title_en": "Universal intro template — any channel",
        "body_md": (
            "[Имя], знаю, что вам нужна бухгалтерия в ОАЭ — могу рекомендовать "
            "команду, с которой сам работаю. Это ONCOUNT, они ведут бухучёт для "
            "бизнеса в Дубае. Если интересно — соединю с их менеджером, "
            "расскажет под вашу ситуацию."
        ),
        "body_md_en": (
            "[name], I know you need accounting in the UAE — I can recommend a "
            "team I work with myself. It's ONCOUNT, they handle bookkeeping for "
            "businesses in Dubai. If you're interested, I'll connect you with "
            "their manager, who'll walk you through your situation."
        ),
        "method": "intro",
        "order_index": 2,
    },
    {
        "slug": "kit-insider-personal-intro",
        "partner_type": "insider",
        "segment": "Личное интро",
        "segment_en": "Personal intro",
        "title": "Личное интро клиенту в переписке",
        "title_en": "Personal intro to a client in chat",
        "body_md": (
            "Привет!\n"
            "\n"
            "Я нашёл наконец классного бухгалтера. С лицензией и страховкой "
            "проф.рисков. Был у них на мастер-классе — чётко по делу всё "
            "говорят. И цена фиксированная: за каждый чих не доплачиваешь, всё "
            "включено — и регистрация, и сдача отчётов.\n"
            "\n"
            "Мне что нравится — они проактивные. Сами пишут, предлагают "
            "варианты, как лучше отражать в учёте, чтоб меньше платить "
            "налогов.\n"
            "\n"
            "В общем, рекомендую. Вот номер: wa.me/971589217784"
        ),
        "body_md_en": (
            "Hey!\n"
            "\n"
            "I've finally found a great accountant. Licensed, with professional "
            "indemnity insurance. I went to their masterclass — they speak "
            "clearly and to the point. And the price is fixed: you don't pay "
            "extra for every little thing, it's all included — both "
            "registration and filing reports.\n"
            "\n"
            "What I like is that they're proactive. They reach out themselves, "
            "suggest options for how best to record things in the books so you "
            "pay less tax.\n"
            "\n"
            "Anyway, I recommend them. Here's the number: wa.me/971589217784"
        ),
        "method": "intro",
        "order_index": 2,
    },
    {
        "slug": "kit-insider-group-intro",
        "partner_type": "insider",
        "segment": "Знакомство в чате",
        "segment_en": "Group intro",
        "title": "Знакомство клиента с ONCOUNT в общем чате",
        "title_en": "Introducing a client to ONCOUNT in a shared chat",
        "body_md": (
            "Всем привет!\n"
            "\n"
            "[Имя клиента], знакомлю с [Имя менеджера] — она помогает с "
            "бухгалтерией для бизнеса в ОАЭ. Я о тебе рассказал, она в курсе "
            "ситуации.\n"
            "\n"
            "[Имя менеджера], [Имя клиента] — недавно открыл компанию в ОАЭ, "
            "нужна команда по бухучёту: налоги, отчёты, текущее обслуживание.\n"
            "\n"
            "Оставляю вас, дальше с [Имя менеджера]. Удачно поговорить!"
        ),
        "body_md_en": (
            "Hi everyone!\n"
            "\n"
            "[Client name], meet [Manager name] — she helps with accounting for "
            "businesses in the UAE. I've told her about you, she's up to speed "
            "on your situation.\n"
            "\n"
            "[Manager name], [Client name] recently opened a company in the UAE "
            "and needs a team for the books: taxes, reports, ongoing support.\n"
            "\n"
            "I'll leave you to it — [Manager name] takes it from here. Have a "
            "good chat!"
        ),
        "method": "intro",
        "order_index": 3,
    },
    # Три варианта «строки в письме» разнесены по отдельным карточкам 2026-07-21
    # (решение Николь): у каждого своя кнопка «Скопировать», партнёр берёт ровно
    # тот текст, который шлёт клиенту. Раньше все три лежали в одном теле через
    # ═-разделители — копировалось всё скопом. Разделители больше не нужны.
    {
        "slug": "kit-insider-email-signature",
        "partner_type": "insider",
        "segment": "Строка в письме",
        "segment_en": "Email line",
        "title": "Вариант А — подпись в письме",
        "title_en": "Option A — email signature",
        "body_md": (
            "P.S. Если нужна бухгалтерия в ОАЭ — рекомендую команду, которую "
            "давно знаю: wa.me/971589217784"
        ),
        "body_md_en": (
            "P.S. If you need accounting in the UAE, I recommend a team I've "
            "known for a long time: wa.me/971589217784"
        ),
        "method": "intro",
        "order_index": 4,
    },
    {
        "slug": "kit-insider-email-forward",
        "partner_type": "insider",
        "segment": "Строка в письме",
        "segment_en": "Email line",
        "title": "Вариант Б — переслать контакт",
        "title_en": "Option B — forwarding a contact",
        "body_md": (
            "[Имя клиента], как договаривались — контакт команды по бухгалтерии "
            "в ОАЭ: wa.me/971589217784. Я их давно знаю, ребята надёжные."
        ),
        "body_md_en": (
            "[Client name], as we agreed — here's the contact of an accounting "
            "team in the UAE: wa.me/971589217784. I've known them a long time, "
            "they're reliable people."
        ),
        "method": "intro",
        "order_index": 5,
    },
    {
        "slug": "kit-insider-email-personal",
        "partner_type": "insider",
        "segment": "Строка в письме",
        "segment_en": "Email line",
        "title": "Вариант В — личное письмо",
        "title_en": "Option C — a personal email",
        "body_md": (
            "[Имя клиента], добрый день!\n"
            "\n"
            "По вашему вопросу про бухгалтерию в ОАЭ — обратитесь к ребятам, "
            "которых давно знаю: wa.me/971589217784. Профи, всё чётко."
        ),
        "body_md_en": (
            "[Client name], hello!\n"
            "\n"
            "On your accounting question in the UAE — reach out to the people "
            "I've known for a long time: wa.me/971589217784. Pros, everything "
            "sharp and clear."
        ),
        "method": "intro",
        "order_index": 6,
    },
]


FAQ = [
    # ── Вход и кабинет ──────────────────────────────────────────────────
    {
        "category": "Вход и кабинет",
        "category_en": "Login & dashboard",
        "question": "Не могу войти в кабинет / не приходит код",
        "question_en": "I can't log in / the code isn't arriving",
        "answer_md": (
            "Войти в кабинет можно через Telegram — кнопка «Войти через Telegram» на "
            "странице входа, подтвердите в Telegram. Что-то не получается — напишите Николь "
            "в WhatsApp: wa.me/971589217784, поможем войти."
        ),
        "answer_md_en": (
            "You can sign in via Telegram — use the “Sign in via Telegram” button on the "
            "login page and confirm in Telegram. If something doesn't work, message Nikole "
            "on WhatsApp: wa.me/971589217784 and we'll help you get in."
        ),
        "order_index": 1,
    },
    # ── Выплаты ─────────────────────────────────────────────────────────
    {
        "category": "Выплаты",
        "category_en": "Payouts",
        "question": "Сколько я получу за клиента?",
        "question_en": "How much do I get for a client?",
        "answer_md": (
            "Вознаграждение зависит от услуги, которую заказал клиент — обычно от $300 "
            "до $1 000. Оно всегда включено в тарифы ONCOUNT и начисляется за факт "
            "оплаты клиентом, разово.\n"
            "\n"
            "• Бухгалтерское обслуживание — 100% оплаты за 1-й месяц.\n"
            "• Открытие компании / бизнес-лицензия — $1 000.\n"
            "• Открытие банковского счёта — $1 000.\n"
            "• Резидентские визы, включая золотую — $300–1 000.\n"
            "• Аудит и восстановление учёта — от $300.\n"
            "• Отчётность (CIT/VAT) и эквайринг — по запросу.\n"
            "\n"
            "Точные суммы по каждой услуге — в разделе «Тарифы и сервисы» в кабинете."
        ),
        "answer_md_en": (
            "The reward depends on the service the client orders — usually from $300 to "
            "$1,000. It is always included in ONCOUNT's pricing and is earned when the "
            "client pays, as a one-off.\n"
            "\n"
            "• Accounting service — 100% of the 1st month's payment.\n"
            "• Company setup / business license — $1,000.\n"
            "• Opening a bank account — $1,000.\n"
            "• Residence visas, incl. the Golden Visa — $300–1,000.\n"
            "• Audit and accounting restoration — from $300.\n"
            "• Reporting (CIT/VAT) and acquiring — on request.\n"
            "\n"
            "Exact amounts per service are in the “Plans and services” section of your "
            "dashboard."
        ),
        "order_index": 1,
    },
    {
        "category": "Выплаты",
        "category_en": "Payouts",
        "question": "Как и когда приходит выплата?",
        "question_en": "How and when is the payout sent?",
        "answer_md": (
            "Выплату отправляем раз в месяц, до 10-го числа месяца, следующего за "
            "оплатой клиента, на удобные вам реквизиты. Способ и валюту согласуете с "
            "менеджером — его контакты в карточке на дашборде.\n"
            "\n"
            "Налоги вы платите сами в своей юрисдикции — ONCOUNT их за вас не "
            "удерживает. Нужен документ по выплате — попросите менеджера.\n"
            "\n"
            "Если клиент уже оплатил и вознаграждение начислено, оно остаётся за вами, "
            "даже если позже клиент перестанет обслуживаться."
        ),
        "answer_md_en": (
            "We send the payout once a month, by the 10th of the month following the "
            "client's payment, to your preferred payment details. You agree the method "
            "and currency with your manager — their contacts are on the dashboard card.\n"
            "\n"
            "You are responsible for your own taxes in your jurisdiction — ONCOUNT does "
            "not withhold them for you. If you need a document confirming the payout, "
            "just ask your manager.\n"
            "\n"
            "Once the client has paid and the reward is accrued, it stays yours — even if "
            "the client later stops using our services."
        ),
        "order_index": 2,
    },
    # ── Передача клиента ────────────────────────────────────────────────
    {
        "category": "Передача клиента",
        "category_en": "Introducing a client",
        "question": "Каких клиентов передавать?",
        "question_en": "Which clients should I introduce?",
        "answer_md": (
            "Предприниматели и компании, у которых есть бизнес в ОАЭ или которые только "
            "его открывают, и которым нужна бухгалтерия, налоги, открытие компании, "
            "банковский счёт или виза. Особенно легко заходят те, кто только открыл "
            "компанию, у кого пошли обороты, или кто недоволен текущим бухгалтером.\n"
            "\n"
            "Сам клиент может находиться в любой стране — важно, чтобы бизнес был в ОАЭ "
            "или планировался. Лимита на количество нет: чем больше клиентов вы "
            "приводите, тем больше вознаграждения и тем лучше условия партнёрства.\n"
            "\n"
            "Клиент закрепляется за тем, кто передал его первым. Если человек уже был у "
            "нас в работе или его раньше передал другой партнёр, повторная передача "
            "закрепление не перекрывает. Сомневаетесь — лучше передайте: система сверяет "
            "по номеру телефона, менеджер проверит.\n"
            "\n"
            "Передавать можно любым удобным способом: Excel-списком клиентов в WhatsApp "
            "или Telegram вашему менеджеру, через личный кабинет или через бота — как "
            "вам удобнее."
        ),
        "answer_md_en": (
            "Entrepreneurs and companies that have a business in the UAE or are just "
            "opening one, and who need accounting, taxes, company setup, a bank account "
            "or a visa. It works especially well for those who just opened a company, "
            "whose revenue is picking up, or who are unhappy with their current "
            "accountant.\n"
            "\n"
            "The client can be based anywhere — what matters is that the business is in "
            "the UAE or is planned there. There's no limit on how many you introduce: the "
            "more clients, the more reward and the better your partnership terms.\n"
            "\n"
            "A client is assigned to the partner who introduced them first. If the person "
            "was already in progress with us, or was introduced earlier by another "
            "partner, a repeat introduction doesn't override that. If in doubt — "
            "introduce them anyway: the system matches by phone number and the manager "
            "will verify it.\n"
            "\n"
            "You can introduce clients any way you like: an Excel list sent to your "
            "manager on WhatsApp or Telegram, via the partner portal, or through the "
            "bot — whatever works best for you."
        ),
        "order_index": 1,
    },
    {
        "category": "Передача клиента",
        "category_en": "Introducing a client",
        "question": "Что происходит после того, как я передал клиента?",
        "question_en": "What happens after I introduce a client?",
        "answer_md": (
            "1. Карточка создаётся в нашей CRM Kommo с вашим именем как партнёра.\n"
            "2. Менеджер связывается с клиентом в рабочее время в течение часа.\n"
            "3. Статус по каждому клиенту виден в разделе «Все заявки» на дашборде: "
            "в работе, успешно, отказ.\n"
            "4. Отчёт и партнёрское вознаграждение — до 10-го числа каждого месяца."
        ),
        "answer_md_en": (
            "1. A card is created in our Kommo CRM with your name as the partner.\n"
            "2. A manager contacts the client during business hours within an hour.\n"
            "3. The status of every client is in the “All requests” section on your "
            "dashboard: in progress, won, or rejected.\n"
            "4. The report and your partner reward — by the 10th of each month."
        ),
        "order_index": 2,
    },
    # ── Материалы и ссылки ──────────────────────────────────────────────
    {
        "category": "Материалы и ссылки",
        "category_en": "Materials & links",
        "question": "Где взять тексты, ссылку и материалы?",
        "question_en": "Where do I get the texts, my link and the materials?",
        "answer_md": (
            "В разделе «Тексты и партнёрские ссылки» на дашборде — готовые тексты для "
            "рассылок и постов, партнёрский кит и ваша личная ссылка: она уже вшита в "
            "каждый текст, рядом кнопка «Скопировать».\n"
            "\n"
            "Логотип и фирменные материалы можно использовать при продвижении ONCOUNT. "
            "Нужен конкретный материал — попросите менеджера."
        ),
        "answer_md_en": (
            "The “Texts and partner links” section on your dashboard has ready-made texts "
            "for outreach and posts, a partner kit, and your personal link — it's already "
            "built into every text, with a “Copy” button next to it.\n"
            "\n"
            "You may use the logo and brand materials when promoting ONCOUNT. Need a "
            "specific asset? Just ask your manager."
        ),
        "order_index": 1,
    },
]


# progress_steps — «только вид» (фиксированный прогресс из данных), не пер-партнёрский
# трекинг. 0 = кнопка «Начать». Поменяй число, чтобы показать «Продолжить»/done.
COURSES = [
    {
        "slug": "ai-employees-setup",
        "title": "Ваш первый AI-сотрудник",
        "subtitle": "⏱ 2 часа · 3 шага",
        "outcome": "сайты и презентации делают AI-сотрудники",
        "title_en": "Your first AI employee",
        "subtitle_en": "⏱ 2 hours · 3 steps",
        "outcome_en": "AI employees build your websites and presentations",
        "done_label_en": "Completed",
        "total_steps": 3,
        "progress_steps": 0,
        "done_label": "Завершено",
        "order_index": 1,
    },
    # Карточка «Курс партнёра ONCOUNT» (slug partner-course) убрана 2026-07-21 по
    # решению Николь: контента у курса не было, CTA «Начать» уводил обратно на
    # витрину (см. аудит 2026-07-06, п. 0.7). Вернуть — когда появятся уроки.
]


def seed_if_empty(session: Session) -> None:
    # ProductBlock и MessageTemplate — force-reseed на каждом старте, чтобы правки
    # в коде гарантированно доехали до прода. FK на эти таблицы нет, удаление безопасно.
    session.query(ProductBlock).delete()
    session.add_all([ProductBlock(**p) for p in PRODUCTS])
    session.query(MessageTemplate).delete()
    # TEMPLATES — генерик-крючки /messages (partner_type=NULL); KITS — материалы
    # /kits по типу партнёра (Фаза C+G, ФИНАЛЫ утв. Николь 2026-06-02, см. KITS выше).
    # Фаза J: кит партнёр копирует и шлёт КЛИЕНТУ → ни одного money-word в теле.
    # Только KITS (partner_type IS NOT NULL); генерик TEMPLATES не валидируем
    # (там «вознаграждение» — норма, это видит сам партнёр). Киты больше не *-draft,
    # поэтому стоп-слово в теле = ValueError (сидер падает явно, а не пишет в БД).
    for kit in KITS:
        _kit_body_clean(kit.get("body_md"), kit.get("body_md_en"), kit.get("slug", ""))
    session.add_all([MessageTemplate(**t) for t in TEMPLATES + KITS])
    session.query(FaqItem).delete()
    session.add_all([FaqItem(**f) for f in FAQ])
    # Course — тоже force-reseed: прогресс хранится отдельно (course_progress) по slug,
    # без FK на courses.id, поэтому пересоздание строк Course его не затрагивает.
    session.query(Course).delete()
    session.add_all([Course(**c) for c in COURSES])
    session.commit()
