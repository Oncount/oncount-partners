"""Привратник канала: статус пишется тому человеку, метка рассылки не теряется.

Отчёт рассылки в ARDORIUM собирается из двух полей одной таблицы — `status` и
`source`, — и обе цифры до 05.09.2026 умели врать молча:

1. кик или одобрение заявки РУКАМИ приходят от админа, а строку искали по
   `from_user` — то есть по исполнителю действия. `left` уезжал на строку
   Николь, а вышедший оставался `in_channel` навсегда;
2. человек, кликнувший ссылку рассылки (`dl:<код>`) и потом постучавшийся в
   канал, получал поверх метки безымянный `join_request` — и выпадал из отчёта
   той самой рассылки, которая за него заплатила.

Ни то, ни другое не видно ни по одной ошибке в журнале: цифры просто другие.
Поэтому стережём поимённо.

БД — in-memory SQLite, `channel_gate.SessionLocal` подменён на неё. Сети нет:
Telegram здесь — четыре простых класса, бот собирает вызовы в списки.

Запуск:  python tests/test_channel_gate.py   |   pytest tests/test_channel_gate.py
"""
import ast
import asyncio
import logging
import os
import sys
from contextlib import contextmanager
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("JWT_SECRET", "test-secret-not-the-default-value-000")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://t:t@localhost:5432/t")
# Пустой токен: Bot() не создаётся, в сеть модуль не ходит.
os.environ["PAY_BOT_TOKEN"] = ""

from aiogram.dispatcher.event.bases import SkipHandler  # noqa: E402
from aiogram.exceptions import TelegramForbiddenError  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app import channel_config as T  # noqa: E402
from app import channel_gate  # noqa: E402
from app.config import settings  # noqa: E402
from app.models import Base, ChannelSubscriber  # noqa: E402

CHANNEL = "-100777"          # наш канал на стенде
CHUZHOY = "-100999"          # чей-то ещё: события оттуда не наши
КОД = "dl:k7m2xqp"           # метка рассылки: 7 знаков из алфавита ARDORIUM


def _sub(telegram_id, *, status="asked", source=None, confirmed=False,
         pending=False):
    return ChannelSubscriber(
        telegram_id=telegram_id, username=f"user{telegram_id}",
        first_name="Кто-то", status=status, source=source,
        pending_request=pending, created_at=datetime(2026, 9, 1, 10, 0),
        age_confirmed_at=datetime(2026, 9, 1, 10, 5) if confirmed else None,
    )


@contextmanager
def _stand(*subs):
    """Стенд привратника: своя SQLite и свой канал.

    Прежние значения возвращаем в `finally` ОБА. Оба глобальные: pytest гоняет
    все файлы в одном процессе, и стенд, не убравший за собой, увёл бы соседние
    тесты в чужую базу или в чужой канал — молча и не там, где сломался.
    """
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine)
    saved_sm, saved_cid = channel_gate.SessionLocal, settings.NIKOL_CHANNEL_ID
    channel_gate.SessionLocal = maker
    settings.NIKOL_CHANNEL_ID = CHANNEL
    # Строки кладём и СРАЗУ отпускаем соединение: у in-memory SQLite оно одно на
    # поток, и открытая сессия делила бы транзакцию с сессиями обработчика.
    seed = maker()
    seed.add_all(subs)
    seed.commit()
    seed.close()
    try:
        yield maker
    finally:
        channel_gate.SessionLocal = saved_sm
        settings.NIKOL_CHANNEL_ID = saved_cid


def _row(maker, telegram_id):
    """Строка из базы свежей сессией: читаем то, что записал обработчик."""
    with maker() as s:
        return s.query(ChannelSubscriber).filter_by(telegram_id=telegram_id).one()


def _count(maker):
    with maker() as s:
        return s.query(ChannelSubscriber).count()


# ─── Telegram на стенде: ни одного сетевого вызова ───────────────────────────

class FakeUser:
    def __init__(self, id, username="someone", first_name="Кто-то"):  # noqa: A002
        self.id, self.username, self.first_name = id, username, first_name


class FakeChat:
    def __init__(self, id, type="channel"):  # noqa: A002
        self.id, self.type = id, type


class FakeChatMemberUpdated:
    def __init__(self, chat, from_user, new_chat_member):
        self.chat, self.from_user = chat, from_user
        self.new_chat_member = new_chat_member


