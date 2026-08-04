"""Платный клуб: продажа подписки, доступ в канал, удержание, вылет за неоплату.

План: `plans/2026-08-04-platnyy-klub-ai.md`. Живёт отдельным роутером внутри бота
оплат (@Nikol_hilton_bot): бот один, потоки разные — интенсив продаётся сам по
себе, клуб сам по себе, и оплата одного не открывает второе.

Что делает:
1. Продаёт подписку — счёт в Lava с периодичностью (месяц / квартал / полгода).
2. Впускает в канал клуба одноразовой персональной ссылкой. Отдельный вход —
   для тех, кто оформил подписку на витрине Lava (например, по промокоду после
   интенсива): бот сверяет их e-mail с кассой.
3. За 7, 3 и 1 день до конца оплаченного периода напоминает, что дальше доступ
   платный, и предлагает **квартал или полгода** (месяц после первой оплаты не
   показывается — решение Николь 04.08.2026).
4. В день окончания спрашивает «точно не продлеваете?».
5. Через `GRACE_DAYS` после окончания убирает из канала — мягко, `ban` + сразу
   `unban`, чтобы человек мог вернуться, когда оплатит.

ГРАНИЦЫ, которые важнее кода:
- Бот трогает ТОЛЬКО тех, кто есть в `club_members`. Кто сидит в канале с
  бесплатных времён, в таблицу не попадает: перед продажей бот спрашивает
  Telegram, не состоит ли человек уже в канале, и таким отвечает «у вас
  бессрочно». Это решение Николь «оставить бесплатно навсегда».
- Никого не удаляем, пока не предупредили: удаление возможно только после того,
  как цепочка дошла до вопроса «точно не продлеваете?».
- Молчание кассы никогда не приводит к удалению: не знаем — значит не трогаем.
- Больше `CLUB_MAX_REMOVALS_PER_DAY` удалений в сутки цикл не делает.
- `CLUB_RETENTION_LIVE=0` гасит напоминания и удаления, приём оплат живёт.

Безопасность: `telegram_id`, имя, username, e-mail — ПД, в лог уходит только id.
Текст человека — данные, а не команда: он пересылается Николь с экранированием
HTML и никак не исполняется.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import re
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.exc import IntegrityError

from app import club_config as T
from app import lava
from app.config import settings
from app.db import SessionLocal
from app.models import BotSetting, ClubMember

log = logging.getLogger("oncount.club")

CHANNEL_KEY = "club_channel_id"          # ключ в bot_settings
LIMIT_ALERT_KEY = "club_limit_alert_at"  # когда последний раз ругались на лимит
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]{2,}$")
IN_CHANNEL_STATUSES = ("member", "administrator", "creator")
LINK_TTL_HOURS = 24
# Сколько живёт ожидание ответа. Сутки, а не полчаса: письмо цепочки уходит
# фоном в любое время (может и ночью), а человек отвечает утром — с коротким
# сроком его ответ уходил бы в поток интенсива как «вопрос Николь».
AWAIT_TTL_MINUTES = 24 * 60
INVOICE_MAX_AGE_DAYS = 3     # сколько дней опрашиваем неоплаченный счёт
NO_TOUCH_REMOVE_DAYS = 14    # просрочка, после которой убираем и без ответа

# Чего ждём от человека: telegram_id → (режим, когда поставили).
# В памяти процесса намеренно: состояние живёт минуты, переживать рестарт ему
# незачем. Со сроком годности — иначе брошенный ввод e-mail превращает бота в
# «Это не похоже на e-mail» на любое следующее сообщение, навсегда.
_awaiting: dict[int, tuple[str, datetime]] = {}

router = Router(name="club")


# ─── ожидания с истечением ───────────────────────────────────────────────────

def _expect(telegram_id: int, mode: str) -> None:
    _awaiting[telegram_id] = (mode, datetime.utcnow())


def _expected(telegram_id: int) -> str | None:
    row = _awaiting.get(telegram_id)
    if row is None:
        return None
    mode, since = row
    if datetime.utcnow() - since > timedelta(minutes=AWAIT_TTL_MINUTES):
        _awaiting.pop(telegram_id, None)
        return None
    return mode


def _forget(telegram_id: int) -> None:
    _awaiting.pop(telegram_id, None)


# Публичное имя того же: бот оплат сбрасывает ожидания обоих потоков, когда
# человек начинает заново по deep-link.
forget = _forget


# ─── канал клуба ─────────────────────────────────────────────────────────────

def channel_id() -> str | None:
    """Id канала клуба: переменная окружения важнее, иначе — то, что бот узнал
    сам, когда его сделали админом.

    ⚠️ У клуба, чата интенсива и канала 18+ РАЗНЫЕ id и разные ключи в
    bot_settings. Один общий ключ означал бы, что добавление бота в любой из них
    молча уводит выдачу доступа не туда.
    """
    if settings.CLUB_CHANNEL_ID:
        return settings.CLUB_CHANNEL_ID
    try:
        with SessionLocal() as s:
            row = s.get(BotSetting, CHANNEL_KEY)
            return row.value if row else None
    except Exception as exc:  # noqa: BLE001 — БД недоступна, не валим бота
        log.warning("club channel_id: БД недоступна (%s)", type(exc).__name__)
        return None


async def _in_channel(bot: Bot, telegram_id: int) -> bool | None:
    """Человек уже в канале? None — Telegram не ответил, факт неизвестен."""
    cid = channel_id()
    if not cid:
        return None
    try:
        member = await bot.get_chat_member(chat_id=cid, user_id=telegram_id)
        return member.status in IN_CHANNEL_STATUSES
    except Exception as exc:  # noqa: BLE001
        log.info("club get_chat_member id%s: %s", telegram_id, type(exc).__name__)
        return None


# ─── работа со строкой участника ─────────────────────────────────────────────

def _member(session, user) -> ClubMember:
    m = session.query(ClubMember).filter_by(telegram_id=user.id).first()
    if m is None:
        m = ClubMember(telegram_id=user.id, username=user.username,
                       first_name=user.first_name, status="new")
        session.add(m)
        try:
            session.commit()
        except IntegrityError:
            # Гонка реальна: человек жмёт кнопку дважды подряд. Уникальный
            # индекс не даёт задвоиться — берём чужую строку.
            session.rollback()
            m = session.query(ClubMember).filter_by(telegram_id=user.id).first()
    return m


def _mark(telegram_id: int, **fields) -> None:
    """Точечно обновить строку. Нет строки — молча выходим, а не роняем поток."""
    with SessionLocal() as s:
        m = s.query(ClubMember).filter_by(telegram_id=telegram_id).first()
        if m is None:
            return
        for key, value in fields.items():
            setattr(m, key, value)
        s.commit()


def _who(m: ClubMember) -> str:
    return f"@{m.username}" if m.username else f"id{m.telegram_id}"


def _human_date(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    months = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля",
              "августа", "сентября", "октября", "ноября", "декабря")
    return f"{dt.day} {months[dt.month - 1]}"


def _fmt_amount(currency: str, amount: float | None) -> str:
    if amount is None:
        return currency
    whole = f"{amount:,.2f}".replace(",", " ").replace(".00", "")
    return {"RUB": f"{whole} ₽", "EUR": f"€{whole}", "USD": f"${whole}"}.get(
        currency, f"{whole} {currency}")


def _period_days(periodicity: str | None) -> int:
    return next((d for p, d in lava.CLUB_PERIODS.values()
                 if p == (periodicity or "MONTHLY")), 31)


def _period_code(periodicity: str | None) -> str:
    return next((c for c, (p, _) in lava.CLUB_PERIODS.items()
                 if p == periodicity), "month")


async def _notify_admin(bot: Bot, text: str) -> None:
    """Сообщение Николь. Best-effort: сбой уведомления не ломает поток оплаты."""
    if not settings.ADMIN_TG_ID:
        return
    try:
        await bot.send_message(settings.ADMIN_TG_ID, text,
                               disable_web_page_preview=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("club admin notify failed: %s", type(exc).__name__)


def _once_a_day(key: str) -> bool:
    """Пускать не чаще раза в сутки — для тревог, которые иначе шлются пачками.

    Сторож лимита удалений срабатывает на КАЖДОГО кандидата и на каждом часовом
    тике: без этой отсечки Николь получала бы сотни одинаковых сообщений.
    """
    now = datetime.utcnow()
    try:
        with SessionLocal() as s:
            row = s.get(BotSetting, key)
            if row and row.value:
                try:
                    if now - datetime.fromisoformat(row.value) < timedelta(days=1):
                        return False
                except ValueError:
                    pass
            if row is None:
                s.add(BotSetting(key=key, value=now.isoformat(), updated_at=now))
            else:
                row.value, row.updated_at = now.isoformat(), now
            s.commit()
        return True
    except Exception as exc:  # noqa: BLE001 — БД молчит: лучше сказать, чем нет
        log.warning("club _once_a_day: %s", type(exc).__name__)
        return True


# ─── клавиатуры ──────────────────────────────────────────────────────────────

def _period_kb(codes: tuple[str, ...], currency: str | None) -> InlineKeyboardMarkup:
    """Кнопки периодов. Валюта известна у тех, кто уже платил — им показываем
    цену сразу; новичку валюту спросим следующим шагом."""
    rows = []
    for code in codes:
        label = (T.price_label(currency, code) if currency
                 else T.PERIOD_LABELS.get(code, code))
        rows.append([InlineKeyboardButton(text=label,
                                          callback_data=f"club:per:{code}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _currency_kb(period: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        text=f"{lava.CURRENCY_LABELS.get(c, c)} — {T.price_label(c, period)}",
        callback_data=f"club:cur:{c}")] for c in lava.CURRENCIES]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _offer_periods(m: ClubMember | None) -> tuple[str, ...]:
    """ЗДЕСЬ ЖИВЁТ ПРАВИЛО НИКОЛЬ: месяц показываем только тому, кто ещё ни разу
    не платил. Заплатил хоть раз — дальше только квартал и полгода.

    Правило намеренно выражено кодом, а не формулировкой в тексте письма: текст
    правят каждую неделю, и правило пережило бы ровно до первой правки. По этой
    же причине оно проверяется ещё раз при выборе периода (`cb_period`): старая
    кнопка «Месяц» из прошлого сообщения иначе работала бы вечно.
    """
    if m is None or (m.payments_count or 0) == 0:
        return ("month",) + T.RENEW_PERIODS
    return T.RENEW_PERIODS


# ─── вход в поток ────────────────────────────────────────────────────────────

async def show_intro(bot: Bot, chat_id: int, user) -> None:
    """Приглашение в клуб: что это и кнопки «вступить» / «уже оплатил на сайте»."""
    with SessionLocal() as s:
        _member(s, user)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=T.BTN_CLUB_JOIN, callback_data="club:join")],
        [InlineKeyboardButton(text=T.BTN_PAID_ON_SITE, callback_data="club:onsite")],
    ])
    await bot.send_message(chat_id, T.CLUB_INTRO, reply_markup=kb,
                           disable_web_page_preview=True)


@router.callback_query(F.data == "club:join")
async def cb_join(call: CallbackQuery) -> None:
    with SessionLocal() as s:
        m = _member(s, call.from_user)
        currency, paid_until = m.lava_currency, m.paid_until
        periods = _offer_periods(m)
        first = (m.payments_count or 0) == 0
        payments = m.payments_count or 0

    # Гость с бесплатных времён: он уже в канале, а платежей за ним нет. Такому
    # продавать подписку нельзя — Николь обещала им бессрочный доступ, и, купив,
    # он попал бы в общий цикл, который однажды его же и удалит.
    if payments == 0 and not paid_until:
        inside = await _in_channel(call.bot, call.from_user.id)
        if inside:
            await call.message.answer(T.ALREADY_FREE)
            await call.answer()
            return
        if inside is None:
            # Telegram не ответил. «Не знаю» — это не «не в канале»: продать
            # подписку бессрочному гостю хуже, чем попросить подождать минуту.
            await call.message.answer(T.CHECK_LATER)
            await call.answer()
            return

    # Оплачено, но человека нет в канале — значит персональная ссылка протухла
    # (она живёт сутки). Ему нужна новая ссылка, а не предложение заплатить
    # ещё раз: это самая обидная развилка для того, кто уже заплатил.
    if paid_until and paid_until > datetime.utcnow():
        if await _in_channel(call.bot, call.from_user.id) is False:
            await _grant_channel_access(call.bot, call.from_user.id)
            await call.answer()
            return

    # Активный доступ — не повод отказать: продлить заранее должно быть можно,
    # иначе человек упирается в «вы уже в клубе» и уходит.
    title = T.PERIOD_TITLE if first else T.PERIOD_TITLE_RENEW
    if paid_until and paid_until > datetime.utcnow():
        title = (T.ALREADY_IN.format(until=_human_date(paid_until))
                 + "\n\n" + T.PERIOD_TITLE_RENEW)
    await call.message.answer(title, reply_markup=_period_kb(periods, currency))
    await call.answer()


@router.callback_query(F.data == "club:onsite")
async def cb_paid_on_site(call: CallbackQuery) -> None:
    """«Я оплатил на сайте» — вход для тех, кто оформил подписку по ссылке Lava.

    Без этого пути выпускники интенсива, вошедшие по промокоду на бесплатный
    первый месяц, оставались без доступа: их счёт бот не выставлял и в кассе их
    не искал.
    """
    _expect(call.from_user.id, "onsite_email")
    await call.message.answer(T.PAID_ON_SITE_ASK_EMAIL)
    await call.answer()


@router.callback_query(F.data.startswith("club:per:"))
async def cb_period(call: CallbackQuery) -> None:
    code = call.data.rsplit(":", 1)[-1]
    if code not in lava.CLUB_PERIODS:
        await call.answer()
        return
    with SessionLocal() as s:
        m = _member(s, call.from_user)
        allowed = _offer_periods(m)
        currency = m.lava_currency
        member_id = m.telegram_id
        permitted = code in allowed
        if permitted:
            m.lava_periodicity = lava.CLUB_PERIODS[code][0]
            s.commit()

    if not permitted:
        # Кнопка из старого сообщения. Правило «месяц только на первый раз»
        # должно держаться и здесь, а не только при отрисовке клавиатуры:
        # сообщения в Telegram живут вечно, и нажать вчерашнюю кнопку можно
        # через месяц.
        await call.message.answer(T.PERIOD_TITLE_RENEW,
                                  reply_markup=_period_kb(allowed, currency))
        await call.answer()
        return

    # Валюту, которой человек платил раньше, второй раз не спрашиваем.
    if currency in lava.CURRENCIES:
        await _ask_email(call.message, member_id)
    else:
        await call.message.answer(T.CURRENCY_TITLE, reply_markup=_currency_kb(code))
    await call.answer()


@router.callback_query(F.data.startswith("club:cur:"))
async def cb_currency(call: CallbackQuery) -> None:
    currency = call.data.rsplit(":", 1)[-1]
    if currency not in lava.CURRENCIES:
        await call.answer()
        return
    _mark(call.from_user.id, lava_currency=currency)
    await _ask_email(call.message, call.from_user.id)
    await call.answer()


async def _ask_email(message: Message, telegram_id: int) -> None:
    with SessionLocal() as s:
        m = s.query(ClubMember).filter_by(telegram_id=telegram_id).first()
        known = m.email if m else None
    if known:
        # Email уже знаем — счёт выставляем сразу, лишний шаг ни к чему.
        await _issue_invoice(message, telegram_id, known)
        return
    _expect(telegram_id, "email")
    await message.answer(T.EMAIL_ASK)


async def handle_text(msg: Message) -> bool:
    """Текст, которого ждёт клуб: e-mail, адрес оплаты на сайте или отзыв.

    Возвращает True, если сообщение обработано здесь. Вызывается из общего
    текстового хендлера бота оплат: в aiogram хендлеры самого диспетчера
    разбираются раньше роутеров, и без этой явной передачи клубный текст уходил
    бы в поток интенсива.
    """
    mode = _expected(msg.from_user.id)
    if mode is None:
        return False

    if mode == "feedback":
        _forget(msg.from_user.id)
        text = (msg.text or "")[:1000]
        _mark(msg.from_user.id, feedback=text)
        with SessionLocal() as s:
            m = s.query(ClubMember).filter_by(telegram_id=msg.from_user.id).first()
            who = _who(m) if m else f"id{msg.from_user.id}"
        # Чужой текст — данные, а не команда: пересылаем как есть, но
        # экранируем. Бот работает в parse_mode=HTML, и один символ «<» в отзыве
        # означал бы, что сообщение Николь не доставлено вовсе.
        await _notify_admin(msg.bot, T.ADMIN_FEEDBACK.format(
            who=html.escape(who), text=html.escape(text)))
        await msg.answer(T.FEEDBACK_THANKS)
        return True

    if mode in ("email", "onsite_email"):
        email = (msg.text or "").strip()
        if not EMAIL_RE.match(email):
            await msg.answer(T.EMAIL_BAD)
            return True
        _forget(msg.from_user.id)
        _mark(msg.from_user.id, email=email)
        if mode == "onsite_email":
            await _check_on_site(msg, msg.from_user.id, email)
        else:
            await _issue_invoice(msg, msg.from_user.id, email)
        return True

    return False


async def _check_on_site(message: Message, telegram_id: int, email: str) -> None:
    """Подписка оформлена на витрине Lava — найти её по e-mail и открыть канал.

    Три предохранителя, без которых этот путь был бы дырой в кассе:
    1. Один зачёт на период. Кнопка «Я оплатил на сайте» живёт в чате вечно, и
       без отметки каждое нажатие добавляло бы ещё месяц доступа.
    2. Один e-mail — один человек. Иначе адрес подписчика, увиденный в чужом
       скриншоте, открывал бы канал кому угодно.
    3. Строгая сверка (`strict=True`): «подписка создана, но не оплачена» —
       не основание пускать в платный канал.
    """
    now = datetime.utcnow()
    marker = f"onsite:{email.strip().lower()}"

    with SessionLocal() as s:
        m = s.query(ClubMember).filter_by(telegram_id=telegram_id).first()
        if m is None:
            await message.answer(T.PAID_ON_SITE_LAVA_SILENT)
            await _notify_admin(message.bot,
                                f"⚠️ id{telegram_id} подтверждает оплату клуба "
                                f"на сайте, но его строки в базе нет.")
            return
        # Этот же адрес уже зачтён и период ещё идёт — просто открываем канал.
        if m.lava_subscription_id == marker and m.paid_until and m.paid_until > now:
            already = True
        else:
            already = False
        taken = (s.query(ClubMember)
                 .filter(ClubMember.email == email)
                 .filter(ClubMember.telegram_id != telegram_id)
                 .filter(ClubMember.paid_until.isnot(None))
                 .first())
    if already:
        await _grant_channel_access(message.bot, telegram_id)
        return
    if taken is not None:
        await message.answer(T.PAID_ON_SITE_NOT_FOUND)
        await _notify_admin(message.bot,
                            f"⚠️ id{telegram_id} назвал e-mail, который уже "
                            f"привязан к другому участнику клуба. Доступ не выдан.")
        return

    items = await asyncio.to_thread(lava.subscriptions)
    if items is None:
        await message.answer(T.PAID_ON_SITE_LAVA_SILENT)
        return
    if not _subscription_active(email, items, strict=True):
        await message.answer(T.PAID_ON_SITE_NOT_FOUND)
        await _notify_admin(message.bot,
                            f"ℹ️ id{telegram_id} говорит, что оплатил клуб на "
                            f"сайте, но живой подписки по его адресу в кассе нет.")
        return

    with SessionLocal() as s:
        m = s.query(ClubMember).filter_by(telegram_id=telegram_id).first()
        if m is None:
            return
        if m.lava_subscription_id == marker and m.paid_until and m.paid_until > now:
            pass                                   # успели зачесть параллельно
        else:
            m.lava_periodicity = m.lava_periodicity or "MONTHLY"
            # ⚠️ Период с витрины бот не знает: в ответе кассы его формат пока
            # не подтверждён. Даём месяц — минимальный шаг. Если человек купил
            # там полгода, цепочка напомнит раньше срока, и это лечится ответом
            # «у меня оплачено до…», а не молчаливой выдачей полугода.
            m.paid_until = max(m.paid_until or now, now) + timedelta(days=31)
            m.paid_at = now
            m.payments_count = (m.payments_count or 0) + 1
            m.status = "paid"
            m.lava_subscription_id = marker
            m.reminder_step, m.unsubscribed, m.grace_given_at = 0, False, None
            m.warned_at = None
        s.commit()
    log.info("club: подписка с витрины подтверждена, id%s", telegram_id)
    await _grant_channel_access(message.bot, telegram_id)


async def _issue_invoice(message: Message, telegram_id: int, email: str) -> None:
    """Счёт в Lava на выбранный период. Сумму показываем ту, что вернула касса."""
    with SessionLocal() as s:
        m = s.query(ClubMember).filter_by(telegram_id=telegram_id).first()
        periodicity = (m.lava_periodicity if m else None) or "MONTHLY"
        currency = (m.lava_currency if m else None) or "RUB"
        renewing = bool(m and (m.payments_count or 0) > 0)

    inv = await asyncio.to_thread(lava.create_invoice, email, currency,
                                  lava.OFFER_CLUB, periodicity)
    if not inv:
        await message.answer("Не удалось выставить счёт. Напишите Николь — "
                             "поможем оплатить вручную.")
        await _notify_admin(message.bot,
                            f"⚠️ Не выставился счёт на клуб для id{telegram_id}")
        return

    _mark(telegram_id, lava_invoice_id=inv["id"], lava_invoice_url=inv["url"],
          invoiced_at=datetime.utcnow(), status="invoiced")

    code = _period_code(periodicity)
    expected = T.PRICES.get(currency, {}).get(code)
    actual = inv.get("amount")
    # Сверка «что в кнопке» и «что просит касса». Проверка появилась не из
    # осторожности: 04.08.2026 в кассе переименовали оффер, не меняя id, и бот
    # сутки продавал не то. Расхождение в цене — тот же класс ошибки.
    if expected is not None and actual is not None and \
            abs(float(actual) - float(expected)) > 0.01:
        await _notify_admin(message.bot, T.ADMIN_PRICE_MISMATCH.format(
            period=T.PERIOD_LABELS.get(code, code), currency=currency,
            expected=_fmt_amount(currency, expected),
            actual=_fmt_amount(currency, actual)))
    if actual is None:
        # Касса не вернула сумму — показываем свою, иначе человек увидит
        # «Счёт на RUB готов» и не поймёт, сколько платит.
        log.warning("club: касса не вернула сумму счёта, показываю цену из конфига")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=T.BTN_INVOICE, url=inv["url"])],
        [InlineKeyboardButton(text=T.BTN_STATUS, callback_data="club:check")],
    ])
    text = T.INVOICE_READY.format(
        amount=_fmt_amount(inv.get("currency") or currency,
                           actual if actual is not None else expected))
    if renewing and code != "month":
        text += T.RENEW_WARNING
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "club:check")
async def cb_check(call: CallbackQuery) -> None:
    """Ручная проверка оплаты по кнопке (фоновая идёт своим чередом)."""
    done = await try_grant_access(call.bot, call.from_user.id)
    if not done:
        await call.message.answer(T.NOT_PAID_YET)
    await call.answer()


# ─── ответы на вопрос в день окончания ───────────────────────────────────────

@router.callback_query(F.data == "club:willpay")
async def cb_will_pay(call: CallbackQuery) -> None:
    """«Оплачу» — отодвигаем удаление на три дня. РОВНО ОДИН РАЗ за период.

    Без этого ограничения кнопка становится бесплатным клубом в один тап:
    старое сообщение с кнопкой живёт в чате вечно, и каждое нажатие добавляло бы
    ещё три дня.
    """
    now = datetime.utcnow()
    with SessionLocal() as s:
        m = _member(s, call.from_user)
        already = m.grace_given_at is not None
        # Удалённому отсрочка бессмысленна: доступа у него уже нет, и «оставляю
        # ещё на три дня» звучало бы издевательством. Ему сразу кнопки оплаты.
        removed = m.status == "removed"
        if not already and not removed:
            m.paid_until = max(m.paid_until or now, now) + timedelta(days=3)
            m.grace_given_at = now
            # Статус `invoiced` не трогаем: у человека на руках счёт, и подмена
            # выкинула бы его из фоновой проверки оплаты.
            if m.status not in ("invoiced",):
                m.status = "expiring"
            # Шаг НЕ обнуляем: иначе за три дня отсрочки человек получит всю
            # цепочку заново, включая «через неделю» при остатке в два дня.
            m.reminder_step = len(T.REMINDER_DAYS)
            m.last_touch_at = now
            s.commit()
        until, currency = m.paid_until, m.lava_currency
    text = (T.PERIOD_TITLE_RENEW if removed
            else (T.WILL_PAY_AGAIN if already else T.WILL_PAY_OK).format(
                until=_human_date(until)))
    await call.message.answer(text, reply_markup=_period_kb(
        _offer_periods_for(call.from_user.id), currency))
    await call.answer()


def _offer_periods_for(telegram_id: int) -> tuple[str, ...]:
    with SessionLocal() as s:
        m = s.query(ClubMember).filter_by(telegram_id=telegram_id).first()
        return _offer_periods(m)


@router.callback_query(F.data == "club:leaving")
async def cb_leaving(call: CallbackQuery) -> None:
    """«Ухожу» — уважаем ответ: больше не пишем, удалим в общем порядке."""
    with SessionLocal() as s:
        m = _member(s, call.from_user)
        m.unsubscribed = True
        m.last_touch_at = datetime.utcnow()
        # Статус `invoiced` не затираем: человек мог передумать и оплатить по
        # уже выставленному счёту, и эту оплату бот обязан заметить.
        if m.status not in ("invoiced", "removed"):
            m.status = "asked"
        s.commit()
    await call.message.answer(T.LEAVING_OK)
    _expect(call.from_user.id, "feedback")
    await call.answer()


# ─── бота сделали админом канала клуба ───────────────────────────────────────

@router.my_chat_member(F.chat.type == "channel")
async def on_added_to_channel(ev: ChatMemberUpdated, bot: Bot) -> None:
    """Канал нельзя подключить из кода — админа назначает человек.

    ⚠️ Этот же тип события ловит привратник канала 18+. Поэтому запоминаем канал
    ТОЛЬКО если он уже назван клубным в переменной окружения: иначе добавление
    бота в любой другой канал молча увело бы клубные ссылки не туда.
    """
    if ev.new_chat_member.status in ("left", "kicked"):
        return
    if not settings.CLUB_CHANNEL_ID or str(ev.chat.id) != str(settings.CLUB_CHANNEL_ID):
        return
    can_invite = bool(getattr(ev.new_chat_member, "can_invite_users", False))
    can_restrict = bool(getattr(ev.new_chat_member, "can_restrict_members", False))
    with SessionLocal() as s:
        row = s.get(BotSetting, CHANNEL_KEY)
        if row is None:
            s.add(BotSetting(key=CHANNEL_KEY, value=str(ev.chat.id),
                             updated_at=datetime.utcnow()))
        else:
            row.value, row.updated_at = str(ev.chat.id), datetime.utcnow()
        s.commit()
    log.info("club: канал %s подключён, invite=%s restrict=%s",
             ev.chat.id, can_invite, can_restrict)
    problems = []
    if not can_invite:
        problems.append("нет права «Пригласительные ссылки» — доступ не выдам")
    if not can_restrict:
        problems.append("нет права «Блокировать пользователей» — не смогу убрать "
                        "того, кто перестал платить")
    await _notify_admin(bot, f"✅ Канал клуба подключён (id {ev.chat.id})."
                             + ("\n\n⚠️ " + "\n⚠️ ".join(problems) if problems
                                else " Прав хватает."))


@router.chat_member(F.chat.type == "channel")
async def on_channel_member(ev: ChatMemberUpdated) -> None:
    """Человек вошёл в канал клуба или вышел. Новых строк не создаём: таблица
    про платящих, а не про всех участников канала — в этом и защита тех, кто
    сидит здесь с бесплатных времён."""
    cid = channel_id()
    if not cid or str(ev.chat.id) != str(cid):
        return
    status = ev.new_chat_member.status
    with SessionLocal() as s:
        m = s.query(ClubMember).filter_by(telegram_id=ev.from_user.id).first()
        if m is None:
            return
        if status in IN_CHANNEL_STATUSES and m.status in ("invoiced", "new", "paid"):
            m.status = "active"
        s.commit()


# ─── выдача доступа ──────────────────────────────────────────────────────────

async def try_grant_access(bot: Bot, telegram_id: int) -> bool:
    """Оплатил? → одноразовая ссылка в канал клуба. Идемпотентно.

    Возвращает True, если оплата подтверждена (в том числе если доступ выдан
    раньше). False — оплаты пока нет.
    """
    with SessionLocal() as s:
        m = s.query(ClubMember).filter_by(telegram_id=telegram_id).first()
        if m is None or not m.lava_invoice_id:
            return False
        invoice_id = m.lava_invoice_id
        # Счёт, который уже зачли, второй раз период не даёт. Кнопка «Проверить
        # оплату» живёт в чате вечно, и без этой проверки одна оплата
        # продлевала бы доступ столько раз, сколько по ней нажали.
        counted = (m.paid_invoice_id == invoice_id)
        active = bool(m.paid_until and m.paid_until > datetime.utcnow())
        periodicity = m.lava_periodicity or "MONTHLY"
        currency = m.lava_currency or "RUB"
        renewing = (m.payments_count or 0) > 0

    if counted:
        # Оплата за этот счёт уже учтена: остаётся убедиться, что человек в
        # канале (мог не дойти по ссылке или выйти).
        if active:
            await _grant_channel_access(bot, telegram_id)
            return True
        return False

    paid = await asyncio.to_thread(lava.invoice_paid, invoice_id)
    if not paid:
        return False

    now = datetime.utcnow()
    days = _period_days(periodicity)
    with SessionLocal() as s:
        m = s.query(ClubMember).filter_by(telegram_id=telegram_id).first()
        if m is None or m.paid_invoice_id == invoice_id:
            return True                      # успели зачесть параллельно
        # Продление считаем ОТ ТЕКУЩЕЙ ДАТЫ ОКОНЧАНИЯ, а не от сегодня: человек,
        # оплативший за три дня до конца, не должен терять эти три дня.
        base = m.paid_until if (m.paid_until and m.paid_until > now) else now
        m.paid_until = base + timedelta(days=days)
        m.paid_at = now
        m.paid_invoice_id = invoice_id
        m.payments_count = (m.payments_count or 0) + 1
        m.status = "paid"
        m.reminder_step = 0          # новая оплата — цепочка с чистого листа
        m.grace_given_at = None
        m.warned_at = None
        # Вернулся и заплатил — снова пишем ему письма. Иначе тот, кто однажды
        # нажал «Ухожу», а потом вернулся, вылетел бы молча, без предупреждений.
        m.unsubscribed = False
        m.invite_failed_at = None
        s.commit()
        who, until, count = _who(m), m.paid_until, m.payments_count

    code = _period_code(periodicity)
    await _notify_admin(bot, T.ADMIN_PAID.format(
        who=html.escape(who), period=T.PERIOD_LABELS.get(code, code),
        amount=_fmt_amount(currency, T.PRICES.get(currency, {}).get(code)),
        until=_human_date(until), invoice=invoice_id))
    if renewing and code != "month":
        # Lava не закрывает старую подписку сама — Николь должна проверить.
        await _notify_admin(bot, T.ADMIN_DOUBLE_SUB.format(
            who=html.escape(who), period=T.PERIOD_LABELS.get(code, code)))
    log.info("club: оплата подтверждена id%s, платёж №%s", telegram_id, count)

    await _grant_channel_access(bot, telegram_id)
    return True


async def _grant_channel_access(bot: Bot, telegram_id: int) -> None:
    """Впустить в канал: сначала проверяем, не внутри ли уже, потом ссылка."""
    cid = channel_id()
    with SessionLocal() as s:
        m = s.query(ClubMember).filter_by(telegram_id=telegram_id).first()
        if m is None:
            return
        until, failed_at = m.paid_until, m.invite_failed_at

    if not cid:
        await _report_invite_problem(bot, telegram_id, "канал не подключён",
                                     failed_at)
        return

    inside = await _in_channel(bot, telegram_id)
    if inside:
        with SessionLocal() as s:
            m = s.query(ClubMember).filter_by(telegram_id=telegram_id).first()
            if m:
                m.status, m.invite_failed_at = "active", None
                until = m.paid_until
                s.commit()
        try:
            await bot.send_message(telegram_id,
                                   T.ALREADY_IN.format(until=_human_date(until)))
        except Exception as exc:  # noqa: BLE001 — заблокировал бота
            log.info("club notify id%s: %s", telegram_id, type(exc).__name__)
        return

    try:
        # Срок жизни ссылки — интервалом, а не датой: aiogram сериализует naive
        # datetime как ЛОКАЛЬНОЕ время, и на сервере в зоне Дубая (+4) ссылка
        # протухала бы на четыре часа раньше срока (урок привратника канала).
        link = await bot.create_chat_invite_link(
            chat_id=cid, member_limit=1, name=f"club-{telegram_id}",
            expire_date=timedelta(hours=LINK_TTL_HOURS))
    except Exception as exc:  # noqa: BLE001
        log.error("club invite failed id%s: %s", telegram_id, type(exc).__name__)
        await _report_invite_problem(bot, telegram_id, type(exc).__name__, failed_at)
        return

    with SessionLocal() as s:
        m = s.query(ClubMember).filter_by(telegram_id=telegram_id).first()
        if m:
            m.invite_link, m.invited_at = link.invite_link, datetime.utcnow()
            m.status, m.invite_failed_at = "active", None
            until = m.paid_until
            s.commit()
    try:
        await bot.send_message(telegram_id, T.PAID_OK.format(
            link=link.invite_link, until=_human_date(until)),
            disable_web_page_preview=True)
    except Exception as exc:  # noqa: BLE001
        log.info("club link id%s не доставлена: %s", telegram_id, type(exc).__name__)


async def _report_invite_problem(bot: Bot, telegram_id: int, error: str,
                                 failed_at: datetime | None) -> None:
    """Доступ выдать не вышло. Человеку говорим ОДИН раз, Николь — раз в сутки.

    Раньше здесь не было отметки времени, а фоновый цикл ходит каждую минуту:
    человек и Николь получали бы по сообщению в минуту, пока проблема не решена.
    """
    now = datetime.utcnow()
    first_time = failed_at is None
    _mark(telegram_id, invite_failed_at=now)
    if first_time:
        try:
            await bot.send_message(telegram_id, T.PAID_NO_CHANNEL)
        except Exception as exc:  # noqa: BLE001
            log.info("club no-channel id%s: %s", telegram_id, type(exc).__name__)
    if _once_a_day(f"club_invite_alert_{telegram_id}"):
        with SessionLocal() as s:
            m = s.query(ClubMember).filter_by(telegram_id=telegram_id).first()
            who = _who(m) if m else f"id{telegram_id}"
        await _notify_admin(bot, T.ADMIN_INVITE_STUCK.format(
            error=error, who=html.escape(who)))


async def poll_payments_once(bot: Bot) -> int:
    """Проверить тех, кто получил счёт, но ещё не в клубе.

    Берём только СВЕЖИЕ счета: брошенный счёт полугодовой давности иначе
    опрашивался бы у кассы каждую минуту вечно — это и лишний трафик, и риск
    упереться в лимит запросов.
    """
    if not lava.is_configured():
        return 0
    since = datetime.utcnow() - timedelta(days=INVOICE_MAX_AGE_DAYS)
    hour_ago = datetime.utcnow() - timedelta(hours=1)
    with SessionLocal() as s:
        rows = (s.query(ClubMember)
                .filter(ClubMember.status.in_(("invoiced", "paid")))
                .filter(ClubMember.lava_invoice_id.isnot(None))
                # Счёт выставлен недавно. У старых строк поля нет (NULL) —
                # их тоже берём: это те, кто платил до появления поля.
                .filter((ClubMember.invoiced_at.is_(None))
                        | (ClubMember.invoiced_at >= since))
                .all())
        ids = [r.telegram_id for r in rows
               # Не бьёмся в стену «инвайт не выдаётся» чаще раза в час.
               if r.invite_failed_at is None or r.invite_failed_at <= hour_ago]
    granted = 0
    for tid in ids:
        try:
            if await try_grant_access(bot, tid):
                granted += 1
        except Exception as exc:  # noqa: BLE001 — один человек не роняет цикл
            log.warning("club poll id%s: %s", tid, type(exc).__name__)
    return granted


# ─── сверка продлений с кассой ───────────────────────────────────────────────

def _iter_strings(obj):
    """Все строковые значения записи — по ним ищем e-mail."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from _iter_strings(value)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            yield from _iter_strings(value)


