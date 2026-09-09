"""Привратник канала числами: GET /admin/api/channel-stats (план 2026-09-09).

Сколько людей подало заявку в закрытый канал и в каком они состоянии на
сейчас: `asked` → `confirmed` → `invited` → `in_channel` / `left`, плюс
`declined`. Заявка — строка `channel_subscribers`; момент заявки — `created_at`
(«впервые у бота»), по нему же идут срез `since` и дни.

Отдельный модуль, а не функция в channel_gate.py: тот тянет aiogram, а вебу
для одного SELECT он не нужен. Кортеж состояний живёт ЗДЕСЬ, а channel_gate
берёт его отсюда: два списка в двух файлах разошлись бы при первом же новом
состоянии, и `channel-tags` с `channel-stats` считали бы разное.

Наружу — только числа и имена состояний: ни telegram_id, ни имени, ни
username, ни пригласительной ссылки. Только чтение.
"""
from datetime import datetime

from sqlalchemy import func, select

from app.models import ChannelSubscriber
from app.usage import day_iso

# Все состояния, которые ставит привратник (channel_gate): `kicked` из Telegram
# он записывает как `left`, а `blocked` не пишет вовсе, поэтому их здесь нет.
# Человек всегда ровно в одном состоянии, и сумма по ключам — это все строки.
STATUSES = ("asked", "confirmed", "invited", "in_channel", "left", "declined")

# Столбец `status` не бывает пустым (default="asked"), но терять строку с
# пустым или неизвестным значением молча нельзя: она считается под своим
# именем, и `total` остаётся суммой по ключам.
UNKNOWN_STATUS = "unknown"


def _zeros() -> dict[str, int]:
    return {st: 0 for st in STATUSES}


def subscriber_counts(session, since: datetime | None = None) -> dict:
    """{"total", "by_status", "by_day"} по строкам `channel_subscribers`.

    `since` и дни — по `created_at` (UTC): это момент заявки. Состояние —
    текущее, а не на тот день: таблица историю не хранит, и «в понедельник он
    был `invited`» узнать неоткуда. Значит, `by_day[день]` читается как «из
    подавших заявку в этот день сейчас столько-то в канале».

    Один запрос с группировкой по дню и состоянию; в ответе все шесть ключей
    в каждом дне и в `by_status`, нулями там, где никого: читающая сторона не
    должна отличать «ноль» от «ключа нет». Дни отсортированы, состояния в
    порядке пути человека. `total` — сумма по состояниям.
    """
    sub = ChannelSubscriber
    day = func.date(sub.created_at)
    stmt = (select(day, sub.status, func.count(sub.id))
            .group_by(day, sub.status))
    if since is not None:
        stmt = stmt.where(sub.created_at >= since)
    by_status = _zeros()
    by_day: dict[str, dict[str, int]] = {}
    for d, st, n in session.execute(stmt):
        key, n = (st or UNKNOWN_STATUS), int(n)
        by_status[key] = by_status.get(key, 0) + n
        row = by_day.setdefault(day_iso(d), _zeros())
        row[key] = row.get(key, 0) + n
    return {
        "total": sum(by_status.values()),
        "by_status": by_status,
        "by_day": dict(sorted(by_day.items())),
    }
