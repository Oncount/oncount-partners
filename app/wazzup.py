"""Отправка кода входа в WhatsApp через Wazzup24 API (план 2026-05-27, Фаза 4).

ПРИМЕЧАНИЕ (2026-06-03): централизация Kommo уже выполнена (см. app/api_client.py),
а централизация Wazzup запланирована СЛЕДУЮЩИМ PR — отправка WhatsApp переедет на
api (POST /api/partner/notify, шаблонные типы). Пока этого endpoint нет, отправка
идёт НАПРЯМУЮ в Wazzup24, как раньше.

Тонкий слой поверх httpx (как app/email.py) — без SDK. Wazzup24 v3:
POST https://api.wazzup24.com/v3/message
  headers: Authorization: Bearer <WAZZUP_API_KEY>
  json:    {channelId, chatType:"whatsapp", chatId:<digits>, text}

Предохранители (опасная тройка — персональные данные + отправка наружу):
- Пустой WAZZUP_API_KEY/WAZZUP_CHANNEL_ID → dev-режим: НИЧЕГО не шлём в сеть.
- WAZZUP_TEST_ONLY_NUMBER задан → шлём ТОЛЬКО на этот номер, остальные молча
  пропускаем (предохранитель на тесте, пока канал не подтверждён живьём).
- Сам код и полный телефон в логи НЕ пишем.
"""
from __future__ import annotations

import logging
import time

import httpx

from app.auth import normalize_phone
from app.config import settings

log = logging.getLogger("oncount.wazzup")

WAZZUP_ENDPOINT = "https://api.wazzup24.com/v3/message"
WAZZUP_CHANNELS_ENDPOINT = "https://api.wazzup24.com/v3/channels"

# ─── Резерв канала (2026-07-27) ─────────────────────────────────────────────
# WhatsApp-канал в Wazzup держится на QR и periодически отваливается в qridle:
# 27.07 так легли сразу три номера, и вместе с ними — коды входа в кабинет и
# доставка чек-листов. Поэтому шлём по цепочке: основной канал → резервные из
# WAZZUP_FALLBACK_CHANNEL_IDS. Мёртвый канал пропускаем ДО отправки (состояние
# из /v3/channels, кэш на 5 минут), а на ошибку отправки идём к следующему.
#
# Состояния, при которых канал точно не доставит. Список — «чёрный», а не
# «белый», намеренно: незнакомое состояние лучше попробовать, чем молча не
# отправить код человеку, который ждёт вход.
DEAD_STATES = frozenset({
    "qr", "qridle", "openelsewhere", "disabled", "blocked", "unauthorized",
    "phoneUnavailable", "notEnoughMoney", "foreignphone", "timeout", "conflict",
})
_STATES_TTL = 300.0            # сек; чаще дёргать /v3/channels смысла нет
_states_cache: dict[str, str] = {}
_states_at = 0.0


def _channel_states(force: bool = False) -> dict[str, str]:
    """channelId → state из Wazzup, кэш 5 минут. Сеть недоступна → {} (неизвестно:
    тогда шлём как раньше, вслепую — недоступность Wazzup не должна блокировать)."""
    global _states_cache, _states_at
    if not force and _states_cache and (time.monotonic() - _states_at) < _STATES_TTL:
        return _states_cache
    try:
        resp = httpx.get(
            WAZZUP_CHANNELS_ENDPOINT,
            headers={"Authorization": f"Bearer {settings.WAZZUP_API_KEY}"},
            timeout=10.0,
        )
        if resp.status_code >= 400:
            log.warning("Wazzup /channels вернул %s — состояния каналов неизвестны", resp.status_code)
            return {}
        _states_cache = {c["channelId"]: c.get("state", "") for c in resp.json()}
        _states_at = time.monotonic()
        return _states_cache
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        log.warning("Wazzup /channels недоступен: %s", type(exc).__name__)
        return {}


def _chain(primary: str) -> list[str]:
    """Основной канал + резервные (по порядку, без пустых и дублей)."""
    out = [primary] if primary else []
    for cid in settings.WAZZUP_FALLBACK_CHANNEL_IDS.split(","):
        cid = cid.strip()
        if cid and cid not in out:
            out.append(cid)
    return out