class FakeInviteLink:
    def __init__(self, name):
        self.name = name


class FakeChatJoinRequest:
    def __init__(self, chat, from_user, user_chat_id, invite_link=None):
        self.chat, self.from_user = chat, from_user
        self.user_chat_id, self.invite_link = user_chat_id, invite_link


# Тот самый 403, что стоял во всех логах 05-07.09.2026. Один текст на всех:
# по Bot API писать автору заявки можно «5 минут и до обработки заявки», а
# кто не нажимал Start у бота, после обработки не получает ничего.
FORBIDDEN_TEXT = "Forbidden: bot can't initiate conversation with a user"


def _forbidden(text=FORBIDDEN_TEXT):
    return TelegramForbiddenError(method=None, message=text)


class FakeChatMember:
    """`ChatMemberMember` / `ChatMemberLeft` / `ChatMemberBanned`: у всех троих
    есть и `status`, и `user` — сам человек, чьё членство изменилось.
    `can_invite_users` — у `ChatMemberAdministrator`, его ждёт startup_check."""

    def __init__(self, status, user, can_invite_users=False):
        self.status, self.user = status, user
        self.can_invite_users = can_invite_users


class FakeBot:
    """Telegram на стенде — с тем правилом, из-за которого всё и сломалось.

    `window_open` — окно `user_chat_id`: пока оно открыто, писать человеку
    можно; approve и decline его ЗАКРЫВАЮТ (заявка обработана). Нажимал ли
    человек Start у бота — `started`: если да, письма проходят всегда. Так
    порядок «письмо → approve» проверяется поведением, а не подглядыванием.

    `member` — что ответит get_chat_member (объект) либо исключение, которое
    он бросит. `approve_error` — исключение вместо одобрения заявки.
    """

    def __init__(self, *, window_open=True, started=False, member=None,
                 approve_error=None, me_id=42):
        self.sent, self.approved, self.declined, self.links = [], [], [], []
        self.calls = []
        self.window_open, self.started = window_open, started
        self.member, self.approve_error, self.me_id = member, approve_error, me_id

    async def send_message(self, *a, **kw):
        self.calls.append("send")
        if not (self.started or self.window_open):
            raise _forbidden()
        self.sent.append((a, kw))

    async def approve_chat_join_request(self, **kw):
        self.calls.append("approve")
        if self.approve_error is not None:
            raise self.approve_error
        self.window_open = False
        self.approved.append(kw)

    async def decline_chat_join_request(self, **kw):
        self.calls.append("decline")
        self.window_open = False
        self.declined.append(kw)

    async def get_chat_member(self, **kw):
        self.calls.append("get_chat_member")
        if isinstance(self.member, BaseException):
            raise self.member
        return self.member or FakeChatMember("left", FakeUser(kw.get("user_id")))

    async def create_chat_invite_link(self, **kw):
        self.calls.append("create_link")
        link = type("Link", (), {"invite_link": f"https://t.me/+{kw.get('name')}"})()
        self.links.append(kw)
        return link

    async def get_me(self):
        return FakeUser(self.me_id, username="stend_bot")


class FakeMessage:
    async def edit_reply_markup(self, **kw):
        pass


class FakeCallbackQuery:
    def __init__(self, user):
        self.from_user, self.message, self.answered = user, FakeMessage(), False

    async def answer(self, *a, **kw):
        self.answered = True


def _texts(bot):
    return [a[1] if len(a) > 1 else kw.get("text") for a, kw in bot.sent]


@contextmanager
def _log():
    """Записи логгера привратника — руками, без caplog: файл обязан работать
    и без pytest (см. test_foreign_channel_is_passed_on)."""
    records = []
    handler = logging.Handler()
    handler.emit = records.append
    saved = channel_gate.log.level
    channel_gate.log.addHandler(handler)
    channel_gate.log.setLevel(logging.DEBUG)
    try:
        yield records
    finally:
        channel_gate.log.removeHandler(handler)
        channel_gate.log.setLevel(saved)


def _member_event(status, *, who_id, by_id, chat_id=CHANNEL):
    """Событие chat_member: действие сделал `by_id`, изменилось членство `who_id`."""
    return FakeChatMemberUpdated(
        chat=FakeChat(int(chat_id)),
        from_user=FakeUser(by_id, username="nikol"),
        new_chat_member=FakeChatMember(status, FakeUser(who_id)),
    )


