"""Привратник канала наружу: GET /admin/api/channel-stats (план 2026-09-09).

Цифры не врут: заявка это строка channel_subscribers, срез since и дни по
created_at, состояние текущее, все шесть ключей в каждом срезе, total = сумма
по состояниям. Наружу ничего лишнего: без права 404 байт в байт как у
несуществующего адреса, в теле ни имени, ни telegram_id, ни username, только
числа и имена состояний.

Запуск:  python tests/test_channel_stats_api.py   |   pytest tests/test_channel_stats_api.py
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from admin_api_stand import (  # noqa: E402
    TOKEN, assert_refusal_indistinguishable, assert_success_headers_and_short_head,
    fingerprint, logs, owner_cookie, run_as_script, sql_seen, stand,
)
from app import channel_stats  # noqa: E402
from app.models import ChannelSubscriber  # noqa: E402

URL = "/admin/api/channel-stats"
MISSING = "/admin/api/channel-statz"
NOW = datetime(2026, 9, 7, 12, 0, 0)
ZEROS = {"asked": 0, "confirmed": 0, "invited": 0, "in_channel": 0, "left": 0, "declined": 0}


def _sub(telegram_id, status="asked", *, days_ago=0, source="dl:sep",
         username="nikolina", first_name="Мария"):
    """Человек у привратника. ПД задаём НАРОЧНО: сторож ищет их в ответе."""
    born = NOW - timedelta(days=days_ago)
    confirmed = status not in ("asked", "declined")
    invited = status in ("invited", "in_channel", "left")
    return ChannelSubscriber(
        telegram_id=telegram_id, username=username, first_name=first_name,
        status=status, source=source, created_at=born,
        age_confirmed_at=born + timedelta(minutes=5) if confirmed else None,
        invited_at=born + timedelta(minutes=10) if invited else None,
        invite_link="https://t.me/+secret-invite" if invited else None,
    )


def _get(client, **params):
    r = client.get(URL, params=params, headers={"X-Api-Token": TOKEN})
    assert r.status_code == 200, r.text
    return r.json()


# ─── (а) цифры ───────────────────────────────────────────────────────────────

def test_total_by_status_by_day():
    with stand(
        _sub(101, "asked"), _sub(102, "asked"),
        _sub(103, "in_channel"), _sub(104, "in_channel", days_ago=1),
        _sub(105, "invited", days_ago=1), _sub(106, "confirmed", days_ago=1),
        _sub(107, "left", days_ago=2), _sub(108, "declined", days_ago=2),
    ) as (client, _):
        body = _get(client)
        assert list(body) == ["generated_at", "since", "total", "by_status", "by_day"]
        assert body["since"] is None
        assert body["total"] == 8
        assert body["by_status"] == {"asked": 2, "confirmed": 1, "invited": 1,
                                     "in_channel": 2, "left": 1, "declined": 1}
        assert list(body["by_status"]) == list(ZEROS), "состояния в порядке пути"
        assert body["by_day"] == {
            "2026-09-05": {**ZEROS, "left": 1, "declined": 1},
            "2026-09-06": {**ZEROS, "in_channel": 1, "invited": 1, "confirmed": 1},
            "2026-09-07": {**ZEROS, "asked": 2, "in_channel": 1},
        }
        assert list(body["by_day"]) == ["2026-09-05", "2026-09-06", "2026-09-07"]
        for day in body["by_day"].values():
            assert list(day) == list(ZEROS), "в каждом дне все шесть ключей по порядку"
        assert body["total"] == sum(body["by_status"].values()) \
            == sum(sum(d.values()) for d in body["by_day"].values())


def test_since_goes_by_created_at():
    with stand(
        _sub(201, "in_channel", days_ago=40),   # заявка давно, в канале до сих пор
        _sub(202, "asked", days_ago=10),
        _sub(203, "invited"),
    ) as (client, _):
        body = _get(client, since="2026-09-01")
        assert body["since"] == "2026-09-01"
        assert body["total"] == 1
        assert body["by_status"] == {**ZEROS, "invited": 1}
        assert body["by_day"] == {"2026-09-07": {**ZEROS, "invited": 1}}
        assert _get(client)["total"] == 3
        assert _get(client, since="2026-08-28")["total"] == 2, "since включает день"
        assert _get(client, since=" 2026-9-1 ")["since"] == "2026-09-01", "эхо нормализованное"


def test_empty_base_and_future_since_are_zeros():
    with stand() as (client, _):
        body = _get(client)
        assert (body["total"], body["by_status"], body["by_day"]) == (0, ZEROS, {})
    with stand(_sub(301, "in_channel", days_ago=5), _sub(302, "asked")) as (client, _):
        body = _get(client, since="2026-09-08")
        assert (body["total"], body["by_status"], body["by_day"]) == (0, ZEROS, {})
        assert list(body["by_status"]) == list(ZEROS), "нули под всеми шестью ключами"


def test_unknown_status_is_counted_not_lost():
    with stand(_sub(401, "asked"), _sub(402, "asked")) as (client, session):
        session.query(ChannelSubscriber).filter_by(telegram_id=402).update({"status": "kicked"})
        session.commit()
        body = _get(client)
        assert body["by_status"] == {**ZEROS, "asked": 1, "kicked": 1}
        assert body["by_day"] == {"2026-09-07": {**ZEROS, "asked": 1, "kicked": 1}}
        assert body["total"] == 2


def test_statuses_are_the_gatekeepers_own():
    # Один кортеж на channel-tags и channel-stats: разойтись им не с чего.
    from app import channel_gate
    assert channel_stats.STATUSES is channel_gate.TAG_STATUSES
    assert tuple(ZEROS) == channel_stats.STATUSES


def test_function_and_route_give_the_same_numbers():
    with stand(_sub(501, "asked"), _sub(502, "in_channel", days_ago=1)) as (client, session):
        direct = channel_stats.subscriber_counts(session)
        body = _get(client)
        assert list(direct) == ["total", "by_status", "by_day"]
        assert {k: body[k] for k in direct} == direct


def test_since_of_spaces_means_no_cut():
    with stand(_sub(601, "asked"), _sub(602, "left", days_ago=5)) as (client, _):
        r = client.get(URL, params={"since": "  "}, headers={"X-Api-Token": TOKEN})
        assert r.status_code == 200, r.text
        assert r.json()["since"] is None and r.json()["total"] == 2


# ─── (б) кривой since = отказ ────────────────────────────────────────────────

def test_since_broken_is_bare_404():
    with stand(_sub(701, "asked")) as (client, _):
        etalon = fingerprint(client.get(MISSING))
        for bad in ("05.09.2026", "2026-13-45", "вчера", "2026-09-07\x00", "\x002026-09-07"):
            r = client.get(URL, params={"since": bad}, headers={"X-Api-Token": TOKEN})
            assert fingerprint(r) == etalon, f"since={bad!r} выдаёт адрес"


# ─── (в) право и неотличимость отказа ────────────────────────────────────────

def test_refusal_is_indistinguishable_from_a_missing_address():
    with stand(_sub(801, "asked")) as (client, session):
        assert_refusal_indistinguishable(client, session, URL, MISSING)


def test_owner_cookie_opens_the_door():
    with stand(_sub(811, "asked")) as (client, session):
        owner_cookie(session, client)
        assert client.get(URL).status_code == 200
        assert client.get(URL, headers={"X-Api-Token": "starye-klyuchi"}).status_code == 200


def test_empty_setting_closes_token_door():
    with stand(_sub(821, "asked"), token="") as (client, _):
        assert client.get(URL, headers={"X-Api-Token": ""}).status_code == 404
        assert client.get(URL).status_code == 404


def test_success_headers_and_short_head():
    with stand(_sub(831, "asked")) as (client, session):
        assert_success_headers_and_short_head(client, session, URL, "channel-stats")


def test_route_not_in_public_catalogue():
    with stand(_sub(841, "asked")) as (client, _):
        schema = client.get("/openapi.json")
        assert schema.status_code == 200
        assert URL not in schema.json()["paths"] and "channel-stats" not in schema.text


def test_closed_door_leaves_a_trace_without_the_key():
    with stand(_sub(851, "asked")) as (client, _):
        with logs() as written:
            client.get(URL, headers={"X-Api-Token": "sovsem-ne-tot-klyuch"})
        trace = [w for w in written if "channel-stats" in w]
        assert trace and trace[0].startswith("WARNING"), "закрытая дверь молчит"
        assert "sovsem-ne-tot-klyuch" not in "\n".join(written), "ключ уехал в журнал"
        with logs() as written:
            client.get(URL, headers={"X-Api-Token": TOKEN})
        assert [w for w in written if w.startswith("INFO") and "channel-stats" in w]
        with logs() as written:
            client.get(URL, params={"since": "kriv\nWARNING channel-stats: подделка"},
                       headers={"X-Api-Token": TOKEN})
        assert all("\n" not in w for w in written if "channel-stats" in w)


# ─── (г) сторож ПД и только чтение ───────────────────────────────────────────

def test_no_personal_data_in_body():
    with stand(
        _sub(700100200, "in_channel", username="nikolina", first_name="Мария"),
        _sub(700100201, "asked", username="petrov", first_name="Пётр", source="jr:"),
    ) as (client, _):
        body = client.get(URL, headers={"X-Api-Token": TOKEN}).text
        for key in ("telegram_id", "username", "first_name", "invite_link", "source",
                    "pending_request", "age_confirmed_at", "invited_at", "tag"):
            assert key not in body, f"ключ {key} уехал наружу"
        for value in ("700100200", "700100201", "nikolina", "petrov", "Мария", "Пётр",
                      "secret-invite", "dl:sep", "jr:"):
            assert value not in body, f"значение {value!r} уехало наружу"


def test_endpoint_only_reads():
    with stand(_sub(901, "asked")) as (client, session):
        with sql_seen(session) as seen:
            assert client.get(URL, headers={"X-Api-Token": TOKEN}).status_code == 200
        assert seen == ["SELECT"], f"ждали один SELECT: {seen}"
        assert not (session.new or session.dirty or session.deleted)


if __name__ == "__main__":
    run_as_script(globals())
