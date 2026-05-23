"""Telegram-бот ONCOUNT Partners + Community.

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
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, engine
from app.messages_text import t
from app.models import Base, EventRegistration, FaqItem, Lead, LoginSession, Partner, ProductBlock
from app.refgen import generate_ref_slug

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
log = logging.getLogger("bot")

EVENT_SLUG = "ai-2brain-2026-05-21"
TZ = "Asia/Dubai"

bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())


# ─────────────── helpers ────────────────────────────────────────────────────


def issue_login_url(session: Session, telegram_id: int) -> str:
    """Create LoginSession pre-bound to telegram_id; return one-click URL to /auth/bot-callback."""
    import secrets as _secrets
    state = _secrets.token_urlsafe(24)
    session.add(LoginSession(state=state, telegram_id=telegram_id))
    session.commit()
    return f"{settings.WEBAPP_URL}/auth/bot-callback?state={state}"


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


# ─────────────── i18n: язык + подписи кнопок ────────────────────────────────
#
# Язык бота определяется ТОЛЬКО явным выбором (partner.lang). При первом входе
# показываем экран выбора (lang_picker_kb); пока выбор не сделан, partner.lang =
# None. resolve_lang даёт безопасный fallback "ru" для мест, где язык всё равно
# нужен (deep-link сразу с действием, рассылки).

DEFAULT_LANG = "ru"
SUPPORTED_LANGS = ("ru", "en")

# Подписи кнопок: BTN[key][lang]. Доступ — через b(key, lang) с ru-fallback.
BTN: dict[str, dict[str, str]] = {
    "event_register": {
        "ru": "📅 Регистрация на мастер-класс 21.05",
        "en": "📅 Register for the masterclass May 21",
    },
    "event_show": {
        "ru": "✅ Ты на мастер-классе 21.05",
        "en": "✅ You're registered for May 21",
    },
    "partner_intro": {
        "ru": "🤝 Партнёрская программа",
        "en": "🤝 Partner program",
    },
    "partner_intro_oncount": {
        "ru": "🤝 Партнёрство с ONCOUNT",
        "en": "🤝 Partner with ONCOUNT",
    },
    "partner_become": {
        "ru": "🤝 Стать партнёром ONCOUNT",
        "en": "🤝 Become an ONCOUNT partner",
    },
    "transfer": {
        "ru": "💰 Передать клиента",
        "en": "💰 Refer a client",
    },
    "open_lk": {
        "ru": "🌐 Открыть кабинет",
        "en": "🌐 Open cabinet",
    },
    "open_my_cabinet": {
        "ru": "🌐 Открыть мой кабинет",
        "en": "🌐 Open my cabinet",
    },
    "login_cabinet": {
        "ru": "🌐 Войти в личный кабинет",
        "en": "🌐 Log in to my cabinet",
    },
    "enter_cabinet": {
        "ru": "🌐 Войти в кабинет",
        "en": "🌐 Enter cabinet",
    },
    "lang_change": {
        "ru": "🌐 Сменить язык / Language",
        "en": "🌐 Change language / Язык",
    },
}


def b(key: str, lang: str = DEFAULT_LANG) -> str:
    """Подпись кнопки по ключу и языку, ru-fallback."""
    variants = BTN.get(key, {})
    return variants.get(lang) or variants.get(DEFAULT_LANG, key)


def resolve_lang(partner: Partner | None) -> str:
    """Язык партнёра с безопасным fallback. None/неизвестный → ru."""
    lang = getattr(partner, "lang", None)
    return lang if lang in SUPPORTED_LANGS else DEFAULT_LANG


def get_lang(session: Session, telegram_id: int) -> str:
    """Язык партнёра по telegram_id (ru-fallback)."""
    partner = session.query(Partner).filter_by(telegram_id=telegram_id).first()
    return resolve_lang(partner)


def _loc(obj, attr: str, lang: str) -> str:
    """Локализованное поле контента из БД: при lang=='en' берёт `{attr}_en`,
    если оно непустое; иначе откатывается на русское поле `{attr}`."""
    if lang == "en":
        en = getattr(obj, f"{attr}_en", None)
        if en:
            return en
    return getattr(obj, attr) or ""


def lang_picker_kb() -> InlineKeyboardMarkup:
    """Экран первого выбора языка (и смены языка из меню)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:set:ru")],
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:set:en")],
    ])


