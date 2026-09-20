"""Сторож зависших заявок в закрытый канал (решение Николь 20.09.2026).

Что чинит. Человек жмёт ссылку на канал и подаёт заявку. Бот пытается задать
ему вопрос в личку, но Telegram открывает боту окно всего на пять минут и
только автору заявки. Не успел, не увидел, заблокировал ботов — и заявка висит
молча, навсегда. За сентябрь так встали 20 человек, включая живого маркетолога
Галину: узнали об этом только потому, что она пожаловалась.

Кто пишет. НЕ бот: ему Telegram запрещает писать первым тому, кто не нажимал
START, и это ровно те люди. Пишет рабочий аккаунт ONCOUNT через телеграм-канал
Wazzup, с которым у человека уже есть переписка.

Границы, согласованные Николь целиком (регламент лежит в
`.business/marketing/rassylka-telegram/STOROZH-ZAYAVOK-REGLAMENT.md`):
* раз в сутки, один прогон;
* берём тех, у кого заявка висит дольше суток и статус остался `asked`;
* одному человеку ОДИН раз за жизнь заявки (`nudged_at`);
* не пишем тем, кто в канале, кто сказал «Позже», кто вышел, кому уже писали;
* не больше `NUDGE_MAX_PER_RUN` за прогон, пауза между сообщениями;
* после каждого прогона отчёт Николь.

Главный предохранитель — `NUDGE_ENABLED`. Это автоматическая отправка живым
людям, поэтому по умолчанию OFF: выключенный сторож всё равно считает заявки и
говорит Николь, сколько людей ждёт, но в сеть не ходит.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from sqlalchemy import select

from app import channel_config as T
from app import wazzup
from app.config import settings
from app.db import SessionLocal
from app.models import ChannelSubscriber

log = logging.getLogger("oncount.nudge")

# Сколько заявка должна провисеть, прежде чем мы напомним. Сутки — это запас:
# человек мог ответить боту вечером следующего дня, и письмо было бы лишним.
STALE_AFTER_HOURS = 24

# Пауза между сообщениями. Тот же темп, что у рассылки: Telegram не любит
# ровную пулемётную очередь с одного аккаунта.
PAUSE_SECONDS = 150


def _link(bot_username: str, source: str | None) -> str:
    """Персональная ссылка в бота. Метка сегмента у человека уже стоит в
    `source` (`jr:<код>`), и мы возвращаем её в ссылке, чтобы учёт сошёлся:
    пришёл по рассылке — в отчёте по меткам он остался тем же человеком.

    Общая метка (`join_request`, `deeplink`) кода не несёт — тогда ссылка без
    хвоста, привратник встретит человека обычным вопросом.
    """
    tag = ""
    if source and ":" in source:
        tag = source.split(":", 1)[1]
    return (f"https://t.me/{bot_username}?start=channel-{tag}" if tag
            else f"https://t.me/{bot_username}?start=channel")


def _text_for(sub: ChannelSubscriber, bot_username: str) -> str:
    """Письмо человеку. Имя берём то, что дал Telegram; пустое имя это норма,
    для него отдельный текст без обращения."""
    link = _link(bot_username, sub.source)
    name = (sub.first_name or "").strip()
    if name:
        return T.NUDGE_WITH_NAME.format(name=name, link=link)
    return T.NUDGE_NO_NAME.format(link=link)


def stale_requests(limit: int | None = None) -> list[ChannelSubscriber]:
    """Кому положено написать: заявка висит дольше суток, ответа нет, сторож
    ещё не писал. Порядок от старых к свежим — кто ждёт дольше, тот первый.

    Отбор идёт по статусу, а не по «прошло ли время с создания строки»: строка
    создаётся в момент заявки, а `pending_request` говорит, что заявка всё ещё
    висит в канале и её есть смысл оживлять.
    """
    edge = datetime.utcnow() - timedelta(hours=STALE_AFTER_HOURS)
    with SessionLocal() as s:
        q = (select(ChannelSubscriber)
             .where(ChannelSubscriber.status == "asked",
                    ChannelSubscriber.pending_request.is_(True),
                    ChannelSubscriber.nudged_at.is_(None),
                    ChannelSubscriber.created_at < edge)
             .order_by(ChannelSubscriber.created_at))
        rows = list(s.scalars(q))
    return rows[:limit] if limit else rows


def _mark_nudged(telegram_id: int) -> None:
    """Отметить, что письмо ушло. Пишем сразу после успешной отправки, а не
    пачкой в конце: упадёт прогон на середине — никто не получит второе письмо.
    """
    with SessionLocal() as s:
        sub = s.query(ChannelSubscriber).filter_by(telegram_id=telegram_id).first()
        if sub:
            sub.nudged_at = datetime.utcnow()
            s.commit()


def run_once(bot_username: str = "Nikol_hilton_bot",
             notify=None, pause: int = PAUSE_SECONDS, dry: bool = False) -> dict:
    """Один прогон. Возвращает счётчики: сколько нашли, написали, не дошло,
    осталось на следующий раз.

    `notify` — как сказать Николь результат (функция от строки). Отдельным
    параметром, чтобы прогон можно было проверить без телеграма.

    `dry` — посчитать очередь и показать, кому ушло бы, ничего не отправляя.
    Нужен для проверки на бою: перед первым живым прогоном видно, кого сторож
    считает зависшими, и не окажется ли там лишних людей.
    """
    found = stale_requests()
    stats = {"found": len(found), "sent": 0, "failed": 0, "left": 0}

    if not found:
        log.info("сторож заявок: зависших нет")
        return stats

    # Выключенный сторож всё равно считает и докладывает: молчащая система,
    # в которой люди стоят в очереди, — это ровно то, что мы сейчас чиним.
    reason = None
    if dry:
        reason = "сухой прогон"
    elif not settings.NUDGE_ENABLED:
        reason = "NUDGE_ENABLED выключен"
    elif not settings.WAZZUP_TG_CHANNEL_ID or not settings.WAZZUP_API_KEY:
        reason = "телеграм-канал Wazzup не настроен"
    if reason:
        log.warning("сторож заявок: %d зависших, но отправка не идёт (%s)",
                    len(found), reason)
        stats["left"] = len(found)
        if notify:
            notify(T.NUDGE_OFF.format(found=len(found), reason=reason))
        return stats

    batch = found[:settings.NUDGE_MAX_PER_RUN]
    stats["left"] = len(found) - len(batch)

    for i, sub in enumerate(batch):
        ok = wazzup.send_tg_text(sub.telegram_id, _text_for(sub, bot_username))
        if ok:
            # Метку ставим и при успехе только: не дошло — попробуем завтра.
            _mark_nudged(sub.telegram_id)
            stats["sent"] += 1
        else:
            stats["failed"] += 1
        log.info("сторож заявок: %s → %s", sub.telegram_id,
                 "написал" if ok else "не дошло")
        if pause and i < len(batch) - 1:
            time.sleep(pause)

    log.info("сторож заявок: найдено %(found)d, написал %(sent)d, "
             "не дошло %(failed)d, осталось %(left)d", stats)
    if notify:
        notify(T.NUDGE_REPORT.format(**stats))
    return stats
