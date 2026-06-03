"""Создание лида с квиза — делегирует в наш api (централизация Kommo, 2026-06-03).

Партнёр-сервис НЕ ходит в Kommo напрямую: payload собирается здесь, отправляется в
api (POST /api/partner/leads/consultation), вся работа с CRM (дедуп контакта,
/leads/complex, перенос воронки, примечание) живёт на стороне api. Контракт ответа
неизменен — {status, kommo_lead_id, error} — чтобы вызывающий код не менялся.
"""
from __future__ import annotations

import logging

from app import api_client
from app.quiz_config import QUESTION_TITLES

log = logging.getLogger("oncount.kommo_lead")


def create_consultation_lead(
    *,
    name: str | None,
    phone_norm: str,
    answers: dict | None = None,
    agent_enum_id: int | None = None,
    utm: dict | None = None,
    ref_slug: str | None = None,
    lead_prefix: str = "Квиз-консультация",
    lead_tag: str = "quiz",
    note_intro: str = "Заявка с квиз-лендинга /consultation.",
    question_titles: dict[str, str] | None = None,
) -> dict:
    """Отправить заявку в api для создания сделки в Kommo. Возвращает
    {status, kommo_lead_id, error}; 'dry' если api не настроен. Никогда не бросает."""
    payload = {
        "name": name,
        "phone": phone_norm,
        "answers": answers or {},
        "agent_enum_id": agent_enum_id,
        "utm": utm or {},
        "ref_slug": ref_slug,
        "lead_prefix": lead_prefix,
        "lead_tag": lead_tag,
        "note_intro": note_intro,
        "question_titles": question_titles or QUESTION_TITLES,
    }
    result = api_client.kommo_create_consultation_lead(payload)
    log.info("consultation lead via api status=%s kommo_id=%s agent_enum=%s",
             result.get("status"), result.get("kommo_lead_id"), agent_enum_id)
    return result
