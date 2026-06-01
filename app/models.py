from datetime import datetime
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Partner(Base):
    __tablename__ = "partners"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # telegram_id больше не обязателен: партнёр может зарегистрироваться по email
    # без Telegram (план 2026-05-23). Postgres unique-индекс допускает несколько
    # NULL, поэтому уникальность для TG-партнёров сохраняется.
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128))
    photo_url: Mapped[str | None] = mapped_column(String(512))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(32))
    segment: Mapped[str | None] = mapped_column(String(32))
    ref_slug: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    # Язык интерфейса бота: "ru"/"en". None → не выбран явно, бот берёт по
    # language_code Telegram (см. resolve_lang в bot.py). Кнопка-переключатель
    # проставляет сюда явный выбор.
    lang: Mapped[str | None] = mapped_column(String(2))
    tier: Mapped[str] = mapped_column(String(16), default="bronze")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # Связь с агентом в Kommo: enum_id значения поля «ID AGENT» (#961886) воронки 1.1.
    # Один Partner ↔ один Kommo-агент. По нему отчёт/дайджест тянут лиды агента.
    # kommo_agent_name — кэш отображаемого имени (латиница), для писем/дайджеста.
    kommo_agent_enum_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    kommo_agent_name: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime)
    links_viewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    products_viewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    checklist_dismissed_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Анкета партнёра (Фаза L, план 2026-05-27): профиль для подбора
    # СТРАТЕГИЧЕСКОГО партнёрства (это анкета самого партнёра, НЕ онбординг
    # клиента). Ответы — только варианты из белого списка (JSON-словарь);
    # survey_completed_at IS NOT NULL → анкета пройдена (баннер скрыт).
    # ⚠️ ПД («опасная тройка»): реквизиты выплат (номера карт/кошельков/IBAN)
    # сюда НЕ пишем — только ТИП канала. Точные реквизиты менеджер собирает
    # в личной переписке, вне БД.
    onboarding_answers: Mapped[dict | None] = mapped_column(JSON)
    survey_completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    referrals: Mapped[list["Referral"]] = relationship(back_populates="partner")
    leads: Mapped[list["Lead"]] = relationship(back_populates="partner")


class Referral(Base):
    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    partner_id: Mapped[int] = mapped_column(ForeignKey("partners.id"), index=True)
    ref_slug: Mapped[str] = mapped_column(String(16), index=True)
    source: Mapped[str] = mapped_column(String(16))
    visitor_meta: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    partner: Mapped[Partner] = relationship(back_populates="referrals")


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    partner_id: Mapped[int] = mapped_column(ForeignKey("partners.id"), index=True)
    client_name: Mapped[str] = mapped_column(String(255))
    client_phone: Mapped[str | None] = mapped_column(String(32))
    client_telegram: Mapped[str | None] = mapped_column(String(64))
    client_email: Mapped[str | None] = mapped_column(String(255))
    company_name: Mapped[str | None] = mapped_column(String(255))
    task_description: Mapped[str | None] = mapped_column(Text)
    # «Что НЕ предлагать клиенту» — обязательное поле в /transfer (Фаза F, план
    # 2026-05-27): партнёр пишет ограничения/табу, чтобы менеджер не повредил
    # его репутации лишним предложением. nullable=True, потому что лиды из
    # kommo_sync и легаси-ТГ-бота этого поля не заполняют.
    do_not_offer: Mapped[str | None] = mapped_column(Text)
    kommo_lead_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(32), default="new", index=True)
    amount_aed: Mapped[float | None] = mapped_column(Numeric(12, 2))
    # Статус партнёрского вознаграждения по ВЫИГРАННОМУ лиду (Фаза B, план
    # 2026-05-27): in_calc / to_pay / paid. Менеджер ставит вручную
    # (scripts/set_payout_state.py). NULL у won-лида = «в расчёте» — дефолт
    # выводим на слое отображения (payout_label в main.py), в данные не пишем,
    # поэтому колонка nullable без DB-default. Таблицу Payout НЕ заводим
    # (решение Николь). kommo_sync это поле не трогает — ручная отметка живёт.
    payout_state: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    partner: Mapped[Partner] = relationship(back_populates="leads")


