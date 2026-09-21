"""Сторож зависших заявок: кому пишет, кому молчит, и почему один раз.

Сторож — единственное место, где система пишет живым людям сама, без «да» на
каждое письмо. Согласовано это ровно в тех границах, что здесь и проверяются:
сутки выдержки, один раз за жизнь заявки, никого лишнего, потолок за прогон.
Ошибка в любом из четырёх правил — это не «неудобно», а письмо человеку,
который его не ждал, или второе письмо тому, кто уже сказал «нет».

Отдельно стережём выключенный режим: при NUDGE_ENABLED=0 сторож обязан СЧИТАТЬ
очередь и доложить Николь. Молчащий сторож, за которым стоит очередь людей, —
это ровно та поломка, ради которой он написан.

БД — in-memory SQLite, отправка подменена: сети в тесте нет.

Запуск:  pytest tests/test_channel_nudge.py
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("JWT_SECRET", "test-secret-not-the-default-value-000")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://t:t@localhost:5432/t")
os.environ["PAY_BOT_TOKEN"] = ""

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app import channel_config as T  # noqa: E402
from app import channel_nudge  # noqa: E402
from app import wazzup  # noqa: E402
from app.config import settings  # noqa: E402
from app.models import Base, ChannelSubscriber  # noqa: E402

engine = create_engine("sqlite://", future=True)
Base.metadata.create_all(engine)
TestSession = sessionmaker(bind=engine, future=True)
channel_nudge.SessionLocal = TestSession


def setup_function() -> None:
    """Чистая база и включённый сторож перед каждым тестом."""
    with TestSession() as s:
        s.query(ChannelSubscriber).delete()
        s.commit()
    settings.NUDGE_ENABLED = True
    settings.WAZZUP_API_KEY = "test-key"
    settings.WAZZUP_TG_CHANNEL_ID = "test-channel"
    settings.NUDGE_MAX_PER_RUN = 30


def add(telegram_id: int, *, status="asked", pending=True, hours_ago=48,
        nudged=False, source="jr:abc1234", name="Антон") -> None:
    with TestSession() as s:
        s.add(ChannelSubscriber(
            telegram_id=telegram_id, first_name=name, status=status,
            pending_request=pending, source=source,
            nudged_at=datetime.utcnow() if nudged else None,
            created_at=datetime.utcnow() - timedelta(hours=hours_ago)))
        s.commit()


class FakeSender:
    """Подмена Wazzup: собирает, кому и что ушло бы."""

    def __init__(self, ok=True):
        self.ok, self.sent = ok, []

    def __call__(self, telegram_id, text):
        self.sent.append((telegram_id, text))
        return self.ok


def run(sender=None, notify_box=None):
    """Прогон без пауз: сон между сообщениями в тесте не нужен."""
    old = wazzup.send_tg_text
    wazzup.send_tg_text = sender or FakeSender()
    try:
        notes = []
        stats = channel_nudge.run_once(
            notify=(notify_box if notify_box is not None else notes).append, pause=0)
        return stats
    finally:
        wazzup.send_tg_text = old


# ─── кому пишем ──────────────────────────────────────────────────────────────

def test_pishet_tomu_kto_visit_dolshe_sutok():
    add(111, hours_ago=48)
    sender = FakeSender()
    stats = run(sender)
    assert stats["sent"] == 1
    assert sender.sent[0][0] == 111
    assert "Антон" in sender.sent[0][1]


def test_svezhuyu_zayavku_ne_trogaet():
    """Заявка младше суток: человек мог ответить боту вечером, письмо лишнее."""
    add(222, hours_ago=3)
    stats = run()
    assert stats == {"found": 0, "sent": 0, "failed": 0, "left": 0}


def test_bez_imeni_drugoy_tekst():
    add(333, name="")
    sender = FakeSender()
    run(sender)
    assert sender.sent[0][1].startswith("Здравствуйте, это Николь")


# ─── кому НЕ пишем ───────────────────────────────────────────────────────────

def test_ne_pishet_tomu_kto_uzhe_v_kanale():
    add(444, status="in_channel", pending=False)
    assert run()["found"] == 0


def test_ne_pishet_tomu_kto_skazal_pozzhe():
    """«Позже» — это ответ человека. Догонять его письмом нельзя."""
    add(555, status="declined", pending=False)
    assert run()["found"] == 0


def test_ne_pishet_tomu_kto_vyshel():
    add(666, status="left", pending=False)
    assert run()["found"] == 0


def test_ne_pishet_vtoroy_raz():
    """Главная граница: одно письмо за жизнь заявки."""
    add(777, nudged=True)
    assert run()["found"] == 0


def test_posle_otpravki_vtoroy_progon_molchit():
    add(888)
    assert run()["sent"] == 1
    assert run()["found"] == 0, "второй прогон написал повторно"


def test_ne_dostavleno_metku_ne_stavit():
    """Не дошло — попробуем завтра, а не запишем человека в отписанные."""
    add(999)
    stats = run(FakeSender(ok=False))
    assert (stats["sent"], stats["failed"]) == (0, 1)
    with TestSession() as s:
        assert s.query(ChannelSubscriber).filter_by(telegram_id=999).first().nudged_at is None


# ─── предохранители ──────────────────────────────────────────────────────────

def test_potolok_za_progon():
    for i in range(5):
        add(1000 + i)
    settings.NUDGE_MAX_PER_RUN = 2
    stats = run()
    assert (stats["sent"], stats["left"]) == (2, 3)


def test_vyklyuchennyy_storozh_schitaet_i_dokladyvaet():
    """Выключен — в сеть не ходит, но очередь считает и говорит о ней Николь."""
    add(1111)
    settings.NUDGE_ENABLED = False
    notes = []
    sender = FakeSender()
    stats = run(sender, notify_box=notes)
    assert (stats["found"], stats["sent"], stats["left"]) == (1, 0, 1)
    assert sender.sent == [], "выключенный сторож полез в сеть"
    assert notes and "выключен" in notes[0]


def test_bez_kanala_ne_shlet():
    add(1222)
    settings.WAZZUP_TG_CHANNEL_ID = ""
    sender = FakeSender()
    stats = run(sender)
    assert (stats["sent"], stats["left"]) == (0, 1)
    assert sender.sent == []


def test_otchyot_uhodit_nikole():
    add(1333)
    notes = []
    run(FakeSender(), notify_box=notes)
    assert notes and "Сторож заявок" in notes[0]


# ─── ссылка ──────────────────────────────────────────────────────────────────

def test_ssylka_neset_metku_cheloveka():
    """Код человека возвращается в ссылке: иначе отчёт по меткам рассылки
    потеряет того, за кого эта рассылка заплатила."""
    add(1444, source="jr:pc7dpkk")
    sender = FakeSender()
    run(sender)
    assert "?start=channel-pc7dpkk" in sender.sent[0][1]


def test_obschaya_metka_daet_ssylku_bez_hvosta():
    add(1555, source="join_request")
    sender = FakeSender()
    run(sender)
    assert "?start=channel" in sender.sent[0][1]
    assert "channel-" not in sender.sent[0][1]


def test_otchyot_poimyonnyy():
    """Отчёт уходит в пульт Стаси и называет людей: ник и код, чтобы ответы
    этих людей в переписке было с чем сверить."""
    with TestSession() as s:
        s.add(ChannelSubscriber(
            telegram_id=1666, first_name="Антон", username="visausa24",
            status="asked", pending_request=True, source="jr:pc7dpkk",
            created_at=datetime.utcnow() - timedelta(hours=48)))
        s.commit()
    notes = []
    run(FakeSender(), notify_box=notes)
    assert "Антон @visausa24 (pc7dpkk)" in notes[0]
    assert "1666" not in notes[0], "telegram_id в отчёт не пишем"


def test_nedoshedshih_v_spiske_net():
    """В список «кому написал» попадают только доставленные."""
    add(1777, name="Пётр")
    notes = []
    run(FakeSender(ok=False), notify_box=notes)
    assert "Пётр" not in notes[0]


def test_otchyot_ukhodit_cherez_stasyu_i_ne_teryaetsya():
    """Нет токена Стаси или бот не ответил — отчёт уходит старым путём."""
    from app import health
    calls = []
    old_admin, old_post = health.alert_admin, health.httpx.post
    health.alert_admin = lambda text: calls.append(("oncount", text)) or True

    class Resp:
        def __init__(self, code): self.status_code = code

    try:
        settings.STASYA_BOT_TOKEN = ""
        assert health.alert_stasya("x")
        assert calls == [("oncount", "x")], "без токена — через бот ONCOUNT"

        calls.clear()
        settings.STASYA_BOT_TOKEN = "tok"
        health.httpx.post = lambda *a, **k: Resp(200)
        assert health.alert_stasya("y")
        assert calls == [], "бот Стаси ответил — второй раз не шлём"

        health.httpx.post = lambda *a, **k: Resp(403)
        assert health.alert_stasya("z")
        assert calls == [("oncount", "z")], "бот Стаси отказал — страхует ONCOUNT"
    finally:
        health.alert_admin, health.httpx.post = old_admin, old_post
        settings.STASYA_BOT_TOKEN = ""


def test_teksty_bez_dlinnyh_tire():
    """Правило Николь 24.08.2026: длинных тире в текстах для людей нет."""
    for t in (T.NUDGE_WITH_NAME, T.NUDGE_NO_NAME, T.NUDGE_REPORT,
              T.NUDGE_REPORT_NAMES, T.NUDGE_OFF):
        assert "—" not in t


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