def main_menu_new(lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=b("event_register", lang), callback_data="event:register")],
        [InlineKeyboardButton(text=b("partner_intro", lang), callback_data="partner:intro")],
        [InlineKeyboardButton(text=b("lang_change", lang), callback_data="lang:pick")],
    ])


def menu_partner(lang: str = DEFAULT_LANG, registered_for_event: bool = False) -> InlineKeyboardMarkup:
    """Меню партнёра. Остальные функции — через команды и через ЛК."""
    kb = []
    if registered_for_event:
        kb.append([InlineKeyboardButton(text=b("event_show", lang), callback_data="event:show")])
    else:
        kb.append([InlineKeyboardButton(text=b("event_register", lang), callback_data="event:register")])
    kb.extend([
        [InlineKeyboardButton(text=b("partner_intro_oncount", lang), callback_data="partner:intro")],
        [InlineKeyboardButton(text=b("transfer", lang), callback_data="partner:transfer")],
        [InlineKeyboardButton(text=b("open_lk", lang), callback_data="partner:open-lk")],
        [InlineKeyboardButton(text=b("lang_change", lang), callback_data="lang:pick")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def _is_registered_for_event(session, telegram_id: int) -> bool:
    return session.query(EventRegistration).filter_by(
        telegram_id=telegram_id, event_slug=EVENT_SLUG
    ).first() is not None


def menu_event_registered(lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=b("partner_become", lang), callback_data="partner:intro")],
    ])


# ─────────────── /start ─────────────────────────────────────────────────────


@dp.message(CommandStart(deep_link=True))
async def cmd_start_with_payload(msg: Message, command: CommandObject) -> None:
    """Handle /start with deep-link payload (login_<state> or ref_<slug>)."""
    payload = (command.args or "").strip()
    with SessionLocal() as session:
        partner = get_or_create_partner(session, msg)
        # deep-link сразу делает действие → язык не спрашиваем, берём явный выбор
        # (если уже был) или ru-fallback; сменить можно кнопкой в меню.
        lang = resolve_lang(partner)

        if payload == "partner":
            # прямая регистрационная ссылка — сразу активируем и даём вход в ЛК
            partner.status = "active"
            session.commit()
            login_url = issue_login_url(session, msg.from_user.id)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=b("open_my_cabinet", lang), url=login_url)],
            ])
            await msg.answer(
                t("PARTNER_ONBOARDING_INTRO", lang) + t("ONBOARDING_PARTNER_OK", lang),
                reply_markup=kb,
            )
            return

        if payload == "lending":
            # пришёл с лендинга мастер-класса — мгновенная регистрация на ивент
            existing = (
                session.query(EventRegistration)
                .filter_by(telegram_id=msg.from_user.id, event_slug=EVENT_SLUG)
                .first()
            )
            if existing is None:
                session.add(EventRegistration(
                    telegram_id=msg.from_user.id,
                    event_slug=EVENT_SLUG,
                    first_name=msg.from_user.first_name,
                    username=msg.from_user.username,
                    meta={
                        "source": "lending",
                        "reminder_24h_sent": False,
                        "zoom_link_sent": False,
                        "start_1h_sent": False,
                    },
                ))
                session.commit()
            await msg.answer(
                t("EVENT_REGISTERED", lang, first_name=msg.from_user.first_name or ""),
                reply_markup=menu_event_registered(lang),
            )
            return

        if payload.startswith("login_"):
            state = payload[len("login_"):]
            login_session = session.get(LoginSession, state)
            if login_session is not None and login_session.consumed_at is None:
                login_session.telegram_id = msg.from_user.id
                session.commit()
                url = f"{settings.WEBAPP_URL}/auth/bot-callback?state={state}"
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=b("login_cabinet", lang), url=url)],
                ])
                await msg.answer(t("LOGIN_READY", lang), reply_markup=kb)
                return
            else:
                await msg.answer(t("LOGIN_EXPIRED", lang))
                return

        if payload.startswith("ref_"):
            ref_slug = payload[len("ref_"):]
            # запишем приход партнёра по реф-ссылке (если ref_slug валиден)
            from app.models import Referral
            owner = session.query(Partner).filter_by(ref_slug=ref_slug).first()
            if owner and owner.id != partner.id:
                session.add(Referral(
                    partner_id=owner.id,
                    ref_slug=ref_slug,
                    source="tg",
                    visitor_meta={"telegram_id": msg.from_user.id},
                ))
                session.commit()
            # fall through to normal welcome

    # default greeting (no recognised payload or ref handled)
    await cmd_start(msg)