# ─── (а) статус пишется тому, чьё членство изменилось ────────────────────────

def test_kick_by_admin_marks_the_kicked_not_the_admin():
    # Николь кикает человека руками. `from_user` — она, `new_chat_member.user` —
    # он. Пока искали по `from_user`, «вышел» записывалось ЕЙ.
    with _stand(_sub(1, status="in_channel", source="deeplink"),
                _sub(2, status="invited", source=КОД)) as maker:
        asyncio.run(channel_gate.on_channel_member(
            _member_event("kicked", who_id=2, by_id=1)))
        assert _row(maker, 2).status == "left", "выход записан не тому"
        assert _row(maker, 1).status == "in_channel", "админа выкинуло из канала"


def test_manual_approve_marks_the_added_not_the_admin():
    # Обратная сторона того же: заявку одобрили руками из интерфейса Telegram.
    with _stand(_sub(1, status="in_channel", source="deeplink"),
                _sub(2, status="invited", source=КОД)) as maker:
        asyncio.run(channel_gate.on_channel_member(
            _member_event("member", who_id=2, by_id=1)))
        assert _row(maker, 2).status == "in_channel", "вход записан не тому"
        assert _row(maker, 1).status == "in_channel"


def test_unknown_person_creates_no_row():
    # Таблица про подтверждения возраста, а не про всех подписчиков канала:
    # прошедший мимо привратника строки не заводит.
    #
    # Статус события задан явно (`kicked`), и утверждаем не только «строк
    # по-прежнему две», но и «обе не изменились». Без второго кейс зелёный и на
    # сломанном коде: при поиске по `from_user.id=1` строка находится, новых
    # всё равно не создаётся — и проверка не отличала бы правку от порчи.
    with _stand(_sub(1, status="in_channel", source="deeplink"),
                _sub(2, status="invited", source=КОД)) as maker:
        asyncio.run(channel_gate.on_channel_member(
            _member_event("kicked", who_id=3, by_id=1)))
        assert _count(maker) == 2, "завели строку тому, кого не спрашивали"
        assert _row(maker, 1).status == "in_channel", "тронули строку админа"
        assert _row(maker, 2).status == "invited", "тронули чужую строку"


def test_person_who_left_on_their_own_is_marked():
    # Самый частый путь на бою, и потому отдельным кейсом: человек ушёл сам,
    # никакого админа нет — `from_user` и `new_chat_member.user` это он же.
    # Статус приходит `left`, а не `kicked`: без этого кейса ветку «left» можно
    # выкинуть из обработчика, и не покраснеет ничего.
    with _stand(_sub(5, status="in_channel", source=КОД)) as maker:
        asyncio.run(channel_gate.on_channel_member(
            _member_event("left", who_id=5, by_id=5)))
        assert _row(maker, 5).status == "left", "уход своими ногами не записан"
        assert _row(maker, 5).source == КОД, "метку рассылки тронули на выходе"


def test_person_who_joined_on_their_own_is_marked():
    # Обратная половина того же: вошёл по персональной ссылке, сам.
    with _stand(_sub(5, status="invited", source=КОД)) as maker:
        asyncio.run(channel_gate.on_channel_member(
            _member_event("member", who_id=5, by_id=5)))
        assert _row(maker, 5).status == "in_channel"


def test_foreign_channel_is_passed_on():
    # Клубный канал ждёт club.on_channel_member: не «не наш — забыли», а
    # «не наш — отдай следующему». Иначе вход в клуб молча пропадает.
    # `pytest.raises` не зовём намеренно: файл обязан работать и без pytest,
    # как соседний test_channel_tags.py — pytest даже не в requirements.txt.
    with _stand(_sub(1, status="in_channel"), _sub(2, status="invited")) as maker:
        try:
            asyncio.run(channel_gate.on_channel_member(
                _member_event("kicked", who_id=2, by_id=1, chat_id=CHUZHOY)))
        except SkipHandler:
            pass
        else:
            raise AssertionError("чужой канал не отдан следующему обработчику")
        assert _row(maker, 1).status == "in_channel"
        assert _row(maker, 2).status == "invited", "чужой канал тронул нашу строку"


