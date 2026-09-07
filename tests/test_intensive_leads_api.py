"""Заявки на интенсив наружу: GET /admin/api/intensive-leads (ТЗ маркетолога 07.09.2026).

Цифры не врут: заявка это строка с applied_at, срез since и дни по ней же, а не
по created_at; total = сумма по источникам. Наружу ничего лишнего: без права
404 байт в байт как у несуществующего адреса, в теле ни имени, ни telegram_id,
ни email, только числа и метки источника.

Запуск:  python tests/test_intensive_leads_api.py   |   pytest tests/test_intensive_leads_api.py
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from admin_api_stand import (  # noqa: E402
    TOKEN, assert_refusal_indistinguishable, assert_success_headers_and_short_head,
    fingerprint, logs, owner_cookie, run_as_script, sql_seen, stand,
)
from app import intensive_stats  # noqa: E402
from app.models import IntensiveLead  # noqa: E402

URL = "/admin/api/intensive-leads"
MISSING = "/admin/api/intensive-leadz"
NOW = datetime(2026, 9, 7, 12, 0, 0)


def _lead(telegram_id, *, applied_days_ago=None, source="cheklist", created_days_ago=0,
          username="nikolina", first_name="Мария", email="maria@example.com"):
    """Человек в боте оплат. ПД задаём НАРОЧНО: сторож ищет их в ответе."""
    applied = None if applied_days_ago is None else NOW - timedelta(days=applied_days_ago)
    return IntensiveLead(
        telegram_id=telegram_id, username=username, first_name=first_name, email=email,
        status="new", applied_at=applied, applied_source=source if applied else None,
        invite_link="https://t.me/+secret-invite", lava_invoice_url="https://lava.top/secret",
        created_at=NOW - timedelta(days=created_days_ago),
    )


def _get(client, **params):
    r = client.get(URL, params=params, headers={"X-Api-Token": TOKEN})
    assert r.status_code == 200, r.text
    return r.json()


# ─── (а) цифры ───────────────────────────────────────────────────────────────

def test_total_by_source_by_day():
    with stand(
        _lead(101, applied_days_ago=0), _lead(102, applied_days_ago=0),
        _lead(103, applied_days_ago=1),
        _lead(104, applied_days_ago=0, source="statya"),
        _lead(105, applied_days_ago=2, source="statya"),
        _lead(106),                                   # в боте, но заявки не оставлял
    ) as (client, _):
        body = _get(client)
        assert list(body) == ["generated_at", "since", "total", "by_source", "by_day"]
        assert body["since"] is None
        assert body["total"] == 5
        assert body["by_source"] == {"cheklist": 3, "statya": 2}
        assert body["by_day"] == {"2026-09-05": 1, "2026-09-06": 1, "2026-09-07": 3}
        assert list(body["by_day"]) == ["2026-09-05", "2026-09-06", "2026-09-07"]
        assert body["total"] == sum(body["by_source"].values()) == sum(body["by_day"].values())


def test_since_goes_by_applied_at_not_created_at():
    with stand(
        _lead(201, applied_days_ago=0, created_days_ago=40),   # в боте давно, заявка сегодня
        _lead(202, applied_days_ago=10, created_days_ago=10),
        _lead(203, created_days_ago=0),                        # свежий, но без заявки
    ) as (client, _):
        body = _get(client, since="2026-09-01")
        assert body["since"] == "2026-09-01"
        assert body["total"] == 1 and body["by_day"] == {"2026-09-07": 1}
        assert _get(client)["total"] == 2
        assert _get(client, since=" 2026-9-1 ")["since"] == "2026-09-01", "эхо нормализованное"


def test_empty_period_is_zero_and_empty_dicts():
    with stand(_lead(301, applied_days_ago=5)) as (client, _):
        body = _get(client, since="2026-09-08")
        assert (body["total"], body["by_source"], body["by_day"]) == (0, {}, {})
    with stand() as (client, _):
        body = _get(client)
        assert (body["total"], body["by_source"], body["by_day"]) == (0, {}, {})


def test_source_without_label_is_counted_not_lost():
    with stand(_lead(401, applied_days_ago=0), _lead(402, applied_days_ago=0)) \
            as (client, session):
        session.query(IntensiveLead).filter_by(telegram_id=402).update({"applied_source": None})
        session.commit()
        body = _get(client)
        assert body["by_source"] == {"cheklist": 1, intensive_stats.UNKNOWN_SOURCE: 1}
        assert body["total"] == 2


def test_function_and_route_give_the_same_numbers():
    with stand(_lead(501, applied_days_ago=0), _lead(502, applied_days_ago=1, source="post")) \
            as (client, session):
        direct = intensive_stats.applied_counts(session)
        body = _get(client)
        assert list(direct) == ["total", "by_source", "by_day"]
        assert {k: body[k] for k in direct} == direct


# ─── (б) кривой since = отказ ────────────────────────────────────────────────

def test_since_broken_is_bare_404():
    with stand(_lead(601, applied_days_ago=0)) as (client, _):
        etalon = fingerprint(client.get(MISSING))
        for bad in ("05.09.2026", "2026-13-45", "вчера"):
            r = client.get(URL, params={"since": bad}, headers={"X-Api-Token": TOKEN})
            assert fingerprint(r) == etalon, f"since={bad!r} выдаёт адрес"


# ─── (в) право и неотличимость отказа ────────────────────────────────────────

def test_refusal_is_indistinguishable_from_a_missing_address():
    with stand(_lead(701, applied_days_ago=0)) as (client, session):
        assert_refusal_indistinguishable(client, session, URL, MISSING)


def test_owner_cookie_opens_the_door():
    with stand(_lead(711, applied_days_ago=0)) as (client, session):
        owner_cookie(session, client)
        assert client.get(URL).status_code == 200
        assert client.get(URL, headers={"X-Api-Token": "starye-klyuchi"}).status_code == 200


def test_empty_setting_closes_token_door():
    with stand(_lead(721, applied_days_ago=0), token="") as (client, _):
        assert client.get(URL, headers={"X-Api-Token": ""}).status_code == 404
        assert client.get(URL).status_code == 404


def test_success_headers_and_short_head():
    with stand(_lead(731, applied_days_ago=0)) as (client, session):
        assert_success_headers_and_short_head(client, session, URL, "intensive-leads")


def test_route_not_in_public_catalogue():
    with stand(_lead(741, applied_days_ago=0)) as (client, _):
        schema = client.get("/openapi.json")
        assert schema.status_code == 200
        assert URL not in schema.json()["paths"] and "intensive-leads" not in schema.text


def test_closed_door_leaves_a_trace_without_the_key():
    with stand(_lead(751, applied_days_ago=0)) as (client, _):
        with logs() as written:
            client.get(URL, headers={"X-Api-Token": "sovsem-ne-tot-klyuch"})
        trace = [w for w in written if "intensive-leads" in w]
        assert trace and trace[0].startswith("WARNING"), "закрытая дверь молчит"
        assert "sovsem-ne-tot-klyuch" not in "\n".join(written), "ключ уехал в журнал"
        with logs() as written:
            client.get(URL, headers={"X-Api-Token": TOKEN})
        assert [w for w in written if w.startswith("INFO") and "intensive-leads" in w]
        with logs() as written:
            client.get(URL, params={"since": "kriv\nWARNING intensive-leads: подделка"},
                       headers={"X-Api-Token": TOKEN})
        assert all("\n" not in w for w in written if "intensive-leads" in w)


# ─── (г) сторож ПД и только чтение ───────────────────────────────────────────

def test_no_personal_data_in_body():
    with stand(
        _lead(700100200, applied_days_ago=0, username="nikolina", first_name="Мария",
              email="maria@example.com"),
        _lead(700100201, applied_days_ago=0, source="statya", username="petrov",
              first_name="Пётр", email="petr@example.com"),
    ) as (client, _):
        body = client.get(URL, headers={"X-Api-Token": TOKEN}).text
        for key in ("telegram_id", "username", "first_name", "email", "invite_link",
                    "lava_invoice", "partner_id", "ref_slug", "status"):
            assert key not in body, f"ключ {key} уехал наружу"
        for value in ("700100200", "700100201", "nikolina", "petrov", "Мария", "Пётр",
                      "example.com", "secret-invite", "lava.top"):
            assert value not in body, f"значение {value!r} уехало наружу"


def test_endpoint_only_reads():
    with stand(_lead(801, applied_days_ago=0)) as (client, session):
        with sql_seen(session) as seen:
            assert client.get(URL, headers={"X-Api-Token": TOKEN}).status_code == 200
        assert seen == ["SELECT", "SELECT"], f"ждали два SELECT: {seen}"
        assert not (session.new or session.dirty or session.deleted)


if __name__ == "__main__":
    run_as_script(globals())
