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
    KOMMO_DOMAIN: str = os.getenv("KOMMO_DOMAIN", "")
    KOMMO_TOKEN: str = os.getenv("KOMMO_TOKEN", "")
    KOMMO_PIPELINE_ID: str = os.getenv("KOMMO_PIPELINE_ID", "")
    ADMIN_TG_ID: int = int(os.getenv("ADMIN_TG_ID", "6634813047"))
    CONTACT_TG_USERNAME: str = os.getenv("CONTACT_TG_USERNAME", "nikol_hillton")
    CONTACT_WA_NUMBER: str = os.getenv("CONTACT_WA_NUMBER", "971589217784")
    # Баннер набора на Mastermind в разделе «Курсы». Меняется по месяцам — из конфига,
    # не хардкодом в шаблоне (правило репо №1). Пустой MASTERMIND_TITLE — баннер скрыт.
    MASTERMIND_TITLE: str = os.getenv(
        "MASTERMIND_TITLE",
        "Открыт набор на Mastermind — Июнь",
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
        "Mastermind enrollment open — June",
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
