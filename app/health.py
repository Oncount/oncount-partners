"""Мониторинг здоровья персональных ссылок агентов (план 2026-07-23, Фаза 3).

Две природы «сломалось», разделены сознательно (см. «разрушь план»):

1. ОДНОЗНАЧНАЯ ПОЛОМКА → алерт Николь в TG (гейт settings.LINK_HEALTH_ALERTS):
   - лендинг отдаёт 5xx/404 (self-проба через 127.0.0.1, НЕ WEBAPP_URL);
   - битый конфиг целей редиректов (пустой/кривой CONTACT_TG_USERNAME / CONTACT_WA_NUMBER,
     нет URL у PDF лид-магнитов) — редиректы всегда 302, поэтому 5xx/404 такую поломку НЕ ловит.
2. СТАТИСТИЧЕСКИЙ СИГНАЛ (перестало собирать переходы / конверсия просела) — на объёме
   десятки/день ловит штатную ночную паузу, а не поломку, поэтому по умолчанию ТОЛЬКО виден
   в /admin (гейт отдельным settings.LINK_HEALTH_STATS_ALERTS, тоже default off).

Канал алерта — прямой TG Николь (как _notify_admin_new_quiz): внутренний, поэтому
NOTIFICATIONS_LIVE его не гейтит; свои предохранители default off. Дедуп: не чаще одного
алерта на issue_key за 24ч, и строку HealthAlert пишем ТОЛЬКО после подтверждённой отправки.

ПД: наружу (Николь) уходят только наши агрегаты и служебные факты — ни имён, ни телефонов
клиентов.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

import httpx

from app import linkstat
from app.config import settings
from app.models import HealthAlert, LinkClick, QuizSubmission

log = logging.getLogger("oncount.health")

# Публичные лендинги с формой — их пробим на доступность.
LANDING_PATHS: tuple[str, ...] = ("/consultation", "/mk", "/guide/corp-tax", "/guide/5-mistakes")

# Правила Telegram-username (4–32 символа, буквы/цифры/подчёркивание).
_TG_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{4,32}$")

# Последний прогон джоба — для панели /admin (в БД сводку не храним, только дедуп-факты).
LAST_RUN: dict = {}


# ─── Транспорт алерта (внутренний канал Николь) ──────────────────────────────
def alert_admin(text: str) -> bool:
    """Отправить алерт Николь в её Telegram через бота. best-effort, возвращает успех."""
    if not settings.BOT_TOKEN:
        return False
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage",
            json={"chat_id": settings.ADMIN_TG_ID, "text": text},
            timeout=10,
        )
        return r.status_code < 400
    except Exception as exc:  # сеть/SDK — не валим джоб
        log.warning("alert_admin failed: %s", type(exc).__name__)
        return False


# ─── Детекторы поломки (алертят) ─────────────────────────────────────────────
def probe_base() -> str:
    """База для self-пробы лендингов: http://127.0.0.1:$PORT. НЕ WEBAPP_URL —
    тот в дефолте localhost:8000 и дал бы вечный ложный «лендинг лежит»."""
    return f"http://127.0.0.1:{settings.HEALTH_PROBE_PORT}"


def classify_up(status: int | None) -> bool:
    """None (нет ответа) / 5xx / 404 → лежит; всё прочее (200/301/302/429…) → жив.
    429 = живой (rate-limit ответил), 3xx = штатный редирект-лендинг."""
    if status is None:
        return False
    return not (status >= 500 or status == 404)


def check_landings_up(now: datetime | None = None, http_get=None) -> list[dict]:
    """Пробит 4 лендинга через probe_base(). Проба помечена PROBE_UA (record_click
    её игнорирует), follow_redirects=False. http_get(url)->status инъектируется в тестах."""
    base = probe_base()
    out = []
    for path in LANDING_PATHS:
        status: int | None = None
        try:
            if http_get is not None:
                status = http_get(base + path)
            else:
                r = httpx.get(base + path,
                              headers={"user-agent": linkstat.PROBE_UA},
                              follow_redirects=False, timeout=8)
                status = r.status_code
        except Exception:
            status = None
        out.append({"path": path, "status": status, "ok": classify_up(status)})
    return out


def check_targets() -> list[dict]:
    """Конфиг-санити целей редиректов: то, что 5xx/404-проба увидеть не может.
    Ловит РЕАЛЬНУЮ поломку (пустой/кривой контакт, нет PDF-URL). Живой HTTP-запрос
    к внешним целям (t.me, Google Drive) в v1 НЕ делаем — их 403/302 дают ложные
    срабатывания; это кандидат в v2."""
    out: list[dict] = []
    tg = (settings.CONTACT_TG_USERNAME or "").lstrip("@")
    out.append({"name": "Telegram-контакт", "ok": bool(_TG_USERNAME_RE.match(tg)),
                "detail": f"username='{tg or '—'}'"})
    wa = re.sub(r"\D", "", settings.CONTACT_WA_NUMBER or "")
    out.append({"name": "WhatsApp-номер", "ok": 8 <= len(wa) <= 15,
                "detail": f"цифр={len(wa)}"})
    try:
        from app import leadmagnet_config as lm
        from app import leadmagnet5_config as lm5
        for label, url in (("PDF 0% Corporate Tax", getattr(lm, "GUIDE_PDF_URL", "")),
                           ("PDF «5 ошибок»", getattr(lm5, "GUIDE_PDF_URL", ""))):
            ok = bool(url) and str(url).startswith("http")
            out.append({"name": label, "ok": ok, "detail": "задан" if ok else "нет URL"})
    except Exception:
        pass
    return out


# ─── Сигналы (в админке; алертят только при LINK_HEALTH_STATS_ALERTS) ─────────
def compute_signals(session, now: datetime | None = None) -> dict:
    """Чисто по БД (без HTTP): затухшие ссылки, провал конверсии, распределение
    kommo_status. Используется и джобом, и живьём в /admin."""
    from sqlalchemy import func
    now = now or datetime.utcnow()
    ev_map = linkstat.content_event_slug_map()
    stale_since = now - timedelta(hours=settings.LINK_STALE_HOURS)
    base_since = now - timedelta(days=settings.LINK_BASELINE_DAYS)

    def _clicks(ck, since):
        return (session.query(func.count(LinkClick.id))
                .filter(LinkClick.content_key == ck, LinkClick.surface == "quiz",
                        LinkClick.created_at >= since).scalar()) or 0

    def _leads(ck, since):
        # event_slug == None у consultation → SQLAlchemy отдаёт IS NULL.
        return (session.query(func.count(QuizSubmission.id))
                .filter(QuizSubmission.event_slug == ev_map[ck],
                        QuizSubmission.created_at >= since).scalar()) or 0

    stale: list[dict] = []
    conv_drop: list[dict] = []
    for ck in linkstat.LANDING_KEYS:
        baseline = _clicks(ck, base_since)
        recent = _clicks(ck, stale_since)
        label = linkstat.CONTENT_KEYS.get(ck, ck)
        if baseline >= settings.LINK_MIN_BASELINE_CLICKS and recent == 0:
            stale.append({"content": ck, "label": label, "baseline": baseline})
        if recent >= settings.LINK_MIN_BASELINE_CLICKS and _leads(ck, stale_since) == 0:
            conv_drop.append({"content": ck, "label": label, "recent_clicks": recent})

    kwin = now - timedelta(hours=settings.KOMMO_FAIL_WINDOW_HOURS)
    kommo: dict[str, int] = {}
    for st, n in (session.query(QuizSubmission.kommo_status, func.count(QuizSubmission.id))
                  .filter(QuizSubmission.created_at >= kwin)
                  .group_by(QuizSubmission.kommo_status).all()):
        kommo[st] = n

    return {"stale": stale, "conv_drop": conv_drop, "kommo": kommo}


# ─── Дедуп + прогон ──────────────────────────────────────────────────────────
def _alerted_today(session, issue_key: str, now: datetime) -> bool:
    """Слали ли уже этот issue_key за последние 24ч (скользящее окно)."""
    since = now - timedelta(hours=24)
    return (session.query(HealthAlert)
            .filter(HealthAlert.issue_key == issue_key, HealthAlert.created_at >= since)
            .first()) is not None


def run_health_check(session, now: datetime | None = None, dry: bool = False) -> dict:
    """Прогон монитора. Считает всё, шлёт TG только по НОВЫМ (не за 24ч) проблемам,
    у которых включён соответствующий гейт. Возвращает summary для /admin и лога.
    dry=True — ничего не шлём (для тестов). Строку дедупа пишем ТОЛЬКО после успешной
    отправки — иначе транзиентный сбой заглушил бы инцидент на сутки."""
    global LAST_RUN
    now = now or datetime.utcnow()
    landings = check_landings_up(now)
    targets = check_targets()
    signals = compute_signals(session, now)

    breakage: list[tuple[str, str]] = []
    for l in landings:
        if not l["ok"]:
            code = l["status"] if l["status"] is not None else "нет ответа"
            breakage.append((f"landings_down:{l['path']}:{l['status']}",
                             f"🔴 Лендинг {l['path']} недоступен (код {code})"))
    for t in targets:
        if not t["ok"]:
            breakage.append((f"target_bad:{t['name']}",
                             f"🔴 Цель ссылки «{t['name']}» настроена неверно ({t['detail']})"))

    stats: list[tuple[str, str]] = []
    for st in signals["stale"]:
        stats.append((f"stale:{st['content']}",
                      f"⚠️ «{st['label']}» перестал собирать переходы: 0 за "
                      f"{settings.LINK_STALE_HOURS}ч (в базлайне ~{st['baseline']} за "
                      f"{settings.LINK_BASELINE_DAYS}д)"))
    for cd in signals["conv_drop"]:
        stats.append((f"conv_drop:{cd['content']}",
                      f"⚠️ «{cd['label']}»: {cd['recent_clicks']} переходов, 0 заявок за "
                      f"{settings.LINK_STALE_HOURS}ч — проверьте форму"))

    alertable = [(k, line, settings.LINK_HEALTH_ALERTS) for (k, line) in breakage]
    alertable += [(k, line, settings.LINK_HEALTH_STATS_ALERTS) for (k, line) in stats]

    sent_keys: list[str] = []
    if not dry:
        fresh = [(k, line) for (k, line, gate) in alertable
                 if gate and not _alerted_today(session, k, now)]
        if fresh:
            text = "🔔 ONCOUNT — мониторинг ссылок\n\n" + "\n".join(line for _, line in fresh)
            if alert_admin(text):
                for k, _ in fresh:
                    session.add(HealthAlert(issue_key=k, created_at=now))
                session.commit()
                sent_keys = [k for k, _ in fresh]

    summary = {
        "ran_at": now, "landings": landings, "targets": targets, "signals": signals,
        "breakage": [line for _, line in breakage], "stats": [line for _, line in stats],
        "alerts_sent": sent_keys,
        "alerts_enabled": settings.LINK_HEALTH_ALERTS,
        "stats_alerts_enabled": settings.LINK_HEALTH_STATS_ALERTS,
    }
    LAST_RUN = summary
    log.info("health_check: landings_down=%d targets_bad=%d stale=%d conv_drop=%d sent=%d dry=%s",
             sum(1 for x in landings if not x["ok"]),
             sum(1 for x in targets if not x["ok"]),
             len(signals["stale"]), len(signals["conv_drop"]), len(sent_keys), dry)
    return summary


def health_check_job() -> None:
    """Точка APScheduler (каждые 6ч). Открывает свою сессию."""
    from app.db import SessionLocal
    session = SessionLocal()
    try:
        run_health_check(session)
    finally:
        session.close()