@dp.message(CommandStart())
async def cmd_start(msg: Message) -> None:
    with SessionLocal() as session:
        partner = get_or_create_partner(session, msg)
        # первый вход (язык ещё не выбран) → показываем экран выбора и выходим;
        # приветствие покажет cb_lang_set после выбора.
        if partner.lang not in SUPPORTED_LANGS:
            await msg.answer(t("LANG_PICK"), reply_markup=lang_picker_kb())
            return
    await _send_welcome(msg, partner_telegram_id=msg.from_user.id,
                        first_name=msg.from_user.first_name or "")


async def _send_welcome(msg: Message, partner_telegram_id: int, first_name: str) -> None:
    """Шлёт приветствие на языке партнёра, учитывая статус и регистрацию на ивент."""
    with SessionLocal() as session:
        partner = session.query(Partner).filter_by(telegram_id=partner_telegram_id).first()
        lang = resolve_lang(partner)
        registered = _is_registered_for_event(session, partner_telegram_id)
        # уже партнёр (active)?
        if partner and partner.status == "active":
            await msg.answer(
                t("WELCOME_PARTNER", lang, first_name=first_name),
                reply_markup=menu_partner(lang, registered_for_event=registered),
            )
            return
        # зарегистрирован на мастер-класс, но ещё не партнёр?
        if registered:
            await msg.answer(
                t("WELCOME_REGISTERED_FOR_EVENT", lang, first_name=first_name),
                reply_markup=menu_event_registered(lang),
            )
            return
        # новый
        await msg.answer(
            t("WELCOME_NEW", lang, first_name=first_name),
            reply_markup=main_menu_new(lang),
        )


# ─────────────── язык: выбор и смена ─────────────────────────────────────────


@dp.callback_query(F.data == "lang:pick")
async def cb_lang_pick(call) -> None:
    """Кнопка «Сменить язык» из меню — снова показывает экран выбора."""
    await call.message.answer(t("LANG_PICK"), reply_markup=lang_picker_kb())
    await call.answer()


@dp.callback_query(F.data.startswith("lang:set:"))
async def cb_lang_set(call) -> None:
    lang = call.data.rsplit(":", 1)[-1]
    if lang not in SUPPORTED_LANGS:
        lang = DEFAULT_LANG
    with SessionLocal() as session:
        partner = session.query(Partner).filter_by(telegram_id=call.from_user.id).first()
        if partner is None:
            partner = get_or_create_partner(session, call)
        partner.lang = lang
        session.commit()
    await call.answer(t("LANG_SWITCHED", lang))
    # сразу показываем приветствие/меню на выбранном языке
    await _send_welcome(call.message, partner_telegram_id=call.from_user.id,
                        first_name=call.from_user.first_name or "")


# ─────────────── event: registration ────────────────────────────────────────