class MessageTemplate(Base):
    __tablename__ = "message_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    segment: Mapped[str | None] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(255))
    body_md: Mapped[str] = mapped_column(Text)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # EN-версии (рендерятся при lang=en, fallback на русское поле). Пусто → русский.
    segment_en: Mapped[str | None] = mapped_column(String(64))
    title_en: Mapped[str | None] = mapped_column(String(255))
    body_md_en: Mapped[str | None] = mapped_column(Text)
    # Тип ПАРТНЁРА, под который собран ассет (Фаза C, план 2026-05-27): ключ из
    # PARTNER_TYPES в main.py (employee/solo/events/agency/media/consultant/insider).
    # NULL → шаблон не привязан к типу (генерик-крючки /messages — старое поведение,
    # они НЕ показываются в /kits). Это ДРУГАЯ ось, чем segment (= тип ассета:
    # «Интро WhatsApp» / «Lead-магнит» / «Disclosure»…). EN-зеркало не нужно:
    # partner_type — внутренний ключ, ярлык берётся из PARTNER_TYPES (ru/en).
    partner_type: Mapped[str | None] = mapped_column(String(32), index=True)


class ProductBlock(Base):
    __tablename__ = "product_blocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(255))
    price_aed: Mapped[str | None] = mapped_column(Text)
    summary_md: Mapped[str] = mapped_column(Text)
    full_md: Mapped[str] = mapped_column(Text)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # EN-версии (рендерятся при lang=en, fallback на русское поле). Пусто → русский.
    title_en: Mapped[str | None] = mapped_column(String(255))
    price_aed_en: Mapped[str | None] = mapped_column(Text)
    summary_md_en: Mapped[str | None] = mapped_column(Text)
    full_md_en: Mapped[str | None] = mapped_column(Text)


class FaqItem(Base):
    __tablename__ = "faq_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    question: Mapped[str] = mapped_column(String(500))
    answer_md: Mapped[str] = mapped_column(Text)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # EN-версии (рендерятся при lang=en, fallback на русское поле). Пусто → русский.
    category_en: Mapped[str | None] = mapped_column(String(64))
    question_en: Mapped[str | None] = mapped_column(String(500))
    answer_md_en: Mapped[str | None] = mapped_column(Text)


class Course(Base):
    """Обучающий курс для партнёра в ЛК (раздел «Курсы»).

    Карточка-витрина: заголовок, подзаголовок (длительность/шаги), строка «Итог»,
    полоса прогресса и одна CTA-кнопка. Контент редактируется через seed
    (force-reseed, как ProductBlock/FaqItem).

    Прогресс пока «только вид»: progress_steps — фиксированное значение из данных,
    не пер-партнёрский трекинг. Статус кнопки выводится из progress_steps/total_steps:
    0 → «Начать», 0<x<total → «Продолжить», x>=total → done_label.
    """
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(255))
    subtitle: Mapped[str | None] = mapped_column(String(255))
    outcome: Mapped[str | None] = mapped_column(Text)
    total_steps: Mapped[int] = mapped_column(Integer, default=0)
    progress_steps: Mapped[int] = mapped_column(Integer, default=0)
    done_label: Mapped[str] = mapped_column(String(64), default="Завершено")
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Английские версии полей витрины (рендерятся при lang=en). Заложены заранее,
    # чтобы таблица создалась сразу со всеми колонками: create_all НЕ умеет ALTER.
    # Пусто → шаблон откатывается на русское поле (graceful fallback).
    title_en: Mapped[str | None] = mapped_column(String(255))
    subtitle_en: Mapped[str | None] = mapped_column(String(255))
    outcome_en: Mapped[str | None] = mapped_column(Text)
    done_label_en: Mapped[str | None] = mapped_column(String(64))


