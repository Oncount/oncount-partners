"""Правила платного клуба, которые нельзя сломать молча (план 2026-08-04).

Проверяем чистую логику — без сети, БД и Telegram: выбор шага цепочки, правило
«месяц только на первый раз», длины периодов, точность сверки по e-mail.

Именно эти четыре места дороже всего ошибиться: неверный шаг шлёт человеку
письмо «через неделю» за два дня до конца; сорванное правило периодов нарушает
прямое решение Николь; неверная длина периода дарит или крадёт оплаченные дни;
сверка подстрокой продлевает доступ не тому человеку.

Запуск:  python tests/test_club_rules.py   |   pytest tests/test_club_rules.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("JWT_SECRET", "test-secret-not-the-default-value-000")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://t:t@localhost:5432/t")

from app import club  # noqa: E402
from app import club_config as T  # noqa: E402
from app import lava  # noqa: E402


class FakeMember:
    """Ровно те поля, которые читают проверяемые функции."""

    def __init__(self, payments_count=0):
        self.payments_count = payments_count


def test_step_for():
    """Шаг цепочки соответствует остатку дней, а не порядку отправки."""
    assert club._step_for(30) == 0, "за месяц до конца писать рано"
    assert club._step_for(7.5) == 0, "за 7,5 дня ещё рано"
    assert club._step_for(7) == 1, "ровно семь дней — первое письмо"
    assert club._step_for(5) == 1
    assert club._step_for(3) == 2, "три дня — второе письмо, не первое"
    assert club._step_for(2) == 2, "остаток 2 дня: «через три дня», а не «неделя»"
    assert club._step_for(1) == 3
    assert club._step_for(0.4) == 3
    assert club._step_for(0) == 4, "день окончания — вопрос «точно не продлеваете»"
    assert club._step_for(-2) == 4, "просрочка не откатывает шаг назад"
    print("ok  выбор шага цепочки")


def test_offer_periods():
    """Решение Николь: месяц показываем только тому, кто ещё не платил."""
    first = club._offer_periods(FakeMember(payments_count=0))
    assert "month" in first, "новичку месяц нужен — это низкий порог входа"
    assert set(T.RENEW_PERIODS).issubset(set(first))

    for paid in (1, 2, 7):
        again = club._offer_periods(FakeMember(payments_count=paid))
        assert "month" not in again, f"после {paid} оплат месяц предлагать нельзя"
        assert again == T.RENEW_PERIODS == ("quarter", "half")

    assert club._offer_periods(None) == ("month",) + T.RENEW_PERIODS
    print("ok  месяц только на первый раз")


def test_period_days():
    """Длина периода берётся из кассы, а не из головы."""
    assert club._period_days("MONTHLY") == 31
    assert club._period_days("PERIOD_90_DAYS") == 92
    assert club._period_days("PERIOD_180_DAYS") == 183
    assert club._period_days("PERIOD_YEAR") == 366
    assert club._period_days(None) == 31, "неизвестный период — минимальный"
    assert club._period_days("ЧУШЬ") == 31
    for code, (periodicity, days) in lava.CLUB_PERIODS.items():
        assert club._period_code(periodicity) == code
        assert days >= 31
    print("ok  длины периодов")


def test_subscription_match():
    """Сверка по e-mail — точная. Подстрока однажды спасла бы не того человека."""
    items = [{"status": "active", "buyer": {"email": "joann@mail.com"}}]
    assert club._subscription_active("joann@mail.com", items) is True
    assert club._subscription_active("ann@mail.com", items) is False, \
        "ann@mail.com не должен находиться внутри joann@mail.com"
    assert club._subscription_active("JoAnn@Mail.com", items) is True, \
        "регистр адреса не должен влиять"

    dead = [{"status": "cancelled", "email": "a@b.com"}]
    assert club._subscription_active("a@b.com", dead) is False

    unknown = [{"status": "", "email": "a@b.com"}]
    assert club._subscription_active("a@b.com", unknown) is True, \
        "неизвестный статус не повод выгнать человека"
    assert club._subscription_active("a@b.com", unknown, strict=True) is False, \
        "но и не повод подарить месяц доступа"

    fresh = [{"status": "new", "email": "a@b.com"}]
    assert club._subscription_active("a@b.com", fresh, strict=True) is False, \
        "созданная, но не оплаченная подписка не открывает платный канал"

    # Подписка на СОСЕДНИЙ продукт не должна считаться клубной.
    other = [{"status": "active", "email": "a@b.com", "offerId": lava.OFFER_INTENSIVE}]
    assert club._subscription_active("a@b.com", other) is False, \
        "подписка на другой продукт не даёт доступ в клуб"
    ours = [{"status": "active", "email": "a@b.com", "offerId": lava.OFFER_CLUB}]
    assert club._subscription_active("a@b.com", ours) is True
    assert club._is_club_record({"status": "active"}) is True, \
        "нет идентификаторов оффера — считаем запись подходящей"

    assert club._emails_visible(items) is True
    assert club._emails_visible([{"id": 1, "status": "active"}]) is False, \
        "нет e-mail в ответе — сверять нечем, удаления надо остановить"
    print("ok  сверка подписки по e-mail")


def test_prices_cover_all_periods():
    """У каждой валюты есть цена на каждый период — иначе кнопка без суммы."""
    for currency, prices in T.PRICES.items():
        for code in lava.CLUB_PERIODS:
            assert code in prices, f"нет цены {code} в {currency}"
        assert prices["quarter"] < prices["month"] * 3, "квартал должен быть выгоднее"
        assert prices["half"] < prices["month"] * 6, "полгода должно быть выгоднее"
    assert "₽" in T.price_label("RUB", "quarter")
    assert "$" in T.price_label("USD", "half")
    print("ok  цены на все периоды")


if __name__ == "__main__":
    test_step_for()
    test_offer_periods()
    test_period_days()
    test_subscription_match()
    test_prices_cover_all_periods()
    print("\nвсе проверки клуба прошли")
