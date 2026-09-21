"""Очередь сторожа для AI-Стаси: смотреть можно, управлять нельзя.

Решение Николь 21.09.2026: Стасе дали посмотреть, кому сторож напишет, но не
рычаги. Стася живым людям сама не пишет, а живой запуск сторожа — это письма
без «да» на каждое. Поэтому у неё свой узкий ключ, и главный сторож здесь —
что этим ключом НЕ открывается живой запуск.

Второе: что уезжает наружу. Имя, @ник и код рассылки — да, Стасе по ним искать
переписку. telegram_id и пригласительная ссылка — нет.

Запуск:  pytest tests/test_nudge_queue_api.py
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from admin_api_stand import stand  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app import channel_nudge  # noqa: E402
from app.config import settings  # noqa: E402
from app.models import ChannelSubscriber  # noqa: E402

URL = "/admin/api/nudge-queue"
NARROW = "narrow-queue-token-000000000000"


def _sub(tid, *, status="asked", hours_ago=48, nudged_days_ago=None,
         opened=False, username="visausa24", name="Антон", source="jr:pc7dpkk"):
    now = datetime.utcnow()
    return ChannelSubscriber(
        telegram_id=tid, first_name=name, username=username, status=status,
        pending_request=status == "asked", source=source,
        created_at=now - timedelta(hours=hours_ago),
        nudged_at=(now - timedelta(days=nudged_days_ago)
                   if nudged_days_ago is not None else None),
        bot_opened_at=now if opened else None,
        invite_link="https://t.me/+secret-invite")


class Narrow:
    """Стенд с узким ключом и базой сторожа на том же движке."""

    def __init__(self, *rows):
        self.ctx = stand(*rows)

    def __enter__(self):
        client, session = self.ctx.__enter__()
        self.saved = (channel_nudge.SessionLocal, settings.NUDGE_QUEUE_TOKEN)
        channel_nudge.SessionLocal = sessionmaker(bind=session.get_bind())
        settings.NUDGE_QUEUE_TOKEN = NARROW
        return client

    def __exit__(self, *exc):
        channel_nudge.SessionLocal, settings.NUDGE_QUEUE_TOKEN = self.saved
        return self.ctx.__exit__(*exc)


def _get(client, token=NARROW, url=URL):
    return client.get(url, headers={"X-Api-Token": token})


# ─── дверь ───────────────────────────────────────────────────────────────────

def test_uzkiy_klyuch_otkryvaet_ochered():
    with Narrow(_sub(1)) as client:
        assert _get(client).status_code == 200


def test_uzkiy_klyuch_ne_otkryvaet_zhivoy_zapusk():
    """Главное: ключ Стаси не запускает сторожа, ни сухо, ни живьём."""
    with Narrow(_sub(2)) as client:
        assert _get(client, url="/admin/api/nudge-run").status_code == 404
        assert _get(client, url="/admin/api/nudge-run?live=1").status_code == 404


def test_uzkiy_klyuch_ne_otkryvaet_sosedey():
    with Narrow() as client:
        for url in ("/admin/api/channel-tags", "/admin/api/channel-stats"):
            assert _get(client, url=url).status_code == 404, url


def test_bez_klyucha_404():
    with Narrow(_sub(3)) as client:
        assert _get(client, token="").status_code == 404
        assert _get(client, token="wrong").status_code == 404


def test_chuzhoy_metod_404():
    with Narrow(_sub(4)) as client:
        assert client.post(URL, headers={"X-Api-Token": NARROW}).status_code == 404


def test_pustaya_nastroyka_ne_otkryvaet_dver():
    """Незаполненная переменная не должна пускать пустой заголовок."""
    with Narrow(_sub(5)) as client:
        settings.NUDGE_QUEUE_TOKEN = ""
        assert _get(client, token="").status_code == 404


# ─── что внутри ──────────────────────────────────────────────────────────────

def test_ochered_i_napisannye():
    with Narrow(
        _sub(10, hours_ago=48),                                   # в очереди
        _sub(12, status="in_channel", nudged_days_ago=1,
             opened=True, username="voshyol"),                    # уже написано, вошёл
    ) as client:
        body = _get(client).json()
    assert [q["username"] for q in body["queue"]] == ["visausa24"]
    assert body["queue"][0]["code"] == "pc7dpkk"
    assert [r["username"] for r in body["recent"]] == ["voshyol"]
    assert body["recent"][0]["in_channel"] is True
    assert body["recent"][0]["opened_bot"] is True


def test_ochered_po_chasam_progona():
    """Кто созреет к ближайшему прогону (09:00 UTC), тот в очереди; кто нет —
    ещё нет. Время фиксированное: от него зависит ответ."""
    now = datetime(2026, 9, 21, 20, 0)        # прогон завтра в 09:00
    rows = [
        # подана в 08:00 сегодня: к 09:00 завтра ей 25 часов — созреет
        ChannelSubscriber(telegram_id=21, first_name="А", username="zreet",
                          status="asked", pending_request=True, source="jr:a",
                          created_at=datetime(2026, 9, 21, 8, 0)),
        # подана в 19:00 сегодня: к 09:00 завтра ей 14 часов — ещё нет
        ChannelSubscriber(telegram_id=22, first_name="Б", username="rano",
                          status="asked", pending_request=True, source="jr:b",
                          created_at=datetime(2026, 9, 21, 19, 0)),
    ]
    with Narrow(*rows):
        snap = channel_nudge.queue_snapshot(now=now)
    assert [q["username"] for q in snap["queue"]] == ["zreet"]
    assert snap["next_run_utc"] == "2026-09-22T09:00"


def test_naruzhu_net_telegram_id_i_ssylok():
    with Narrow(_sub(987654321)) as client:
        text = _get(client).text
    assert "987654321" not in text
    assert "secret-invite" not in text
    assert "telegram_id" not in text


def test_zayavka_sozreet_k_progonu_popadaet_v_ochered():
    """Стасе важно заранее: кто созреет к ближайшему прогону, тот в очереди,
    даже если сейчас ему меньше суток."""
    now = datetime(2026, 9, 21, 20, 0)
    run = channel_nudge.next_run(now)
    assert run == datetime(2026, 9, 22, 9, 0)
    assert channel_nudge.next_run(datetime(2026, 9, 21, 8, 0)) == datetime(2026, 9, 21, 9, 0)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