class LoginSession(Base):
    """Однократный токен для входа в ЛК через бота (deep-link auth)."""
    __tablename__ = "login_sessions"

    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Если вход начат по персональной инвайт-ссылке /invite/<slug> (Фаза 0.7),
    # сюда кладётся ref_slug пред-созданного Partner-агента — чтобы привязать
    # telegram_id к НЕМУ, а не плодить дубль.
    ref_slug: Mapped[str | None] = mapped_column(String(16))


class EmailLoginToken(Base):
    """Одноразовый токен для входа в ЛК по email (магическая ссылка, план 2026-05-23).

    Партнёр запрашивает вход → сюда пишется криптослучайный token + email.
    Письмо со ссылкой `…/auth/email/callback?token=…` уходит через Resend. Клик:
    токен валиден (не использован, не истёк, TTL 15 мин) → выдаём JWT-cookie.
    consumed_at делает токен одноразовым; старые невостребованные чистятся в startup.
    """
    __tablename__ = "email_login_tokens"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime)
    # ref_slug пред-созданного Partner-агента, если вход начат по инвайт-ссылке (Фаза 0.7).
    ref_slug: Mapped[str | None] = mapped_column(String(16))


class PartnerIdentity(Base):
    """Идентификатор агента для входа (план 2026-05-27, Вариант А).

    Один кабинет (Partner) ↔ много идентификаторов разного типа:
    - `kind="phone"`     — номер (digits-only, как normalize_phone) для входа по WhatsApp-коду;
    - `kind="tg_username"` — username Telegram (lower, без `@`) — доверенные ники канала.

    Нужно, потому что у агента бывает несколько номеров, а у канала-корзины
    (`4dev`, `Ilya+Andrey`…) — массив номеров и ников команды. Матч на входе идёт
    по этой таблице (value → partner_id), `Partner.phone` остаётся как основной/совместимость.

    value уникален В РАМКАХ kind (один номер/ник не ведёт в два кабинета).
    Заполняется из `dumps/agent_phone_map.json` (phone) + ручных от Николь
    (`agent_phone_manual.json`: phones[]/tg_usernames[]) — Фаза 1б, на Railway.
    """
    __tablename__ = "partner_identities"
    __table_args__ = (UniqueConstraint("kind", "value", name="uq_identity_kind_value"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    partner_id: Mapped[int] = mapped_column(ForeignKey("partners.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    value: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    partner: Mapped["Partner"] = relationship()


class PhoneLoginToken(Base):
    """Одноразовый код для входа в ЛК по номеру телефона (план 2026-05-27).

    Телефон — сквозной идентификатор агента (WhatsApp = телефон, карточка
    воронки 6 = телефон), поэтому вход по номеру одновременно аутентифицирует и
    объединяет каналы. Партнёр вводит номер → сюда пишется hmac-хэш 6-значного
    кода + нормализованный (digits-only) телефон. Код уходит в WhatsApp через
    Wazzup. На вводе кода: не истёк (TTL 10 мин), не использован, ≤5 попыток →
    выдаём JWT-cookie.

    Безопасность (опасная тройка — персональные данные): хранится ТОЛЬКО хэш кода
    (hmac-sha256 с JWT_SECRET-перцем), сам код и телефон НЕ логируются. attempts
    режет брутфорс, consumed_at делает код одноразовым, протухшие чистятся в
    startup. phone здесь — не PK: на номер может быть несколько запросов, verify
    берёт последний невостребованный.
    """
    __tablename__ = "phone_login_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone: Mapped[str] = mapped_column(String(32), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime)


class EventRegistration(Base):
    """Регистрации на мастер-классы и события — наследник telegram-bot-2brain."""
    __tablename__ = "event_registrations"
    __table_args__ = (UniqueConstraint("telegram_id", "event_slug", name="uq_event_per_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    event_slug: Mapped[str] = mapped_column(String(64), index=True)
    first_name: Mapped[str | None] = mapped_column(String(128))
    username: Mapped[str | None] = mapped_column(String(64))
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    attended: Mapped[bool] = mapped_column(Boolean, default=False)
    meta: Mapped[dict | None] = mapped_column(JSON)