# ─── (б) метка рассылки: побеждает первое касание ────────────────────────────

def test_mailing_tag_survives_a_join_request():
    # Главный случай ради которого всё: кликнул в рассылке, потом постучался в
    # канал. Метка `dl:` обязана остаться — по ней ARDORIUM и считает отчёт.
    with _stand(_sub(777, source=КОД)) as maker:
        bot = FakeBot()
        asyncio.run(channel_gate.ask_age(bot, 777, FakeUser(777), "join_request"))
        assert _row(maker, 777).source == КОД, "метку рассылки затёрли заявкой"
        assert T.AGE_ASK in _texts(bot), "вопрос про 18+ не задан"


def test_general_tag_gives_way_to_the_mailing_one():
    # Обратный порядок: сперва просто открыл бота, потом пришёл по рассылке.
    # Общей метке уступать нечего, `deeplink` меняется на код.
    with _stand(_sub(777, source="deeplink")) as maker:
        asyncio.run(channel_gate.ask_age(FakeBot(), 777, FakeUser(777), КОД))
        assert _row(maker, 777).source == КОД


def test_empty_source_is_filled():
    # Строки нет вовсе — её заводит _sub, и метка пишется как есть.
    with _stand() as maker:
        asyncio.run(channel_gate.ask_age(FakeBot(), 777, FakeUser(777),
                                         "join_request"))
        assert _row(maker, 777).source == "join_request"
        assert _row(maker, 777).status == "asked"


def test_channel_command_does_not_wipe_the_tag():
    # `/channel` шлёт «deeplink» всегда (paybot.py:651) — это «вернулся, ссылка
    # истекла», а не новый источник. Раньше он стирал метку рассылки у всех,
    # кто хоть раз воспользовался командой.
    with _stand(_sub(777, source=КОД)) as maker:
        asyncio.run(channel_gate.ask_age(FakeBot(), 777, FakeUser(777), "deeplink"))
        assert _row(maker, 777).source == КОД


def test_first_touch_wins_between_two_concrete_tags():
    # Две конкретные метки: `dl:` из рассылки против `jr:agents` с именной
    # ссылки. Оставляем ПЕРВУЮ — ARDORIUM сверяет по коду, который сам отправил.
    with _stand(_sub(777, source=КОД)) as maker:
        asyncio.run(channel_gate.ask_age(FakeBot(), 777, FakeUser(777), "jr:agents"))
        assert _row(maker, 777).source == КОД
    # И два разных кода рассылки между собой — тоже: побеждает первый.
    with _stand(_sub(778, source=КОД)) as maker:
        asyncio.run(channel_gate.ask_age(FakeBot(), 778, FakeUser(778), "dl:b4n9wzr"))
        assert _row(maker, 778).source == КОД


def test_source_rule_relies_on_an_uninterrupted_block():
    """Правило «первое касание» держится на устройстве бота, а не на SQL.

    `_set_source` читает `sub.source`, решает и пишет — три шага. Правильно это
    только пока между ними никто не вклинивается, а не вклинивается по одной
    причине: бот живёт одной задачей в одном процессе, и внутри
    `with SessionLocal()` нет ни одного `await`, то есть задача доходит до
    `commit`, не уступая управления соседней.

    Условие невидимое: поставить `await` между чтением и записью (спросить
    что-то у Telegram) можно одной строкой, прогон останется зелёным, а метки
    рассылки начнут теряться в редких парах событий — молча и невоспроизводимо.
    Поэтому условие проверяем прямо по дереву разбора: появился `await` внутри
    блока — проверка краснеет и говорит, что делать (перевести условие в SQL).
    """
    источник = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "app", "channel_gate.py")
    дерево = ast.parse(open(источник, encoding="utf-8").read())
    сторожим = {"ask_age", "on_join_request", "on_channel_member"}
    осмотрено = set()
    for fn in ast.walk(дерево):
        if not isinstance(fn, ast.AsyncFunctionDef) or fn.name not in сторожим:
            continue
        for узел in ast.walk(fn):
            блок = (isinstance(узел, ast.With) and any(
                isinstance(i.context_expr, ast.Call)
                and getattr(i.context_expr.func, "id", "") == "SessionLocal"
                for i in узел.items))
            if not блок:
                continue
            осмотрено.add(fn.name)
            ждёт = [n for n in ast.walk(узел) if isinstance(n, ast.Await)]
            assert not ждёт, (
                f"{fn.name}: внутри with SessionLocal() появился await "
                f"(строка {ждёт[0].lineno}). Задача теперь уступает управление "
                f"между чтением и записью — переводите условие _set_source в SQL")
    assert осмотрено == сторожим, f"блок нашёлся не у всех: {осмотрено}"


