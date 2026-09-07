"""Просмотры страниц наружу: GET /admin/api/page-views (ТЗ маркетолога 07.09.2026).

Два страха, как у соседа channel-tags: цифры не врут (views, unique, by_day по
каждому запрошенному пути, срез since) и наружу не уезжает ничего лишнего:
без права 404 байт в байт как у несуществующего адреса, в теле только числа
и сами запрошенные пути, ни partner_id, ни секций, ни списка чужих путей.

Запуск:  python tests/test_page_views_api.py   |   pytest tests/test_page_views_api.py
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from admin_api_stand import (  # noqa: E402
    TOKEN, assert_refusal_indistinguishable, assert_success_headers_and_short_head,
    fingerprint, logs, owner_cookie, run_as_script, sql_seen, stand,
)
from app import usage  # noqa: E402
from app.models import PageView  # noqa: E402

URL = "/admin/api/page-views"
MISSING = "/admin/api/page-viewz"
NOW = datetime(2026, 9, 7, 12, 0, 0)
A, B, C = 700100200, 700100201, 700100202     # partner_id, которых в теле быть не должно


def _view(partner_id, path, *, days_ago=0, section="dashboard"):
    return PageView(partner_id=partner_id, path=path, section=section,
                    created_at=NOW - timedelta(days=days_ago))


def _get(client, **params):
    r = client.get(URL, params=params, headers={"X-Api-Token": TOKEN})
    assert r.status_code == 200, r.text
    return r.json()


def _rows(client, **params):
    return {row["path"]: row for row in _get(client, **params)["rows"]}


# ─── (а) цифры ───────────────────────────────────────────────────────────────

def test_views_unique_and_by_day():
    with stand(
        _view(A, "/dashboard"), _view(A, "/dashboard"), _view(A, "/dashboard", days_ago=1),
        _view(B, "/dashboard"),
        _view(C, "/tools", section="tools"),          # чужой путь в строку не попадает
    ) as (client, _):
        row = _rows(client, path="/dashboard")["/dashboard"]
        assert list(row) == ["path", "views", "unique", "by_day"], "форма строки"
        assert (row["views"], row["unique"]) == (4, 2)
        assert row["by_day"] == {"2026-09-06": 1, "2026-09-07": 3}
        assert list(row["by_day"]) == ["2026-09-06", "2026-09-07"], "дни по порядку"


def test_since_cuts_by_day_and_unique_is_not_a_sum_of_days():
    with stand(
        _view(A, "/dashboard", days_ago=3), _view(A, "/dashboard"),   # один человек, два дня
        _view(B, "/dashboard", days_ago=3),
    ) as (client, _):
        full = _rows(client, path="/dashboard")["/dashboard"]
        assert (full["views"], full["unique"]) == (3, 2), "A за два дня: один уникальный"
        win = _get(client, path="/dashboard", since="2026-09-05")
        assert win["since"] == "2026-09-05"
        assert win["rows"][0]["views"] == 1 and win["rows"][0]["unique"] == 1
        assert win["rows"][0]["by_day"] == {"2026-09-07": 1}
        # Эхо нормализованное: что применили, то и вернули.
        assert _get(client, path="/dashboard", since=" 2026-9-5 ")["since"] == "2026-09-05"
        assert _get(client, path="/dashboard")["since"] is None


def test_empty_period_gives_zeros_not_a_missing_row():
    with stand(_view(A, "/dashboard", days_ago=10)) as (client, _):
        body = _get(client, path="/dashboard", since="2026-09-07")
        assert body["rows"] == [{"path": "/dashboard", "views": 0, "unique": 0, "by_day": {}}]


def test_several_paths_in_request_order_with_zeros_for_unknown():
    with stand(
        _view(A, "/tools", section="tools"), _view(B, "/dashboard"), _view(B, "/dashboard"),
    ) as (client, _):
        asked = ["/tools", "/dashboard", "/tools", "/nikogda-ne-otkryvali"]
        body = _get(client, path=asked)
        assert [r["path"] for r in body["rows"]] == \
            ["/tools", "/dashboard", "/nikogda-ne-otkryvali"], "порядок как спросили, без повторов"
        by = {r["path"]: r for r in body["rows"]}
        assert (by["/tools"]["views"], by["/dashboard"]["views"]) == (1, 2)
        assert by["/nikogda-ne-otkryvali"] == \
            {"path": "/nikogda-ne-otkryvali", "views": 0, "unique": 0, "by_day": {}}
        # Две выгрузки подряд: одинаковый порядок.
        again = _get(client, path=asked)
        assert [r["path"] for r in again["rows"]] == [r["path"] for r in body["rows"]]


def test_path_normalized_the_same_way_as_on_write():
    # Запись идёт через classify_path; чтение обязано искать под тем же именем,
    # иначе `/courses/ai-setup/day/2` находил бы пустоту при живых заходах.
    stored = usage.classify_path("/courses/ai-setup/day/2")[0]
    assert stored == "/courses/:slug/day/:day"
    with stand(
        _view(A, stored, section="courses"), _view(A, "/dashboard"),
    ) as (client, _):
        rows = _rows(client, path=["/courses/ai-setup/day/2", "/dashboard/", "   "])
        assert set(rows) == {stored, "/dashboard"}, "пустой путь выброшен, остальные нормализованы"
        assert rows[stored]["views"] == 1 and rows["/dashboard"]["views"] == 1


def test_no_path_means_empty_rows_not_a_catalogue():
    # Наружу только то, что спросили. Без path список путей таблицы не уезжает.
    with stand(_view(A, "/dashboard"), _view(B, "/tools", section="tools")) as (client, _):
        body = client.get(URL, headers={"X-Api-Token": TOKEN})
        assert body.status_code == 200
        assert body.json()["rows"] == []
        assert "/dashboard" not in body.text and "/tools" not in body.text


def test_function_and_route_give_the_same_shape():
    with stand(_view(A, "/dashboard")) as (client, session):
        direct = usage.page_view_counts(session, ["/dashboard"])
        assert direct == _get(client, path="/dashboard")["rows"]
        assert usage.page_view_counts(session, []) == []


# ─── (б) кривой запрос = отказ ───────────────────────────────────────────────

def test_since_broken_and_too_many_paths_are_bare_404():
    with stand(_view(A, "/dashboard")) as (client, _):
        etalon = fingerprint(client.get(MISSING))
        for bad in ("05.09.2026", "2026-13-45", "вчера", "2026-09-07T00:00"):
            r = client.get(URL, params={"path": "/dashboard", "since": bad},
                           headers={"X-Api-Token": TOKEN})
            assert fingerprint(r) == etalon, f"since={bad!r} выдаёт адрес"
        too_many = [f"/p{i}" for i in range(usage.PAGE_VIEW_PATHS_MAX + 1)]
        r = client.get(URL, params={"path": too_many}, headers={"X-Api-Token": TOKEN})
        assert fingerprint(r) == etalon, "сверх потолка путей ответ отличим от 404"
        # Ровно потолок: ещё успех. Граница закреплена числом, а не «примерно».
        r = client.get(URL, params={"path": too_many[:-1]}, headers={"X-Api-Token": TOKEN})
        assert r.status_code == 200 and len(r.json()["rows"]) == usage.PAGE_VIEW_PATHS_MAX
        # Повторы не считаются за отдельные пути.
        r = client.get(URL, params={"path": ["/dashboard"] * (usage.PAGE_VIEW_PATHS_MAX + 5)},
                       headers={"X-Api-Token": TOKEN})
        assert r.status_code == 200 and len(r.json()["rows"]) == 1


# ─── (в) право и неотличимость отказа ────────────────────────────────────────

def test_refusal_is_indistinguishable_from_a_missing_address():
    with stand(_view(A, "/dashboard")) as (client, session):
        assert_refusal_indistinguishable(client, session, URL, MISSING)


def test_owner_cookie_opens_the_door():
    with stand(_view(A, "/dashboard")) as (client, session):
        owner_cookie(session, client)
        assert client.get(URL, params={"path": "/dashboard"}).status_code == 200
        # Старый заголовок при живой куке: не отказ, а переход к следующей двери.
        assert client.get(URL, params={"path": "/dashboard"},
                          headers={"X-Api-Token": "starye-klyuchi"}).status_code == 200


def test_empty_setting_closes_token_door():
    with stand(_view(A, "/dashboard"), token="") as (client, _):
        assert client.get(URL, headers={"X-Api-Token": ""}).status_code == 404
        assert client.get(URL).status_code == 404


def test_success_headers_and_short_head():
    with stand(_view(A, "/dashboard")) as (client, session):
        assert_success_headers_and_short_head(client, session, URL, "page-views")


def test_route_not_in_public_catalogue():
    with stand(_view(A, "/dashboard")) as (client, _):
        schema = client.get("/openapi.json")
        assert schema.status_code == 200
        assert URL not in schema.json()["paths"] and "page-views" not in schema.text


def test_closed_door_leaves_a_trace_without_the_key():
    with stand(_view(A, "/dashboard")) as (client, _):
        with logs() as written:
            client.get(URL, headers={"X-Api-Token": "sovsem-ne-tot-klyuch"})
        trace = [w for w in written if "page-views" in w]
        assert trace and trace[0].startswith("WARNING"), "закрытая дверь молчит"
        assert "sovsem-ne-tot-klyuch" not in "\n".join(written), "ключ уехал в журнал"
        with logs() as written:
            client.get(URL, params={"path": "/dashboard"}, headers={"X-Api-Token": TOKEN})
        assert [w for w in written if w.startswith("INFO") and "page-views" in w]


def test_query_cannot_forge_a_log_line():
    with stand(_view(A, "/dashboard")) as (client, _):
        with logs() as written:
            client.get(URL, params={"path": "/dashboard\nWARNING page-views: всё хорошо",
                                    "since": "kriv\nWARNING page-views: подделка"},
                       headers={"X-Api-Token": TOKEN})
        ours = [w for w in written if "page-views" in w]
        assert ours and all("\n" not in w for w in ours), "чужая строка попала в журнал"


# ─── (г) сторож ПД и только чтение ───────────────────────────────────────────

def test_no_personal_data_in_body():
    with stand(_view(A, "/dashboard"), _view(B, "/dashboard"),
               _view(C, "/tools", section="tools")) as (client, _):
        body = client.get(URL, params={"path": "/dashboard"},
                          headers={"X-Api-Token": TOKEN}).text
        for key in ("partner_id", "section", "telegram_id", "created_at"):
            assert key not in body, f"ключ {key} уехал наружу"
        for value in (str(A), str(B), str(C), "/tools"):
            assert value not in body, f"значение {value!r} уехало наружу"


def test_endpoint_only_reads():
    with stand(_view(A, "/dashboard")) as (client, session):
        with sql_seen(session) as seen:
            assert client.get(URL, params={"path": ["/dashboard", "/tools"]},
                              headers={"X-Api-Token": TOKEN}).status_code == 200
        assert seen == ["SELECT", "SELECT"], f"ждали два SELECT на весь список: {seen}"
        assert not (session.new or session.dirty or session.deleted)


if __name__ == "__main__":
    run_as_script(globals())
