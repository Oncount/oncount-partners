"""Отправка кода входа / текста в WhatsApp — через наш api (централизация Wazzup,
2026-06-03).

Партнёр-сервис БОЛЬШЕ НЕ ходит в api.wazzup24.com напрямую: текст формируется здесь,
отправка делегируется в api (POST /api/wazzup/messages) через app.api_client. Сам
канал/ключ Wazzup живёт на стороне api.

Предохранители (опасная тройка — персональные данные + отправка наружу) остаются
на стороне партнёра:
- Пустой ONCOUNT_API_URL → dev-режим: НИЧЕГО не шлём в сеть.
- WAZZUP_TEST_ONLY_NUMBER задан → шлём ТОЛЬКО на этот номер, остальные молча
  пропускаем (предохранитель на тесте, пока канал не подтверждён живьём).
- Сам код и полный телефон в логи НЕ пишем.
"""
from __future__ import annotations

import logging

from app import api_client
from app.auth import normalize_phone
from app.config import settings

log = logging.getLogger("oncount.wazzup")


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

    if not settings.ONCOUNT_API_URL:
        log.warning("ONCOUNT_API_URL не задан → код не отправлен (dev), %s", _mask(norm))
        return True

    # Предохранитель теста: пока канал не подтверждён живьём, шлём только на свой номер.
    test_only = normalize_phone(settings.WAZZUP_TEST_ONLY_NUMBER)
    if test_only and norm != test_only:
        log.info("WAZZUP test-guard: пропуск %s (разрешён только тестовый номер)", _mask(norm))
        return True

    return api_client.wazzup_send(norm, _text(code, lang))


def send_wa_text(phone: str, text: str) -> bool:
    """Отправить ПРОИЗВОЛЬНЫЙ текст в WhatsApp (Фаза K: digest / win-пуш).

    Тот же транспорт и те же предохранители, что и у send_wa_code, но текст
    приходит готовым извне (банк формулировок в app/notifications.py). Возвращает
    True при успешной отправке, False при сетевой/HTTP-ошибке.

    ВАЖНО: эта функция делегирует отправку в api ВСЕГДА, когда задан ONCOUNT_API_URL
    и номер прошёл test-guard. Главный предохранитель Фазы K (NOTIFICATIONS_LIVE)
    живёт ВЫШЕ — в send_notification: при live=false сюда вообще не заходим. Здесь —
    только WA-специфичные гарды (dev + test-only)."""
    norm = normalize_phone(phone)
    if not norm:
        log.warning("WAZZUP send_wa_text: пустой/мусорный номер — пропуск")
        return False

    if not settings.ONCOUNT_API_URL:
        log.warning("ONCOUNT_API_URL не задан → текст не отправлен (dev), %s", _mask(norm))
        return False

    # Предохранитель теста: пока канал не подтверждён живьём, шлём только на свой номер.
    test_only = normalize_phone(settings.WAZZUP_TEST_ONLY_NUMBER)
    if test_only and norm != test_only:
        log.info("WAZZUP test-guard: пропуск %s (разрешён только тестовый номер)", _mask(norm))
        return False

    return api_client.wazzup_send(norm, text)
