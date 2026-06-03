"""Тонкий клиент к нашему api-сервису (NestJS). Единая точка выхода для Kommo и
Wazzup: партнёр-сервис БОЛЬШЕ НЕ ходит в kommo.com / api.wazzup24.com напрямую —
все такие вызовы идут через api (правило централизации, 2026-06-03).

Аутентификация к api пока НЕ добавлена (решение: позже). База — settings.ONCOUNT_API_URL.
ВАЖНО: api монтирует все маршруты под глобальным префиксом /api (см. CONTRIBUTING.md),
поэтому пути здесь включают /api. Сетевые ошибки НЕ пробрасываются вызывающему —
возвращаем нейтральный результат, чтобы приём заявки/вход не падали из-за api.
"""
from __future__ import annotations

import logging

import httpx

from app.config import settings

log = logging.getLogger("oncount.api_client")

# Приём заявки/вход не должны висеть на медленном api — короткий таймаут,
# при провале вызывающий получает безопасный дефолт.
_TIMEOUT = 12


def _base() -> str:
    return (settings.ONCOUNT_API_URL or "").rstrip("/")


def _configured() -> bool:
    return bool(_base())


def kommo_create_consultation_lead(payload: dict) -> dict:
    """POST /api/kommo/leads/consultation. → {status, kommo_lead_id, error}.
    Если api не настроен — {'status': 'dry', ...} (как прежний QUIZ_KOMMO_LIVE off)."""
    if not _configured():
        return {"status": "dry", "kommo_lead_id": None, "error": "api_not_configured"}
    try:
        r = httpx.post(f"{_base()}/api/kommo/leads/consultation",
                       json=payload, timeout=_TIMEOUT)
        if r.status_code >= 300:
            log.error("api consultation lead failed: HTTP %s", r.status_code)
            return {"status": "failed", "kommo_lead_id": None, "error": f"http_{r.status_code}"}
        data = r.json()
        return {
            "status": data.get("status", "sent"),
            "kommo_lead_id": data.get("kommo_lead_id"),
            "error": data.get("error"),
        }
    except Exception as exc:  # сеть/JSON — не валим приём заявки
        log.error("api consultation lead error: %s", type(exc).__name__)
        return {"status": "failed", "kommo_lead_id": None, "error": type(exc).__name__}


def kommo_agent_leads(pipeline_id: int) -> list[dict] | None:
    """GET /api/kommo/agent-leads. → плоский список лидов воронки агентов, или None
    при ошибке/неконфигурации (вызывающий трактует None как «пропустить синк»).

    Контракт (плоская форма, api сам маппит из Kommo): каждый элемент —
    {kommo_lead_id, agent_enum_id, status, amount_aed, client_name}, где status уже
    приведён к 'won' | 'lost' | 'in_progress'."""
    if not _configured():
        return None
    try:
        r = httpx.get(f"{_base()}/api/kommo/agent-leads",
                      params={"pipeline_id": pipeline_id}, timeout=30)
        if r.status_code >= 300:
            log.warning("api agent-leads failed: HTTP %s", r.status_code)
            return None
        data = r.json()
        return data.get("leads", data) if isinstance(data, dict) else data
    except Exception as exc:
        log.warning("api agent-leads error: %s", type(exc).__name__)
        return None


def kommo_agent_enums() -> list[dict] | None:
    """GET /api/kommo/agent-enums. → [{id, value}, …] поля «ID AGENT», или None."""
    if not _configured():
        return None
    try:
        r = httpx.get(f"{_base()}/api/kommo/agent-enums", timeout=30)
        if r.status_code >= 300:
            log.warning("api agent-enums failed: HTTP %s", r.status_code)
            return None
        data = r.json()
        return data.get("enums", data) if isinstance(data, dict) else data
    except Exception as exc:
        log.warning("api agent-enums error: %s", type(exc).__name__)
        return None


def wazzup_send(phone: str, text: str) -> bool:
    """POST /api/wazzup/messages {phone, text}. → True если api подтвердил отправку.
    Неконфигурация/ошибка → False (вызывающий уже учитывает dev/предохранители)."""
    if not _configured():
        log.warning("ONCOUNT_API_URL не задан → WhatsApp не отправлен")
        return False
    try:
        r = httpx.post(f"{_base()}/api/wazzup/messages",
                       json={"phone": phone, "text": text}, timeout=10.0)
        if r.status_code >= 400:
            log.error("api wazzup send returned %s", r.status_code)
            return False
        data = r.json()
        return bool(data.get("sent", True))
    except httpx.HTTPError as exc:
        log.error("api wazzup send unavailable: %s", type(exc).__name__)
        return False
