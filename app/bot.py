"""Telegram-бот OnCount Partners + Community.

Один токен @community_oncount_bot обслуживает:
1. Регистрацию на мастер-класс «AI 2-й мозг» 21.05.2026.
2. 3 cron-напоминания зарегистрированным.
3. Партнёрскую программу (онбординг, реф-ссылки, передача клиента, статистика, продукты, FAQ).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, engine
from app.messages_text import (
    EVENT_REGISTERED,
    EVENT_REMINDER_1H,
    EVENT_REMINDER_24H,
    EVENT_REMINDER_ZOOM,
    PARTNER_LINKS,
    PARTNER_ONBOARDING_INTRO,
    TRANSFER_DONE,
    TRANSFER_INTRO,
    WELCOME_NEW,
    WELCOME_PARTNER,
    WELCOME_REGISTERED_FOR_EVENT,
)
from app.models import Base, EventRegistration, FaqItem, Lead, Partner, ProductBlock
from app.refgen import generate_ref_slug

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
log = logging.getLogger("bot")

EVENT_SLUG = "ai-2brain-2026-05-21"
TZ = "Asia/Dubai"

bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher(storage=MemoryStorage())


# ─────────────── helpers ────────────────────────────────────────────────────


def get_or_create_partner(session: Session, msg: Message) -> Partner:
    partner = session.query(Partner).filter_by(telegram_id=msg.from_user.id).first()
    if partner:
        return partner
    partner = Partner(
        telegram_id=msg.from_user.id,
        username=msg.from_user.username,
        first_name=msg.from_user.first_name,
        last_name=msg.from_user.last_name,
        ref_slug=generate_ref_slug(),
        status="pending",
    )
    session.add(partner)
    session.commit()
    session.refresh(partner)
    return partner


def main_menu_new() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Регистрация на мастер-класс 21.05", callback_data="event:register")],
        [InlineKeyboardButton(text="🤝 Партнёрская программа", callback_data="partner:intro")],
    ])


def menu_partner() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="🔗 Мои ссылки", callback_data="partner:links")],
        [InlineKeyboardButton(text="📨 Тексты рассылок", callback_data="partner:messages")],
        [InlineKeyboardButton(text="📊 Моя статистика", callback_data="partner:stats")],
        [InlineKeyboardButton(text="📦 Тарифы и сервисы", callback_data="partner:products")],
        [InlineKeyboardButton(text="📍 Передать клиента", callback_data="partner:transfer")],
        [InlineKeyboardButton(text="❓ FAQ", callback_data="partner:faq")],
        [InlineKeyboardButton(text="🌐 Открыть ЛК в браузере", url=settings.WEBAPP_URL + "/login")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def menu_event_registered() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤝 Стать партнёром OnCount", callback_data="partner:intro")],
    ])


# ─────────────── /start ─────────────────────────────────────────────────────


@dp.message(CommandStart())
async def cmd_start(msg: Message) -> None:
    with SessionLocal() as session:
        partner = get_or_create_partner(session, msg)
        # уже партнёр (active)?
        if partner.status == "active":
            await msg.answer(
                WELCOME_PARTNER.format(first_name=msg.from_user.first_name or ""),
                reply_markup=menu_partner(),
            )
            return
        # зарегистрирован на мастер-класс?
        evt = (
            session.query(EventRegistration)
            .filter_by(telegram_id=msg.from_user.id, event_slug=EVENT_SLUG)
            .first()
        )
        if evt:
            await msg.answer(
                WELCOME_REGISTERED_FOR_EVENT.format(first_name=msg.from_user.first_name or ""),
                reply_markup=menu_event_registered(),
            )
            return
        # новый
        await msg.answer(
            WELCOME_NEW.format(first_name=msg.from_user.first_name or ""),
            reply_markup=main_menu_new(),
        )


# ─────────────── event: registration ────────────────────────────────────────


@dp.callback_query(F.data == "event:register")
async def cb_event_register(call) -> None:
    with SessionLocal() as session:
        exists = (
            session.query(EventRegistration)
            .filter_by(telegram_id=call.from_user.id, event_slug=EVENT_SLUG)
            .first()
        )
        if not exists:
            session.add(EventRegistration(
                telegram_id=call.from_user.id,
                event_slug=EVENT_SLUG,
                first_name=call.from_user.first_name,
                username=call.from_user.username,
                meta={"reminder_24h_sent": False, "zoom_link_sent": False, "start_1h_sent": False},
            ))
            session.commit()
    await call.message.answer(
        EVENT_REGISTERED.format(first_name=call.from_user.first_name or ""),
        reply_markup=menu_event_registered(),
    )
    await call.answer("Зарегистрирован/-а!")


# ─────────────── partner: onboarding & menu ─────────────────────────────────


@dp.callback_query(F.data == "partner:intro")
async def cb_partner_intro(call) -> None:
    with SessionLocal() as session:
        partner = session.query(Partner).filter_by(telegram_id=call.from_user.id).first()
        if partner and partner.status != "active":
            partner.status = "active"
            session.commit()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Открыть кабинет", url=settings.WEBAPP_URL + "/login")],
        [InlineKeyboardButton(text="🔗 Получить мои ссылки", callback_data="partner:links")],
    ])
    await call.message.answer(PARTNER_ONBOARDING_INTRO, reply_markup=kb)
    await call.answer()


@dp.message(Command("menu"))
async def cmd_menu(msg: Message) -> None:
    await msg.answer("Меню партнёра:", reply_markup=menu_partner())


@dp.message(Command("links"))
@dp.callback_query(F.data == "partner:links")
async def cmd_links(event) -> None:
    user_id = event.from_user.id
    msg = event if isinstance(event, Message) else event.message
    with SessionLocal() as session:
        partner = session.query(Partner).filter_by(telegram_id=user_id).first()
        if not partner:
            partner = get_or_create_partner(session, event)
    bot_link = f"https://t.me/{settings.BOT_USERNAME}?start=ref_{partner.ref_slug}"
    site_link = f"https://oncount.com/?ref={partner.ref_slug}"
    await msg.answer(PARTNER_LINKS.format(bot_link=bot_link, site_link=site_link))
    if not isinstance(event, Message):
        await event.answer()


@dp.message(Command("stats"))
@dp.callback_query(F.data == "partner:stats")
async def cmd_stats(event) -> None:
    user_id = event.from_user.id
    msg = event if isinstance(event, Message) else event.message
    with SessionLocal() as session:
        partner = session.query(Partner).filter_by(telegram_id=user_id).first()
        if not partner:
            await msg.answer("Сначала /start.")
            return
        leads_q = session.query(Lead).filter_by(partner_id=partner.id)
        total = leads_q.count()
        won = leads_q.filter(Lead.status == "won").count()
        in_progress = leads_q.filter(Lead.status.in_(["new", "in_progress"])).count()
    conversion = round(won / total * 100, 1) if total else 0
    await msg.answer(
        f"📊 *Твоя статистика:*\n\n"
        f"• Передано клиентов: *{total}*\n"
        f"• Успешных: *{won}*\n"
        f"• В работе: *{in_progress}*\n"
        f"• Конверсия: *{conversion}%*\n\n"
        f"Полный дашборд: {settings.WEBAPP_URL}/dashboard"
    )
    if not isinstance(event, Message):
        await event.answer()


@dp.message(Command("products"))
@dp.callback_query(F.data == "partner:products")
async def cmd_products(event) -> None:
    msg = event if isinstance(event, Message) else event.message
    with SessionLocal() as session:
        items = (
            session.query(ProductBlock)
            .filter_by(is_active=True)
            .order_by(ProductBlock.order_index)
            .all()
        )
    text = "📦 *Тарифы и сервисы OnCount*\n\n"
    for item in items:
        text += f"*{item.title}* — {item.price_aed or ''}\n{item.summary_md}\n\n"
    text += f"Подробности — в ЛК: {settings.WEBAPP_URL}/products"
    await msg.answer(text)
    if not isinstance(event, Message):
        await event.answer()


@dp.message(Command("faq"))
@dp.callback_query(F.data == "partner:faq")
async def cmd_faq(event) -> None:
    msg = event if isinstance(event, Message) else event.message
    with SessionLocal() as session:
        items = (
            session.query(FaqItem)
            .filter_by(is_active=True)
            .order_by(FaqItem.category, FaqItem.order_index)
            .limit(10)
            .all()
        )
    text = "❓ *Частые вопросы*\n\n"
    last_cat = None
    for item in items:
        if item.category != last_cat:
            text += f"\n_*{item.category}*_\n"
            last_cat = item.category
        text += f"\n*Q:* {item.question}\n*A:* {item.answer_md}\n"
    text += f"\nПолный FAQ: {settings.WEBAPP_URL}/faq"
    await msg.answer(text)
    if not isinstance(event, Message):
        await event.answer()


@dp.callback_query(F.data == "partner:messages")
async def cb_messages(call) -> None:
    await call.message.answer(
        "📨 *Тексты рассылок* — 5 готовых шаблонов под разные сегменты.\n\n"
        f"Полный список с кнопкой «Скопировать» — в ЛК:\n{settings.WEBAPP_URL}/messages"
    )
    await call.answer()


# ─────────────── partner: transfer (FSM) ────────────────────────────────────


class TransferStates(StatesGroup):
    name = State()
    phone = State()
    task = State()


@dp.message(Command("transfer"))
@dp.callback_query(F.data == "partner:transfer")
async def cmd_transfer(event, state: FSMContext) -> None:
    msg = event if isinstance(event, Message) else event.message
    await state.set_state(TransferStates.name)
    await msg.answer(TRANSFER_INTRO)
    if not isinstance(event, Message):
        await event.answer()


@dp.message(TransferStates.name)
async def transfer_name(msg: Message, state: FSMContext) -> None:
    await state.update_data(client_name=msg.text.strip())
    await state.set_state(TransferStates.phone)
    await msg.answer("Телефон или WhatsApp клиента (можно пропустить — отправь «-»):")


@dp.message(TransferStates.phone)
async def transfer_phone(msg: Message, state: FSMContext) -> None:
    phone = msg.text.strip()
    await state.update_data(client_phone=None if phone == "-" else phone)
    await state.set_state(TransferStates.task)
    await msg.answer("Опиши задачу клиента в одном сообщении:")


@dp.message(TransferStates.task)
async def transfer_task(msg: Message, state: FSMContext) -> None:
    data = await state.get_data()
    with SessionLocal() as session:
        partner = session.query(Partner).filter_by(telegram_id=msg.from_user.id).first()
        if not partner:
            await msg.answer("Сначала /start.")
            await state.clear()
            return
        lead = Lead(
            partner_id=partner.id,
            client_name=data["client_name"],
            client_phone=data.get("client_phone"),
            task_description=msg.text.strip(),
            status="new",
        )
        session.add(lead)
        session.commit()
    await msg.answer(TRANSFER_DONE.format(name=data["client_name"]), reply_markup=menu_partner())
    # уведомить админа
    try:
        await bot.send_message(
            settings.ADMIN_TG_ID,
            f"🆕 Партнёр {msg.from_user.full_name} (@{msg.from_user.username or '—'}) "
            f"передал клиента *{data['client_name']}*\n"
            f"Телефон: {data.get('client_phone') or '—'}\n"
            f"Задача: {msg.text.strip()}",
        )
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        log.warning("admin notify failed: %s", e)
    await state.clear()


# ─────────────── event reminders (APScheduler) ──────────────────────────────


async def send_reminder(field: str, text: str) -> None:
    """Шлёт `text` всем регистрациям мастер-класса, у которых meta[field] != True."""
    sent = 0
    with SessionLocal() as session:
        regs = (
            session.query(EventRegistration)
            .filter_by(event_slug=EVENT_SLUG)
            .all()
        )
        for reg in regs:
            meta = reg.meta or {}
            if meta.get(field):
                continue
            try:
                await bot.send_message(reg.telegram_id, text)
                meta[field] = True
                reg.meta = meta
                sent += 1
            except (TelegramBadRequest, TelegramForbiddenError) as e:
                log.warning("reminder send fail for %s: %s", reg.telegram_id, e)
        session.commit()
    log.info("Reminder %s — sent to %s recipients", field, sent)


async def reminder_24h() -> None:
    await send_reminder("reminder_24h_sent", EVENT_REMINDER_24H)


async def reminder_zoom() -> None:
    await send_reminder("zoom_link_sent", EVENT_REMINDER_ZOOM)


async def reminder_1h() -> None:
    await send_reminder("start_1h_sent", EVENT_REMINDER_1H)


def start_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=TZ)
    # 20.05.2026 18:00 GST → за сутки
    scheduler.add_job(reminder_24h, CronTrigger(month=5, day=20, hour=18, minute=0, timezone=TZ),
                      id="rem_24h", replace_existing=True)
    # 21.05.2026 10:00 GST → утром с ссылкой
    scheduler.add_job(reminder_zoom, CronTrigger(month=5, day=21, hour=10, minute=0, timezone=TZ),
                      id="rem_zoom", replace_existing=True)
    # 21.05.2026 17:00 GST → за час до старта
    scheduler.add_job(reminder_1h, CronTrigger(month=5, day=21, hour=17, minute=0, timezone=TZ),
                      id="rem_1h", replace_existing=True)
    scheduler.start()
    log.info("Scheduler started, jobs: %s", [j.id for j in scheduler.get_jobs()])
    return scheduler


# ─────────────── entry point ────────────────────────────────────────────────


async def main() -> None:
    Base.metadata.create_all(engine)
    scheduler = start_scheduler()
    log.info("Bot polling start, bot=@%s, time=%s", settings.BOT_USERNAME, datetime.utcnow())
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