def test_join_request_keeps_the_tag_end_to_end():
    # Целиком путь неподтвердившего: заявка → метка цела → вопрос в личку.
    # Метку тут пишут ДВАЖДЫ — сам on_join_request и ask_age внутри него.
    with _stand(_sub(777, source=КОД)) as maker:
        bot = FakeBot()
        ev = FakeChatJoinRequest(chat=FakeChat(int(CHANNEL)),
                                 from_user=FakeUser(777), user_chat_id=777)
        asyncio.run(channel_gate.on_join_request(ev, bot))
        row = _row(maker, 777)
        assert row.source == КОД, "метку затёрли по дороге заявки"
        assert row.pending_request is True, "заявка не отмечена как висящая"
        assert T.AGE_ASK in _texts(bot)


def test_join_request_of_a_confirmed_person_keeps_the_tag():
    # Подтвердившему возраст вопрос не задают — ему сразу открывают канал через
    # grant_access. Метка обязана пережить и эту ветку, где ask_age не зовётся.
    with _stand(_sub(777, source=КОД, status="invited", confirmed=True)) as maker:
        bot = FakeBot()
        ev = FakeChatJoinRequest(chat=FakeChat(int(CHANNEL)),
                                 from_user=FakeUser(777), user_chat_id=777,
                                 invite_link=FakeInviteLink("agents"))
        asyncio.run(channel_gate.on_join_request(ev, bot))
        row = _row(maker, 777)
        assert row.source == КОД, "именная ссылка затёрла метку рассылки"
        assert row.status == "in_channel", "заявку не одобрили"
        assert [kw["user_id"] for kw in bot.approved] == [777]


# ─── (в) окно user_chat_id: письмо до approve, 403 не рвёт выдачу ────────────

def test_greeting_goes_before_approve_and_status_is_in_channel():
    # Бой 05-07.09: 40 из 40 вошли в канал, ни один не получил приветствия.
    # Человек Start не нажимал, approve закрывает окно — значит, дойдёт только
    # то, что отправлено ДО approve. И статус — in_channel, а не invited.
    with _stand(_sub(777, source=КОД, status="confirmed", confirmed=True,
                     pending=True)) as maker:
        bot = FakeBot()
        asyncio.run(channel_gate.grant_access(bot, 777))
        assert T.ACCESS_APPROVED in _texts(bot), "приветствие не дошло"
        assert bot.calls == ["send", "approve"], f"порядок вызовов: {bot.calls}"
        row = _row(maker, 777)
        assert row.status == "in_channel", "одобренный числится не в канале"
        assert row.pending_request is False
        assert bot.links == [], "ссылку создали тому, кто уже внутри"
        assert row.invite_link is None


def test_yes_button_is_answered_even_when_nothing_can_be_sent():
    # Кнопка «Да» нажата позже 5 минут, окно закрыто, Start не нажат: письма не
    # доходят, но заявка одобряется, статус in_channel, часики с кнопки сняты,
    # обработчик не падает трейсбеком в aiogram.
    with _stand(_sub(777, source=КОД, pending=True)) as maker:
        bot, call = FakeBot(window_open=False), FakeCallbackQuery(FakeUser(777))
        asyncio.run(channel_gate.cb_age_yes(call, bot))
        assert call.answered, "кнопка осталась висеть"
        assert bot.approved and bot.approved[0]["user_id"] == 777
        assert _row(maker, 777).status == "in_channel"
        assert _row(maker, 777).age_confirmed_at is not None