def _is_club_record(item: dict) -> bool:
    """Запись подписки относится к клубу?

    В кассе Николь живут и другие продукты, и подписочных станет больше. Без
    этой проверки человек с подпиской на соседний продукт открыл бы клубный
    канал, а переставший платить за клуб не был бы удалён — его адрес нашёлся бы
    в чужой подписке.

    Пока формат ответа не подтверждён живыми данными, действуем осторожно: если
    в записи вообще не видно ни одного идентификатора оффера/продукта, считаем
    её подходящей (иначе сверка перестала бы работать вовсе).
    """
    ids = {s.strip().lower() for s in _iter_strings(item) if len(s) == 36}
    known = {lava.OFFER_CLUB.lower(), lava.OFFER_INTENSIVE.lower(),
             lava.OFFER_FIRST_DAY.lower(), lava.OFFER_DFY.lower()}
    if not (ids & known):
        return True
    return lava.OFFER_CLUB.lower() in ids


def _subscription_active(email: str, items: list[dict], strict: bool = False) -> bool:
    """Есть ли у этого e-mail живая подписка на КЛУБ.

    Сравниваем ТОЧНО, а не подстрокой: `ann@mail.com` содержится в
    `joann@mail.com`, и поиск подстрокой однажды продлил бы доступ не тому
    человеку — а заодно отменил бы его удаление.

    `strict=True` — для решений, которые дают человеку оплаченное время
    (продлить период, открыть канал по заявлению «я оплатил на сайте»): там
    нужен явно живой статус. `strict=False` — для решений в его пользу (не
    удалять): там неизвестный статус трактуем как «возможно платит».

    ⚠️ Формат `/api/v1/subscriptions` на 04.08.2026 не проверен на живых данных
    (подписок в кассе не было). Когда появится первая, `lava.subscriptions()`
    запишет ключи в лог — тогда разбор можно сделать точным.
    """
    needle = email.strip().lower()
    dead = ("cancel", "expired", "failed", "inactive", "declin")
    # `new` и `trial` в этот список НЕ входят намеренно: только что созданная
    # подписка ещё не оплачена, и дарить за неё период (или открывать канал)
    # означало бы выдавать доступ за намерение заплатить.
    alive = ("active", "paid", "completed", "success")
    for item in items:
        if not _is_club_record(item):
            continue
        if not any(s.strip().lower() == needle for s in _iter_strings(item)):
            continue
        status = str(item.get("status", "")).lower()
        if status and any(bad in status for bad in dead):
            continue
        if strict and not (status and any(good in status for good in alive)):
            continue
        return True
    return False


