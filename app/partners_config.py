"""Контент публичной страницы о партнёрской программе — /partners.

План: plans/2026-07-27-perenos-oncount-co-s-tildy.md, Фаза 1. Страница заменяет
собой главную старого сайта на Тильде (oncount.co): те же смыслы, но у нас, на
нашем домене, с трекингом перехода по ссылке агента.

Правило репо №1: тексты, цифры, отзывы и дата встречи живут ЗДЕСЬ, не в вёрстке.
Двуязычие: значения вида {"ru": ..., "en": ...}; шаблон берёт по текущему языку
через t(). EN-версия нужна, потому что у части партнёров клиенты нерусскоязычные.
"""
from __future__ import annotations


def t(value, lang: str = "ru"):
    """Значение по языку. Не словарь ru/en → возвращаем как есть (общее для обоих)."""
    if isinstance(value, dict) and ("ru" in value or "en" in value):
        return value.get(lang) or value.get("ru")
    return value


HERO = {
    "kicker": {"ru": "Партнёрская программа", "en": "Partner program"},
    "title": {"ru": "Приводите клиентов в ONCOUNT и получайте вознаграждение",
              "en": "Refer clients to ONCOUNT and earn a reward"},
    "lead": {"ru": "Вы передаёте клиента — мы ведём его бухгалтерию. "
                   "Вознаграждение приходит, когда клиент оплатил обслуживание.",
             "en": "You introduce the client — we take over the accounting. "
                   "Your reward arrives once the client pays for the service."},
    "call": {"ru": "Станьте партнёром ONCOUNT и зарабатывайте, не отвлекаясь от основной работы.",
             "en": "Become an ONCOUNT partner and earn without stepping away from your main job."},
    "cta": {"ru": "Записаться на Zoom с Николь", "en": "Book a Zoom with Nikole"},
    "cta_secondary": {"ru": "Стать партнёром", "en": "Become a partner"},
    # Отдельная подпись для шапки: там ссылка ведёт на вход, а не в бота.
    "login": {"ru": "Войти в кабинет", "en": "Log in"},
    # Кнопка ведёт в личный Telegram Николь с готовым первым сообщением —
    # партнёру не надо думать, с чего начать, а Николь сразу видит контекст.
    "zoom_url": "https://t.me/nikol_hillton?text="
                "%D0%97%D0%B4%D1%80%D0%B0%D0%B2%D1%81%D1%82%D0%B2%D1%83%D0%B9%D1%82%D0%B5%21%20"
                "%D0%A5%D0%BE%D1%87%D1%83%20%D0%BE%D0%B1%D1%81%D1%83%D0%B4%D0%B8%D1%82%D1%8C%20"
                "%D0%BF%D0%B0%D1%80%D1%82%D0%BD%D1%91%D1%80%D1%81%D1%82%D0%B2%D0%BE%20%D1%81%20ONCOUNT",
    "photo": "/static/img/partners/nikole.jpg",
    "photo_caption": {"ru": "<b>Николь Хилтон</b> — директор по развитию ONCOUNT, кофаундер и серийный предприниматель.",
                      "en": "<b>Nikole Hillton</b> — Head of Growth at ONCOUNT, co-founder and serial entrepreneur."},
}

# Блок «ближайшая встреча». None → блок не рендерится. Так сделано намеренно: на
# Тильде висела протухшая дата «17 сентября», и страница выглядела заброшенной.
# Заполнять ТОЛЬКО когда встреча реально назначена.
MEETING: dict | None = None
# Пример: {"date": "17 сентября, 19:00 по Дубаю", "format": "Онлайн, Zoom",
#          "host": "Николь Хилтон — директор по развитию ONCOUNT",
#          "note": "Количество мест ограничено"}

