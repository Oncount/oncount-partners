"""Отправка кода входа в WhatsApp через Wazzup24 API (план 2026-05-27, Фаза 4).

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
