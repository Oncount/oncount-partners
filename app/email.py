"""Тонкий слой отправки транзакционных писем через Resend (план 2026-05-23).

Без CrewAI/SDK — прямой POST на https://api.resend.com/emails через httpx
(httpx уже в зависимостях). Пустой RESEND_API_KEY → dev-режим: ссылка пишется
в лог, сеть не дёргается. Так весь поток входа отлаживается локально без Resend.
"""
from __future__ import annotations

import logging

import httpx

from app.config import settings

log = logging.getLogger("oncount.email")

RESEND_ENDPOINT = "https://api.resend.com/emails"

# Двуязычный шаблон письма со ссылкой входа. {url} подставляется в обе версии.
_SUBJECT = {
    "ru": "Вход в кабинет партнёра ONCOUNT",
    "en": "Sign in to your ONCOUNT partner dashboard",
}
_INTRO = {
    "ru": "Нажми на кнопку ниже, чтобы войти в кабинет партнёра. Ссылка действует 15 минут и сработает один раз.",
    "en": "Click the button below to sign in to your partner dashboard. The link is valid for 15 minutes and works once.",
}
_BTN = {"ru": "Войти в кабинет", "en": "Sign in"}
_IGNORE = {
    "ru": "Если вы не запрашивали вход — просто проигнорируйте это письмо.",
    "en": "If you didn’t request this, just ignore this email.",
}


def _html(url: str, lang: str) -> str:
    return (
        f'<div style="font-family:Arial,Helvetica,sans-serif;max-width:480px;margin:0 auto;'
        f'padding:32px 24px;color:#10463E;">'
        f'<h2 style="margin:0 0 16px;">ONCOUNT</h2>'
        f'<p style="font-size:15px;line-height:1.5;">{_INTRO[lang]}</p>'
        f'<p style="margin:28px 0;">'
        f'<a href="{url}" style="background:#10463E;color:#fff;text-decoration:none;'
        f'padding:14px 28px;border-radius:8px;font-size:16px;display:inline-block;">'
        f'{_BTN[lang]}</a></p>'
        f'<p style="font-size:13px;color:#667;line-height:1.5;">{url}</p>'
        f'<p style="font-size:12px;color:#99a;margin-top:24px;">{_IGNORE[lang]}</p>'
        f'</div>'
    )


def _text(url: str, lang: str) -> str:
    return f"{_INTRO[lang]}\n\n{url}\n\n{_IGNORE[lang]}"


def send_magic_link(to: str, url: str, lang: str = "ru") -> bool:
    """Отправить письмо с магической ссылкой. Возвращает True, если отправлено
    (или dev-режим). Сетевые ошибки логируются и НЕ пробрасываются — роут отвечает
    нейтрально в любом случае (анти-энумерация)."""
    lang = "en" if lang == "en" else "ru"

    if not settings.RESEND_API_KEY:
        # Ссылку входа НЕ логируем (security 2026-05-26): в логах она = готовый
        # доступ в чужой ЛК. Для локальной отладки временно раскомментируй url.
        log.warning("RESEND_API_KEY пуст → письмо не отправлено (dev), ссылка не логируется")
        return True

    try:
        resp = httpx.post(
            RESEND_ENDPOINT,
            headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
            json={
                "from": settings.EMAIL_FROM,
                "to": [to],
                "subject": _SUBJECT[lang],
                "html": _html(url, lang),
                "text": _text(url, lang),
            },
            timeout=10.0,
        )
        if resp.status_code >= 400:
            log.error("Resend вернул %s для %s: %s", resp.status_code, to, resp.text[:300])
            return False
        return True
    except httpx.HTTPError as exc:
        log.error("Resend недоступен для %s: %s", to, exc)
        return False
