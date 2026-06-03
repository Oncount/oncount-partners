"""Уведомления партнёру: еженедельный digest + точечный win-пуш (Фаза K).

План 2026-05-27 (kabinet-uderzhanie-partnerov), решения Николь 2026-06-01.

ГЛАВНЫЙ ПРЕДОХРАНИТЕЛЬ — settings.NOTIFICATIONS_LIVE (default false). Пока он не
"true", НИЧЕГО наружу не уходит: каждый триггер пишется в notification_attempts
со status='dry_run', сеть не дёргается. Включается ТОЛЬКО осознанно в Railway env
по команде Николь ([[feedback_no_agent_outreach_yet]]), не дефолтом в коде.

Что делает модуль:
- send_notification() — единый гард-канал наружу (TG-first → WhatsApp fallback),
  пишет попытку в БД при любом исходе, в общий лог — только partner_id/kind/status.
- digest_job() — ежедневный джоб 16:00 Asia/Dubai. Адаптивная частота: прислал
  заявку за неделю → недельные итоги в его день (partner_id % 7); не прислал →
  месячный нудж «ждём заявки». Гард _engaged() сохраняется.
- notify_lead_won() — точечный пуш на переходе лида в `won` (идемпотентно).
- payout_due_date() — дата выплаты: 10-е число месяца, следующего за `won_at`.

ТЕКСТЫ — УТВЕРЖДЕНЫ Николь 2026-06-02 (Фаза 4 go-live), single fixed без ротации.
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

# Тексты утверждены Николь 2026-06-02 (Фаза 4 go-live). Единые фиксированные
# формулировки без ротации: разворачивать в неутверждённые варианты и метить их
# «финальными» — повтор ошибки Фаз E/F. Анти-бан держится на TG-first + редкости.
NOTIFICATIONS_DRAFT = False

# Дубай не переходит на летнее время → фиксированный сдвиг от UTC. Так обходимся
# без zoneinfo (надёжнее на Windows/Railway, нет зависимости от tz-базы).
DUBAI_OFFSET = timedelta(hours=4)

# Анти-бан: не больше стольких РЕАЛЬНО отправленных WhatsApp за сутки на канал
# ([[project_wa_broadcast_limit]] — держать ≤40/день/номер). dry-run не считается.
WA_DAILY_LIMIT = 40

# ─── Тексты уведомлений (УТВЕРЖДЕНЫ Николь 2026-06-02, single fixed) ─────────
# Без ротации: одно фиксированное сообщение каждого типа. Плейсхолдеры win:
# {name}, {client}, {phone_part}, {payout_line}; digest: {name} + счётчики.

# WIN-пуш: клиент оплатил. Телефон клиента показываем (правка Николь 2026-06-02 —
# осознанное ПД-решение: партнёр сам привёл клиента, номер у него и так есть).
# Выплата — после онбординга клиента и получения от него документов.
WIN_TEXT = {
    "ru": ("{name}, отличная новость! Ваш клиент {client}{phone_part} оплатил "
           "и теперь с ONCOUNT.\n\n"
           "{payout_line}\n\n"
           "Полная история по клиенту — в вашем кабинете ONCOUNT."),
    "en": ("{name}, great news! Your client {client}{phone_part} has paid "
           "and is now with ONCOUNT.\n\n"
           "{payout_line}\n\n"
           "The full client history is in your ONCOUNT dashboard."),
}
WIN_PAYOUT_WITH_DATE = {
    "ru": ("Ожидаемая дата выплаты вам — {date}, после того как клиент пройдёт "
           "онбординг. Сейчас ждём от него документы."),
    "en": ("Your expected payout date — {date}, once the client completes "
           "onboarding. We're currently waiting for their documents."),
}
WIN_PAYOUT_NO_DATE = {
    "ru": ("Выплата вам — после того как клиент пройдёт онбординг. Сейчас ждём "
           "от него документы."),
    "en": ("Your payout — once the client completes onboarding. We're currently "
           "waiting for their documents."),
}

# DIGEST: недельная/месячная сводка. Тело — только агрегаты по всем заявкам
# партнёра (без имён клиентов — ПД). Один и тот же текст для недели и месяца.
DIGEST_HEAD = {
    "ru": "{name}, добрый день!\nКоротко, что нового по вашим клиентам за неделю:",
    "en": "{name}, good afternoon!\nA quick update on your clients this week:",
}
DIGEST_BODY = {
    "ru": "{in_progress} - в работе\n{won} - оплатил\n{lost} - отказ\n{total} - всего",
    "en": "{in_progress} - in progress\n{won} - paid\n{lost} - declined\n{total} - total",
}
DIGEST_CLOSE = {
    "ru": ("Ждём от вас новые заявки.\n"
           "Полная картина по каждому клиенту и тексты для рассылок — "
           "в вашем партнёрском кабинете ONCOUNT."),
    "en": ("We're waiting for your new referrals.\n"
           "The full picture for every client and ready-to-send texts — "
           "in your ONCOUNT partner dashboard."),
}


# ─── Язык / дата выплаты ─────────────────────────────────────────────────────
def _plang(partner: Partner) -> str:
    return "en" if getattr(partner, "lang", None) == "en" else "ru"


def _greet_name(partner: Partner, lang: str) -> str:
    """Имя для обращения в рассылках — ТОЛЬКО имя, без фамилии и номера
    (решение Николь 2026-06-03). Источник (first_name / kommo_agent_name) часто
    приходит из Kommo как «Zhanara Issagaliyeva 0072» — берём первое слово,
    не являющееся числовым кодом. Если ничего пригодного нет — обезличенный fallback."""
    raw = (partner.first_name or partner.kommo_agent_name or "").strip()
    for token in raw.split():
        cleaned = token.strip(".,").replace("-", "")
        if cleaned and not cleaned.isdigit():
            return token.strip(".,")
    return "партнёр" if lang == "ru" else "partner"


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


# ─── Адаптивная частота digest ───────────────────────────────────────────────
DIGEST_WEEKLY_WINDOW = timedelta(days=7)   # прислал заявку за неделю → недельные итоги
DIGEST_MONTHLY_GAP = timedelta(days=28)    # иначе — не чаще раза в ~месяц


def _sent_lead_this_week(session: Session, partner_id: int, now: datetime) -> bool:
    """Прислал ли партнёр хоть одну заявку за последнюю неделю (Lead.created_at).
    Да → шлём недельные итоги; нет → партнёр в месячном режиме (нудж «ждём заявки»)."""
    window = now - DIGEST_WEEKLY_WINDOW
    return (session.query(Lead)
            .filter(Lead.partner_id == partner_id, Lead.created_at >= window)
            .first()) is not None


def _last_digest_at(session: Session, partner_id: int) -> datetime | None:
    rec = (session.query(NotificationAttempt)
           .filter(NotificationAttempt.partner_id == partner_id,
                   NotificationAttempt.kind == "digest")
           .order_by(NotificationAttempt.created_at.desc())
           .first())
    return rec.created_at if rec else None


# ─── Сборка текстов ──────────────────────────────────────────────────────────
def build_win_text(partner: Partner, lead: Lead, session: Session) -> str:
    """Пуш на оплату клиента. Телефон клиента — в тексте (правка Николь 2026-06-02).
    Выплата — после онбординга клиента и получения документов (см. WIN_PAYOUT_*)."""
    lang = _plang(partner)
    name = _greet_name(partner, lang)
    client = (lead.client_name or "").strip() or ("ваш клиент" if lang == "ru" else "your client")
    # Контакт клиента в скобках: телефон, а если его нет — Telegram (решение Николь
    # 2026-06-03: у kommo-синканных лидов телефон часто пуст, тянем TG-контакт).
    phone = (lead.client_phone or "").strip()
    contact = phone or (lead.client_telegram or "").strip()
    phone_part = f" ({contact})" if contact else ""
    due = payout_due_date(lead, lang)
    if due and due.get("date"):
        payout_line = WIN_PAYOUT_WITH_DATE[lang].format(date=due["date"])
    else:
        payout_line = WIN_PAYOUT_NO_DATE[lang]
    return WIN_TEXT[lang].format(
        name=name, client=client, phone_part=phone_part, payout_line=payout_line
    )


def build_digest_text(partner: Partner, session: Session, now: datetime) -> str:
    """Сводка по заявкам партнёра. Тело — только АГРЕГАТЫ по ВСЕМ его заявкам
    (без имён клиентов — ПД): в работе / оплатил / отказ / всего. Текст один и тот
    же для недельной (активный) и месячной (реактивация) рассылки — частоту решает
    run_weekly_digest, не этот сборщик."""
    lang = _plang(partner)
    rows = session.query(Lead).filter_by(partner_id=partner.id).all()
    in_progress = sum(1 for l in rows if l.status in ("new", "in_progress"))
    won = sum(1 for l in rows if l.status == "won")
    lost = sum(1 for l in rows if l.status == "lost")
    total = len(rows)
    name = _greet_name(partner, lang)
    head = DIGEST_HEAD[lang].format(name=name)
    body = DIGEST_BODY[lang].format(in_progress=in_progress, won=won, lost=lost, total=total)
    return f"{head}\n{body}\n\n{DIGEST_CLOSE[lang]}"


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
    Адаптивная частота (решение Николь 2026-06-02): прислал заявку за неделю →
    недельные итоги в его слот; не прислал → месячный нудж (если с прошлого digest
    прошло ≥28 дней). Идемпотентно: ≤1 digest/день."""
    now = now or datetime.utcnow()
    dubai_weekday = (now + DUBAI_OFFSET).weekday()  # Пн=0 … Вс=6
    # Только партнёры-агенты, КОТОРЫЕ УЖЕ ЗАХОДИЛИ В КАБИНЕТ (last_login_at):
    # digest — инструмент удержания для пользователей кабинета, необонбординным
    # агентам холодную рассылку не шлём ([[feedback_no_agent_outreach_yet]]).
    agents = (session.query(Partner)
              .filter(Partner.kommo_agent_enum_id.isnot(None),
                      Partner.last_login_at.isnot(None))
              .all())
    sent = monthly_skip = skipped_today = 0
    for p in agents:
        if p.id % 7 != dubai_weekday:
            continue
        if _digest_already_today(session, p.id, now):
            skipped_today += 1
            continue
        # Не присылал заявок на этой неделе — месячный режим (нудж не чаще ~раза в месяц).
        if not _sent_lead_this_week(session, p.id, now):
            last = _last_digest_at(session, p.id)
            if last is not None and (now - last) < DIGEST_MONTHLY_GAP:
                monthly_skip += 1
                continue
        send_notification(p, build_digest_text(p, session, now), "digest", session, now=now)
        sent += 1
    res = {"weekday": dubai_weekday, "sent": sent, "monthly_skip": monthly_skip,
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
