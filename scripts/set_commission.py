"""Проставить комиссию партнёра (AED) по конкретной сделке.

Комиссия у сделок разная — согласуется индивидуально (решение Николь 2026-07-20),
поэтому храним суммой в `Lead.commission_aed`, а не выводим из чека клиента.
Значение видно партнёру в кабинете: строкой «Ваша комиссия» и в сумме
«Комиссия» в балансовой полосе. NULL = «не посчитана», вклад в сумму 0.

kommo_sync это поле не трогает — ручная отметка переживает синк.

Запуск (деплой-зона, ТОЛЬКО по команде Николь) — на Railway, база доступна лишь
по внутреннему хосту:
    python scripts/set_commission.py --kommo-lead 26470738            # показать
    python scripts/set_commission.py --kommo-lead 26470738 --aed 550 --apply
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal
from app.models import Lead, Partner


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kommo-lead", type=int, required=True, help="kommo_lead_id сделки")
    ap.add_argument("--aed", type=float, help="сумма комиссии в AED")
    ap.add_argument("--apply", action="store_true", help="записать (иначе dry-run)")
    args = ap.parse_args()

    session = SessionLocal()
    try:
        lead = session.query(Lead).filter_by(kommo_lead_id=args.kommo_lead).first()
        if lead is None:
            print(f"ОШИБКА: лида с kommo_lead_id={args.kommo_lead} нет в базе портала.")
            print("Возможно, синк ещё не отработал после простановки ID AGENT в Kommo.")
            sys.exit(1)

        partner = session.query(Partner).filter_by(id=lead.partner_id).first()
        pname = partner.kommo_agent_name if partner else "?"
        print(f"Сделка: {lead.client_name!r} | статус={lead.status} | чек={lead.amount_aed} AED")
        print(f"Партнёр: {pname} (id={lead.partner_id})")
        print(f"Комиссия сейчас: {lead.commission_aed if lead.commission_aed is not None else '— не проставлена'}")

        if args.aed is None:
            print("\nСумма не задана (--aed) — только просмотр.")
            return

        if lead.status != "won":
            print(f"\nВНИМАНИЕ: статус лида {lead.status!r}, а не 'won'.")
            print("Комиссия показывается партнёру только по выигранным сделкам.")

        if not args.apply:
            print(f"\nDRY-RUN: будет проставлено commission_aed = {args.aed} AED")
            print("Для записи добавь --apply")
            return

        lead.commission_aed = args.aed
        session.commit()
        print(f"\nГОТОВО: комиссия {args.aed} AED проставлена по сделке {args.kommo_lead}.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
