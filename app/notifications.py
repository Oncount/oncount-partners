"""Уведомления партнёру: еженедельный digest + точечный win-пуш (Фаза K).

План 2026-05-27 (kabinet-uderzhanie-partnerov), решения Николь 2026-06-01.

ГЛАВНЫЙ ПРЕДОХРАНИТЕЛЬ — settings.NOTIFICATIONS_LIVE (default false). Пока он не
"true", НИЧЕГО наружу не уходит: каждый триггер пишется в notification_attempts
со status='dry_run', сеть не дёргается. Включается ТОЛЬКО осознанно в Railway env
по команде Николь ([[feedback_no_agent_outreach_yet]]), не дефолтом в коде.

Что делает модуль:
- send_notification() — единый гард-канал наружу (TG-first → WhatsApp fallback),
  пишет попытку в БД при любом исходе, в общий лог — только partner_id/kind/status.
- digest_job() — раз в неделю в 16:00 Asia/Dubai в назначенный партнёру день
  (partner_id % 7). Если за 7 дней ничего не изменилось — МОЛЧИМ (не шлём пустое).
- notify_lead_won() — точечный пуш на переходе лида в `won` (идемпотентно).
- payout_due_date() — дата выплаты: 10-е число месяца, следующего за `won_at`.

ТЕКСТЫ — ЧЕРНОВИК (NOTIFICATIONS_DRAFT=True), на утверждении Николь (урок Фаз C/L).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

import httpx
from sqlalchemy.orm import Session

from app.auth import normalize_phone
from app.config import settings
from app.models import Lead, NotificationAttempt, Partner, PartnerIdentity
from app.wazzup import send_wa_text

log = logging.getLogger("oncount.notifications")

# Тексты ниже НЕ утверждены Николь — это рыба. show_notifications.py печатает
# плашку, win/digest помечаются в логе. Снять после утверждения текстов.
NOTIFICATIONS_DRAFT = True

# Дубай не переходит на летнее время → фиксированный сдвиг от UTC. Так обходимся
# без zoneinfo (надёжнее на Windows/Railway, нет зависимости от tz-базы).
DUBAI_OFFSET = timedelta(hours=4)

# Анти-бан: не больше стольких РЕАЛЬНО отправленных WhatsApp за сутки на канал
# ([[project_wa_broadcast_limit]] — держать ≤40/день/номер). dry-run не считается.
WA_DAILY_LIMIT = 40

# ─── Банк формулировок (ЧЕРНОВИК) ───────────────────────────────────────────
# Уникальность (анти-бан): шапка/концовка ротируются по числу прошлых сообщений
# партнёру → два подряд сообщения не совпадают. Плейсхолдеры: {name}, {client}.

GREETINGS_DIGEST = {
    "ru": [
        "{name}, добрый день! Коротко — что нового по вашим клиентам в ONCOUNT за неделю.",
        "Здравствуйте, {name}. Еженедельная сводка по вашим рекомендациям в ONCOUNT.",
        "{name}, на связи ONCOUNT. Как продвигаются клиенты, которых вы привели.",
        "Добрый день, {name}! Обновления по вашим клиентам за прошедшую неделю.",
        "{name}, ваша недельная сводка ONCOUNT готова — главное ниже.",
        "Приветствуем, {name}! Что изменилось у ваших клиентов за 7 дней.",
    ],
    "en": [
        "{name}, hello! A quick weekly update on your clients at ONCOUNT.",
        "Hi {name}. Your weekly summary on the clients you introduced to ONCOUNT.",
        "{name}, it's ONCOUNT. Here's how your introduced clients are progressing.",
        "Good day, {name}! Updates on your clients over the past week.",
        "{name}, your weekly ONCOUNT summary is ready — highlights below.",
        "Hello {name}! What changed for your clients in the last 7 days.",
    ],
}

CLOSINGS_DIGEST = {
    "ru": [
        "Полная картина по каждому клиенту — в вашем кабинете ONCOUNT.",
        "Детали по каждому клиенту всегда в кабинете. Спасибо, что рекомендуете ONCOUNT.",
        "Загляните в кабинет — там статус по каждому вашему клиенту.",
        "Появится клиент, которому нужна бухгалтерия в ОАЭ, — вы знаете, куда передать.",
        "Спасибо за доверие. Вопросы — ваш партнёрский менеджер на связи.",
        "Материалы для новых рекомендаций — в кабинете ONCOUNT.",
    ],
    "en": [
        "The full picture for every client is in your ONCOUNT dashboard.",
        "Details on each client are always in your dashboard. Thank you for recommending ONCOUNT.",
        "Drop by your dashboard — it shows the status of each of your clients.",
        "If a client needs accounting in the UAE, you know where to introduce them.",
        "Thank you for your trust. Questions? Your partner manager is one tap away.",
        "Materials for new recommendations are waiting in your ONCOUNT dashboard.",
    ],
}

GREETINGS_WIN = {
    "ru": [
        "{name}, отличная новость! Ваш клиент {client} теперь с ONCOUNT.",
        "{name}, поздравляем — {client} оплатил и работает с ONCOUNT.",
        "Хорошие новости, {name}! {client}, которого вы привели, оформил сотрудничество.",
        "{name}, ваш клиент {client} с нами. Спасибо за рекомендацию!",
        "{name}, {client} оплатил — рекомендация сработала. Спасибо!",
    ],
    "en": [
        "{name}, great news! Your client {client} is now with ONCOUNT.",
        "{name}, congratulations — {client} has signed up with ONCOUNT.",
        "Good news, {name}! {client}, whom you introduced, has come on board.",
        "{name}, your client {client} is with us. Thank you for the recommendation!",
        "{name}, {client} signed up — your recommendation worked. Thank you!",
    ],
}

CLOSINGS_WIN = {
    "ru": [
        "Статус выплаты виден в вашем кабинете ONCOUNT.",
        "Детали — в кабинете. Будем рады новым вашим клиентам.",
        "Спасибо, что доверяете ONCOUNT своих клиентов.",
        "Ваш партнёрский менеджер на связи, если будут вопросы.",
        "Полная история по клиенту — в кабинете ONCOUNT.",
    ],
    "en": [
        "The payout status is visible in your ONCOUNT dashboard.",
        "Details are in your dashboard. We'd be glad to welcome more of your clients.",
        "Thank you for trusting ONCOUNT with your clients.",
        "Your partner manager is here if any questions come up.",
        "The full client history is in your ONCOUNT dashboard.",
    ],
}

# Видимое правило выплат (решение Николь #4) — без конкретной суммы (решение #6).
PAYOUT_RULE = {
    "ru": "Партнёрское вознаграждение выплачивается до 10-го числа месяца, следующего за оплатой клиентом.",
    "en": "Your partner reward is paid by the 10th of the month following the client's payment.",
}


# ─── Язык / дата выплаты ─────────────────────────────────────────────────────
def _plang(partner: Partner) -> str:
    return "en" if getattr(partner, "lang", None) == "en" else "ru"


def _next_month_tenth(dt: datetime) -> date:
    y, m = dt.year, dt.month
    if m == 12:
        y, m = y + 1, 1
    else:
        m += 1
    return date(y, m, 10)


def payout_due_date(lead: Lead, lang: str = "ru") -> dict | None:
    """Дата выплаты по выигранному лиду → {date, label} для шаблонов и текстов.

    Деньги показываем ТОЛЬКО по won (как payout_label). Якорь — won_at (Фаза K),
    дата = 10-е число СЛЕДУЮЩЕГО месяца. Мягкая деградация: won-лид без won_at
    (легаси/бэкфилл до фичи) → дата неизвестна, формулируем как ожидание."""
    if getattr(lead, "status", None) != "won":
        return None
    lang = lang if lang in ("ru", "en") else "ru"
    if not lead.won_at:
        return {"date": None,
                "label": "после оплаты клиентом" if lang == "ru" else "after the client pays"}
    ds = _next_month_tenth(lead.won_at).strftime("%d.%m.%Y")
    label = f"К выплате до {ds}" if lang == "ru" else f"Due by {ds}"
    return {"date": ds, "label": label}


# ─── Выбор варианта (уникальность) ───────────────────────────────────────────
def _prior_count(session: Session, partner_id: int, kind: str) -> int:
    return (session.query(NotificationAttempt)
            .filter(NotificationAttempt.partner_id == partner_id,
                    NotificationAttempt.kind == kind)
            .count())


def _pick(bank: dict[str, list[str]], lang: str, n: int) -> str:
    """Детерминированная ротация по счётчику n: соседние сообщения различаются
    (n и n+1 дают разные индексы при len>=2). Без random — тестируемо."""
    variants = bank.get(lang) or bank["ru"]
    return variants[n % len(variants)]


# ─── Сборка текстов ──────────────────────────────────────────────────────────
def build_win_text(partner: Partner, lead: Lead, session: Session) -> str:
    lang = _plang(partner)
    n = _prior_count(session, partner.id, "win")
    name = partner.first_name or partner.kommo_agent_name or ("партнёр" if lang == "ru" else "partner")
    client = (lead.client_name or "").strip() or ("ваш клиент" if lang == "ru" else "your client")
    greet = _pick(GREETINGS_WIN, lang, n).format(name=name, client=client)
    close = _pick(CLOSINGS_WIN, lang, n).format(name=name, client=client)
    due = payout_due_date(lead, lang)
    body_mid: list[str] = []
    if due and due["date"]:
        body_mid.append(f"Ожидаемая дата выплаты — {due['date']}."
                        if lang == "ru" else f"Expected payout date — {due['date']}.")
    # Правило выплат — всегда (без конкретной суммы, решение Николь #6).
    body_mid.append(PAYOUT_RULE[lang])
    return "\n\n".join([greet, *body_mid, close])


def build_digest_text(partner: Partner, session: Session, now: datetime) -> str | None:
    """Сводка по лидам партнёра. None → за 7 дней ничего не изменилось (МОЛЧИМ).

    «Изменение» = новый лид (created_at) ИЛИ выигранный (won_at) за окно 7 дней
    (решение Николь: digest-детект по 1 полю won_at + created_at). Тело — только
    АГРЕГАТЫ, без имён клиентов (ПД: имя чужого клиента в сводку НЕ кладём)."""
    lang = _plang(partner)
    window = now - timedelta(days=7)
    rows = session.query(Lead).filter_by(partner_id=partner.id).all()
    if not rows:
        return None
    new_week = sum(1 for l in rows if l.created_at and l.created_at >= window)
    won_week = sum(1 for l in rows if l.won_at and l.won_at >= window)
    if new_week == 0 and won_week == 0:
        return None  # тишина — нет хороших новостей за неделю

    in_progress = sum(1 for l in rows if l.status in ("new", "in_progress"))
    won_total = sum(1 for l in rows if l.status == "won")

    n = _prior_count(session, partner.id, "digest")
    name = partner.first_name or partner.kommo_agent_name or ("партнёр" if lang == "ru" else "partner")
    greet = _pick(GREETINGS_DIGEST, lang, n).format(name=name)
    close = _pick(CLOSINGS_DIGEST, lang, n).format(name=name)

    if lang == "en":
        body = [
            f"In progress with the accountant: {in_progress}.",
            f"Already with us (paid): {won_total}.",
            f"New introductions this week: {new_week}.",
        ]
    else:
        body = [
            f"В работе у бухгалтера: {in_progress}.",
            f"Уже с нами (оплатили): {won_total}.",
            f"Новые заявки за неделю: {new_week}.",
        ]
    if won_total:
        body.append(PAYOUT_RULE[lang])
    return "\n\n".join([greet, "\n".join(body), close])


# ─── Канал-роутинг (TG-first) ────────────────────────────────────────────────
def _mask_phone(norm: str) -> str:
    if not norm or len(norm) <= 6:
        return "***"
    return f"{norm[:3]}***{norm[-2:]}"


def resolve_channel(partner: Partner, session: Session) -> tuple[str, str | None, str | None]:
    """(channel, destination, recipient_masked).

    TG-first (решение Николь): через бота — бесплатно, без риска бана, без лимита
    40/день. ВАЖНО: для Telegram нужен numeric chat_id (Partner.telegram_id), а
    НЕ @username — по username приватному пользователю Bot API слать не может,
    поэтому PartnerIdentity.kind='tg_username' для доставки не используется.
    Fallback → WhatsApp по номеру (PartnerIdentity.kind='phone' → Partner.phone)."""
    if partner.telegram_id:
        return "tg", str(partner.telegram_id), f"tg:{partner.telegram_id}"
    ident = (session.query(PartnerIdentity)
             .filter(PartnerIdentity.kind == "phone", PartnerIdentity.partner_id == partner.id)
             .first())
    norm = ""
    if ident:
        norm = normalize_phone(ident.value)
    if not norm and partner.phone:
        norm = normalize_phone(partner.phone)
    if norm:
        return "wa", norm, _mask_phone(norm)
    return "none", None, None


# ─── Транспорт ───────────────────────────────────────────────────────────────
def _send_tg(chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage"
    try:
        r = httpx.post(url, json={"chat_id": chat_id, "text": text}, timeout=15)
        return r.status_code < 400
    except httpx.HTTPError:
        return False


def _wa_sent_today(session: Session, now: datetime) -> int:
    """Сколько РЕАЛЬНО отправленных WA за текущие дубайские сутки (для лимита)."""
    dubai_now = now + DUBAI_OFFSET
    dubai_midnight_utc = datetime.combine(dubai_now.date(), time.min) - DUBAI_OFFSET
    return (session.query(NotificationAttempt)
            .filter(NotificationAttempt.channel == "wa",
                    NotificationAttempt.status == "sent",
                    NotificationAttempt.created_at >= dubai_midnight_utc)
            .count())


def send_notification(partner: Partner, body: str, kind: str, session: Session,
                      lead: Lead | None = None, now: datetime | None = None) -> NotificationAttempt:
    """Единственная дверь наружу. Пишет попытку в БД при ЛЮБОМ исходе и коммитит.

    Предохранитель: при NOTIFICATIONS_LIVE != true — status='dry_run', сеть не
    дёргается. В общий лог — только partner_id/kind/status/тип-ошибки (не телефон,
    не текст). Полный текст и маскированный получатель — в строке БД (аудит)."""
    now = now or datetime.utcnow()
    channel, dest, recipient = resolve_channel(partner, session)
    status = "dry_run"
    error_short: str | None = None

    if channel == "none":
        status = "no_channel"
    elif not settings.NOTIFICATIONS_LIVE:
        status = "dry_run"  # ПРЕДОХРАНИТЕЛЬ: наружу 0 пакетов
    else:
        try:
            if channel == "wa":
                if _wa_sent_today(session, now) >= WA_DAILY_LIMIT:
                    status = "rate_limited"
                else:
                    status = "sent" if (dest and send_wa_text(dest, body)) else "failed"
            elif channel == "tg":
                status = "sent" if (dest and _send_tg(dest, body)) else "failed"
        except Exception as exc:  # сеть/SDK — не валим синк/джоб
            status = "failed"
            error_short = type(exc).__name__

    attempt = NotificationAttempt(
        partner_id=partner.id, kind=kind, channel=channel, recipient=recipient,
        body=body, status=status, error_short=error_short,
        lead_id=lead.id if lead else None, created_at=now,
    )
    session.add(attempt)
    session.commit()
    log.info("notify partner=%s kind=%s channel=%s status=%s%s",
             partner.id, kind, channel, status,
             f" err={error_short}" if error_short else "")
    return attempt


# ─── Триггеры ────────────────────────────────────────────────────────────────
def _engaged(partner: Partner) -> bool:
    """Партнёр УЖЕ заходил в кабинет хотя бы раз? Гейт против холодной рассылки
    необонбординным агентам ([[feedback_no_agent_outreach_yet]]): seed создаёт
    Partner из enum-справочника со status='invited' и без входа — таким про
    кабинет ещё не сказали, слать «загляните в кабинет» нельзя. Шлём только тем,
    кто уже в кабинете (last_login_at проставлен на входе)."""
    return partner.last_login_at is not None


def notify_lead_won(lead: Lead, session: Session, now: datetime | None = None) -> None:
    """Точечный пуш на переходе лида в won. Идемпотентно (won_notified_at).

    Помечаем won_notified_at при ЛЮБОМ исходе (в т.ч. dry_run/no_channel/не
    вовлечён) — событие «прожито», повтор не нужен; при go-live лавины старых
    пушей не будет. Партнёру, который ещё не входил в кабинет, не шлём (правило
    no-outreach), но событие тоже помечаем обработанным."""
    if lead.won_notified_at is not None:
        return
    now = now or datetime.utcnow()
    partner = lead.partner or session.get(Partner, lead.partner_id)
    if partner is None:
        return
    if not _engaged(partner):
        log.info("win suppressed (partner=%s не входил в кабинет)", partner.id)
        lead.won_notified_at = now
        session.commit()
        return
    text = build_win_text(partner, lead, session)
    send_notification(partner, text, "win", session, lead=lead, now=now)
    lead.won_notified_at = now
    session.commit()


def _digest_already_today(session: Session, partner_id: int, now: datetime) -> bool:
    dubai_now = now + DUBAI_OFFSET
    dubai_midnight_utc = datetime.combine(dubai_now.date(), time.min) - DUBAI_OFFSET
    return (session.query(NotificationAttempt)
            .filter(NotificationAttempt.partner_id == partner_id,
                    NotificationAttempt.kind == "digest",
                    NotificationAttempt.created_at >= dubai_midnight_utc)
            .first()) is not None


def run_weekly_digest(session: Session, now: datetime | None = None) -> dict:
    """Тело джоба (вынесено для тестируемости). Бежит ежедневно в 16:00 Дубай;
    отбирает партнёров, у кого СЕГОДНЯ их день (partner_id % 7 == weekday Дубай).
    Молчит, если за неделю изменений нет. Идемпотентно: ≤1 digest/день/партнёр."""
    now = now or datetime.utcnow()
    dubai_weekday = (now + DUBAI_OFFSET).weekday()  # Пн=0 … Вс=6
    # Только партнёры-агенты, КОТОРЫЕ УЖЕ ЗАХОДИЛИ В КАБИНЕТ (last_login_at):
    # digest — инструмент удержания для пользователей кабинета, необонбординным
    # агентам холодную рассылку не шлём ([[feedback_no_agent_outreach_yet]]).
    agents = (session.query(Partner)
              .filter(Partner.kommo_agent_enum_id.isnot(None),
                      Partner.last_login_at.isnot(None))
              .all())
    sent = silent = skipped_today = 0
    for p in agents:
        if p.id % 7 != dubai_weekday:
            continue
        if _digest_already_today(session, p.id, now):
            skipped_today += 1
            continue
        text = build_digest_text(p, session, now)
        if text is None:
            silent += 1
            continue
        send_notification(p, text, "digest", session, now=now)
        sent += 1
    res = {"weekday": dubai_weekday, "sent": sent, "silent": silent,
           "skipped_today": skipped_today, "live": settings.NOTIFICATIONS_LIVE}
    log.info("weekly_digest: %s", res)
    return res


def digest_job() -> None:
    """Точка для APScheduler (ежедневно 12:00 UTC = 16:00 Asia/Dubai)."""
    from app.db import SessionLocal
    session = SessionLocal()
    try:
        run_weekly_digest(session)
    finally:
        session.close()
