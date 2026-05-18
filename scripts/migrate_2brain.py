"""Одноразовая миграция регистраций мастер-класса из Google Sheet в Postgres.

Запуск:
    1. В Google Sheets «AI 2-й мозг — регистрации 21.05.2026» → File → Download → CSV.
    2. Сохрани файл как 2brain-registrations.csv в этой папке.
    3. python scripts/migrate_2brain.py 2brain-registrations.csv

Скрипт идемпотентен — повторный запуск не создаёт дубликатов
(UniqueConstraint telegram_id + event_slug в модели EventRegistration).
"""
import csv
import sys
from datetime import datetime
from pathlib import Path

# поднимаем корень проекта в sys.path, чтобы импортировать app.*
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import SessionLocal
from app.models import EventRegistration

EVENT_SLUG = "ai-2brain-2026-05-21"


def parse_dt(value: str) -> datetime:
    value = (value or "").strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return datetime.utcnow()


def parse_bool(value: str) -> bool:
    return (value or "").strip().lower() in {"true", "1", "yes", "да"}


def migrate(csv_path: Path) -> int:
    session = SessionLocal()
    count = 0
    try:
        with csv_path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                tg_id = row.get("telegram_id") or row.get("Telegram ID") or row.get("id")
                if not tg_id:
                    continue
                try:
                    tg_id_int = int(str(tg_id).strip())
                except ValueError:
                    continue

                stmt = pg_insert(EventRegistration).values(
                    telegram_id=tg_id_int,
                    event_slug=EVENT_SLUG,
                    first_name=(row.get("first_name") or row.get("First name") or "").strip() or None,
                    username=(row.get("username") or "").strip() or None,
                    registered_at=parse_dt(row.get("registered_at") or row.get("registered_at (UTC)") or ""),
                    attended=parse_bool(row.get("attended", "")),
                    meta={
                        "reminder_24h_sent": parse_bool(row.get("reminder_24h_sent", "")),
                        "zoom_link_sent": parse_bool(row.get("zoom_link_sent", "")),
                        "start_1h_sent": parse_bool(row.get("start_1h_sent", "")),
                        "language_code": (row.get("language_code") or "").strip() or None,
                        "last_name": (row.get("last_name") or "").strip() or None,
                    },
                ).on_conflict_do_nothing(constraint="uq_event_per_user")
                session.execute(stmt)
                count += 1
        session.commit()
    finally:
        session.close()
    return count


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/migrate_2brain.py <path-to-csv>")
        sys.exit(1)
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(2)
    n = migrate(path)
    print(f"Processed {n} rows. Done.")