def _emails_visible(items: list[dict]) -> bool:
    """Видно ли в ответе кассы вообще хоть один e-mail.

    Сторож против самой дорогой ошибки этой фичи. Сверка ищет человека по
    e-mail; если Lava перестанет отдавать его в подписках (или формат окажется
    другим), поиск не найдёт НИКОГО — и цикл добросовестно выгонит из канала
    всех платящих. Поэтому: подписки есть, а e-mail в них не видно → сверке
    верить нельзя.
    """
    for item in items:
        try:
            if "@" in json.dumps(item, ensure_ascii=False):
                return True
        except (TypeError, ValueError):
            continue
    return False


async def refresh_from_lava(bot: Bot, items: list[dict] | None) -> None:
    """Продлить `paid_until` тем, у кого касса списала сама.

    ⚠️ САМОЕ ТОНКОЕ МЕСТО ФИЧИ. Продлеваем ТОЛЬКО просроченных — тех, у кого
    оплаченный период уже кончился. Раньше окно было «за 8 дней до конца», и оно
    оказалось шире окна первого напоминания (за 7 дней): подписка в кассе
    считалась живой, дата уезжала вперёд, и ни одно письмо цепочки не уходило
    никогда. То есть ровно то, ради чего фича написана, не работало.

    Продлеваем строго при живом статусе (`strict=True`): «статус неизвестен» —
    это не повод дарить месяц доступа.

    `items` — снимок подписок, полученный ОДИН раз за проход цикла: так решения
    одного тика согласованы между собой, а касса не опрашивается по кругу.
    """
    if items is None:
        return
    if items and not _emails_visible(items):
        log.error("club: в подписках Lava не видно e-mail — сверка невозможна")
        if _once_a_day("club_subs_format_alert"):
            await _notify_admin(bot, T.ADMIN_SUBS_FORMAT)
        return
    now = datetime.utcnow()
    with SessionLocal() as s:
        rows = (s.query(ClubMember)
                .filter(ClubMember.status.in_(("active", "expiring", "asked")))
                .filter(ClubMember.email.isnot(None))
                .filter(ClubMember.paid_until.isnot(None))
                .filter(ClubMember.paid_until <= now).all())
        for m in rows:
            if not _subscription_active(m.email, items, strict=True):
                continue
            # Касса подтверждает живую подписку у просроченного — значит она
            # списала сама. Продлеваем на длину купленного периода.
            days = _period_days(m.lava_periodicity)
            m.paid_until = now + timedelta(days=days)
            m.payments_count = (m.payments_count or 0) + 1
            m.status = "active"
            m.reminder_step = 0
            m.grace_given_at = None
            m.warned_at = None
            # Оплата отменяет «не пишите мне»: человек, который однажды нажал
            # «Ухожу», а потом продолжил платить, должен снова получать
            # предупреждения — иначе однажды вылетит молча.
            m.unsubscribed = False
            log.info("club: подписка продлена кассой, id%s", m.telegram_id)
        s.commit()


