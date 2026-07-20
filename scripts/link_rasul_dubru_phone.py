"""Разовая привязка: телефон Расула Чарыева (Dubru) → кабинет партнёра `dubru`.

Контекст: Dubru — командный канал (собственник Артём, менеджеры Расул Чарыев и
Ксения Дунько). Кабинет один на канал, енум «ID AGENT» = 757864
«dubru (Instagram-kanal)». Расул входит по своему номеру и видит ВСЕ лиды канала.

ВАЖНО (приватность): вход по этому номеру открывает лиды всей команды Dubru,
включая ПД клиентов (имя + телефон). Это осознанное решение Николь — канал
командный. Отдельному человеку отдельный кабинет НЕ заводим.

Номер пишется digits-only (как app.auth.normalize_phone), иначе матч на входе
молча не сработает. Уникальность (kind, value) гарантирует, что один номер не
ведёт в два кабинета.

Идемпотентно: повторный запуск ничего не дублирует.

Запуск (деплой-зона, ТОЛЬКО по команде Николь) — на Railway, т.к. база доступна
лишь по внутреннему хосту:
    python scripts/link_rasul_dubru_phone.py          # dry-run, ничего не пишет
    python scripts/link_rasul_dubru_phone.py --apply  # запись
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth import normalize_phone
from app.db import SessionLocal
from app.models import Partner, PartnerIdentity

DUBRU_ENUM_ID = 757864          # «dubru (Instagram-kanal)» в справочнике ID AGENT
RASUL_PHONE_RAW = "+971568149179"  # Charyev Rasul, контакт Kommo #26790978
KIND = "phone"


def main() -> None:
    apply = "--apply" in sys.argv
    value = normalize_phone(RASUL_PHONE_RAW)
    if not value:
        print("ОШИБКА: телефон не нормализовался — проверь RASUL_PHONE_RAW")
        sys.exit(1)

    session = SessionLocal()
    try:
        partner = session.query(Partner).filter_by(
            kommo_agent_enum_id=DUBRU_ENUM_ID).first()
        if partner is None:
            print(f"ОШИБКА: нет Partner с kommo_agent_enum_id={DUBRU_ENUM_ID}.")
            print("Сначала синк/seed_partners_from_enums должен создать партнёра.")
            sys.exit(1)

        print(f"Партнёр: id={partner.id} | {partner.kommo_agent_name!r} | статус={partner.status}")
        print(f"Телефон к привязке: {RASUL_PHONE_RAW} → {value!r} (digits-only)")

        # Занят ли номер другим кабинетом (uq_identity_kind_value)
        existing = session.query(PartnerIdentity).filter_by(kind=KIND, value=value).first()
        if existing is not None:
            if existing.partner_id == partner.id:
                print("УЖЕ ПРИВЯЗАН к этому же кабинету — делать нечего.")
            else:
                print(f"КОНФЛИКТ: номер уже ведёт в кабинет partner_id={existing.partner_id}.")
                print("Один номер не может вести в два кабинета — разбери вручную.")
                sys.exit(1)
            return

        if not apply:
            print("\nDRY-RUN: будет создана строка partner_identities:")
            print(f"  partner_id={partner.id}, kind={KIND!r}, value={value!r}")
            print("Для записи запусти с --apply")
            return

        session.add(PartnerIdentity(partner_id=partner.id, kind=KIND, value=value))
        session.commit()
        print(f"ГОТОВО: номер {value} привязан к кабинету partner_id={partner.id} ({partner.kommo_agent_name}).")
        print("Проверь вход: /account → ввод номера → код в WhatsApp.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
