"""Синхронизация лидов агентов из Kommo в локальную таблицу Lead (Фаза 1 + кабинет).

Идея: кабинет (/dashboard, /leads) читает локальный Lead по partner_id мгновенно.
Этот модуль периодически тянет из Kommo (воронка 1.1) лиды, сгруппированные по
полю «ID AGENT» (enum_id), и раскладывает их по Partner.kommo_agent_enum_id.

Ключ агента — enum_id (стабильный), НЕ текст-снимок. Идемпотентно: upsert по
kommo_lead_id. Запускается планировщиком (см. main.on_startup).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

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
PIPELINE_FIRST = 9617055   # воронка 1 «1. Fist line»
# Синк читает 1.1 + воронку 1 (фильтр по ID AGENT в коде, см. ниже). НЕ читаем
# «6. Agents партнеры» (9707963): там карточки агентов с проставленным ID AGENT —
# иначе синк создал бы мусорный «лид-клиент» = сам агент.
SYNC_PIPELINES = [PIPELINE_AGENT]  # только 1.1; воронки 1 и 4 НЕ сканируем (решение Николь 2026-06-03) — won берём точечно из WON_BACKFILL
WON, LOST = 142, 143

# Успешные сделки из комиссионного Excel (источник истины «оплачено», решение Николь
# 2026-06-03). Их помечаем won в портале ТОЧЕЧНО по id — воронку «4. Production»
# целиком НЕ читаем. Удалённые id (404 в Kommo) тихо пропускаются.
WON_BACKFILL = frozenset({
    15004438, 20095641, 20244435, 19820817, 20094653, 20874532, 20680617, 19862707,
    21020769, 22084042, 19566821, 21390245, 19916917, 21295713, 22188816, 21652955,
    21798843, 22362692, 22591576, 22575846, 19176687, 22269880, 23412046, 23476242,
    23069317, 23166707, 20851299, 23357551, 23477216, 24015149, 23983590, 17166610,
    22824655, 21965547, 20484903, 24866910, 21827517, 23187991, 23995422, 25880202,
    25016652, 26311040,
})


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


# Хвост названия сделки в Kommo: «… - Заявка от (X)», «… агент Y». В колонку
# «Клиент» и в win-пуш он не нужен — режем, оставляя осмысленную «голову»
# (обычно компанию). Используется ТОЛЬКО как фолбэк, если у лида нет контакта.
_DEAL_NOISE = re.compile(r"\s*[-—]?\s*(заявка\s+от|агент)\b.*$", re.IGNORECASE)


def _clean_deal_name(name: str) -> str:
    cleaned = _DEAL_NOISE.sub("", name).strip(" -—()")
    return cleaned or name


def _main_contact_id(lead: dict) -> int | None:
    """id основного контакта лида (is_main, иначе первый)."""
    contacts = (lead.get("_embedded") or {}).get("contacts") or []
    if not contacts:
        return None
    main = next((c for c in contacts if c.get("is_main")), contacts[0])
    return main.get("id")


def _fetch_contacts(client: httpx.Client, ids: list[int]) -> dict[int, dict]:
    """id контакта → {'name','phone'} из Kommo. Батчами по 50 (filter[id][]).
    Имя/телефон в списке лидов не приходят — берём из карточки контакта. Только чтение."""
    out: dict[int, dict] = {}
    uniq = [i for i in dict.fromkeys(ids) if i]
    for i in range(0, len(uniq), 50):
        chunk = uniq[i:i + 50]
        params = [("filter[id][]", c) for c in chunk] + [("limit", 50)]
        try:
            r = client.get(f"{BASE}/contacts", params=params)
        except httpx.HTTPError:
            continue
        if r.status_code != 200:
            continue
        for ct in (r.json().get("_embedded") or {}).get("contacts") or []:
            phone = None
            for f in (ct.get("custom_fields_values") or []):
                if f.get("field_code") == "PHONE":
                    vals = f.get("values") or []
                    if vals:
                        phone = (vals[0].get("value") or "").strip() or None
                    break
            out[ct.get("id")] = {
                "name": (ct.get("name") or "").strip() or None,
                "phone": phone,
            }
    return out


def _client_name(lead: dict, contact: dict | None = None) -> str:
    """Имя клиента для портала: ПРИОРИТЕТ — чистое имя контакта (решение Николь
    2026-06-03), иначе очищенное название сделки (без «Заявка от …»)."""
    if contact and contact.get("name"):
        return str(contact["name"])[:255]
    name = (lead.get("name") or "").strip()
    if name and not name.lower().startswith(("lead #", "сделка #", "сделка по")):
        return _clean_deal_name(name)[:255]
    embedded = (lead.get("_embedded") or {}).get("contacts") or []
    if embedded and embedded[0].get("name"):
        return str(embedded[0]["name"])[:255]
    return name[:255] or f"#{lead.get('id')}"


def _upsert_lead(session, kommo_id, pid, st, amount, client_name, client_phone,
                 backfill_won, newly_won):
    """Upsert портал-Lead по kommo_lead_id. backfill_won=True → форсим статус won
    БЕЗ win-пуша (история из Excel). Возвращает True если создан, False если обновлён.
    Имя/телефон клиента бэкфиллим и у существующих строк (источник истины — Kommo),
    но НЕ затираем уже сохранённое пустым значением."""
    if backfill_won:
        st = "won"
    row = session.query(Lead).filter_by(kommo_lead_id=kommo_id).first()
    now = datetime.utcnow()
    if row:
        old = row.status
        row.status = st
        row.partner_id = pid
        if amount is not None:
            row.amount_aed = amount
        if client_name:
            row.client_name = client_name
        if client_phone:
            row.client_phone = client_phone
        if st == "won" and old != "won":
            if row.won_at is None:
                row.won_at = now
            if row.won_notified_at is None:
                if backfill_won:
                    row.won_notified_at = now   # история — помечаем обработанным, не пушим
                else:
                    newly_won.append(kommo_id)
        return False
    session.add(Lead(
        partner_id=pid, kommo_lead_id=kommo_id, client_name=client_name,
        client_phone=client_phone or None,
        status=st, amount_aed=amount,
        won_at=now if st == "won" else None,
        won_notified_at=now if st == "won" else None,
    ))
    return True


def sync_agent_leads() -> dict:
    """Тянет лиды воронок 1.1 + «1. Fist line» (SYNC_PIPELINES) и раскладывает по
    партнёрам по полю ID AGENT. Возвращает счётчики. Только чтение Kommo."""
    token = settings.KOMMO_TOKEN
    if not token:
        log.warning("KOMMO_TOKEN пуст — синк пропущен")
        return {"skipped": True}

    session: Session = SessionLocal()
    created = updated = 0
    # kommo_lead_id лидов, ТОЛЬКО ЧТО перешедших в won на существующей строке —
    # их извещаем после commit (Фаза K). Лиды, созданные сразу как won (бэкфилл
    # истории), сюда НЕ попадают: им ставим won_notified_at без отправки.
    newly_won: list[int] = []
    try:
        # Шаг 1 (план backfill 2026-06): перед привязкой лидов убеждаемся, что на
        # КАЖДОГО агента из справочника «ID AGENT» есть Partner. Идемпотентно
        # (upsert по kommo_agent_enum_id) — новые опции справочника получают Partner,
        # иначе их лиды не к чему привязать. Свой сбой не валит синк.
        try:
            seed_partners_from_enums()
        except Exception as exc:
            log.warning("seed_partners_from_enums пропущен: %s", type(exc).__name__)
        # карта enum_id агента -> partner_id
        by_enum = {
            p.kommo_agent_enum_id: p.id
            for p in session.query(Partner).filter(Partner.kommo_agent_enum_id.isnot(None)).all()
        }
        if not by_enum:
            return {"agents": 0, "note": "нет партнёров с kommo_agent_enum_id"}

        with httpx.Client(timeout=30, headers={"Authorization": f"Bearer {token}"}) as client:
            seen: set[int] = set()
            page = 1
            while True:
                r = client.get(
                    f"{BASE}/leads",
                    params={
                        "filter[pipeline_id][]": SYNC_PIPELINES,
                        "with": "contacts",
                        "limit": 250,
                        "page": page,
                    },
                )
                if r.status_code == 204 or r.status_code >= 400:
                    break
                leads = (r.json().get("_embedded") or {}).get("leads") or []
                # Контакты (имя+телефон) догружаем ОДНИМ батчем на страницу и только
                # для лидов с известным агентом — лишних запросов в Kommo не делаем.
                matched = [(l, pid) for l in leads if (pid := by_enum.get(_agent_enum_id(l)))]
                cmap = _fetch_contacts(client, [_main_contact_id(l) for l, _ in matched])
                for l, pid in matched:
                    kommo_id = l.get("id")
                    seen.add(kommo_id)
                    contact = cmap.get(_main_contact_id(l))
                    phone = contact.get("phone") if contact else None
                    if _upsert_lead(session, kommo_id, pid, _status(l.get("status_id")),
                                    l.get("price") or None, _client_name(l, contact), phone,
                                    kommo_id in WON_BACKFILL, newly_won):
                        created += 1
                    else:
                        updated += 1
                if len(leads) < 250:
                    break
                page += 1
                if page > 80:
                    break

            # Успешные сделки из Excel, которых НЕ было в прочитанных воронках
            # (например, ушли в «4. Production»): берём ТОЧЕЧНО по id и помечаем won.
            # Воронку 4 целиком не читаем; удалённые id (404) тихо пропускаем.
            for kid in WON_BACKFILL:
                if kid in seen:
                    continue
                row = session.query(Lead).filter_by(kommo_lead_id=kid).first()
                if row is not None and row.status == "won":
                    continue
                lr = client.get(f"{BASE}/leads/{kid}", params={"with": "contacts"})
                if lr.status_code != 200:
                    continue
                l = lr.json()
                pid = by_enum.get(_agent_enum_id(l))
                if not pid:
                    continue
                cid = _main_contact_id(l)
                contact = _fetch_contacts(client, [cid]).get(cid) if cid else None
                phone = contact.get("phone") if contact else None
                if _upsert_lead(session, kid, pid, "won", l.get("price") or None,
                                _client_name(l, contact), phone, True, newly_won):
                    created += 1
                else:
                    updated += 1
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