# ─── цепочка удержания ───────────────────────────────────────────────────────

def _renew_kb(currency: str | None) -> InlineKeyboardMarkup:
    """Кнопки продления: только квартал и полгода. Месяца здесь нет."""
    return _period_kb(T.RENEW_PERIODS, currency)


async def _touch(bot: Bot, telegram_id: int, step: int, text: str,
                 keyboard: InlineKeyboardMarkup | None) -> bool:
    """Одно касание. Возвращает True, если сообщение ушло.

    Отметку времени ставим в любом случае — даже когда доставить не удалось:
    иначе заблокировавший бота человек заставлял бы цикл ломиться к нему каждый
    час, а цепочка на нём же и застревала бы.
    """
    now = datetime.utcnow()
    try:
        await bot.send_message(telegram_id, text, reply_markup=keyboard,
                               disable_web_page_preview=True)
    except Exception as exc:  # noqa: BLE001 — заблокировал бота или удалил чат
        log.info("club touch id%s не доставлено: %s", telegram_id,
                 type(exc).__name__)
        _mark(telegram_id, last_touch_at=now, reminder_step=step)
        return False
    # Статус двигаем аккуратно: `invoiced` не трогаем — у человека на руках счёт,
    # и подмена статуса выкинула бы его из проверки оплаты.
    with SessionLocal() as s:
        m = s.query(ClubMember).filter_by(telegram_id=telegram_id).first()
        if m:
            m.reminder_step = max(m.reminder_step or 0, step)
            m.last_touch_at = now
            if step >= len(T.REMINDER_DAYS):
                # Последний шаг ДОСТАВЛЕН — только теперь человек считается
                # предупреждённым, и только теперь его можно убирать из канала.
                m.warned_at = now
            if m.status not in ("invoiced", "removed"):
                m.status = "expiring" if step < len(T.REMINDER_DAYS) else "asked"
            s.commit()
    return True


