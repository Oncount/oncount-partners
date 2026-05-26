"""Миграция: связь Partner ↔ Kommo-агент (Фаза 0.7).

Добавляет в таблицу partners колонки:
  - kommo_agent_enum_id BIGINT   — enum_id значения поля «ID AGENT» (#961886) в Kommo;
  - kommo_agent_name    VARCHAR  — кэш отображаемого имени агента (латиница).
И индекс по kommo_agent_enum_id.

Идемпотентно (ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS).
Запуск (деплой-зона, только по команде Николь):
    python scripts/migrate_agent_link.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.db import engine

DDL = [
    "ALTER TABLE partners ADD COLUMN IF NOT EXISTS kommo_agent_enum_id BIGINT",
    "ALTER TABLE partners ADD COLUMN IF NOT EXISTS kommo_agent_name VARCHAR(128)",
    "CREATE INDEX IF NOT EXISTS ix_partners_kommo_agent_enum_id ON partners (kommo_agent_enum_id)",
    # Фаза 0.7: ref_slug инвайта в сессиях входа (привязка TG/email к Partner-агенту)
    "ALTER TABLE login_sessions ADD COLUMN IF NOT EXISTS ref_slug VARCHAR(16)",
    "ALTER TABLE email_login_tokens ADD COLUMN IF NOT EXISTS ref_slug VARCHAR(16)",
]


def main() -> None:
    with engine.begin() as conn:
        for stmt in DDL:
            conn.execute(text(stmt))
            print("OK:", stmt)
    print("Миграция agent_link завершена.")


if __name__ == "__main__":
    main()
