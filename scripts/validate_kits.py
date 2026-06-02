"""Проверить тела китов в БД на money-words (Фаза J) — для менеджера/Николь.

READ-ONLY: ничего не пишет и не меняет, только печатает найденные нарушения.
Полезно ПОСЛЕ ручного upsert текстов китов в прод-БД (когда Николь утвердит
финальные формулировки и заменит body черновиков напрямую в базе) — машинно
убедиться, что в текст, который партнёр копирует и шлёт КЛИЕНТУ, не просочилось
«комиссия / commission / referral fee / партнёрское вознаграждение».

Проверяет только КИТЫ (`partner_type IS NOT NULL`). Генерик /messages и тексты
кабинета НЕ трогает (там «вознаграждение» разрешено — это видит сам партнёр).

Запуск локально с DATABASE_URL или в Railway shell:
    python scripts/validate_kits.py            # все киты
    python scripts/validate_kits.py --drafts   # включить и *-draft (по умолч. пропускаются)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal
from app.kit_validator import find_money_words
from app.models import MessageTemplate


def main() -> None:
    ap = argparse.ArgumentParser(description="Проверка китов на money-words (Фаза J).")
    ap.add_argument(
        "--drafts", action="store_true",
        help="проверять и черновики (*-draft); по умолчанию они пропускаются",
    )
    args = ap.parse_args()

    session = SessionLocal()
    try:
        kits = (
            session.query(MessageTemplate)
            .filter(MessageTemplate.partner_type.isnot(None))
            .order_by(MessageTemplate.partner_type, MessageTemplate.order_index)
            .all()
        )
    finally:
        session.close()

    checked = 0
    flagged = 0
    skipped_drafts = 0
    for kit in kits:
        is_draft = (kit.slug or "").endswith("-draft")
        if is_draft and not args.drafts:
            skipped_drafts += 1
            continue
        checked += 1
        violations = find_money_words(kit.body_md, kit.body_md_en)
        if not violations:
            continue
        flagged += 1
        tag = " [DRAFT]" if is_draft else ""
        print(f"\n⚠️  {kit.slug}{tag} (тип: {kit.partner_type})")
        for field, word in violations:
            print(f"     {field}: «{word}»")

    print(
        f"\nИтог: проверено {checked}, с нарушениями {flagged}, "
        f"черновиков пропущено {skipped_drafts}."
    )
    if flagged:
        print("Перепиши помеченные на партнёрский тон (рекомендация / introduce) "
              "перед публикацией клиенту.")
    sys.exit(1 if flagged else 0)


if __name__ == "__main__":
    main()
