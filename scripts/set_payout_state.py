"""Проставить статус партнёрского вознаграждения по выигранному лиду (Фаза B).

Минимальный ручной способ для менеджера/Николь — БЕЗ публичного эндпоинта и БЕЗ
секрета в URL (усвоенный урок: прежние admin-эндпоинты с key= в query удалены по
security-review). Запускается в деплой-зоне с доступом к БД (Railway shell или
локально с DATABASE_URL), по команде Николь.

Безопасность (опасная тройка — деньги + чужой клиент): пишем ТОЛЬКО колонку
payout_state одного лида; значение валидируется по белому списку; лид должен быть
won (по не-won деньги показывать рано); телефон/имя клиента не логируем.
Идемпотентно: повторный запуск с тем же значением ничего не меняет.

Примеры:
    python scripts/set_payout_state.py --lead 42 --state to_pay
    python scripts/set_payout_state.py --kommo 1234567 --state paid
    python scripts/set_payout_state.py --lead 42 --state in_calc   # сброс к дефолту
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal
from app.main import PAYOUT_STATE_VALUES  # единый источник белого списка
from app.models import Lead


def main() -> None:
    ap = argparse.ArgumentParser(description="Set Lead.payout_state for a won lead.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--lead", type=int, help="локальный Lead.id")
    g.add_argument("--kommo", type=int, help="kommo_lead_id (из карточки Kommo)")
    ap.add_argument("--state", required=True, choices=PAYOUT_STATE_VALUES,
                    help="статус вознаграждения: " + " / ".join(PAYOUT_STATE_VALUES))
    args = ap.parse_args()

    session = SessionLocal()
    try:
        if args.lead is not None:
            lead = session.query(Lead).filter_by(id=args.lead).first()
        else:
            lead = session.query(Lead).filter_by(kommo_lead_id=args.kommo).first()

        if not lead:
            sys.exit(f"❌ Лид не найден ({'id=' + str(args.lead) if args.lead else 'kommo=' + str(args.kommo)}).")
        if lead.status != "won":
            sys.exit(f"❌ Лид #{lead.id} в статусе '{lead.status}', а не 'won'. "
                     "Статус вознаграждения ставим только по выигранным.")

        if lead.payout_state == args.state:
            print(f"= Лид #{lead.id}: payout_state уже '{args.state}' — без изменений.")
            return

        old = lead.payout_state or "(пусто = в расчёте)"
        lead.payout_state = args.state
        session.commit()
        print(f"✅ Лид #{lead.id}: payout_state {old} → '{args.state}'.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
