"""Telegram-бот ONCOUNT Partners + Community.

Один токен @community_oncount_bot обслуживает:
1. Курс «Ваш первый AI-сотрудник» (готовый курс в личном кабинете).
2. Партнёрскую программу (онбординг, реф-ссылки, передача клиента, статистика, продукты, FAQ).
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
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, engine
from app.messages_text import t
from app.models import Base, FaqItem, Lead, LoginSession, Partner, ProductBlock
from app.refgen import generate_ref_slug

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
log = logging.getLogger("bot")

# Slug курса-практикума в кабинете (см. seed.py / main.py LESSON_TEMPLATES).
PRACTICUM_SLUG = "ai-employees-setup"
PRACTICUM_PATH = f"/courses/{PRACTICUM_SLUG}"

bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())


# ─────────────── helpers ────────────────────────────────────────────────────


def issue_login_url(session: Session, telegram_id: int, next_path: str | None = None) -> str:
    """Create LoginSession pre-bound to telegram_id; return one-click URL to /auth/bot-callback.

    next_path (если задан) прокидывается в колбэк как ?next= — после входа кабинет
    откроется сразу на этой внутренней странице (валидируется на стороне сервера)."""
    import secrets as _secrets
    from urllib.parse import quote
    state = _secrets.token_urlsafe(24)
    session.add(LoginSession(state=state, telegram_id=telegram_id))
    session.commit()
    url = f"{settings.WEBAPP_URL}/auth/bot-callback?state={state}"
    if next_path:
        url += f"&next={quote(next_path, safe='/')}"
    return url


def cabinet_kb(label: str, url: str) -> InlineKeyboardMarkup:
    """Кнопка входа в ЛК — обычная url-кнопка (кабинет открывается во внешнем
    браузере, где JWT-кука сохраняется надёжно).

    Пробовали web_app=WebAppInfo(...) чтобы убрать системное окно «Open Link»,
    но в Telegram Mini App вход не доходил до /dashboard (кука/домен в webview) —
    логин ломался. Откат на url= (2026-06-01). Окно «Open Link» Telegram задаёт
    сам; убрать его без поломки входа можно только через регистрацию домена
    Mini App в BotFather — отдельной задачей, с проверкой."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, url=url)],
    ])


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
    "course_practicum": {
        "ru": "🎓 Ваш первый AI-сотрудник",
        "en": "🎓 Your first AI employee",
    },
    "open_practicum": {
        "ru": "🎓 Открыть практикум",
        "en": "🎓 Open the practicum",
    },
    "partner_intro": {
        "ru": "🤝 Партнёрская программа",
        "en": "🤝 Partner program",
    },
    "partner_intro_oncount": {
        "ru": "🤝 Партнёрство с ONCOUNT",
        "en": "🤝 Partner with ONCOUNT",
    },
    "transfer": {
        "ru": "💰 Передать клиента",
        "en": "💰 Introduce a client",
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
        "ru": "🔠 En/Ru",
        "en": "🔠 En/Ru",
    },
}


def b(key: str, lang: str = DEFAULT_LANG) -> str:
    """Подпись кнопки по ключу и языку, ru-fallback."""
    variants = BTN.get(key, {})
    return variants.get(lang) or variants.get(DEFAULT_LANG, key)


# Telegram центрирует текст inline-кнопок — отдельной «выровнять влево» опции в API
# нет. Добиваем короткие подписи NBSP (U+00A0, не схлопывается и не обрезается)
# справа до длины самой длинной кнопки: при центрировании одинаковых по длине строк
# их текст начинается на одном уровне у левого края. Шрифт пропорциональный, поэтому
# выравнивание аккуратное, но не пиксель-в-пиксель.
def _left_align(labels: list[str]) -> list[str]:
    width = max(len(s) for s in labels)
    return [s + " " * (width - len(s)) for s in labels]  # NBSP-добивка справа


def _menu(rows: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """rows = [(подпись, callback_data), ...] → клавиатура с выровненными влево подписями."""
    labels = _left_align([text for text, _ in rows])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=cb)]
        for label, (_, cb) in zip(labels, rows)
    ])


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
    return _menu([
        (b("course_practicum", lang), "course:practicum"),
        (b("partner_intro", lang), "partner:intro"),
        (b("lang_change", lang), "lang:pick"),
    ])


