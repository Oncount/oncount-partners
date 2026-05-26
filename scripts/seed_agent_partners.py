"""Фаза 0.7: пред-создание Partner для Kommo-агентов. Делегирует в app.kommo_sync.

    python scripts/seed_agent_partners.py --dry
    python scripts/seed_agent_partners.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.kommo_sync import seed_partners_from_enums

if __name__ == "__main__":
    print(seed_partners_from_enums(dry="--dry" in sys.argv))
