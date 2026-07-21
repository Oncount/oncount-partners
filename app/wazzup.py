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

import httpx

from app.auth import normalize_phone
from app.config import settings

log = logging.getLogger("oncount.wazzup")

WAZZUP_ENDPOINT = "https://api.wazzup24.com/v3/message"


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

    try:
        resp = httpx.post(
            WAZZUP_ENDPOINT,
            headers={"Authorization": f"Bearer {settings.WAZZUP_API_KEY}"},
            json={
                "channelId": settings.WAZZUP_CHANNEL_ID,
                "chatType": "whatsapp",
                "chatId": norm,
                "text": _text(code, lang),
            },
            timeout=10.0,
        )
        if resp.status_code >= 400:
            log.error("Wazzup вернул %s для %s: %s", resp.status_code, _mask(norm), resp.text[:300])
            return False
        return True
    except httpx.HTTPError as exc:
        log.error("Wazzup недоступен для %s: %s", _mask(norm), exc)
        return False


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

    try:
        resp = httpx.post(
            WAZZUP_ENDPOINT,
            headers={"Authorization": f"Bearer {settings.WAZZUP_API_KEY}"},
            json={
                # channel_id → клиентские сообщения (подтверждения/PDF) с продажного
                # номера; без него — сервисный канал кодов входа (WAZZUP_CHANNEL_ID).
                "channelId": channel_id or settings.WAZZUP_CHANNEL_ID,
                "chatType": "whatsapp",
                "chatId": norm,
                "text": text,
            },
            timeout=10.0,
        )
        if resp.status_code >= 400:
            log.error("Wazzup вернул %s для %s: %s", resp.status_code, _mask(norm), resp.text[:300])
            return False
        return True
    except httpx.HTTPError as exc:
        log.error("Wazzup недоступен для %s: %s", _mask(norm), exc)
        return False
