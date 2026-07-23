import os
from dotenv import load_dotenv

load_dotenv()


_JWT_SECRET = os.getenv("JWT_SECRET", "")
if not _JWT_SECRET or _JWT_SECRET == "dev-secret-change-me":
    raise RuntimeError(
        "JWT_SECRET env var must be set to a non-default value. "
        "Set it in Railway → Variables before deploying."
    )


class Settings:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    BOT_USERNAME: str = os.getenv("BOT_USERNAME", "community_oncount_bot")
    WEBAPP_URL: str = os.getenv("WEBAPP_URL", "http://localhost:8000")
    JWT_SECRET: str = _JWT_SECRET
    JWT_ALGO: str = "HS256"
    JWT_TTL_DAYS: int = 30
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://oncount:oncount@localhost:5432/oncount_partners",
    )
    # Resend — транзакционные письма (магическая ссылка входа по email).
    # Пустой RESEND_API_KEY → dev-режим: ссылка пишется в лог, письмо не уходит.
    # EMAIL_FROM должен быть на верифицированном в Resend домене (nikole-ai.com),
    # иначе Resend отклоняет отправку. Имя отправителя — ONCOUNT (бренд).
    RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
    EMAIL_FROM: str = os.getenv("EMAIL_FROM", "ONCOUNT <noreply@nikole-ai.com>")
    # Централизация Kommo (2026-06-03): партнёр-сервис обращается к Kommo ТОЛЬКО
    # через наш api-сервис (NestJS), префикс /api/partner/* под ключом x-api-key.
    # Глобальный префикс /api добавляется в путях клиента (см. app/api_client.py).
    # Пусто → dev-режим: синк Kommo не регистрируется, лиды квиза остаются 'dry'.
    ONCOUNT_API_URL: str = os.getenv("ONCOUNT_API_URL", "")
    # Ключ к /api/partner/* (выдан api). Пусто в dev. Сетевой рубеж — Security Group
    # на EC2 (см. Documentation/PARTNER_API_SECURITY_DESIGN.md §4).
    PARTNER_API_KEY: str = os.getenv("PARTNER_API_KEY", "")
    # Wazzup24 — доставка кода входа / уведомлений в WhatsApp. ПОКА напрямую (план:
    # следующий PR переведёт отправку на api /api/partner/notify). Пустой ключ/канал
    # → dev-режим: в сеть ничего не уходит (см. app/wazzup.py).
    # WAZZUP_TEST_ONLY_NUMBER — предохранитель теста: если задан, шлём ТОЛЬКО на него.
    WAZZUP_API_KEY: str = os.getenv("WAZZUP_API_KEY", "")
    WAZZUP_CHANNEL_ID: str = os.getenv("WAZZUP_CHANNEL_ID", "")
    WAZZUP_TEST_ONLY_NUMBER: str = os.getenv("WAZZUP_TEST_ONLY_NUMBER", "")
    # Канал для КЛИЕНТСКИХ сообщений (подтверждения /mk и /consultation, PDF
    # лид-магнитов) — по решению Николь 2026-07-21 они уходят с продажного
    # номера 84 (971589217784), чтобы диалог клиента сразу жил в переписке
    # менеджера. Пусто → фолбэк на WAZZUP_CHANNEL_ID (сервисный канал кодов).
    # ⚠️ На 2026-07-21 WhatsApp-канал 84 в Wazzup blocked/qridle — перед
    # заполнением переменной переподключить канал (QR) в кабинете Wazzup.
    WAZZUP_CLIENT_CHANNEL_ID: str = os.getenv("WAZZUP_CLIENT_CHANNEL_ID", "")
    # Предохранитель Telegram-дайджеста (Фаза 4). По умолчанию OFF: планировщик 5/20
    # работает в dry (превью в лог), реально НЕ шлёт. Включить только осознанно:
    # DIGEST_ENABLED=1 в Railway, когда агенты уже в боте и формат подтверждён.
    DIGEST_ENABLED: bool = os.getenv("DIGEST_ENABLED", "") in ("1", "true", "True")
    # ГЛАВНЫЙ ПРЕДОХРАНИТЕЛЬ уведомлений партнёрам (Фаза K, план 2026-05-27).
    # default FALSE: пока агентов не пригласили в кабинет ([[feedback_no_agent_outreach_yet]]),
    # НИЧЕГО наружу не уходит — каждый триггер логируется в notification_attempts
    # со status='dry_run', в сеть 0 пакетов. Включать ТОЛЬКО осознанно в Railway
    # env (NOTIFICATIONS_LIVE=true) по команде Николь, НЕ дефолтом в коде.
    # Доп. слой для WhatsApp — WAZZUP_TEST_ONLY_NUMBER (шлёт только на тестовый).
    NOTIFICATIONS_LIVE: bool = os.getenv("NOTIFICATIONS_LIVE", "") in ("1", "true", "True")
    ADMIN_TG_ID: int = int(os.getenv("ADMIN_TG_ID", "6634813047"))
    # Куда ЕЩЁ дублировать заявки, кроме личного Telegram владельца (2026-07-21).
    # Фолбэк на время, пока api не создаёт сделки в Kommo (диагностика 21.07:
    # заявка принята, ответ api — failed, сделки в CRM нет): менеджер получает
    # заявку в закрытую группу и заносит её в CRM руками. CSV chat_id; у группы
    # id отрицательный (напр. "-1001234567890"). Пусто = прежнее поведение.
    # ⚠️ В этих сообщениях ПД клиентов — только закрытые чаты своей команды.
    NOTIFY_TG_CHAT_IDS: list[str] = [
        x.strip() for x in os.getenv("NOTIFY_TG_CHAT_IDS", "").split(",") if x.strip()
    ]
    CONTACT_TG_USERNAME: str = os.getenv("CONTACT_TG_USERNAME", "nikol_hillton")
    CONTACT_WA_NUMBER: str = os.getenv("CONTACT_WA_NUMBER", "971589217784")
    # Баннер набора на Mastermind в разделе «Курсы». Меняется по месяцам — из конфига,
    # не хардкодом в шаблоне (правило репо №1). Пустой MASTERMIND_TITLE — баннер скрыт.
    # Сейчас СКРЫТ (решение Николь 2026-06-02): набор закрыт. Чтобы вернуть — задать
    # MASTERMIND_TITLE/_EN (env или дефолт) с новым текстом месяца.
    MASTERMIND_TITLE: str = os.getenv(
        "MASTERMIND_TITLE",
        "",
    )
    # Программа: 5 AI-сотрудников, по пунктам через «;» (в баннере — через запятую).
    # Пункты 4–5 — заглушки до уточнения.
    MASTERMIND_DETAILS: str = os.getenv(
        "MASTERMIND_DETAILS",
        "Анализ конкурентов; "
        "Тексты для рассылок, постов и рилсов; "
        "Рассылки из CRM и Telegram-бота; "
        "Уточняется; "
        "Уточняется",
    )
    MASTERMIND_FOOTER: str = os.getenv(
        "MASTERMIND_FOOTER",
        "Старт 26 мая. Осталось 3 места из 10.",
    )
    # Английские версии баннера — выбираются в шаблоне при lang == 'en' (как title_en у курсов).
    # Без них EN-витрина показывала русский текст баннера.
    MASTERMIND_TITLE_EN: str = os.getenv(
        "MASTERMIND_TITLE_EN",
        "",
    )
    MASTERMIND_DETAILS_EN: str = os.getenv(
        "MASTERMIND_DETAILS_EN",
        "Competitor analysis; "
        "Copy for broadcasts, posts and reels; "
        "Broadcasts from CRM and Telegram bot; "
        "TBA; "
        "TBA",
    )
    MASTERMIND_FOOTER_EN: str = os.getenv(
        "MASTERMIND_FOOTER_EN",
        "Starts May 26. 3 of 10 seats left.",
    )
    # Обучающие видео в разделе «Обучение» (решение Николь 2026-07-23): два ролика
    # YouTube «доступ по ссылке» над курсами. ID — из конфига, не хардкодом (правило №1).
    # Пустой ID — карточка видео скрыта.
    TRAINING_VIDEO_PROGRAM_ID: str = os.getenv("TRAINING_VIDEO_PROGRAM_ID", "O1qprCkhXBM")
    TRAINING_VIDEO_CABINET_ID: str = os.getenv("TRAINING_VIDEO_CABINET_ID", "__7kQAR0Yjo")


settings = Settings()