def test_forbidden_on_approve_and_member_is_logged_with_text_and_channel():
    # Защита (а): 403 на approve и на get_chat_member — в лог уходят ТЕКСТ
    # ответа Telegram и id канала. По одному имени класса 05-07.09 отказ
    # sendMessage читался как отказ approve. Токена и имён в записях нет.
    with _stand(_sub(777, source=КОД, status="confirmed", confirmed=True,
                     pending=True)) as maker:
        err = _forbidden("Forbidden: bot is not a member of the channel chat")
        bot = FakeBot(approve_error=err, member=_forbidden())
        with _log() as records:
            asyncio.run(channel_gate.grant_access(bot, 777))
        lines = [r.getMessage() for r in records]
        approve_line = [l for l in lines if l.startswith("approve 777")]
        member_line = [l for l in lines if l.startswith("get_chat_member 777")]
        assert approve_line and "not a member of the channel chat" in approve_line[0]
        assert CHANNEL in approve_line[0], "в строке approve нет id канала"
        assert member_line and FORBIDDEN_TEXT in member_line[0]
        assert CHANNEL in member_line[0], "в строке get_chat_member нет id канала"
        assert not any("user777" in l for l in lines), "username утёк в лог"
        # Запасной путь: заявка не одобрилась → выдана ссылка, статус invited.
        assert bot.links and bot.links[0]["name"] == "age18-777"
        assert _row(maker, 777).status == "invited"
        assert any(t.startswith("Спасибо. Вот ваша персональная ссылка")
                   for t in _texts(bot)), "ссылку не отправили"
        assert _row(maker, 777).pending_request is False


def test_member_answer_sets_in_channel_even_if_letter_is_lost():
    # Telegram ответил member, а письмо «вы уже подписаны» получило 403:
    # статус ставится по ответу Telegram, ссылка не создаётся, обработчик жив.
    with _stand(_sub(777, source=КОД, status="confirmed", confirmed=True)) as maker:
        bot = FakeBot(window_open=False, member=FakeChatMember("member", FakeUser(777)))
        with _log() as records:
            asyncio.run(channel_gate.grant_access(bot, 777))
        assert _row(maker, 777).status == "in_channel"
        assert bot.links == []
        lost = [r for r in records if "не доставлено" in r.getMessage()]
        assert lost and FORBIDDEN_TEXT in lost[0].getMessage()
        assert CHANNEL in lost[0].getMessage()


def test_invited_does_not_downgrade_in_channel():
    # Гонка: событие chat_member об одобрении уже поставило in_channel, а
    # выдача ссылки дописывает invited. Раньше затирала — теперь нет.
    with _stand(_sub(777, source=КОД, status="in_channel", confirmed=True)) as maker:
        bot = FakeBot(started=True, member=_forbidden())
        asyncio.run(channel_gate.grant_access(bot, 777))
        row = _row(maker, 777)
        assert row.status == "in_channel", "invited понизил in_channel"
        assert row.invite_link, "ссылка не записана"
    # А обычному confirmed ссылка ставит invited, как и прежде.
    with _stand(_sub(778, source=КОД, status="confirmed", confirmed=True)) as maker:
        asyncio.run(channel_gate.grant_access(FakeBot(started=True), 778))
        assert _row(maker, 778).status == "invited"


def test_no_button_sends_reply_before_decline_and_survives_403():
    # «Нет»: письмо ДО decline (decline закрывает окно), заявка отклонена,
    # кнопка отвечена. То же самое, когда окно уже закрыто: 403 на письме не
    # мешает отклонить заявку и не роняет обработчик.
    with _stand(_sub(777, source=КОД, pending=True)) as maker:
        bot, call = FakeBot(), FakeCallbackQuery(FakeUser(777))
        asyncio.run(channel_gate.cb_age_no(call, bot))
        assert T.AGE_NO in _texts(bot), "«нет так нет» не дошло"
        assert bot.calls == ["send", "decline"], f"порядок вызовов: {bot.calls}"
        assert bot.declined[0]["user_id"] == 777
        assert call.answered
        assert _row(maker, 777).status == "declined"
        assert _row(maker, 777).pending_request is False
    with _stand(_sub(778, source=КОД, pending=True)) as maker:
        bot, call = FakeBot(window_open=False), FakeCallbackQuery(FakeUser(778))
        with _log() as records:
            asyncio.run(channel_gate.cb_age_no(call, bot))
        assert bot.declined and bot.declined[0]["user_id"] == 778
        assert call.answered
        assert _row(maker, 778).status == "declined"
        assert any(FORBIDDEN_TEXT in r.getMessage() for r in records)


