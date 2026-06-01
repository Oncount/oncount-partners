"""Показать ответы анкеты партнёра (Фаза L) — для менеджера/Николь.

READ-ONLY: ничего не пишет в БД, только выводит сводку. БЕЗ публичного эндпоинта
(усвоенный урок Фазы B: ручные операции менеджера — через CLI в деплой-зоне, не
через admin-URL). Запуск локально с DATABASE_URL или в Railway shell.

Анкета по дизайну НЕ содержит реквизитов карт/кошельков — только тип канала
выплаты. Тем не менее это бизнес-профиль партнёра: выводим осознанно, по команде.

Примеры:
    python scripts/show_onboarding.py --partner 12        # по Partner.id
    python scripts/show_onboarding.py --slug ab12cd        # по ref_slug
    python scripts/show_onboarding.py --all                # все заполнившие
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal
from app.main import partner_onboarding
from app.models import Partner


def _print(partner: Partner) -> None:
    info = partner_onboarding(partner, lang="ru")
    who = partner.first_name or partner.username or f"id={partner.id}"
    if not info["completed"]:
        print(f"— Партнёр {who} (id={partner.id}, slug={partner.ref_slug}): анкета НЕ пройдена.")
        return
    done = partner.survey_completed_at.strftime("%Y-%m-%d %H:%M") if partner.survey_completed_at else "?"
    print(f"\n✅ Партнёр {who} (id={partner.id}, slug={partner.ref_slug}) — заполнено {done} UTC")
    for row in info["summary"]:
        print(f"   • {row['question']}\n     → {row['value']}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Показать ответы анкеты партнёра (Фаза L).")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--partner", type=int, help="Partner.id")
    g.add_argument("--slug", type=str, help="Partner.ref_slug")
    g.add_argument("--all", action="store_true", help="все партнёры, прошедшие анкету")
    args = ap.parse_args()

    session = SessionLocal()
    try:
        if args.all:
            rows = (
                session.query(Partner)
                .filter(Partner.survey_completed_at.isnot(None))
                .order_by(Partner.survey_completed_at.desc())
                .all()
            )
            if not rows:
                print("Пока никто не заполнил анкету.")
                return
            print(f"Заполнили анкету: {len(rows)} партнёр(ов).")
            for p in rows:
                _print(p)
            return

        if args.partner is not None:
            p = session.query(Partner).filter_by(id=args.partner).first()
        else:
            p = session.query(Partner).filter_by(ref_slug=args.slug).first()
        if not p:
            sys.exit("❌ Партнёр не найден.")
        _print(p)
    finally:
        session.close()


if __name__ == "__main__":
    main()
