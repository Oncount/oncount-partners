"""Фаза 0.7: пред-создание Partner для активных Kommo-агентов.

Один Partner ↔ один Kommo-агент (по kommo_agent_enum_id). У каждого свой ref_slug
для персональной инвайт-ссылки. Идемпотентно: по kommo_agent_enum_id — upsert.

Активный агент = у его enum есть ≥1 лид в воронках 1.1 / 1.

ВАЖНО: деплой-зона (пишет в прод-БД). Запускать ТОЛЬКО по команде Николь, на Railway
(где есть DATABASE_URL и KOMMO_TOKEN). Сначала прогон с --dry для проверки.

    python scripts/seed_agent_partners.py --dry   # показать, что создаст
    python scripts/seed_agent_partners.py         # применить
"""
import os
import sys
import subprocess
import urllib.request
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal
from app.models import Partner
from app.refgen import generate_ref_slug

BASE = "https://primeadvice.kommo.com/api/v4"
FIELD = 961886
PIPES = [11126307, 9617055]


def token() -> str:
    t = os.getenv("KOMMO_TOKEN")
    if t:
        return t
    # локально — из .env через grep (правило репо №8)
    out = subprocess.check_output(["grep", "^KOMMO_TOKEN=", ".env"]).decode()
    return out.split("=", 1)[1].strip()


def kget(url: str, tok: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + tok})
    with urllib.request.urlopen(req) as r:
        if r.status == 204:
            return {}
        return json.loads(r.read().decode())


def agent_enum_id(lead: dict):
    f = next((x for x in (lead.get("custom_fields_values") or []) if x.get("field_name") == "ID AGENT"), None)
    return f["values"][0].get("enum_id") if f and f.get("values") else None


def main() -> None:
    dry = "--dry" in sys.argv
    tok = token()
    field = kget(f"{BASE}/leads/custom_fields/{FIELD}", tok)
    names = {e["id"]: e["value"] for e in (field.get("enums") or [])}

    active = set()
    for p in PIPES:
        page = 1
        while True:
            d = kget(f"{BASE}/leads?filter%5Bpipeline_id%5D%5B%5D={p}&limit=250&page={page}", tok)
            leads = (d.get("_embedded") or {}).get("leads") or []
            for l in leads:
                eid = agent_enum_id(l)
                if eid:
                    active.add(eid)
            if len(leads) < 250:
                break
            page += 1
            if page > 80:
                break

    print(f"Активных агентов (enum с лидами): {len(active)}")
    session = SessionLocal()
    created = updated = 0
    try:
        for eid in active:
            name = names.get(eid, f"agent {eid}")
            partner = session.query(Partner).filter_by(kommo_agent_enum_id=eid).first()
            if partner:
                if partner.kommo_agent_name != name:
                    if not dry:
                        partner.kommo_agent_name = name
                    updated += 1
                continue
            created += 1
            if dry:
                print(f"  + Partner(agent={name}, enum={eid})")
                continue
            session.add(Partner(
                kommo_agent_enum_id=eid,
                kommo_agent_name=name,
                ref_slug=generate_ref_slug(),
                status="invited",
            ))
        if not dry:
            session.commit()
    finally:
        session.close()
    print(f"{'[DRY] ' if dry else ''}создать: {created} | обновить имя: {updated}")


if __name__ == "__main__":
    main()