def _step_for(days_left: float) -> int:
    """Какой шаг цепочки уместен при таком остатке дней. 0 — ещё рано писать.

    Шаг выбирается ПО ОСТАТКУ, а не «первый непройденный». Иначе человек,
    оплативший поздно (или получивший трёхдневную отсрочку), получал бы письмо
    «через неделю доступ заканчивается» при остатке в два дня — и следом,
    по одному в сутки, всю остальную цепочку с неверными сроками.

    Берём САМЫЙ ПОЗДНИЙ подходящий шаг: при остатке 2 дня это «через три дня»,
    а не «через неделю»; при остатке 10 дней — ни одного.
    """
    step = 0
    for idx, days_before in enumerate(T.REMINDER_DAYS, start=1):
        if days_left <= days_before:
            step = idx
    return step


async def retention_tick(bot: Bot, items: list[dict] | None = None) -> dict:
    """Один проход цепочки: напоминания и удаления. Зовётся раз в час.

    `items` — снимок подписок кассы на этот проход. `None` означает «касса не
    ответила»: тогда напоминания идут (им касса не нужна), а удаления нет —
    внутри `_remove_member` без снимка решение не принимается.
    """
    stats = {"reminded": 0, "asked": 0, "removed": 0, "skipped": 0}
    if not settings.CLUB_RETENTION_LIVE:
        return stats
    if not channel_id():
        # Канал не подключён: ссылки выдавать некуда, но и молчать нельзя —
        # иначе продукт тихо выключается целиком, и никто об этом не узнает.
        if _once_a_day("club_no_channel_alert"):
            await _notify_admin(bot, T.ADMIN_NO_CHANNEL)
        return stats

    await refresh_from_lava(bot, items)

    now = datetime.utcnow()
    with SessionLocal() as s:
        rows = (s.query(ClubMember)
                # `invoiced` тоже здесь: продлевающий получает этот статус в
                # момент выставления счёта, и без него человек со счётом на
                # руках выпадал бы и из напоминаний, и из удаления.
                .filter(ClubMember.status.in_(
                    ("active", "expiring", "asked", "invoiced")))
                .filter(ClubMember.paid_until.isnot(None)).all())
        # Отвязываем от сессии: дальше идут сетевые вызовы, держать открытую
        # транзакцию всё это время незачем.
        members = [(r.telegram_id, r.paid_until, r.reminder_step or 0,
                    r.last_touch_at, r.lava_currency, bool(r.unsubscribed),
                    r.warned_at, r.invoiced_at)
                   for r in rows]

    for (telegram_id, paid_until, step, last_touch, currency, unsub,
         warned_at, invoiced_at) in members:
        days_left = (paid_until - now).total_seconds() / 86400

        if days_left < -T.GRACE_DAYS:
            # Человек прямо сейчас платит: счёт выставлен за последние сутки.
            # Выгнать его в эту минуту — самое обидное, что бот может сделать.
            if invoiced_at and (now - invoiced_at) < timedelta(days=1):
                stats["skipped"] += 1
                continue
            # Удаляем только тех, кому предупреждение ДОШЛО: цепочка должна была
            # доставить вопрос «точно не продлеваете?». Исключение — просрочка в
            # две недели: если письма не доходят вовсе (бот заблокирован),
            # человек не может занимать платное место бесконечно.
            warned = warned_at is not None
            long_overdue = days_left < -NO_TOUCH_REMOVE_DAYS
            if not (warned or long_overdue):
                stats["skipped"] += 1
                continue
            if await _remove_member(bot, telegram_id, items):
                stats["removed"] += 1
            else:
                stats["skipped"] += 1
            continue

        if unsub:                      # сказал «ухожу» — молчим до удаления
            stats["skipped"] += 1
            continue

        # Не чаще одного касания в сутки — правило плана: два письма за день
        # выглядят как сбой, а не как забота.
        if last_touch and (now - last_touch) < timedelta(hours=20):
            stats["skipped"] += 1
            continue

        target = _step_for(days_left)
        if target == 0 or target <= step:
            stats["skipped"] += 1
            continue
        days_before = T.REMINDER_DAYS[target - 1]
        if days_before == 0:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=T.BTN_WILL_PAY,
                                      callback_data="club:willpay")],
                [InlineKeyboardButton(text=T.BTN_LEAVING,
                                      callback_data="club:leaving")],
            ])
            if await _touch(bot, telegram_id, target, T.ASK_DAY0, kb):
                stats["asked"] += 1
        else:
            text = {7: T.REMIND_7, 3: T.REMIND_3, 1: T.REMIND_1}[days_before]
            text = text.format(date=_human_date(paid_until))
            if await _touch(bot, telegram_id, target, text, _renew_kb(currency)):
                stats["reminded"] += 1
                if days_before == 7 and _expected(telegram_id) is None:
                    # Ответ на «что было полезным» ждём после первого письма:
                    # там задан вопрос. Но только если бот не ждёт от человека
                    # чего-то другого — иначе e-mail, который он сейчас пишет
                    # для счёта, уйдёт Николь как «отзыв о клубе».
                    _expect(telegram_id, "feedback")

    if stats["removed"] or stats["reminded"] or stats["asked"]:
        log.info("club retention: %s", stats)
    return stats


