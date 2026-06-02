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
    # Wazzup24 — доставка кода входа в WhatsApp (план 2026-05-27, вход по номеру).
    # Пустой ключ/канал → dev-режим: код в сеть не уходит (см. app/wazzup.py).
    # WAZZUP_TEST_ONLY_NUMBER — предохранитель теста: если задан, код шлётся ТОЛЬКО
    # на этот номер. Слать с НЕ основного номера (не жечь основной 84).
    WAZZUP_API_KEY: str = os.getenv("WAZZUP_API_KEY", "")
    WAZZUP_CHANNEL_ID: str = os.getenv("WAZZUP_CHANNEL_ID", "")
    WAZZUP_TEST_ONLY_NUMBER: str = os.getenv("WAZZUP_TEST_ONLY_NUMBER", "")
    KOMMO_DOMAIN: str = os.getenv("KOMMO_DOMAIN", "primeadvice.kommo.com")
    KOMMO_TOKEN: str = os.getenv("KOMMO_TOKEN", "")
    KOMMO_PIPELINE_ID: str = os.getenv("KOMMO_PIPELINE_ID", "")
    # Квиз-лендинг /consultation (план 2026-06-02). Лид создаётся в Kommo воронке 1.1
    # с привязкой к агенту через поле «ID AGENT». ПРЕДОХРАНИТЕЛЬ QUIZ_KOMMO_LIVE
    # (default false, как NOTIFICATIONS_LIVE): пока false — в Kommo НЕ ходим, заявка
    # живёт только в Postgres + TG-пуш админу (kommo_status='dry'). Снять ТОЛЬКО
    # осознанно в Railway env (QUIZ_KOMMO_LIVE=true) по команде Николь.
    # id воронки/этапа 1.1 — из конфига (правило репо №1), сверены ниже.
    # Поле «ID AGENT» = #961886 (см. Partner.kommo_agent_enum_id).
    QUIZ_KOMMO_LIVE: bool = os.getenv("QUIZ_KOMMO_LIVE", "") in ("1", "true", "True")
    # Дефолты сверены kommo_quiz_discover 2026-06-02. Воронка «1.1 Line agent lid»
    # pipeline_id=11126307. ВАЖНО: «Incoming leads» (85364779) — это unsorted-этап,
    # API его НЕ принимает (NotSupportedChoice). Берём первый РЕГУЛЯРНЫЙ этап
    # «Первый ход» status_id=85364783 (проверено live-тестом 2026-06-02).
    QUIZ_KOMMO_PIPELINE_ID: str = os.getenv("QUIZ_KOMMO_PIPELINE_ID", "11126307")
    QUIZ_KOMMO_STATUS_ID: str = os.getenv("QUIZ_KOMMO_STATUS_ID", "85364783")
    KOMMO_ID_AGENT_FIELD_ID: int = int(os.getenv("KOMMO_ID_AGENT_FIELD_ID", "961886"))
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


settings = Settings()
