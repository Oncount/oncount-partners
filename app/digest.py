"""Telegram-дайджест партнёру 2×/месяц (5 и 20 числа). Фаза 4.

Формат-эталон утверждён Николь (см. память reference_partner_digest_template).
Данные берём из локального Lead (его наполняет app/kommo_sync). Шлём только агентам,
у кого есть telegram_id (вошли в бот). ПРЕДОХРАНИТЕЛЬ: реальная отправка только при
settings.DIGEST_ENABLED. По умолчанию dry — складывает превью в лог, в сеть не ходит.
"""
from __future__ import annotations

import logging

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import Lead, Partner

log = logging.getLogger("oncount.digest")

MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь",
          "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]
EXP_LOW, EXP_HIGH = 300, 1000


def _commission_usd(lead: Lead) -> int:
    """Оценка комиссии по оплаченному лиду (как в утверждённом образце).
    Точная сумма — будущий шаг (журнал комиссий Excel «Fee AED»)."""
    svc = (lead.client_name or "").lower()
    price = float(lead.amount_aed or 0)
    if any(k in svc for k in ("visa", "виз", "golden")):
        return 600
    if any(k in svc for k in ("bank", "счет", "счёт", "account", "company", "компан", "setup", "регистрац")):
        return 1000
    if price > 0:
        return round(price * 0.30)
    return 0


def build_digest(partner: Partner, session: Session) -> str | None:
    """Собрать текст дайджеста для агента из локальных Lead. None — если лидов нет."""
    rows = session.query(Lead).filter_by(partner_id=partner.id).order_by(Lead.created_at.desc()).all()
    if not rows:
        return None
    total = len(rows)
    won = [l for l in rows if l.status == "won"]
    opn = [l for l in rows if l.status in ("new", "in_progress")]
    paid = sum(_commission_usd(l) for l in won)
    name = partner.kommo_agent_name or partner.first_name or "партнёр"
    month = MONTHS[__import__("datetime").datetime.utcnow().month - 1]

    def emoji(l: Lead) -> str:
        return "✅ оплачено" if l.status == "won" else "✖️ отказ" if l.status == "lost" else "⏳ в работе"

    lines = [
        f"Бодрый и продуктивный день, партнер, {name}",
        "",
        f"🔔 ONCOUNT — отчёт за {month}",
        "",
        f"📊 Лидов всего: {total}",
        f"⏳ в работе: {len(opn)}",
        f"✅ оплат: {len(won)}",
        f"💰 Ожидаемое вознаграждение: ${total * EXP_LOW:,} – ${total * EXP_HIGH:,}",
        f"Выплачено уже ${paid:,}",
        "",
        "Ваши лиды:",
    ]
    for l in rows[:12]:
        lines.append(f"• {(l.client_name or ('#' + str(l.kommo_lead_id)))[:40]} — {emoji(l)}")
    if total > 12:
        lines.append(f"…ещё {total - 12}")
    lines += [
        "Если не все учтены — пришлите номера телефонов, проверю по базе.",
        "",
        "Ждём ещё от Вас клиентов на бухгалтерский сервис в ОАЭ, заработаем вам вознаграждение.",
        "В личном кабинете свежие партнёрские ссылки и посты для рассылок.",
    ]
    return "\n".join(lines)


def _send_telegram(chat_id: int, text: str) -> bool:
    url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage"
    try:
        r = httpx.post(url, json={"chat_id": chat_id, "text": text}, timeout=15)
        return r.status_code < 400
    except httpx.HTTPError as exc:
        log.error("digest send fail to %s: %s", chat_id, exc)
        return False


def send_digests(dry: bool = True) -> dict:
    """Разослать дайджест агентам с telegram_id. dry=True — только превью в лог."""
    session = SessionLocal()
    sent = skipped_no_tg = no_leads = 0
    try:
        agents = (session.query(Partner)
                  .filter(Partner.kommo_agent_enum_id.isnot(None),
                          Partner.telegram_id.isnot(None))
                  .all())
        # тех, кто без telegram_id (не в боте) — на доинвайт
        not_in_bot = (session.query(Partner)
                      .filter(Partner.kommo_agent_enum_id.isnot(None),
                              Partner.telegram_id.is_(None)).count())
        for p in agents:
            text = build_digest(p, session)
            if not text:
                no_leads += 1
                continue
            if dry:
                log.info("DIGEST[dry] → %s:\n%s", p.telegram_id, text)
                sent += 1
            else:
                if _send_telegram(p.telegram_id, text):
                    sent += 1
        return {"sent": sent, "no_leads": no_leads, "not_in_bot": not_in_bot, "dry": dry}
    finally:
        session.close()


def scheduled_digest() -> None:
    """Точка для APScheduler (5 и 20 числа). Шлёт по-настоящему только при DIGEST_ENABLED."""
    res = send_digests(dry=not settings.DIGEST_ENABLED)
    log.info("scheduled_digest: %s", res)