def menu_partner(lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    """Меню партнёра. Остальные функции — через команды и через ЛК."""
    return _menu([
        (b("course_practicum", lang), "course:practicum"),
        (b("partner_intro_oncount", lang), "partner:intro"),
        (b("transfer", lang), "partner:transfer"),
        (b("open_lk", lang), "partner:open-lk"),
        (b("lang_change", lang), "lang:pick"),
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
            kb = cabinet_kb(b("open_my_cabinet", lang), login_url)
            await msg.answer(
                t("PARTNER_ONBOARDING_INTRO", lang) + t("ONBOARDING_PARTNER_OK", lang),
                reply_markup=kb,
            )
            return

        if payload.startswith("login_"):
            state = payload[len("login_"):]
            login_session = session.get(LoginSession, state)
            if login_session is not None and login_session.consumed_at is None:
                login_session.telegram_id = msg.from_user.id
                session.commit()
                url = f"{settings.WEBAPP_URL}/auth/bot-callback?state={state}"
                kb = cabinet_kb(b("login_cabinet", lang), url)
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
    """Шлёт приветствие на языке партнёра, учитывая статус."""
    with SessionLocal() as session:
        partner = session.query(Partner).filter_by(telegram_id=partner_telegram_id).first()
        lang = resolve_lang(partner)
        # уже партнёр (active)?
        if partner and partner.status == "active":
            await msg.answer(
                t("WELCOME_PARTNER", lang, first_name=first_name),
                reply_markup=menu_partner(lang),
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


# ─────────────── course: практикум ──────────────────────────────────────────


@dp.callback_query(F.data == "course:practicum")
async def cb_course_practicum(call) -> None:
    """Курс «Ваш первый AI-сотрудник» лежит в кабинете за логином.
    Выдаём одноразовую ссылку входа, ведущую сразу на курс."""
    with SessionLocal() as session:
        lang = get_lang(session, call.from_user.id)
        login_url = issue_login_url(session, call.from_user.id, next_path=PRACTICUM_PATH)
    kb = cabinet_kb(b("open_practicum", lang), login_url)
    await call.message.answer(t("PRACTICUM_INTRO", lang), reply_markup=kb)
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
    kb = cabinet_kb(b("open_my_cabinet", lang), login_url)
    await call.message.answer(t("PARTNER_ONBOARDING_INTRO", lang), reply_markup=kb)
    await call.answer()


@dp.message(Command("lk"))
async def cmd_open_lk(msg: Message) -> None:
    with SessionLocal() as session:
        lang = get_lang(session, msg.from_user.id)
        login_url = issue_login_url(session, msg.from_user.id)
    kb = cabinet_kb(b("enter_cabinet", lang), login_url)
    await msg.answer(t("OPEN_CABINET_PROMPT", lang), reply_markup=kb)


@dp.callback_query(F.data == "partner:open-lk")
async def cb_partner_open_lk(call) -> None:
    with SessionLocal() as session:
        lang = get_lang(session, call.from_user.id)
        login_url = issue_login_url(session, call.from_user.id)
    kb = cabinet_kb(b("enter_cabinet", lang), login_url)
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


# ─────────────── entry point ────────────────────────────────────────────────


# Описания команд в меню Telegram. Telegram сам выбирает набор по языку
# приложения пользователя: EN-набор привязан через language_code="en",
# RU — дефолтный (для всех остальных).
PARTNER_COMMANDS = [
    BotCommand(command="menu", description="🏠 Главное меню"),
    BotCommand(command="links", description="🔗 Мои партнёрские ссылки"),
    BotCommand(command="stats", description="📊 Моя статистика"),
    BotCommand(command="transfer", description="💰 Передать клиента"),
    BotCommand(command="products", description="📦 Тарифы и сервисы"),
    BotCommand(command="messages", description="📨 Тексты рассылок"),
    BotCommand(command="faq", description="❓ Частые вопросы"),
    BotCommand(command="lk", description="🌐 Открыть кабинет в браузере"),
]

PARTNER_COMMANDS_EN = [
    BotCommand(command="menu", description="🏠 Main menu"),
    BotCommand(command="links", description="🔗 My partner links"),
    BotCommand(command="stats", description="📊 My stats"),
    BotCommand(command="transfer", description="💰 Introduce a client"),
    BotCommand(command="products", description="📦 Plans and services"),
    BotCommand(command="messages", description="📨 Outreach copy"),
    BotCommand(command="faq", description="❓ FAQ"),
    BotCommand(command="lk", description="🌐 Open cabinet in browser"),
]


async def main() -> None:
    Base.metadata.create_all(engine)
    await bot.set_my_commands(PARTNER_COMMANDS)  # дефолт (RU)
    await bot.set_my_commands(PARTNER_COMMANDS_EN, language_code="en")
    log.info("Bot polling start, bot=@%s, time=%s", settings.BOT_USERNAME, datetime.utcnow())
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