@dp.callback_query(F.data == "event:register")
async def cb_event_register(call) -> None:
    with SessionLocal() as session:
        exists = (
            session.query(EventRegistration)
            .filter_by(telegram_id=call.from_user.id, event_slug=EVENT_SLUG)
            .first()
        )
        was_already = exists is not None
        if not exists:
            session.add(EventRegistration(
                telegram_id=call.from_user.id,
                event_slug=EVENT_SLUG,
                first_name=call.from_user.first_name,
                username=call.from_user.username,
                meta={"reminder_24h_sent": False, "zoom_link_sent": False, "start_1h_sent": False},
            ))
            session.commit()
        lang = get_lang(session, call.from_user.id)
    await call.message.answer(
        t("EVENT_REGISTERED", lang, first_name=call.from_user.first_name or ""),
    )
    await call.answer(t("EVENT_TOAST_ALREADY", lang) if was_already else t("EVENT_TOAST_DONE", lang))


@dp.callback_query(F.data == "event:show")
async def cb_event_show(call) -> None:
    with SessionLocal() as session:
        lang = get_lang(session, call.from_user.id)
    await call.message.answer(
        t("EVENT_REGISTERED", lang, first_name=call.from_user.first_name or ""),
    )
    await call.answer()


# ─────────────── partner: onboarding & menu ─────────────────────────────────


@dp.callback_query(F.data == "partner:intro")
async def cb_partner_intro(call) -> None:
    with SessionLocal() as session:
        partner = session.query(Partner).filter_by(telegram_id=call.from_user.id).first()
        if partner and partner.status != "active":
            partner.status = "active"
            session.commit()
        lang = resolve_lang(partner)
        login_url = issue_login_url(session, call.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=b("open_my_cabinet", lang), url=login_url)],
    ])
    await call.message.answer(t("PARTNER_ONBOARDING_INTRO", lang), reply_markup=kb)
    await call.answer()


@dp.message(Command("lk"))
async def cmd_open_lk(msg: Message) -> None:
    with SessionLocal() as session:
        lang = get_lang(session, msg.from_user.id)
        login_url = issue_login_url(session, msg.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=b("enter_cabinet", lang), url=login_url)],
    ])
    await msg.answer(t("OPEN_CABINET_PROMPT", lang), reply_markup=kb)


@dp.callback_query(F.data == "partner:open-lk")
async def cb_partner_open_lk(call) -> None:
    with SessionLocal() as session:
        lang = get_lang(session, call.from_user.id)
        login_url = issue_login_url(session, call.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=b("enter_cabinet", lang), url=login_url)],
    ])
    await call.message.answer(t("OPEN_CABINET_PROMPT", lang), reply_markup=kb)
    await call.answer()


@dp.message(Command("menu"))
async def cmd_menu(msg: Message) -> None:
    with SessionLocal() as session:
        lang = get_lang(session, msg.from_user.id)
    await msg.answer(t("MENU_PARTNER_TITLE", lang), reply_markup=menu_partner(lang))


@dp.message(Command("links"))
@dp.callback_query(F.data == "partner:links")
async def cmd_links(event) -> None:
    user_id = event.from_user.id
    msg = event if isinstance(event, Message) else event.message
    with SessionLocal() as session:
        partner = session.query(Partner).filter_by(telegram_id=user_id).first()
        if not partner:
            partner = get_or_create_partner(session, event)
        ref = partner.ref_slug
        lang = resolve_lang(partner)
    base = settings.WEBAPP_URL.rstrip("/")
    await msg.answer(t("PARTNER_LINKS", lang,
        ref_slug=ref,
        link_consult_tg=f"{base}/ct/{ref}",
        link_consult_wa=f"{base}/cw/{ref}",
        link_mclass_tg=f"{base}/mt/{ref}",
        link_mclass_wa=f"{base}/mw/{ref}",
        link_partner_bot=f"{base}/p/{ref}",
        webapp_url=base,
    ))
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
            await msg.answer(t("NEED_START"))
            return
        lang = resolve_lang(partner)
        leads_q = session.query(Lead).filter_by(partner_id=partner.id)
        total = leads_q.count()
        won = leads_q.filter(Lead.status == "won").count()
        in_progress = leads_q.filter(Lead.status.in_(["new", "in_progress"])).count()
    conversion = round(won / total * 100, 1) if total else 0
    await msg.answer(t("STATS_BODY", lang,
        total=total, won=won, in_progress=in_progress, conversion=conversion,
        dashboard_url=f"{settings.WEBAPP_URL}/dashboard",
    ))
    if not isinstance(event, Message):
        await event.answer()


