"""Синхронизация лидов агентов из Kommo в локальную таблицу Lead (Фаза 1 + кабинет).

Идея: кабинет (/dashboard, /leads) читает локальный Lead по partner_id мгновенно.
Этот модуль периодически тянет лиды агентов через наш api (воронка 1.1) и
раскладывает их по Partner.kommo_agent_enum_id.

Централизация (2026-06-03): партнёр-сервис НЕ ходит в Kommo напрямую. api отдаёт
лиды в ПЛОСКОЙ форме (api сам маппит статус/агента/имя из Kommo): каждый элемент —
{kommo_lead_id, agent_enum_id, status, amount_aed, client_name}, status уже приведён
к 'won' | 'lost' | 'in_progress'. Словарь вокабуляра Kommo (поле «ID AGENT»,
status_id 142/143) живёт на стороне api, не здесь.

Ключ агента — enum_id (стабильный), НЕ текст-снимок. Идемпотентно: upsert по
kommo_lead_id. Запускается планировщиком (см. main.on_startup).
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app import api_client
from app.db import SessionLocal
from app.models import Lead, Partner
from app.refgen import generate_ref_slug

log = logging.getLogger("oncount.kommo_sync")

PIPELINE_AGENT = 11126307  # воронка 1.1 «Line agent lid» (контракт фильтра с api)


def seed_partners_from_enums(dry: bool = False) -> dict:
    """Фаза 0.7: создать Partner на каждого агента из enum-справочника «ID AGENT».
    Идемпотентно (upsert по kommo_agent_enum_id), быстро (без скана лидов).
    У каждого ref_slug для персональной инвайт-ссылки. Enum'ы тянет через api."""
    enums = api_client.kommo_agent_enums()
    if enums is None:
        return {"error": "api недоступен или ONCOUNT_API_URL не задан"}
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


def sync_agent_leads() -> dict:
    """Тянет лиды воронки 1.1 через api и раскладывает по партнёрам. Возвращает счётчики."""
    leads_all = api_client.kommo_agent_leads(PIPELINE_AGENT)
    if leads_all is None:
        log.warning("api недоступен / ONCOUNT_API_URL не задан — синк пропущен")
        return {"skipped": True}

    session: Session = SessionLocal()
    created = updated = 0
    # kommo_lead_id лидов, ТОЛЬКО ЧТО перешедших в won на существующей строке —
    # их извещаем после commit (Фаза K). Лиды, созданные сразу как won (бэкфилл
    # истории), сюда НЕ попадают: им ставим won_notified_at без отправки.
    newly_won: list[int] = []
    try:
        # карта enum_id агента -> partner_id
        by_enum = {
            p.kommo_agent_enum_id: p.id
            for p in session.query(Partner).filter(Partner.kommo_agent_enum_id.isnot(None)).all()
        }
        if not by_enum:
            return {"agents": 0, "note": "нет партнёров с kommo_agent_enum_id"}

        for l in leads_all:
            eid = l.get("agent_enum_id")
            pid = by_enum.get(eid)
            if not pid:
                continue
            kommo_id = l.get("kommo_lead_id")
            row = session.query(Lead).filter_by(kommo_lead_id=kommo_id).first()
            st = l.get("status") or "in_progress"
            amount = l.get("amount_aed") or None
            if row:
                old_status = row.status
                row.status = st
                row.partner_id = pid
                if amount is not None:
                    row.amount_aed = amount
                # Переход в won (Фаза K): фиксируем якорь выплаты один раз
                # и помечаем лид на извещение партнёра (после commit).
                if st == "won" and old_status != "won":
                    if row.won_at is None:
                        row.won_at = datetime.utcnow()
                    if row.won_notified_at is None:
                        newly_won.append(kommo_id)
                updated += 1
            else:
                # Лид впервые виден синком. Если он уже won — это история
                # (бэкфилл): ставим якорь, но помечаем извещённым БЕЗ
                # отправки, чтобы при go-live не ушла лавина старых пушей.
                now = datetime.utcnow()
                session.add(Lead(
                    partner_id=pid,
                    kommo_lead_id=kommo_id,
                    client_name=l.get("client_name") or f"#{kommo_id}",
                    status=st,
                    amount_aed=amount,
                    won_at=now if st == "won" else None,
                    won_notified_at=now if st == "won" else None,
                ))
                created += 1
        session.commit()
        # Извещаем партнёров о только что выигранных лидах (Фаза K). Делаем ПОСЛЕ
        # commit статусов: уведомление — отдельная забота, его сбой не должен
        # откатывать синк. notify_lead_won идемпотентен (won_notified_at) и сам
        # уважает предохранитель NOTIFICATIONS_LIVE (в dry наружу 0 пакетов).
        notified = 0
        if newly_won:
            from app.notifications import notify_lead_won
            for kid in newly_won:
                lead = session.query(Lead).filter_by(kommo_lead_id=kid).first()
                if lead is not None:
                    try:
                        notify_lead_won(lead, session)
                        notified += 1
                    except Exception as exc:  # одно уведомление не валит весь синк
                        log.error("win-notify fail lead kommo=%s: %s", kid, type(exc).__name__)
        log.info("kommo_sync: создано %s, обновлено %s, win-пушей %s", created, updated, notified)
        return {"created": created, "updated": updated, "won_notified": notified}
    finally:
        session.close()