async def _removals_today() -> int:
    since = datetime.utcnow() - timedelta(days=1)
    with SessionLocal() as s:
        return (s.query(ClubMember)
                .filter(ClubMember.removed_at.isnot(None))
                .filter(ClubMember.removed_at >= since).count())


async def _remove_member(bot: Bot, telegram_id: int,
                         items: list[dict] | None) -> bool:
    """Убрать из канала: ban + сразу unban, чтобы человек мог вернуться.

    Предохранители, каждый из которых уже был нужен хотя бы раз в похожих
    системах:
    1. До дня, с которого клуб платный, не удаляем вообще.
    2. Лимит удалений в сутки — столько людей разом почти всегда значит сбой
       сверки, а не отток. Тревога Николь при этом уходит раз в сутки, а не на
       каждого кандидата каждый час.
    3. Последняя сверка с кассой прямо перед удалением: между проходом цикла и
       этой минутой человек мог оплатить.
    4. Молчание кассы или нечитаемый формат подписок = не удаляем.
    """
    cid = channel_id()
    if not cid:
        return False

    if datetime.utcnow() < T.PAID_FROM:
        return False

    if await _removals_today() >= settings.CLUB_MAX_REMOVALS_PER_DAY:
        log.warning("club: лимит удалений в сутки исчерпан")
        if _once_a_day(LIMIT_ALERT_KEY):
            await _notify_admin(bot, T.ADMIN_REMOVAL_LIMIT.format(
                count=settings.CLUB_MAX_REMOVALS_PER_DAY))
        return False

    with SessionLocal() as s:
        m = s.query(ClubMember).filter_by(telegram_id=telegram_id).first()
        if m is None or m.status == "removed":
            return False
        email, until, who = m.email, m.paid_until, _who(m)
        feedback, periodicity = m.feedback, m.lava_periodicity

    # Последняя проверка: вдруг оплатил только что. Без e-mail сверить нечем —
    # тогда не удаляем и зовём Николь: это может быть доступ, выданный руками.
    if items is None:
        log.info("club: касса молчит — удаление id%s отложено", telegram_id)
        return False
    if items and not _emails_visible(items):
        log.error("club: в подписках Lava не видно e-mail — удаления остановлены")
        if _once_a_day("club_subs_format_alert"):
            await _notify_admin(bot, T.ADMIN_SUBS_FORMAT)
        return False
    if not email:
        if _once_a_day(f"club_no_email_{telegram_id}"):
            await _notify_admin(bot, f"ℹ️ У {html.escape(who)} закончился доступ "
                                     f"в клуб, но e-mail не известен — сверить с "
                                     f"кассой не могу, из канала не убираю.")
        return False
    if _subscription_active(email, items):
        _mark(telegram_id,
              paid_until=datetime.utcnow() + timedelta(days=_period_days(periodicity)),
              status="active", reminder_step=0, grace_given_at=None,
              warned_at=None, unsubscribed=False)
        log.info("club: id%s оплачен, удаление отменено", telegram_id)
        return False

    try:
        await bot.ban_chat_member(chat_id=cid, user_id=telegram_id)
        await bot.unban_chat_member(chat_id=cid, user_id=telegram_id,
                                    only_if_banned=True)
    except Exception as exc:  # noqa: BLE001 — мог выйти сам или бота лишили прав
        log.warning("club remove id%s: %s", telegram_id, type(exc).__name__)
        if _once_a_day(f"club_remove_fail_{telegram_id}"):
            await _notify_admin(bot, f"⚠️ Не смог убрать {html.escape(who)} из "
                                     f"клуба: {type(exc).__name__}")
        return False

    _mark(telegram_id, status="removed", removed_at=datetime.utcnow())
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=T.BTN_RETURN, callback_data="club:join")]])
    try:
        await bot.send_message(telegram_id, T.GOODBYE, reply_markup=kb)
    except Exception as exc:  # noqa: BLE001 — заблокировал бота
        log.info("club goodbye id%s: %s", telegram_id, type(exc).__name__)
    await _notify_admin(bot, T.ADMIN_REMOVED.format(
        who=html.escape(who), until=_human_date(until),
        feedback=(f"Ответ про пользу: {html.escape(feedback)}" if feedback
                  else "Отзыв не оставил.")))
    log.info("club: id%s убран из канала", telegram_id)
    return True


