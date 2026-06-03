"""Тонкий клиент к нашему api-сервису (NestJS) для доступа к Kommo.

Партнёр-сервис НЕ ходит в kommo.com напрямую — все вызовы Kommo идут через api
(правило централизации, 2026-06-03), на выделенный префикс /api/partner/* под
ключом PARTNER_API_KEY (заголовок x-api-key). Сетевой рубеж — Security Group на
EC2 (см. Documentation/PARTNER_API_SECURITY_DESIGN.md §4).

Wazzup НА ЭТОМ ЭТАПЕ ещё НЕ централизован — отправка WhatsApp идёт напрямую из
app/wazzup.py (следующий PR переведёт её на /api/partner/notify).

База — settings.ONCOUNT_API_URL. Сетевые ошибки НЕ пробрасываются вызывающему —
возвращаем нейтральный результат, чтобы приём заявки/синк не падали из-за api.
"""
from __future__ import annotations

import logging

import httpx

from app.config import settings

log = logging.getLogger("oncount.api_client")

# Приём заявки/синк не должны висеть на медленном api — короткий таймаут,
# при провале вызывающий получает безопасный дефолт.
_TIMEOUT = 12


def _base() -> str:
    return (settings.ONCOUNT_API_URL or "").rstrip("/")


def _configured() -> bool:
    return bool(_base())


def _headers() -> dict:
    # Ключ может быть пуст в dev — тогда api отдаст 401, что мы трактуем как «не
    # настроено» (нейтральный дефолт у вызывающего). В prod ключ обязателен.
    h = {}
    if settings.PARTNER_API_KEY:
        h["x-api-key"] = settings.PARTNER_API_KEY
    return h


def kommo_create_consultation_lead(payload: dict) -> dict:
    """POST /api/partner/leads/consultation.
    → {status, kommo_lead_id, lead_correlation_id, error}.
    Если api не настроен — {'status': 'dry', ...} (как прежний QUIZ_KOMMO_LIVE off)."""
    if not _configured():
        return {
            "status": "dry",
            "kommo_lead_id": None,
            "lead_correlation_id": None,
            "error": "api_not_configured",
        }
    try:
        r = httpx.post(f"{_base()}/api/partner/leads/consultation",
                       json=payload, headers=_headers(), timeout=_TIMEOUT)
        if r.status_code >= 300:
            log.error("api consultation lead failed: HTTP %s", r.status_code)
            return {"status": "failed", "kommo_lead_id": None,
                    "lead_correlation_id": None, "error": f"http_{r.status_code}"}
        data = r.json()
        return {
            "status": data.get("status", "sent"),
            "kommo_lead_id": data.get("kommo_lead_id"),
            "lead_correlation_id": data.get("lead_correlation_id"),
            "error": data.get("error"),
        }
    except Exception as exc:  # сеть/JSON — не валим приём заявки
        log.error("api consultation lead error: %s", type(exc).__name__)
        return {"status": "failed", "kommo_lead_id": None,
                "lead_correlation_id": None, "error": type(exc).__name__}


def kommo_agent_leads(pipeline_id: int) -> list[dict] | None:
    """GET /api/partner/agent-leads. → плоский список лидов воронки агентов, или None
    при ошибке/неконфигурации (вызывающий трактует None как «пропустить синк»).

    Контракт (плоская форма, api сам маппит из Kommo): каждый элемент —
    {kommo_lead_id, agent_enum_id, status, amount_aed, client_name}, где status уже
    приведён к 'won' | 'lost' | 'in_progress'."""
    if not _configured():
        return None
    try:
        r = httpx.get(f"{_base()}/api/partner/agent-leads",
                      params={"pipeline_id": pipeline_id},
                      headers=_headers(), timeout=30)
        if r.status_code >= 300:
            log.warning("api agent-leads failed: HTTP %s", r.status_code)
            return None
        data = r.json()
        return data.get("leads", data) if isinstance(data, dict) else data
    except Exception as exc:
        log.warning("api agent-leads error: %s", type(exc).__name__)
        return None


def kommo_agent_enums() -> list[dict] | None:
    """GET /api/partner/agent-enums. → [{id, value}, …] поля «ID AGENT», или None."""
    if not _configured():
        return None
    try:
        r = httpx.get(f"{_base()}/api/partner/agent-enums",
                      headers=_headers(), timeout=30)
        if r.status_code >= 300:
            log.warning("api agent-enums failed: HTTP %s", r.status_code)
            return None
        data = r.json()
        return data.get("enums", data) if isinstance(data, dict) else data
    except Exception as exc:
        log.warning("api agent-enums error: %s", type(exc).__name__)
        return None