# ─── (б) проверка прав при старте ────────────────────────────────────────────

def test_startup_check_notices_missing_invite_right():
    with _stand():
        bot = FakeBot(member=FakeChatMember("administrator", FakeUser(42),
                                            can_invite_users=False))
        with _log() as records:
            reason = asyncio.run(channel_gate.startup_check(bot))
        assert reason and "Пригласительные ссылки" in reason
        errors = [r for r in records if r.levelno >= logging.ERROR]
        assert len(errors) == 1, "ожидалась ровно одна строка ошибки"
        assert CHANNEL in errors[0].getMessage()
        assert "Пригласительные ссылки" in errors[0].getMessage()


def test_startup_check_notices_bot_is_not_admin():
    with _stand():
        bot = FakeBot(member=FakeChatMember("member", FakeUser(42)))
        with _log() as records:
            reason = asyncio.run(channel_gate.startup_check(bot))
        assert reason and "не администратор" in reason
        assert [r for r in records if r.levelno >= logging.ERROR]
    # Telegram не ответил (бота выгнали): строка с текстом ответа, без падения.
    with _stand():
        bot = FakeBot(member=_forbidden("Forbidden: bot is not a member of the channel chat"))
        with _log() as records:
            reason = asyncio.run(channel_gate.startup_check(bot))
        assert reason and "not a member" in reason
        assert any(CHANNEL in r.getMessage() and "not a member" in r.getMessage()
                   for r in records)


def test_startup_check_prints_role_as_value_for_real_chat_member():
    # Приёмка 07.09 (пункт 3): у настоящего ChatMemberMember status — str-Enum,
    # и f-строка в 3.11 даёт «ChatMemberStatus.MEMBER»; в журнале нужно «member».
    from aiogram.types import ChatMemberMember, User
    with _stand():
        bot = FakeBot(member=ChatMemberMember(user=User(id=42, is_bot=True, first_name="b")))
        with _log() as records:
            reason = asyncio.run(channel_gate.startup_check(bot))
        assert reason and "(роль member)" in reason, reason
        assert "ChatMemberStatus" not in reason
        assert any("(роль member)" in r.getMessage() for r in records)


def test_err_hides_bot_token_from_url_in_exception_text():
    # Приёмка 07.09 (пункт 4): сетевые ошибки несут полный URL запроса, а в нём
    # токен `/bot<id>:<секрет>/`. В строке для журнала его быть не должно.
    url = "https://api.telegram.org/bot123:ABC/sendMessage"
    line = channel_gate._err(RuntimeError(f"Cannot connect to {url}: timeout"))
    assert "123:ABC" not in line and "ABC" not in line, line
    assert "/bot<скрыто>/sendMessage" in line and line.startswith("RuntimeError: ")
    # Реальный вид токена (цифры:буквы_-), без хвостового слэша — тоже вырезан.
    real = "https://api.telegram.org/bot7012345678:AAH-x_Y9zQ"
    assert "7012345678:AAH" not in channel_gate._err(ValueError(real))
    # Текст без токена не тронут.
    exc = _forbidden()
    assert channel_gate._err(exc) == f"TelegramForbiddenError: {exc}"
    assert FORBIDDEN_TEXT in channel_gate._err(exc)
    # Сквозь startup_check: get_chat_member упал с URL в тексте — в журнале и в
    # причине токена нет, канал и текст есть.
    with _stand():
        bot = FakeBot(member=RuntimeError(f"Cannot connect to {url}"))
        with _log() as records:
            reason = asyncio.run(channel_gate.startup_check(bot))
        assert reason and "123:ABC" not in reason and CHANNEL in reason
        assert not any("123:ABC" in r.getMessage() for r in records), "токен утёк в лог"
        assert any("/bot<скрыто>/" in r.getMessage() for r in records)


def test_startup_check_is_quiet_when_rights_are_fine():
    with _stand():
        bot = FakeBot(member=FakeChatMember("administrator", FakeUser(42),
                                            can_invite_users=True))
        with _log() as records:
            assert asyncio.run(channel_gate.startup_check(bot)) is None
        assert not [r for r in records if r.levelno >= logging.WARNING]
        assert bot.sent == [], "при исправных правах Николь писать незачем"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} тестов пройдено.")