@dp.message(Command("products"))
@dp.callback_query(F.data == "partner:products")
async def cmd_products(event) -> None:
    msg = event if isinstance(event, Message) else event.message
    with SessionLocal() as session:
        lang = get_lang(session, event.from_user.id)
        items = (
            session.query(ProductBlock)
            .filter_by(is_active=True)
            .order_by(ProductBlock.order_index)
            .all()
        )
        text = t("PRODUCTS_HEADER", lang)
        for item in items:
            title = _loc(item, "title", lang)
            price = _loc(item, "price_aed", lang)
            summary = _loc(item, "summary_md", lang)
            text += f"<b>{title}</b> — {price}\n{summary}\n\n"
    text += t("PRODUCTS_FOOTER", lang, products_url=f"{settings.WEBAPP_URL}/products")
    await msg.answer(text)
    if not isinstance(event, Message):
        await event.answer()


@dp.message(Command("faq"))
@dp.callback_query(F.data == "partner:faq")
async def cmd_faq(event) -> None:
    msg = event if isinstance(event, Message) else event.message
    with SessionLocal() as session:
        lang = get_lang(session, event.from_user.id)
        items = (
            session.query(FaqItem)
            .filter_by(is_active=True)
            .order_by(FaqItem.category, FaqItem.order_index)
            .limit(10)
            .all()
        )
        text = t("FAQ_HEADER", lang)
        last_cat = None
        for item in items:
            cat = _loc(item, "category", lang)
            if cat != last_cat:
                text += f"\n<b><i>{cat}</i></b>\n"
                last_cat = cat
            text += f"\n<b>Q:</b> {_loc(item, 'question', lang)}\n<b>A:</b> {_loc(item, 'answer_md', lang)}\n"
    text += t("FAQ_FOOTER", lang, faq_url=f"{settings.WEBAPP_URL}/faq")
    await msg.answer(text)
    if not isinstance(event, Message):
        await event.answer()


@dp.message(Command("messages"))
@dp.callback_query(F.data == "partner:messages")
async def cmd_messages(event) -> None:
    msg = event if isinstance(event, Message) else event.message
    with SessionLocal() as session:
        lang = get_lang(session, event.from_user.id)
    await msg.answer(t("MESSAGES_BODY", lang, messages_url=f"{settings.WEBAPP_URL}/messages"))
    if not isinstance(event, Message):
        await event.answer()


# ─────────────── partner: transfer (FSM) ────────────────────────────────────


class TransferStates(StatesGroup):
    name = State()
    phone = State()
    task = State()


@dp.message(Command("transfer"))
@dp.callback_query(F.data == "partner:transfer")
async def cmd_transfer(event, state: FSMContext) -> None:
    msg = event if isinstance(event, Message) else event.message
    with SessionLocal() as session:
        lang = get_lang(session, event.from_user.id)
    # язык фиксируем на старте FSM, чтобы все шаги были на одном языке
    await state.update_data(lang=lang)
    await state.set_state(TransferStates.name)
    await msg.answer(t("TRANSFER_INTRO", lang))
    if not isinstance(event, Message):
        await event.answer()


