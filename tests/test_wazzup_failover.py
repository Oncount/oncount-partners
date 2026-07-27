"""Тесты резерва WhatsApp-канала (2026-07-27).

Почему это вообще есть: канал Wazzup живёт по QR и отваливается в qridle сам по
себе — 27.07 так легли три номера разом, и вместе с ними тихо умерли вход в
кабинет по коду и доставка чек-листов. Резерв должен переключаться САМ.

Сеть не трогаем: httpx.post/get подменяются заглушками.
Запуск без pytest:  python tests/test_wazzup_failover.py
Под pytest:         pytest tests/test_wazzup_failover.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("JWT_SECRET", "test-secret-not-default")
os.environ.setdefault("BOT_TOKEN", "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw")

from app import wazzup                                              # noqa: E402
from app.config import settings                                     # noqa: E402

PRIMARY, BACKUP = "chan-primary", "chan-backup"


class _Resp:
    def __init__(self, status_code: int, text: str = "", payload=None):
        self.status_code, self.text, self._payload = status_code, text, payload

    def json(self):
        return self._payload


def _setup(states: dict, post_results: list):
    """Подменяет сеть: /v3/channels отдаёт states, /v3/message — по очереди из
    post_results. Возвращает список каналов, в которые реально ушёл POST."""
    used = []
    settings.WAZZUP_API_KEY = "test-key"
    settings.WAZZUP_CHANNEL_ID = PRIMARY
    settings.WAZZUP_FALLBACK_CHANNEL_IDS = BACKUP
    settings.WAZZUP_TEST_ONLY_NUMBER = ""
    wazzup._states_cache, wazzup._states_at = {}, 0.0

    def fake_get(url, **kw):
        return _Resp(200, payload=[{"channelId": k, "state": v} for k, v in states.items()])

    def fake_post(url, **kw):
        used.append(kw["json"]["channelId"])
        return post_results.pop(0) if post_results else _Resp(201)

    wazzup.httpx.get, wazzup.httpx.post = fake_get, fake_post
    return used


def test_primary_alive_backup_not_touched():
    used = _setup({PRIMARY: "active", BACKUP: "active"}, [_Resp(201)])
    assert wazzup.send_wa_code("+971500000000", "123456") is True
    assert used == [PRIMARY], "живой основной канал не должен уходить в резерв"


def test_primary_qridle_goes_to_backup():
    # Ровно случай 27.07: номер отвалился в qridle, код входа обязан уйти резервом.
    used = _setup({PRIMARY: "qridle", BACKUP: "active"}, [_Resp(201)])
    assert wazzup.send_wa_code("+971500000000", "123456") is True
    assert used == [BACKUP], "мёртвый канал должен пропускаться ДО отправки"


def test_primary_http_error_falls_back():
    # Состояние active, но Wazzup ответил ошибкой → добираем резервом.
    used = _setup({PRIMARY: "active", BACKUP: "active"}, [_Resp(500, "boom"), _Resp(201)])
    assert wazzup.send_wa_text("+971500000000", "чек-лист") is True
    assert used == [PRIMARY, BACKUP]


def test_all_channels_dead_returns_false():
    used = _setup({PRIMARY: "qridle", BACKUP: "blocked"}, [])
    assert wazzup.send_wa_text("+971500000000", "чек-лист") is False
    assert used == [], "в мёртвые каналы не стучимся вообще"


def test_unknown_state_is_tried_not_skipped():
    # Незнакомое состояние — пробуем: молча не отправить код хуже, чем попробовать.
    used = _setup({PRIMARY: "somethingNew", BACKUP: "active"}, [_Resp(201)])
    assert wazzup.send_wa_code("+971500000000", "123456") is True
    assert used == [PRIMARY]


def test_chain_dedupes_and_drops_empty():
    settings.WAZZUP_FALLBACK_CHANNEL_IDS = f" {BACKUP} , , {PRIMARY} "
    assert wazzup._chain(PRIMARY) == [PRIMARY, BACKUP]
    assert wazzup._chain("") == [BACKUP, PRIMARY]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} тестов пройдено.")
