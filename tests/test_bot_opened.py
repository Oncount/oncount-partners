"""Переход по ссылке: кто САМ открыл бота, а кому написал бот.

Вопрос Николь 20.09.2026 после первой отправки сторожа: «сколько получили,
сколько перешли, сколько зашли?». Ответить было нечем: статус движется только
по нажатию кнопки «Вступить», поэтому человек, который открыл бота и передумал,
выглядел в отчёте ровно как тот, кто ссылку не открывал. Без этой разницы не
видно, где рвётся воронка — на письме или на кнопке.

Стережём три вещи: отметка ставится, когда человек пришёл сам; НЕ ставится,
когда бот написал ему по заявке; и не переписывается при повторном заходе
(интересен момент прихода, а не последнее касание).

БД — in-memory SQLite. Сети нет.

Запуск:  pytest tests/test_bot_opened.py
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("JWT_SECRET", "test-secret-not-the-default-value-000")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://t:t@localhost:5432/t")
os.environ["PAY_BOT_TOKEN"] = ""

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app import channel_gate  # noqa: E402
from app.channel_stats import subscriber_counts  # noqa: E402
from app.models import Base, ChannelSubscriber  # noqa: E402

engine = create_engine("sqlite://", future=True)
Base.metadata.create_all(engine)
TestSession = sessionmaker(bind=engine, future=True)
channel_gate.SessionLocal = TestSession


def setup_function() -> None:
    with TestSession() as s:
        s.query(ChannelSubscriber).delete()
        s.commit()


class FakeUser:
    def __init__(self, uid):
        self.id, self.username, self.first_name = uid, "u", "Антон"


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))


def ask(uid, source="dl:abc", opened_bot=False):
    asyncio.run(channel_gate.ask_age(FakeBot(), uid, FakeUser(uid), source,
                                     opened_bot=opened_bot))


def row(uid):
    with TestSession() as s:
        return s.query(ChannelSubscriber).filter_by(telegram_id=uid).first()


def test_prishyol_sam_otmetka_stavitsya():
    ask(111, opened_bot=True)
    assert row(111).bot_opened_at is not None


def test_bot_napisal_sam_otmetki_net():
    """Заявка в канал: пишет бот, человек ещё никуда не переходил."""
    ask(222, source="jr:kod1234", opened_bot=False)
    assert row(222).bot_opened_at is None


def test_data_ne_perepisyvaetsya():
    """Второй заход не сдвигает дату: интересен момент прихода."""
    ask(333, opened_bot=True)
    first = row(333).bot_opened_at
    with TestSession() as s:
        sub = s.query(ChannelSubscriber).filter_by(telegram_id=333).first()
        sub.bot_opened_at = first - timedelta(days=2)
        s.commit()
        was = sub.bot_opened_at
    ask(333, opened_bot=True)
    assert row(333).bot_opened_at == was


def test_snachala_zayavka_potom_prishyol_sam():
    """Главный случай сторожа: бот написал по заявке, человек потом нажал
    ссылку из письма. Переход обязан посчитаться."""
    ask(444, source="jr:kod1234", opened_bot=False)
    assert row(444).bot_opened_at is None
    ask(444, source="dl:kod1234", opened_bot=True)
    assert row(444).bot_opened_at is not None


# ─── счётчики ────────────────────────────────────────────────────────────────

def test_schyotchik_v_svodke():
    ask(555, opened_bot=True)
    ask(666, opened_bot=False)
    with TestSession() as s:
        counts = subscriber_counts(s)
    assert counts["total"] == 2
    assert counts["bot_opened"] == 1


def test_schyotchik_po_metkam():
    ask(777, source="jr:kodaaa", opened_bot=True)
    ask(888, source="jr:kodaaa", opened_bot=False)
    with TestSession() as s:
        rows = channel_gate.tag_counts(s, prefix="jr:")
    assert len(rows) == 1
    assert rows[0]["bot_opened"] == 1
    assert rows[0]["asked"] == 2, "переход не должен подменять статус"


def test_bot_opened_ne_status():
    """bot_opened пересекается со статусами и в их сумму не входит:
    сложить всё вместе значит посчитать человека дважды."""
    ask(999, source="jr:kodbbb", opened_bot=True)
    with TestSession() as s:
        r = channel_gate.tag_counts(s, prefix="jr:")[0]
    six = sum(r[k] for k in ("asked", "confirmed", "invited",
                             "in_channel", "left", "declined"))
    assert six == 1 and r["bot_opened"] == 1


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