WHY = {
    "title": {"ru": "Что вы получаете", "en": "What you get"},
    "lead": {"ru": "Работу с клиентом берём на себя. Вложений с вашей стороны нет, "
                   "статус эксперта в глазах клиента остаётся за вами.",
             "en": "We take the work off your hands. It costs you nothing, and the "
                   "client still sees you as the expert who helped."},
    "items": {
        "ru": [
            "Клиента ведём мы: подбор тарифа, договор, бухгалтерия, отчётность.",
            "Вознаграждение — за каждого клиента, который дошёл до оплаты.",
            "Личный кабинет: ваши ссылки, заявки, статусы и начисления в одном месте.",
            "Готовые тексты, посты и материалы — берите и отправляйте своим клиентам.",
        ],
        "en": [
            "We handle the client: plan, contract, bookkeeping, reporting.",
            "A reward for every client who reaches payment.",
            "Your dashboard: links, leads, statuses and payouts in one place.",
            "Ready-made texts, posts and materials — send them to your clients.",
        ],
    },
}

# Тёмный блок «Наши партнёры» — как на старом сайте (там он назывался «Кого мы
# ждём на встрече»). Категории перенесены дословно; риелторы добавлены к
# консультантам, чтобы список лёг ровно в две строки без пустой ячейки.
AUDIENCE = {
    "title": {"ru": "Наши партнёры", "en": "Our partners"},
    "lead": {"ru": "Ваши клиенты — предприниматели в ОАЭ? Значит, это про вас.",
             "en": "Are your clients business owners in the UAE? Then this is for you."},
    "items": {
        "ru": [
            "CFO, CEO, COO — те, к кому идут за советом",
            "Инвестиционные консультанты и wealth-менеджеры",
            "Сотрудники банков",
            "Представители финтех-проектов и платёжных сервисов",
            "Консультанты, юристы, риелторы, консьерж-сервисы",
            "Бизнес-блогеры, спикеры, владельцы бизнес-порталов",
        ],
        "en": [
            "CFOs, CEOs, COOs — the people others come to for advice",
            "Investment advisors and wealth managers",
            "Bank professionals",
            "Fintech and payment-service companies",
            "Consultants, lawyers, real estate agents, concierge services",
            "Business bloggers, speakers, owners of business media",
        ],
    },
}

# Блок со старого сайта: почему сотрудничество выгодно + фото офиса ONCOUNT.
BENEFIT = {
    "title": {"ru": "Сотрудничество с ONCOUNT выгодно",
              "en": "Working with ONCOUNT pays off"},
    "text": {"ru": "Мы берём на себя всю работу, вы получаете доход и укрепляете свой "
                   "статус. Никаких дополнительных затрат — чистая прибыль. Ваша "
                   "репутация растёт, клиенты рекомендуют вас.",
             "en": "We take on all the work, you earn and strengthen your standing. No "
                   "extra costs — pure profit. Your reputation grows and clients "
                   "recommend you."},
    "cta": {"ru": "Стать партнёром", "en": "Become a partner"},
    "photo": "/static/img/partners/office.jpg",
}

STEPS = {
    "title": {"ru": "Как это работает", "en": "How it works"},
    "items": {
        "ru": [
            ("01", "Вы передаёте клиента или зовёте его на Zoom с консультантом ONCOUNT."),
            ("02", "Наш эксперт подбирает тариф под его задачи."),
            ("03", "Мы заключаем договор и ведём бухгалтерию."),
            ("04", "Вы получаете вознаграждение и благодарность довольного клиента."),
        ],
        "en": [
            ("01", "You introduce the client or invite them to a Zoom call with ONCOUNT."),
            ("02", "Our expert picks the plan that fits their situation."),
            ("03", "We sign the contract and run the accounting."),
            ("04", "You get your reward — and the client's thanks."),
        ],
    },
}