def _send(norm: str, text: str, primary: str, what: str) -> bool:
    """Отправка по цепочке каналов. True — доставлено хотя бы одним каналом.
    `what` — что шлём («код входа» / «текст»), только для лога."""
    chain = _chain(primary)
    states = _channel_states() if len(chain) > 1 else {}
    for i, channel_id in enumerate(chain):
        state = states.get(channel_id)
        if state in DEAD_STATES:
            log.warning("Wazzup: канал %s в состоянии %s — пропуск, пробуем резерв",
                        channel_id[:8], state)
            continue
        try:
            resp = httpx.post(
                WAZZUP_ENDPOINT,
                headers={"Authorization": f"Bearer {settings.WAZZUP_API_KEY}"},
                json={
                    "channelId": channel_id,
                    "chatType": "whatsapp",
                    "chatId": norm,
                    "text": text,
                },
                timeout=10.0,
            )
        except httpx.HTTPError as exc:
            log.error("Wazzup недоступен (%s, канал %s) для %s: %s",
                      what, channel_id[:8], _mask(norm), exc)
            continue
        if resp.status_code < 400:
            if i:
                log.warning("Wazzup: %s ушёл РЕЗЕРВНЫМ каналом %s (основной не сработал)",
                            what, channel_id[:8])
            return True
        log.error("Wazzup вернул %s (%s, канал %s) для %s: %s",
                  resp.status_code, what, channel_id[:8], _mask(norm), resp.text[:300])
        _channel_states(force=True)   # состояние протухло — обновим перед резервом
    log.error("Wazzup: %s НЕ доставлен ни одним каналом (%s) для %s",
              what, ", ".join(c[:8] for c in chain) or "нет каналов", _mask(norm))
    return False


def _mask(phone: str) -> str:
    """Маскирует номер для лога: видны код страны и 2 последние цифры."""
    if len(phone) <= 6:
        return "***"
    return f"{phone[:3]}***{phone[-2:]}"


def _text(code: str, lang: str) -> str:
    if lang == "en":
        return (
            f"Your ONCOUNT partner dashboard sign-in code: {code}\n"
            f"Valid for 10 minutes. If you didn't request it, ignore this message."
        )
    return (
        f"Код для входа в кабинет партнёра ONCOUNT: {code}\n"
        f"Действует 10 минут. Если вы не запрашивали вход — проигнорируйте."
    )


def send_wa_code(phone: str, code: str, lang: str = "ru") -> bool:
    """Отправить 6-значный код в WhatsApp. Возвращает True, если отправлено
    (или dev-режим/предохранитель — поток входа отвечает нейтрально в любом
    случае, анти-энумерация). Сетевые ошибки логируются и НЕ пробрасываются."""
    lang = "en" if lang == "en" else "ru"
    norm = normalize_phone(phone)

    if not settings.WAZZUP_API_KEY or not settings.WAZZUP_CHANNEL_ID:
        log.warning("WAZZUP не настроен → код не отправлен (dev), %s", _mask(norm))
        return True

    # Предохранитель теста: пока канал не подтверждён живьём, шлём только на свой номер.
    test_only = normalize_phone(settings.WAZZUP_TEST_ONLY_NUMBER)
    if test_only and norm != test_only:
        log.info("WAZZUP test-guard: пропуск %s (разрешён только тестовый номер)", _mask(norm))
        return True

    return _send(norm, _text(code, lang), settings.WAZZUP_CHANNEL_ID, "код входа")


def send_wa_text(phone: str, text: str, channel_id: str | None = None) -> bool:
    """Отправить ПРОИЗВОЛЬНЫЙ текст в WhatsApp (Фаза K: digest / win-пуш).

    Тот же транспорт и те же предохранители, что и у send_wa_code, но текст
    приходит готовым извне (банк формулировок в app/notifications.py). Возвращает
    True при успешной отправке, False при сетевой/HTTP-ошибке.

    ВАЖНО: эта функция выполняет реальный сетевой вызов ВСЕГДА, когда задан
    ключ/канал и номер прошёл test-guard. Главный предохранитель Фазы K
    (NOTIFICATIONS_LIVE) живёт ВЫШЕ — в send_notification: при live=false сюда
    вообще не заходим. Здесь — только WA-специфичные гарды (dev + test-only)."""
    norm = normalize_phone(phone)
    if not norm:
        log.warning("WAZZUP send_wa_text: пустой/мусорный номер — пропуск")
        return False

    if not settings.WAZZUP_API_KEY or not settings.WAZZUP_CHANNEL_ID:
        log.warning("WAZZUP не настроен → текст не отправлен (dev), %s", _mask(norm))
        return False

    # Предохранитель теста: пока канал не подтверждён живьём, шлём только на свой номер.
    test_only = normalize_phone(settings.WAZZUP_TEST_ONLY_NUMBER)
    if test_only and norm != test_only:
        log.info("WAZZUP test-guard: пропуск %s (разрешён только тестовый номер)", _mask(norm))
        return False

    # channel_id → клиентские сообщения (подтверждения/PDF) с продажного номера;
    # без него — сервисный канал кодов входа (WAZZUP_CHANNEL_ID). Если канал лежит,
    # _send сам уйдёт на резервный из WAZZUP_FALLBACK_CHANNEL_IDS.
    return _send(norm, text, channel_id or settings.WAZZUP_CHANNEL_ID, "текст")
