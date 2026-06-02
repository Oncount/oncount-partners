"""Создание лида с квиза в Kommo воронку 1.1 (план 2026-06-02).

`POST /leads/complex` — лид + контакт + телефон одним вызовом. Привязка к агенту:
поле «ID AGENT» (#961886) = `Partner.kommo_agent_enum_id`. Дальше существующий
`kommo_sync` (ежечасно) сам подтянет лид и привяжет его к партнёру по этому полю —
отдельной логики привязки не пишем.

ГЛАВНЫЙ ПРЕДОХРАНИТЕЛЬ — settings.QUIZ_KOMMO_LIVE (default false). Пока не "true":
в Kommo НЕ ходим, возвращаем status='dry' (заявка живёт в Postgres + TG-пуш).
id воронки/этапа — из конфига (правило репо №1), сверяются скриптом
scripts/kommo_quiz_discover.js ПЕРЕД снятием гарда.

Безопасность: телефон/имя клиента уходят в НАШ Kommo (не сторонний сервис) —
это и есть назначение заявки. В общий лог пишем только статус и id лида,
не телефон.
"""
from __future__ import annotations

import logging

import httpx

from app.config import settings
from app.quiz_config import QUESTION_TITLES

log = logging.getLogger("oncount.kommo_lead")

# Таймаут на сетевой вызов Kommo: приём заявки не должен висеть на медленном CRM —
# в Postgres запись уже есть, при провале помечаем 'failed' и отвечаем клиенту ok.
_TIMEOUT = 12


def _base() -> str:
    domain = settings.KOMMO_DOMAIN or "primeadvice.kommo.com"
    return f"https://{domain}/api/v4"


def _answers_note(answers: dict | None, utm: dict | None, ref_slug: str | None,
                  *, note_intro: str, question_titles: dict[str, str]) -> str:
    """Человекочитаемое примечание к лиду: ответы квиза + источник трафика."""
    lines: list[str] = [note_intro, ""]
    for qid, title in question_titles.items():
        val = (answers or {}).get(qid)
        if val:
            lines.append(f"• {title} — {val}")
    if ref_slug:
        lines.append("")
        lines.append(f"Реф-метка агента: {ref_slug}")
    utm = {k: v for k, v in (utm or {}).items() if v}
    if utm:
        lines.append("UTM: " + ", ".join(f"{k}={v}" for k, v in utm.items()))
    return "\n".join(lines)


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
    """Создать лид в воронке 1.1. Возвращает {status, kommo_lead_id, error}.

    status: 'dry' (гард off / нет конфига — в сеть не ходили), 'sent' (лид создан),
    'failed' (API/сеть). Никогда не бросает — приём заявки не должен падать из-за CRM.

    lead_prefix/lead_tag/note_intro/question_titles параметризуют лид под событие
    (по умолчанию — квиз /consultation; мастер-класс передаёт свои, план 2026-06-02).
    """
    if question_titles is None:
        question_titles = QUESTION_TITLES
    # Предохранитель + проверка конфига: без него молча НЕ ходим в сеть.
    if not settings.QUIZ_KOMMO_LIVE:
        return {"status": "dry", "kommo_lead_id": None, "error": None}
    if not (settings.KOMMO_TOKEN and settings.QUIZ_KOMMO_PIPELINE_ID
            and settings.QUIZ_KOMMO_STATUS_ID):
        log.warning("quiz lead: QUIZ_KOMMO_LIVE=true, но не задан token/pipeline/status — пропуск")
        return {"status": "dry", "kommo_lead_id": None, "error": "config_missing"}

    display = (name or "").strip() or f"+{phone_norm}"
    lead: dict = {
        "name": f"{lead_prefix}: {display}"[:250],
        "pipeline_id": int(settings.QUIZ_KOMMO_PIPELINE_ID),
        "status_id": int(settings.QUIZ_KOMMO_STATUS_ID),
        "_embedded": {
            "contacts": [{
                "name": display,
                "custom_fields_values": [{
                    "field_code": "PHONE",
                    "values": [{"value": f"+{phone_norm}", "enum_code": "WORK"}],
                }],
            }],
            "tags": [{"name": lead_tag}],
        },
    }
    # Привязка к агенту через поле «ID AGENT» (enum). Нет enum_id → лид без агента
    # + тег для ручного разбора (премортем: не угадываем агента).
    if agent_enum_id:
        lead["custom_fields_values"] = [{
            "field_id": settings.KOMMO_ID_AGENT_FIELD_ID,
            "values": [{"enum_id": int(agent_enum_id)}],
        }]
    else:
        lead["_embedded"]["tags"].append({"name": "no-agent"})

    headers = {"Authorization": f"Bearer {settings.KOMMO_TOKEN}"}
    try:
        r = httpx.post(_base() + "/leads/complex", json=[lead], headers=headers, timeout=_TIMEOUT)
        if r.status_code >= 300:
            log.error("quiz lead create failed: HTTP %s", r.status_code)
            return {"status": "failed", "kommo_lead_id": None, "error": f"http_{r.status_code}"}
        data = r.json()
        lead_id = (data[0].get("id") if isinstance(data, list) and data else None)
    except Exception as exc:  # сеть/JSON — не валим приём заявки
        log.error("quiz lead create error: %s", type(exc).__name__)
        return {"status": "failed", "kommo_lead_id": None, "error": type(exc).__name__}

    # Примечание с ответами/UTM — best-effort: лид уже создан, провал не критичен.
    if lead_id:
        try:
            note = {"note_type": "common",
                    "params": {"text": _answers_note(answers, utm, ref_slug,
                                                     note_intro=note_intro,
                                                     question_titles=question_titles)}}
            httpx.post(f"{_base()}/leads/{lead_id}/notes", json=[note],
                       headers=headers, timeout=_TIMEOUT)
        except Exception as exc:
            log.warning("quiz lead note failed (lead=%s): %s", lead_id, type(exc).__name__)

    log.info("quiz lead created kommo_id=%s agent_enum=%s", lead_id, agent_enum_id)
    return {"status": "sent", "kommo_lead_id": lead_id, "error": None}