# Отзывы партнёров и их фото перенесены со старой страницы (Тильда) как есть.
# Фото лежат у нас в static/img/partners/ — со стороннего CDN не тянем, иначе
# картинки умрут вместе с подпиской Тильды.
REVIEWS = {
    "title": {"ru": "С нами сотрудничают около 200 партнёров — вот что они говорят",
              "en": "Around 200 partners work with us — here is what they say"},
    "items": [
        {
            "photo": "review-starovoytov.jpg",
            "name": {"ru": "Олег Старовойтов", "en": "Oleg Starovoytov"},
            "role": {"ru": "Владелец консалтинговой фирмы в Дубае",
                     "en": "Owner of a consulting firm in Dubai"},
            "text": {
                "ru": "Я уже полгода сотрудничаю с ONCOUNT как агент. У меня своя "
                      "небольшая консалтинговая компания по открытию бизнеса в Дубае, "
                      "и я просто передаю им клиентов, которым нужен бухгалтер. Передал "
                      "семь лидов, закрыли в оплаты пять. Я получил 5300 $ в первый же "
                      "месяц. Ребята работают быстро. Для меня это отличный "
                      "дополнительный доход без лишней нагрузки.",
                "en": "I have been working with ONCOUNT as a partner for six months. I "
                      "run a small company-formation consultancy in Dubai and simply "
                      "hand over the clients who need an accountant. I referred seven, "
                      "five of them paid, and I earned $5,300 in the very first month. "
                      "The team moves fast. Great extra income with no extra load.",
            },
        },
        {
            "photo": "review-razumov.jpg",
            "name": {"ru": "Николай Разумов", "en": "Oliver"},
            "role": {"ru": "Менеджер в юридической компании",
                     "en": "Manager at a law firm"},
            "text": {
                "ru": "Наша юридическая компания передаёт 50 лидов в месяц в ONCOUNT, "
                      "и в первый месяц мы получили 7000 $, а во второй ещё 14 000 $. "
                      "Вовремя, без напоминаний. А ещё ONCOUNT слышат запросы клиентов: "
                      "провели для наших менеджеров мини-обучение по налогам и срокам и "
                      "участвуют с нами в зумах с клиентами. Приятно сотрудничать с "
                      "профессионалами.",
                "en": "Our law firm passes about 50 leads a month to ONCOUNT. We earned "
                      "$7,000 in the first month and another $14,000 in the second — on "
                      "time, without reminders. They also listen: they ran a short tax "
                      "and deadlines training for our managers and join client calls "
                      "with us. A pleasure to work with professionals.",
            },
        },
        {
            "photo": "review-malyshev.jpg",
            "name": {"ru": "Никита Малышев", "en": "Nikita Malyshev"},
            "role": {"ru": "Риелтор", "en": "Real estate agent"},
            "text": {
                "ru": "С ONCOUNT сотрудничаю недавно. 3 месяца назад передал клиента и "
                      "забыл о нём. А сегодня мне пришло вознаграждение 1000 $ за этого "
                      "клиента. Порадовали. Советую ONCOUNT, особенно если ваши клиенты "
                      "— бизнесмены.",
                "en": "I started working with ONCOUNT recently. Three months ago I "
                      "referred a client and forgot about it — and today a $1,000 reward "
                      "landed for that client. Nice surprise. Recommended, especially if "
                      "your clients are business owners.",
            },
        },
    ],
}

# Иконки перенесены со старого сайта на Тильде (фирменный оранжевый), лежат в
# static/img/partners/. Порядок карточек = порядок иконок.
CLIENT_VALUE = {
    "title": {"ru": "Почему ваши клиенты останутся довольны",
              "en": "Why your clients will be happy"},
    "items": [
        {"icon": "documentation.png",
         "title": {"ru": "Знание требований", "en": "We know the rules"},
         "text": {"ru": "Команда с опытом 8+ лет в ОАЭ: законодательство, налоговое "
                        "регулирование, требования к финансовой отчётности.",
                  "en": "A team with 8+ years in the UAE: legislation, tax regulation "
                        "and financial reporting requirements."}},
        {"icon": "cash.png",
         "title": {"ru": "Экономия бюджета", "en": "Lower cost"},
         "text": {"ru": "Аутсорсинг обходится дешевле, чем свой бухгалтер или целый отдел.",
                  "en": "Outsourcing costs less than an in-house accountant or a whole "
                        "finance department."}},
        {"icon": "systems.png",
         "title": {"ru": "Современные технологии", "en": "Modern tooling"},
         "text": {"ru": "Удобные системы учёта без вложений со стороны клиента, "
                        "экспертный анализ и тройная проверка отчётности.",
                  "en": "Convenient accounting systems at no cost to the client, expert "
                        "review and a triple check of every report."}},
        {"icon": "shield.png",
         "title": {"ru": "Защита данных", "en": "Data protection"},
         "text": {"ru": "Финансовые данные клиента под корпоративными стандартами "
                        "безопасности.",
                  "en": "Client financial data is kept under corporate security "
                        "standards."}},
        {"icon": "growth.png",
         "title": {"ru": "Гибкость и рост", "en": "Room to grow"},
         "text": {"ru": "Услуги масштабируются: растёт бизнес — растёт и поддержка.",
                  "en": "The service scales: as the business grows, so does the support."}},
    ],
}

