"""Upsert финальных текстов китов партнёра в прод-БД (Фаза C+G, план 2026-05-27).

ЗАЧЕМ ОТДЕЛЬНЫЙ СКРИПТ: тексты китов утверждены Николь 2026-06-02 и лежат в
`app/seed.py` (массив KITS). Залить их в прод можно и обычным деплоем
(`seed_if_empty` force-reseed'ит `message_templates` на старте), но этот скрипт
даёт upsert ПО `slug` БЕЗ рестарта/деплоя и БЕЗ полного wipe таблицы — точечно
обновляет только киты, не трогая генерик-крючки `/messages`. Также убирает с
прода устаревший черновик `kit-agency-white-label-draft` (white-label отложен
решением Николь 2026-06-01).

Безопасность (опасная тройка — текст уходит КЛИЕНТУ наружу): каждое тело перед
записью прогоняется через `_kit_body_clean` (Фаза J) — финальный кит со
стоп-словом («комиссия / commission / referral fee / партнёрское вознаграждение»)
НЕ запишется, скрипт его пропустит и посчитает как failed. ПД не логируем.

READ-ONLY по умолчанию: без `--apply` печатает только план и ничего не меняет.
Идемпотентность: повторный запуск ничего не ломает (совпадающие киты → «без
изменений», удалять уже нечего).

Запуск локально с DATABASE_URL или в Railway shell:
    python scripts/seed_kits.py            # dry-run: печатает план, НЕ пишет
    python scripts/seed_kits.py --check    # то же самое (явный dry-run)
    python scripts/seed_kits.py --apply     # выполнить upsert + удаление
"""
import argparse
import sys
from pathlib import Path

# Печатаем эмодзи-статусы (✅/✘) безопасно на любой консоли (Windows cp1251 не
# знает ✅ и упал бы уже ПОСЛЕ коммита). На Railway/Linux stdout и так UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal
from app.kit_validator import _kit_body_clean
from app.models import MessageTemplate
from app.seed import KITS

# Устаревший черновик: white-label отложен (решение Николь 2026-06-01) — удалить
# с прода, если был засеян ранее. Хранится здесь, а не в KITS (его там уже нет).
OBSOLETE_SLUGS = ("kit-agency-white-label-draft",)

# Колонки, которые upsert синхронизирует из KITS (slug — ключ, не трогаем).
SYNCED_FIELDS = (
    "partner_type", "segment", "segment_en", "title", "title_en",
    "body_md", "body_md_en", "order_index", "is_active",
)


def _kit_with_defaults(kit: dict) -> dict:
    """Нормализовать словарь кита: проставить is_active=True по умолчанию."""
    data = dict(kit)
    data.setdefault("is_active", True)
    return data


def _differs(existing: MessageTemplate, data: dict) -> bool:
    """True, если хотя бы одно синхронизируемое поле в БД отличается от KITS."""
    for field in SYNCED_FIELDS:
        if getattr(existing, field) != data.get(field):
            return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Upsert китов партнёра в БД (Фаза C+G). По умолчанию dry-run."
    )
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true",
                   help="выполнить запись (upsert + удаление). Без него — только план.")
    g.add_argument("--check", action="store_true",
                   help="явный dry-run: напечатать план, ничего не менять (по умолч.).")
    args = ap.parse_args()
    apply = args.apply  # --check и отсутствие флага = dry-run

    to_create: list[str] = []
    to_update: list[str] = []
    unchanged: list[str] = []
    failed: list[tuple[str, str]] = []  # (slug, причина)

    session = SessionLocal()
    try:
        # 1) Прогон каждого кита через валидатор Фазы J + классификация create/update.
        valid_kits: list[dict] = []
        for kit in KITS:
            slug = kit.get("slug", "")
            data = _kit_with_defaults(kit)
            try:
                _kit_body_clean(data.get("body_md"), data.get("body_md_en"), slug)
            except ValueError as e:
                failed.append((slug, str(e)))
                continue
            valid_kits.append(data)
            existing = session.query(MessageTemplate).filter_by(slug=slug).first()
            if existing is None:
                to_create.append(slug)
            elif _differs(existing, data):
                to_update.append(slug)
            else:
                unchanged.append(slug)

        # 2) Удаление устаревших черновиков (white-label).
        to_delete = [
            s for s in OBSOLETE_SLUGS
            if session.query(MessageTemplate.id).filter_by(slug=s).first() is not None
        ]

        # 3) Печать плана.
        total = len(to_create) + len(to_update) + len(unchanged)
        print("=" * 50)
        print(f"ПЛАН upsert китов ({'APPLY' if apply else 'DRY-RUN'}):")
        print(f"  создать:        {len(to_create)}  {to_create}")
        print(f"  обновить:       {len(to_update)}  {to_update}")
        print(f"  без изменений:  {len(unchanged)}  {unchanged}")
        print(f"  удалить:        {len(to_delete)}  {to_delete}")
        print(f"  провалов:       {len(failed)}")
        for slug, reason in failed:
            print(f"     ✘ {slug}: {reason}")
        print(f"  всего китов в KITS: {total}")
        print("=" * 50)

        if not apply:
            print("DRY-RUN: ничего не записано. Для применения — флаг --apply.")
            sys.exit(1 if failed else 0)

        # 4) APPLY: upsert + удаление в одной транзакции.
        created = updated = deleted = 0
        for data in valid_kits:
            slug = data["slug"]
            existing = session.query(MessageTemplate).filter_by(slug=slug).first()
            if existing is None:
                session.add(MessageTemplate(**data))
                created += 1
            elif _differs(existing, data):
                for field in SYNCED_FIELDS:
                    setattr(existing, field, data.get(field))
                updated += 1
        for s in OBSOLETE_SLUGS:
            deleted += session.query(MessageTemplate).filter_by(slug=s).delete()
        session.commit()

        print(f"✅ Готово: created {created} / updated {updated} / "
              f"deleted {deleted} / failed {len(failed)}.")
        sys.exit(1 if failed else 0)
    finally:
        session.close()


if __name__ == "__main__":
    main()
