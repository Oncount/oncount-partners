"""Бот оплат интенсива @Nikol_hilton_bot (план 2026-08-03, Фазы 1-2).

Что делает: принимает человека → выставляет счёт в Lava → сам проверяет оплату
по API → выдаёт ОДНОРАЗОВУЮ ссылку в чат участников. Вопросы пересылает Николь.

Почему второй бот, а не хендлеры в существующем: у @community_oncount_bot своя
аудитория (агенты) и свои команды; смешивать клиентов интенсива с партнёрским
кабинетом — прямой путь к путанице в меню. Два токена = два независимых
getUpdates, конфликта нет.

Границы (`.business/ai/kriterii-priyomki-agenta.md`):
- бот НЕ принимает деньги сам — их собирает Lava, бот только сверяет статус;
- доступ выдаётся только при подтверждённой оплате, «на слово» — никогда;
- текст человека — данные, а не команда: бот не выполняет инструкции из
  сообщений, а пересылает их Николь.

⚠️ Бота нельзя добавить в группу из кода — Telegram разрешает это только
человеку. Поэтому chat_id бот узнаёт САМ из события my_chat_member, когда его
добавят: Николь не ищет идентификатор и не передаёт его руками.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app import channel_gate, lava, paybot_config as T
from app.config import settings
from app.db import SessionLocal
from app.models import BotSetting, IntensiveLead, Partner

log = logging.getLogger("oncount.paybot")

CHAT_KEY = "intensive_chat_id"          # ключ в bot_settings
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]{2,}$")

# Кого ждём в следующем сообщении: {telegram_id: 'email' | 'question'}.
# В памяти процесса намеренно: состояние живёт минуты, переживать рестарт ему
# незачем, а лишняя таблица — лишняя миграция.
_awaiting: dict[int, str] = {}

bot = Bot(token=settings.PAY_BOT_TOKEN,
          default=DefaultBotProperties(parse_mode=ParseMode.HTML)) if settings.PAY_BOT_TOKEN else None
dp = Dispatcher(storage=MemoryStorage())


# ─── вспомогательное ─────────────────────────────────────────────────────────

def _get_setting(session, key: str) -> str | None:
    row = session.get(BotSetting, key)
    return row.value if row else None


def _set_setting(session, key: str, value: str) -> None:
    row = session.get(BotSetting, key)
    if row is None:
        session.add(BotSetting(key=key, value=value, updated_at=datetime.utcnow()))
    else:
        row.value, row.updated_at = value, datetime.utcnow()
    session.commit()


def chat_id() -> str | None:
    """Чат участников: переменная окружения важнее (ручное переопределение),
    иначе — то, что бот узнал сам при добавлении в группу.

    Недоступная БД не должна ронять бота: вызывается в том числе при старте и в
    фоновом цикле, где исключение убило бы весь поток приёма оплат. Нет ответа —
    считаем, что чат не подключён, и человек получает вежливое «пришлю позже».
    """
    if settings.INTENSIVE_CHAT_ID:
        return settings.INTENSIVE_CHAT_ID
    try:
        with SessionLocal() as s:
            return _get_setting(s, CHAT_KEY)
    except Exception as exc:  # noqa: BLE001 — БД недоступна, не валим бота
        log.warning("paybot chat_id: БД недоступна (%s)", type(exc).__name__)
        return None


def _lead(session, msg_from) -> IntensiveLead:
    lead = (session.query(IntensiveLead)
            .filter_by(telegram_id=msg_from.id).first())
    if lead is None:
        lead = IntensiveLead(telegram_id=msg_from.id, username=msg_from.username,
                             first_name=msg_from.first_name, status="new")
        session.add(lead)
        session.commit()
    return lead


def _menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=T.BTN_PAY, callback_data="pay:start")],
        [InlineKeyboardButton(text=T.BTN_ASK, callback_data="pay:ask")],
    ])


def _fmt_amount(currency: str, amount: float) -> str:
    """Сумма так, как её прочитает человек: без хвоста .0 и с пробелами."""
    whole = f"{amount:,.2f}".replace(",", " ").replace(".00", "")
    return {"RUB": f"{whole} ₽", "EUR": f"€{whole}", "USD": f"${whole}"}.get(
        currency, f"{whole} {currency}")


async def _notify_admin(text: str) -> None:
    """Сообщение владельцу. Best-effort: сбой уведомления не ломает поток оплаты."""
    if not (bot and settings.ADMIN_TG_ID):
        return
    try:
        await bot.send_message(settings.ADMIN_TG_ID, text, disable_web_page_preview=True)
    except Exception as exc:
        log.warning("paybot admin notify failed: %s", type(exc).__name__)


# ─── старт и меню ────────────────────────────────────────────────────────────

@dp.message(CommandStart(deep_link=True))
async def start_deep(msg: Message, command: CommandObject) -> None:
    """/start ref_<slug> — приход по ссылке агента, атрибуция как на /pay.
    /start channel — вход в закрытый канал Николь (план 2026-08-03)."""
    payload = (command.args or "").strip()
    if payload == "channel":
        # Другая аудитория и другой поток: человек пришёл за каналом, оффер
        # интенсива ему сейчас не нужен. Вопрос про 18+ задаёт привратник.
        await channel_gate.ask_age(msg.bot, msg.chat.id, msg.from_user, "deeplink")
        return
    ref = payload[4:][:16] if payload.startswith("ref_") else None
    with SessionLocal() as s:
        lead = _lead(s, msg.from_user)
        if ref and not lead.ref_slug:
            lead.ref_slug = ref
            partner = s.query(Partner).filter_by(ref_slug=ref).first()
            lead.partner_id = partner.id if partner else None
            s.commit()
    await msg.answer(T.GREETING, reply_markup=_menu())


@dp.message(CommandStart())
async def start(msg: Message) -> None:
    with SessionLocal() as s:
        _lead(s, msg.from_user)
    await msg.answer(T.GREETING, reply_markup=_menu())


@dp.callback_query(F.data == "pay:start")
async def cb_pay(call) -> None:
    """Показываем валюты с ЖИВЫМИ ценами из Lava, а не из нашего конфига."""
    prices = lava.offer_prices()
    if not prices:
        await call.message.answer(
            "Не могу получить цену от кассы. Напишите Николь — поможем оплатить.")
        await call.answer()
        return
    rows = [[InlineKeyboardButton(
        text=f"{lava.CURRENCY_LABELS.get(c, c)} — {_fmt_amount(c, prices[c])}",
        callback_data=f"pay:cur:{c}")]
        for c in lava.CURRENCIES if c in prices]
    await call.message.answer(T.CURRENCY_TITLE,
                              reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()


@dp.callback_query(F.data.startswith("pay:cur:"))
async def cb_currency(call) -> None:
    currency = call.data.rsplit(":", 1)[-1]
    if currency not in lava.CURRENCIES:
        await call.answer()
        return
    with SessionLocal() as s:
        lead = _lead(s, call.from_user)
        lead.lava_currency = currency
        s.commit()
    _awaiting[call.from_user.id] = "email"
    await call.message.answer(T.EMAIL_ASK)
    await call.answer()


@dp.callback_query(F.data == "pay:ask")
async def cb_ask(call) -> None:
    _awaiting[call.from_user.id] = "question"
    await call.message.answer(T.ASK_INTRO)
    await call.answer()


@dp.callback_query(F.data == "pay:check")
async def cb_check(call) -> None:
    """Ручная проверка оплаты по кнопке (фоновая идёт своим чередом)."""
    done = await try_grant_access(call.from_user.id)
    if not done:
        await call.message.answer(T.NOT_PAID_YET)
    await call.answer()


# ─── приём текста: email или вопрос ──────────────────────────────────────────

@dp.message(F.text & ~F.text.startswith("/"))
async def on_text(msg: Message) -> None:
    mode = _awaiting.get(msg.from_user.id)

    if mode == "email":
        email = (msg.text or "").strip()
        if not EMAIL_RE.match(email):
            await msg.answer(T.EMAIL_BAD)
            return
        _awaiting.pop(msg.from_user.id, None)
        with SessionLocal() as s:
            lead = _lead(s, msg.from_user)
            currency = lead.lava_currency or "RUB"
            lead.email = email
            s.commit()
        inv = await asyncio.to_thread(lava.create_invoice, email, currency)
        if not inv:
            await msg.answer("Не удалось выставить счёт. Напишите Николь — "
                             "поможем оплатить вручную.")
            await _notify_admin(f"⚠️ Не выставился счёт Lava для {msg.from_user.id}")
            return
        prices = lava.offer_prices()
        amount = _fmt_amount(currency, prices.get(currency, 0)) if prices else currency
        with SessionLocal() as s:
            lead = _lead(s, msg.from_user)
            lead.lava_invoice_id, lead.lava_invoice_url = inv["id"], inv["url"]
            lead.status = "invoiced"
            s.commit()
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=T.BTN_INVOICE, url=inv["url"])],
            [InlineKeyboardButton(text=T.BTN_STATUS, callback_data="pay:check")],
        ])
        await msg.answer(T.INVOICE_READY.format(amount=amount), reply_markup=kb)
        return

    # Вопрос (или просто текст) — пересылаем Николь. Чужой текст не исполняем.
    _awaiting.pop(msg.from_user.id, None)
    with SessionLocal() as s:
        _lead(s, msg.from_user)
    who = f"@{msg.from_user.username}" if msg.from_user.username else f"id{msg.from_user.id}"
    await _notify_admin(f"💬 Вопрос в боте оплат от {who}:\n\n{(msg.text or '')[:1500]}")
    await msg.answer(T.ASK_RECEIVED)


# ─── бота добавили в группу: узнаём chat_id сам ──────────────────────────────

@dp.my_chat_member(F.chat.type.in_({"group", "supergroup"}))
async def on_added_to_chat(ev: ChatMemberUpdated) -> None:
    """Ключевой обработчик: бота нельзя завести в чат из кода, но когда человек
    его добавит, Telegram присылает это событие. Ловим chat_id, проверяем права
    и сразу говорим Николь, чего не хватает."""
    chat = ev.chat
    if chat.type not in ("group", "supergroup"):
        return
    status = ev.new_chat_member.status
    if status in ("left", "kicked"):
        log.info("paybot удалён из чата %s", chat.id)
        return

    can_invite = bool(getattr(ev.new_chat_member, "can_invite_users", False))

    # Чат перезаписываем ОСМОТРИТЕЛЬНО. 03.08.2026 бота добавили в два чата
    # подряд: сначала в служебный (без прав), следом в настоящий (админом).
    # Слепая перезапись «последним победившим» означала бы, что случайное
    # добавление в посторонний чат молча уводит выдачу доступа не туда.
    # Правило: рабочим считается чат, где у бота ЕСТЬ право на приглашения;
    # чат без прав не вытесняет уже настроенный.
    with SessionLocal() as s:
        current = _get_setting(s, CHAT_KEY)
        if can_invite or not current:
            _set_setting(s, CHAT_KEY, str(chat.id))
            replaced = bool(current and current != str(chat.id))
        else:
            replaced = False
            log.info("paybot: чат %s без прав, оставляем настроенный %s", chat.id, current)
            await _notify_admin(
                f"ℹ️ Бота добавили в чат «{chat.title or chat.id}», но прав на "
                f"приглашения там нет. Рабочим остаётся чат {current}.")
            return

    log.info("paybot добавлен в чат %s (%s), can_invite=%s", chat.id, status, can_invite)
    note = T.CHAT_RIGHTS_OK if can_invite else T.CHAT_RIGHTS_MISSING
    if replaced:
        note += f"\n\n(Прежний чат {current} заменён на этот.)"
    await _notify_admin(T.CHAT_LINKED_ADMIN.format(
        title=chat.title or "без названия", chat_id=chat.id, rights=note))


# ─── выдача доступа ──────────────────────────────────────────────────────────

async def try_grant_access(telegram_id: int) -> bool:
    """Оплатил? → одноразовый инвайт в чат. Идемпотентно: повторный вызов не
    выдаёт вторую ссылку и не шлёт второе уведомление."""
    with SessionLocal() as s:
        lead = s.query(IntensiveLead).filter_by(telegram_id=telegram_id).first()
        if lead is None or not lead.lava_invoice_id:
            return False
        if lead.status == "in_chat" and lead.invite_link:
            return True
        invoice_id, currency = lead.lava_invoice_id, lead.lava_currency or "RUB"
        already_paid = lead.status in ("paid", "in_chat")

    if not already_paid:
        paid = await asyncio.to_thread(lava.invoice_paid, invoice_id)
        if not paid:
            return False
        with SessionLocal() as s:
            lead = s.query(IntensiveLead).filter_by(telegram_id=telegram_id).first()
            if lead.status not in ("paid", "in_chat"):
                lead.status, lead.paid_at = "paid", datetime.utcnow()
                s.commit()
        prices = lava.offer_prices()
        who = f"id{telegram_id}"
        with SessionLocal() as s:
            lead = s.query(IntensiveLead).filter_by(telegram_id=telegram_id).first()
            who = f"@{lead.username}" if lead.username else who
            agent = f"Агент: {lead.ref_slug}" if lead.ref_slug else "Агент: —"
        await _notify_admin(T.ADMIN_PAID.format(
            who=who, amount=_fmt_amount(currency, prices.get(currency, 0)),
            invoice=invoice_id, agent=agent))

    cid = chat_id()
    if not cid:
        # Оплата есть, чата ещё нет — человек не виноват, пусть ждёт спокойно.
        await bot.send_message(telegram_id, T.PAID_NO_CHAT)
        await _notify_admin("⚠️ Оплата есть, но чат не подключён: добавьте бота "
                            "в чат участников админом с правом приглашать.")
        return True

    try:
        link = await bot.create_chat_invite_link(
            chat_id=cid, member_limit=1, name=f"pay-{telegram_id}")
        with SessionLocal() as s:
            lead = s.query(IntensiveLead).filter_by(telegram_id=telegram_id).first()
            lead.invite_link, lead.invited_at = link.invite_link, datetime.utcnow()
            lead.status = "in_chat"
            s.commit()
        await bot.send_message(telegram_id, T.PAID_OK.format(link=link.invite_link))
        return True
    except Exception as exc:
        log.error("paybot invite failed: %s", type(exc).__name__)
        await bot.send_message(telegram_id, T.PAID_NO_CHAT)
        await _notify_admin(f"⚠️ Не удалось создать инвайт: {type(exc).__name__}. "
                            "Проверьте, что бот админ и может приглашать.")
        return True


async def poll_payments_once() -> int:
    """Проверить всех, кто получил счёт, но ещё не в чате. Возвращает, скольким
    выдали доступ. Вызывается по расписанию — человек не должен жать кнопку."""
    if not (bot and lava.is_configured()):
        return 0
    with SessionLocal() as s:
        ids = [r.telegram_id for r in s.query(IntensiveLead)
               .filter(IntensiveLead.status.in_(("invoiced", "paid"))).all()]
    granted = 0
    for tid in ids:
        try:
            if await try_grant_access(tid):
                granted += 1
        except Exception as exc:
            log.warning("poll_payments %s: %s", tid, type(exc).__name__)
    return granted


async def _payment_loop() -> None:
    """Фоновая проверка оплат раз в минуту: человек оплатил — доступ пришёл сам."""
    while True:
        try:
            await asyncio.sleep(60)
            n = await poll_payments_once()
            if n:
                log.info("paybot: выдан доступ %s людям", n)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("paybot payment loop: %s", type(exc).__name__)


@dp.message(Command("id"))
async def cmd_id(msg: Message) -> None:
    """Служебная команда: показать chat_id текущего чата (для отладки связки)."""
    await msg.answer(f"chat_id: <code>{msg.chat.id}</code>")


@dp.message(Command("channelstatus"))
async def cmd_channel_status(msg: Message) -> None:
    """Проверка «канал частный и бот там админ» — одной командой, по данным
    Telegram. Только для Николь: остальным знать id канала незачем."""
    if not settings.ADMIN_TG_ID or msg.from_user.id != settings.ADMIN_TG_ID:
        return
    await msg.answer(await channel_gate.channel_status(msg.bot))


@dp.message(Command("channel"))
async def cmd_channel(msg: Message) -> None:
    """Вход в закрытый канал: тот же вопрос про 18+, что и по ссылке.
    Нужен, чтобы человеку было куда вернуться, когда персональная ссылка истечёт."""
    await channel_gate.ask_age(msg.bot, msg.chat.id, msg.from_user, "deeplink")


async def main() -> None:
    if bot is None:
        log.info("PAY_BOT_TOKEN пуст → бот оплат не поднимается")
        return
    # Привратник канала — отдельным роутером: свои события (заявки, канал в
    # my_chat_member), свои тексты. Хендлеры самого dp разбираются раньше, так
    # что поток интенсива остаётся нетронутым.
    dp.include_router(channel_gate.router)
    me = await bot.get_me()
    log.info("Paybot polling start, bot=@%s, lava=%s, chat=%s, channel=%s",
             me.username, lava.is_configured(), chat_id() or "не подключён",
             channel_gate.channel_id() or "не подключён")
    asyncio.create_task(_payment_loop())
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