# Блок доверия. Формулировка Николь 2026-07-27: регламенты и KPI у бухгалтеров
# плюс страховка профессиональных рисков сводят штрафы к нулю — и это в любом
# случае не проблема клиента. ⚠️ Полис профответственности DB/PI/2025/197 истёк
# 01.06.2026 — как продлят, ничего править не нужно, но пока фраза про страховку
# держится на слове (Николь предупреждена).
GUARANTEE = {
    "title": {"ru": "Штрафы — не проблема вашего клиента",
              "en": "Penalties are not your client's problem"},
    "text": {
        "ru": "У наших бухгалтеров есть регламенты и KPI, а у компании — страховка "
              "профессиональных рисков. Вместе это сводит вероятность штрафа почти к "
              "нулю. А если ошибка всё-таки случится, разбираться с ней и платить будем "
              "мы, а не клиент. Вы приводите к нам человека, который вам доверяет, — мы "
              "дорожим и вашей репутацией, и своей.",
        "en": "Our accountants work to written procedures and KPIs, and the company "
              "carries professional indemnity insurance. Together that brings the risk "
              "of a penalty close to zero. And if a mistake does happen, we deal with it "
              "and we pay — not the client. You are introducing someone who trusts you, "
              "and we value your reputation as much as our own.",
    },
}

LICENCE = {
    "image": "/static/img/doc-licence.jpg",
    "title": "Trade Licence №37408",
    "text": {
        "ru": "PADVICE ACCOUNTING AND MANAGEMENT — FZCO, фризона IFZA (Dubai Silicon "
              "Oasis). Действует до 13.11.2026. Виды деятельности: Accounting & "
              "Bookkeeping, Project Management Services, Banking Consultant.",
        "en": "PADVICE ACCOUNTING AND MANAGEMENT — FZCO, IFZA free zone (Dubai Silicon "
              "Oasis). Valid until 13.11.2026. Activities: Accounting & Bookkeeping, "
              "Project Management Services, Banking Consultant.",
    },
}

TEAM_TITLE = {"ru": "Кто работает с вашим клиентом", "en": "Who works with your client"}

FINAL = {
    "title": {"ru": "Готовы начать?", "en": "Ready to start?"},
    "text": {
        "ru": "Регистрация занимает 1 минуту — и вы сразу получаете тексты для отправки "
              "клиентам и свои индивидуальные ссылки с UTM-метками, по которым мы видим, "
              "что клиент пришёл от вас.",
        "en": "Registration takes one minute — and you immediately get ready-made texts "
              "to send to clients plus your own links with UTM tags, so we can see the "
              "client came from you.",
    },
}

CONTACTS = {
    "address": ("The One Tower, 15 floor, office 14, Sheikh Zayed Rd, "
                "Dubai, United Arab Emirates"),
    "email": "info@oncount.com",
    "site": "https://oncount.com",
    "telegram": "https://t.me/oncountt",
    "instagram": "https://instagram.com/nikol_hillton",
}

# Юридические ссылки. Со старого сайта НЕ переносим: там под /policy и /oferta
# лежат документы GG Academy и GGO Consult LLC (ggacadem.com) — чужое юрлицо и
# чужой проект, ONCOUNT в них не упоминается вовсе (проверено 2026-07-27).
# Здесь только наша политика; оферту добавим, когда её подготовит юрист.
LEGAL_LINKS = [
    ({"ru": "Политика конфиденциальности", "en": "Privacy policy"}, "/policy"),
]

# Иконка-маркер у списков (звезда с Тильды) — вместо серых точек браузера.
BULLET_ICON = "audience.png"
