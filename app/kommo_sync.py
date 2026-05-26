"""Синхронизация лидов агентов из Kommo в локальную таблицу Lead (Фаза 1 + кабинет).

Идея: кабинет (/dashboard, /leads) читает локальный Lead по partner_id мгновенно.
Этот модуль периодически тянет из Kommo (воронка 1.1) лиды, сгруппированные по
полю «ID AGENT» (enum_id), и раскладывает их по Partner.kommo_agent_enum_id.

Ключ агента — enum_id (стабильный), НЕ текст-снимок. Идемпотентно: upsert по
kommo_lead_id. Запускается планировщиком (см. main.on_startup).
"""
from __future__ import annotations

import logging

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import Lead, Partner
from app.refgen import generate_ref_slug

log = logging.getLogger("oncount.kommo_sync")

BASE = "https://primeadvice.kommo.com/api/v4"
AGENT_FIELD = 961886       # поле «ID AGENT»
PIPELINE_AGENT = 11126307  # воронка 1.1 «Line agent lid»
WON, LOST = 142, 143


def seed_partners_from_enums(dry: bool = False) -> dict:
    """Фаза 0.7: создать Partner на каждого агента из enum-справочника «ID AGENT».
    Идемпотентно (upsert по kommo_agent_enum_id), быстро (без скана лидов).
    У каждого ref_slug для персональной инвайт-ссылки."""
    token = settings.KOMMO_TOKEN
    if not token:
        return {"error": "KOMMO_TOKEN пуст"}
    with httpx.Client(timeout=30, headers={"Authorization": f"Bearer {token}"}) as c:
        enums = (c.get(f"{BASE}/leads/custom_fields/{AGENT_FIELD}").json().get("enums") or [])
    session = SessionLocal()
    created = updated = 0
    try:
        for e in enums:
            eid, name = e["id"], e["value"]
            p = session.query(Partner).filter_by(kommo_agent_enum_id=eid).first()
            if p:
                if p.kommo_agent_name != name and not dry:
                    p.kommo_agent_name = name
                    updated += 1
                continue
            created += 1
            if not dry:
                session.add(Partner(
                    kommo_agent_enum_id=eid, kommo_agent_name=name,
                    ref_slug=generate_ref_slug(), status="invited",
                ))
        if not dry:
            session.commit()
    finally:
        session.close()
    return {"agents_in_field": len(enums), "created": created, "updated": updated, "dry": dry}


def _status(status_id: int) -> str:
    if status_id == WON:
        return "won"
    if status_id == LOST:
        return "lost"
    return "in_progress"


def _agent_enum_id(lead: dict):
    f = next((x for x in (lead.get("custom_fields_values") or [])
              if x.get("field_name") == "ID AGENT"), None)
    return f["values"][0].get("enum_id") if f and f.get("values") else None


def _client_name(lead: dict) -> str:
    name = (lead.get("name") or "").strip()
    if name and not name.lower().startswith(("lead #", "сделка #", "сделка по")):
        return name[:255]
    contacts = (lead.get("_embedded") or {}).get("contacts") or []
    if contacts and contacts[0].get("name"):
        return str(contacts[0]["name"])[:255]
    return name[:255] or f"#{lead.get('id')}"


def sync_agent_leads() -> dict:
    """Тянет лиды воронки 1.1 и раскладывает по партнёрам. Возвращает счётчики."""
    token = settings.KOMMO_TOKEN
    if not token:
        log.warning("KOMMO_TOKEN пуст — синк пропущен")
        return {"skipped": True}

    session: Session = SessionLocal()
    created = updated = 0
    try:
        # карта enum_id агента -> partner_id
        by_enum = {
            p.kommo_agent_enum_id: p.id
            for p in session.query(Partner).filter(Partner.kommo_agent_enum_id.isnot(None)).all()
        }
        if not by_enum:
            return {"agents": 0, "note": "нет партнёров с kommo_agent_enum_id"}

        with httpx.Client(timeout=30, headers={"Authorization": f"Bearer {token}"}) as client:
            page = 1
            while True:
                r = client.get(
                    f"{BASE}/leads",
                    params={
                        "filter[pipeline_id][]": PIPELINE_AGENT,
                        "with": "contacts",
                        "limit": 250,
                        "page": page,
                    },
                )
                if r.status_code == 204 or r.status_code >= 400:
                    break
                leads = (r.json().get("_embedded") or {}).get("leads") or []
                for l in leads:
                    eid = _agent_enum_id(l)
                    pid = by_enum.get(eid)
                    if not pid:
                        continue
                    kommo_id = l.get("id")
                    row = session.query(Lead).filter_by(kommo_lead_id=kommo_id).first()
                    st = _status(l.get("status_id"))
                    amount = l.get("price") or None
                    if row:
                        row.status = st
                        row.partner_id = pid
                        if amount is not None:
                            row.amount_aed = amount
                        updated += 1
                    else:
                        session.add(Lead(
                            partner_id=pid,
                            kommo_lead_id=kommo_id,
                            client_name=_client_name(l),
                            status=st,
                            amount_aed=amount,
                        ))
                        created += 1
                if len(leads) < 250:
                    break
                page += 1
                if page > 80:
                    break
        session.commit()
        log.info("kommo_sync: создано %s, обновлено %s", created, updated)
        return {"created": created, "updated": updated}
    finally:
        session.close()