@dp.message(TransferStates.name)
async def transfer_name(msg: Message, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("lang", DEFAULT_LANG)
    await state.update_data(client_name=msg.text.strip())
    await state.set_state(TransferStates.phone)
    await msg.answer(t("TRANSFER_ASK_PHONE", lang))


@dp.message(TransferStates.phone)
async def transfer_phone(msg: Message, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("lang", DEFAULT_LANG)
    phone = msg.text.strip()
    await state.update_data(client_phone=None if phone == "-" else phone)
    await state.set_state(TransferStates.task)
    await msg.answer(t("TRANSFER_ASK_TASK", lang))


@dp.message(TransferStates.task)
async def transfer_task(msg: Message, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("lang", DEFAULT_LANG)
    with SessionLocal() as session:
        partner = session.query(Partner).filter_by(telegram_id=msg.from_user.id).first()
        if not partner:
            await msg.answer(t("NEED_START", lang))
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
    await msg.answer(t("TRANSFER_DONE", lang, name=data["client_name"]), reply_markup=menu_partner(lang))
    # уведомить админа
    try:
        await bot.send_message(
            settings.ADMIN_TG_ID,
            f"🆕 Партнёр {msg.from_user.full_name} (@{msg.from_user.username or '—'}) "
            f"передал клиента <b>{data['client_name']}</b>\n"
            f"Телефон: {data.get('client_phone') or '—'}\n"
            f"Задача: {msg.text.strip()}",
        )
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        log.warning("admin notify failed: %s", e)
    await state.clear()


# ─────────────── event reminders (APScheduler) ──────────────────────────────


async def send_reminder(field: str, text_key: str) -> None:
    """Шлёт текст `text_key` всем регистрациям мастер-класса, у которых meta[field]
    != True. Язык — по выбору партнёра (partners.lang), ru-fallback."""
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
            lang = get_lang(session, reg.telegram_id)
            try:
                await bot.send_message(reg.telegram_id, t(text_key, lang))
                meta[field] = True
                reg.meta = meta
                sent += 1
            except (TelegramBadRequest, TelegramForbiddenError) as e:
                log.warning("reminder send fail for %s: %s", reg.telegram_id, e)
        session.commit()
    log.info("Reminder %s — sent to %s recipients", field, sent)


async def reminder_24h() -> None:
    await send_reminder("reminder_24h_sent", "EVENT_REMINDER_24H")


async def reminder_zoom() -> None:
    await send_reminder("zoom_link_sent", "EVENT_REMINDER_ZOOM")


async def reminder_1h() -> None:
    await send_reminder("start_1h_sent", "EVENT_REMINDER_1H")


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


# Описания команд в меню Telegram. Telegram сам выбирает набор по языку
# приложения пользователя: EN-набор привязан через language_code="en",
# RU — дефолтный (для всех остальных).
PARTNER_COMMANDS = [
    BotCommand(command="menu", description="🏠 Главное меню"),
    BotCommand(command="links", description="🔗 Мои реф-ссылки"),
    BotCommand(command="stats", description="📊 Моя статистика"),
    BotCommand(command="transfer", description="💰 Передать клиента"),
    BotCommand(command="products", description="📦 Тарифы и сервисы"),
    BotCommand(command="messages", description="📨 Тексты рассылок"),
    BotCommand(command="faq", description="❓ Частые вопросы"),
    BotCommand(command="lk", description="🌐 Открыть кабинет в браузере"),
]

PARTNER_COMMANDS_EN = [
    BotCommand(command="menu", description="🏠 Main menu"),
    BotCommand(command="links", description="🔗 My referral links"),
    BotCommand(command="stats", description="📊 My stats"),
    BotCommand(command="transfer", description="💰 Refer a client"),
    BotCommand(command="products", description="📦 Plans and services"),
    BotCommand(command="messages", description="📨 Outreach copy"),
    BotCommand(command="faq", description="❓ FAQ"),
    BotCommand(command="lk", description="🌐 Open cabinet in browser"),
]


async def main() -> None:
    Base.metadata.create_all(engine)
    scheduler = start_scheduler()
    await bot.set_my_commands(PARTNER_COMMANDS)  # дефолт (RU)
    await bot.set_my_commands(PARTNER_COMMANDS_EN, language_code="en")
    log.info("Bot polling start, bot=@%s, time=%s", settings.BOT_USERNAME, datetime.utcnow())
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
