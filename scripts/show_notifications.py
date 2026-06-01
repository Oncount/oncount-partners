"""Просмотр уведомлений партнёрам (Фаза K) — для Николь/менеджера.

READ-ONLY: ничего не пишет в БД. Две функции:
  --bank      печатает БАНК черновых текстов (digest + win) для утверждения Николь;
  --log       печатает последние попытки из notification_attempts (что «ушло» бы /
              реально ушло), со статусами и маскированным получателем.

БЕЗ публичного эндпоинта (урок Фазы B: ручные операции — через CLI в деплой-зоне,
не admin-URL). Запуск локально с DATABASE_URL или в Railway shell.

⚠️ Тексты — ЧЕРНОВИК (NOTIFICATIONS_DRAFT). Это «плашка для admin-проверки текстов»
из плана: Николь читает банк здесь, утверждает → исполнитель снимает флаг.

Примеры:
    python scripts/show_notifications.py --bank
    python scripts/show_notifications.py --log            # последние 30 попыток
    python scripts/show_notifications.py --log --limit 100
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import notifications as N
from app.db import SessionLocal
from app.models import NotificationAttempt


def print_bank() -> None:
    flag = "ЧЕРНОВИК (не утверждён)" if N.NOTIFICATIONS_DRAFT else "утверждён"
    print(f"\n=== БАНК ТЕКСТОВ УВЕДОМЛЕНИЙ — {flag} ===")
    print(f"NOTIFICATIONS_DRAFT = {N.NOTIFICATIONS_DRAFT}")
    blocks = [
        ("DIGEST — шапки", N.GREETINGS_DIGEST),
        ("DIGEST — концовки", N.CLOSINGS_DIGEST),
        ("WIN — шапки", N.GREETINGS_WIN),
        ("WIN — концовки", N.CLOSINGS_WIN),
    ]
    for title, bank in blocks:
        print(f"\n— {title} —")
        for lang in ("ru", "en"):
            print(f"  [{lang}]")
            for i, v in enumerate(bank[lang], 1):
                print(f"    {i}. {v}")
    print("\n— Правило выплат —")
    for lang in ("ru", "en"):
        print(f"  [{lang}] {N.PAYOUT_RULE[lang]}")
    print()


def print_log(limit: int) -> None:
    session = SessionLocal()
    try:
        rows = (session.query(NotificationAttempt)
                .order_by(NotificationAttempt.created_at.desc())
                .limit(limit).all())
        if not rows:
            print("notification_attempts пуст — ни одного триггера ещё не было.")
            return
        print(f"\nПоследние {len(rows)} попыток (новые сверху):\n")
        for a in rows:
            ts = a.created_at.strftime("%Y-%m-%d %H:%M") if a.created_at else "?"
            head = a.body.splitlines()[0] if a.body else ""
            print(f"[{ts}] partner={a.partner_id} {a.kind}/{a.channel} "
                  f"→ {a.status}{' (' + a.error_short + ')' if a.error_short else ''} "
                  f"to={a.recipient or '—'}")
            print(f"    «{head[:80]}»")
    finally:
        session.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Просмотр уведомлений партнёрам (Фаза K).")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--bank", action="store_true", help="показать банк черновых текстов")
    g.add_argument("--log", action="store_true", help="показать последние попытки из БД")
    ap.add_argument("--limit", type=int, default=30, help="сколько записей лога (default 30)")
    args = ap.parse_args()

    if args.bank:
        print_bank()
    else:
        print_log(args.limit)


if __name__ == "__main__":
    main()