# ─── фоновый цикл ────────────────────────────────────────────────────────────

async def loop(bot: Bot) -> None:
    """Раз в час: сверка с кассой, напоминания, удаления.

    Час, а не минута: цепочка живёт в днях, а частый опрос кассы ничего не
    ускоряет. Оплаты при этом проверяются раз в минуту — в цикле бота оплат.
    """
    silent_since: datetime | None = None
    # Первый проход — через две минуты после старта, а не через час: Railway
    # перезапускает процесс на каждом деплое, и в активный день правок цепочка
    # иначе не отрабатывала бы ни разу.
    delay = 120
    while True:
        try:
            await asyncio.sleep(delay)
            delay = 3600
            # Снимок подписок берём ОДИН раз за проход и передаём дальше: так
            # решения тика согласованы между собой, а касса не опрашивается по
            # разу на каждого кандидата.
            items = await asyncio.to_thread(lava.subscriptions)
            if items is None:
                # Касса молчит: напоминания идут (им касса не нужна), удаления
                # внутри не выполняются. Николь узнаёт, если это тянется сутки.
                silent_since = silent_since or datetime.utcnow()
                if datetime.utcnow() - silent_since > timedelta(days=1) \
                        and _once_a_day("club_lava_silent_alert"):
                    await _notify_admin(bot, T.ADMIN_LAVA_SILENT)
            else:
                silent_since = None
            await retention_tick(bot, items)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — цикл не имеет права умирать
            log.warning("club loop: %s", type(exc).__name__)
