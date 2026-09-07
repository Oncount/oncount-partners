"""Заявки на интенсив числами (ТЗ маркетолога 2026-09-07, задача 3).

Заявка — это `intensive_leads.applied_at` (когда) и `applied_source` (откуда:
`cheklist`, `statya`, `post`), их ставит бот оплат на `/start zayavka-<метка>`.
До этого модуля цифра жила строкой в логе Railway и пропадала через часы.

Отдельный модуль, а не функция в paybot.py: тот тянет aiogram, а вебу для двух
SELECT он не нужен. Наружу — только числа и метки источника: ни telegram_id,
ни имени, ни email. Только чтение.
"""
from datetime import datetime

from sqlalchemy import func, select

from app.models import IntensiveLead
from app.usage import day_iso

# Заявка без метки быть не должна (бот пишет `tag or "cheklist"`), но столбец
# nullable, и молча терять такую строку нельзя: она считается под этим ключом.
UNKNOWN_SOURCE = "unknown"


def applied_counts(session, since: datetime | None = None) -> dict:
    """{"total", "by_source", "by_day"} по строкам, у которых стоит applied_at.

    `since` и дни считаются по `applied_at`, а не по `created_at`: последний
    значит «впервые у бота», а заявку оставляет и тот, кто в боте давно.
    `total` — сумма по источникам: один столбец, каждая строка ровно в одном
    ключе, отдельный COUNT ничего бы не добавил. Ключи отсортированы, чтобы две
    выгрузки подряд читались одинаково.
    """
    il = IntensiveLead
    applied = il.applied_at.is_not(None)
    day = func.date(il.applied_at)
    by_source_q = (select(il.applied_source, func.count(il.id))
                   .where(applied).group_by(il.applied_source))
    by_day_q = select(day, func.count(il.id)).where(applied).group_by(day)
    if since is not None:
        by_source_q = by_source_q.where(il.applied_at >= since)
        by_day_q = by_day_q.where(il.applied_at >= since)
    by_source: dict[str, int] = {}
    for source, n in session.execute(by_source_q):
        key = source or UNKNOWN_SOURCE
        by_source[key] = by_source.get(key, 0) + int(n)
    by_day = {day_iso(d): int(n) for d, n in session.execute(by_day_q)}
    return {
        "total": sum(by_source.values()),
        "by_source": dict(sorted(by_source.items())),
        "by_day": dict(sorted(by_day.items())),
    }
