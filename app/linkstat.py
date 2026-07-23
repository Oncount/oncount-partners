"""Трекинг переходов по персональным ссылкам агентов (план 2026-07-23), Фаза 1.

Клик = вход ЧЕЛОВЕКА по публичной ссылке агента: лендинг-квиз (/consultation, /mk,
/guide/*) или редирект в чат/бот (/ct, /cw, /mt, /mw, /p). Недостающая координата
аналитики — QuizSubmission ловит ЛИДА, а LinkClick — ПЕРЕХОД; вместе дают конверсию
и сигнал «ссылка перестала собирать переходы».

Запись СИНХРОННАЯ best-effort (решение после «разрушь план»): на объёме десятки/день
буфер (как у app/usage.py) избыточен и МЕНЕЕ надёжен — теряет пачку при рестарте
Railway/краше, а короткий INSERT в своей сессии под try/except не блокирует и не
роняет ответ. Никакого буфера/Lock/фонового флаша — меньше кода и гонок (bus factor 1).

ПД-минимизация («опасная тройка»): в БД пишем ТОЛЬКО контент + канал + ref_slug +
время. НЕ пишем IP, query-строку (там бывают токены входа), User-Agent, сырой ввод.
User-Agent читаем ЗДЕСЬ, в памяти, лишь чтобы отсеять превью-краулеры мессенджеров и
self-пробу монитора здоровья — в таблицу он не попадает.
"""
from __future__ import annotations

import logging

_log = logging.getLogger("oncount.linkstat")

# Что за ссылкой (ось «какой чек-лист / мастер-класс»). Стабильные ключи — в отчёте
# атрибуции (main.build_attribution) маппятся на event_slug лендинга.
CONTENT_KEYS: dict[str, str] = {
    "consultation":         "Консультация",
    "mk":                   "Мастер-класс",
    "leadmagnet_corptax":   "Чек-лист 0% Corporate Tax",
    "leadmagnet_5mistakes": "Чек-лист «5 ошибок»",
    "partner_bot":          "Приглашение в бот",
}

# Как открыли ссылку (ось «через что»): страница-квиз / редирект в TG/WA / бот.
SURFACES: set[str] = {"quiz", "tg", "wa", "bot"}

# Контенты-лендинги с квиз-формой (есть сток QuizSubmission → считаем конверсию).
# partner_bot сюда НЕ входит (нет квиз-стока, приход учитывает Referral).
LANDING_KEYS: tuple[str, ...] = ("consultation", "mk", "leadmagnet_corptax", "leadmagnet_5mistakes")


def content_event_slug_map() -> dict[str, str | None]:
    """content_key → event_slug лендинга. Единый источник для отчёта атрибуции
    (main.build_attribution) и монитора (app.health). Импорт конфигов — чтобы
    EVENT_SLUG не хардкодить (правило репо №1). consultation → NULL event_slug."""
    from app import mk_config
    from app import leadmagnet_config as lm
    from app import leadmagnet5_config as lm5
    return {
        "consultation": None,
        "mk": mk_config.EVENT_SLUG,
        "leadmagnet_corptax": lm.EVENT_SLUG,
        "leadmagnet_5mistakes": lm5.EVENT_SLUG,
    }

# Метка self-пробы монитора здоровья (app/health.check_landings_up): приходит в
# User-Agent, клик по ней НЕ пишем (проба ≠ переход человека).
PROBE_UA = "oncount-healthcheck"

# Превью-краулеры мессенджеров/соцсетей: делают server-side GET ссылки ради превью,
# это НЕ человек. Агент вставляет ссылку в WhatsApp/Telegram → превьюшный GET c верным
# ref_slug ДО того, как человек кликнул → фантомный клик. Матч по подстроке в
# User-Agent (lower). Обычный браузерный UA этих токенов не содержит, так что риск
# отсеять живого человека минимален; зато метрика не смещается ботами.
_PREVIEW_BOTS: tuple[str, ...] = (
    "telegrambot", "facebookexternalhit", "facebot", "whatsapp", "slackbot",
    "linkedinbot", "twitterbot", "discordbot", "skypeuripreview", "vkshare",
    "viber", "pinterest", "redditbot", "googlebot", "bingbot", "yandexbot",
    "applebot", "petalbot", "semrushbot", "ahrefsbot",
    "bot", "crawler", "spider", "preview", "monitor",
)


def sanitize_ref(raw: str | None) -> str | None:
    """Реф-метка агента из сырого ввода → безопасное значение для БД.

    Обрезаем до 16 символов (как Partner.ref_slug): без обрезки чужой длинный ?ref=
    или /ct/<длинный> дал бы Postgres «value too long» → 502 (документированный
    инцидент репо, link_key=16). Пусто → None (переход без метки)."""
    if not raw:
        return None
    ref = raw.strip()[:16]
    return ref or None


def is_preview_bot(ua: str | None) -> bool:
    """True, если User-Agent похож на превью-краулер/бот (не человек)."""
    if not ua:
        return False
    low = ua.lower()
    return any(tok in low for tok in _PREVIEW_BOTS)


def record_click(content_key: str, surface: str, ref: str | None, ua: str | None) -> None:
    """Записать переход по ссылке. Синхронно, best-effort.

    Ранний выход: self-проба монитора (PROBE_UA) и превью-краулеры — НЕ пишем.
    Любое исключение (БД недоступна и т.п.) проглатываем и логируем: трекинг НИКОГДА
    не ломает ответ пользователю (ни рендер лендинга, ни редирект в чат)."""
    ua = ua or ""
    low = ua.lower()
    if PROBE_UA in low or is_preview_bot(low):
        return
    if surface not in SURFACES:  # защита от опечатки в call-site (данные всё равно пишем)
        _log.warning("record_click: неизвестный surface %r (content=%s)", surface, content_key)
    ref = sanitize_ref(ref)
    try:
        from app.db import SessionLocal
        from app.models import LinkClick, Partner
        s = SessionLocal()
        try:
            partner_id = None
            if ref:
                row = s.query(Partner.id).filter(Partner.ref_slug == ref).first()
                partner_id = int(row[0]) if row else None
            s.add(LinkClick(
                content_key=content_key, surface=surface,
                ref_slug=ref, partner_id=partner_id,
            ))
            s.commit()
        finally:
            s.close()
    except Exception as exc:  # БД/сеть — не валим ответ, теряем один клик
        _log.warning("record_click fail (%s/%s): %s", content_key, surface, type(exc).__name__)
