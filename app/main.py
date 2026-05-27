import asyncio
import logging
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import (
    COOKIE_NAME,
    current_partner,
    find_partner_by_phone,
    hash_login_code,
    issue_jwt,
    normalize_phone,
    verify_login_code,
)
from app.config import settings
from app.email import send_magic_link
from app.wazzup import send_wa_code
from app.db import SessionLocal, engine, get_session
from app.models import (
    Base,
    Course,
    EmailLoginToken,
    EventRegistration,
    FaqItem,
    Lead,
    LoginSession,
    MessageTemplate,
    Partner,
    PhoneLoginToken,
    ProductBlock,
    Referral,
)
from app.refgen import generate_ref_slug
from app.seed import seed_if_empty

LOGIN_SESSION_TTL = timedelta(minutes=10)
# Магическая ссылка входа по email (план 2026-05-23).
EMAIL_TOKEN_TTL = timedelta(minutes=15)
EMAIL_RATE_LIMIT = 3  # запросов на один email за окно EMAIL_TOKEN_TTL
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Вход по номеру телефона — код в WhatsApp (план 2026-05-27).
PHONE_CODE_TTL = timedelta(minutes=10)
PHONE_CODE_MAX_ATTEMPTS = 5  # неверных вводов кода до блокировки токена
PHONE_RATE_LIMIT = 3         # запросов кода на один номер за окно PHONE_CODE_TTL
PHONE_MIN_DIGITS = 9         # короче — заведомо мусор, код не шлём

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

# Стадии «пути клиента» по лиду — единый источник истины для кабинета.
# Цвет завязан на CSS-класс .status-<status> (static/css/oncount.css);
# здесь — только человекочитаемый ярлык (ru/en) + иконка. Под-статусы НЕ
# заводим (решение Николь): рисуем поверх 4 существующих Lead.status.
LEAD_STAGES: dict[str, dict[str, str]] = {
    "new":         {"icon": "📥", "ru": "Принят",                "en": "Received"},
    "in_progress": {"icon": "🧮", "ru": "В работе у бухгалтера", "en": "With accountant"},
    "won":         {"icon": "🤝", "ru": "Клиент с нами",         "en": "Client onboarded"},
    "lost":        {"icon": "🌙", "ru": "Не сложилось",          "en": "Didn’t work out"},
}


def lead_stage(status: str, lang: str = "ru") -> dict[str, str]:
    """Стадия лида → {label, icon, status} для шаблонов кабинета.
    Неизвестный/пустой статус деградирует мягко: показываем сырое значение
    без иконки, чтобы шаблон никогда не падал."""
    lang = lang if lang in ("ru", "en") else "ru"
    stage = LEAD_STAGES.get(status or "")
    if not stage:
        return {"label": status or "—", "icon": "", "status": status or ""}
    return {"label": stage[lang], "icon": stage["icon"], "status": status}


# Статус партнёрского вознаграждения по ВЫИГРАННОМУ лиду — единый источник
# истины кабинета (Фаза B, план 2026-05-27). Деньги показываем ТОЛЬКО по won;
# под-таблицу выплат НЕ заводим (решение Николь) — значение в Lead.payout_state,
# менеджер ставит вручную (scripts/set_payout_state.py). hint — короткий смысл
# статуса для партнёра (репутация = операционное доверие).
PAYOUT_STATES: dict[str, dict[str, str]] = {
    "in_calc": {"icon": "🧾", "ru": "В расчёте", "en": "Being calculated",
                "hint_ru": "Считаем ваше вознаграждение по этому клиенту.",
                "hint_en": "We’re calculating your reward for this client."},
    "to_pay":  {"icon": "⏳", "ru": "К выплате", "en": "To be paid",
                "hint_ru": "Вознаграждение подтверждено, готовим выплату.",
                "hint_en": "Reward confirmed — payout is on the way."},
    "paid":    {"icon": "✅", "ru": "Выплачено", "en": "Paid",
                "hint_ru": "Вознаграждение по этому клиенту выплачено.",
                "hint_en": "Your reward for this client has been paid."},
}

# Разрешённые значения payout_state — единый список для валидации (UI и CLI).
PAYOUT_STATE_VALUES: tuple[str, ...] = tuple(PAYOUT_STATES.keys())


def payout_label(lead: Lead, lang: str = "ru") -> dict[str, str] | None:
    """Статус вознаграждения по лиду → {state, label, icon, hint} для шаблонов.
    Деньги показываем ТОЛЬКО по выигранным (won) лидам — по остальным рано,
    возвращаем None (шаблон не рисует ничего про деньги). У won без явного
    payout_state дефолт «в расчёте» выводим здесь (в данные не пишем).
    Неизвестное значение деградирует мягко: сырой текст без иконки/подсказки."""
    if getattr(lead, "status", None) != "won":
        return None
    lang = lang if lang in ("ru", "en") else "ru"
    state = lead.payout_state or "in_calc"
    meta = PAYOUT_STATES.get(state)
    if not meta:
        return {"state": state, "label": state, "icon": "", "hint": ""}
    return {"state": state, "label": meta[lang], "icon": meta["icon"], "hint": meta[f"hint_{lang}"]}


# Типы партнёра для раздела «Материалы / Партнёрский кит» (Фаза C, план
# 2026-05-27) — единый источник истины. Ключ = MessageTemplate.partner_type;
# партнёр сам выбирает свой тип вкладками (решение Николь). Ярлыки ru/en, как
# LEAD_STAGES. ВАЖНО (приватность): тип `insider` (скрытые рефереры, Imran)
# подписан нейтрально «Конфиденциально / Confidential» — нигде не светим «банк/
# инсайдер/комиссия» ([[feedback_brand_name_oncount]], перекличка с Фазой G).
# Порядок ключей = порядок вкладок.
PARTNER_TYPES: dict[str, dict[str, str]] = {
    "employee":   {"icon": "💼", "ru": "В найме / сотрудник",      "en": "Employed professional"},
    "solo":       {"icon": "🧑‍💻", "ru": "Соло-консультант",         "en": "Solo operator"},
    "events":     {"icon": "🎤", "ru": "События и сообщества",      "en": "Events & community"},
    "agency":     {"icon": "🏷️", "ru": "Агентство (white-label)",  "en": "Agency (white-label)"},
    "media":      {"icon": "📣", "ru": "Медиа и блог",             "en": "Media & blog"},
    "consultant": {"icon": "📊", "ru": "Консультант / фин-директор", "en": "Consultant / CFO"},
    "insider":    {"icon": "🔒", "ru": "Конфиденциально",          "en": "Confidential"},
}


def partner_type_label(key: str, lang: str = "ru") -> dict[str, str]:
    """Тип партнёра → {key, label, icon} для вкладок/заголовков /kits.
    Неизвестный/пустой ключ деградирует мягко: сырое значение без иконки."""
    lang = lang if lang in ("ru", "en") else "ru"
    meta = PARTNER_TYPES.get(key or "")
    if not meta:
        return {"key": key or "", "label": key or "—", "icon": ""}
    return {"key": key, "label": meta[lang], "icon": meta["icon"]}


# Партнёрский менеджер — ОДИН общий на всех партнёров (решение Николь 2026-05-28,
# Фаза E). Единый источник истины кабинета: имя/контакт/SLA в одном месте, БЕЗ
# поля в Partner и БЕЗ миграции. ВАЖНО (ПД, «опасная тройка»): имя и контакт —
# РЕАЛЬНЫЕ данные, их НЕ выдумываем. До подтверждения Николь стоят помеченные
# плейсхолдеры (name_confirmed / contact_confirmed = False) — UI тогда НЕ выдаёт
# их за живой контакт и не строит кликабельную ссылку. Фото — реальное из
# team-2026-05 (static/img/manager.jpg). SLA-формулировка совпадает с уже
# обещанной в transfer.html / seed.py / messages_text.py («в рабочее время в
# течение часа») — не противоречит существующей копии кабинета.
PARTNER_MANAGER: dict = {
    "photo": "/static/img/manager.jpg",  # реальное фото Николь (team-2026-05)
    # Подтверждено Николь 2026-05-28: менеджер партнёров = Николь Хилтон.
    "name_confirmed": True,
    "name": {"ru": "Николь Хилтон", "en": "Nicole Hilton"},
    "role": {"ru": "Ваш партнёрский менеджер", "en": "Your partner manager"},
    # Контакты менеджера. channel ∈ {"whatsapp","telegram","email"};
    # value — цифры номера / username / email. confirmed=True → строим
    # кликабельную ссылку; False → UI помечает «на утверждении Николь» и НЕ
    # выдаёт выдуманные ПД за живой контакт. ВАЖНО (ПД): value НЕ выдумываем.
    "contacts": [
        # Номер WhatsApp подтверждён Николь 2026-05-28 (оканчивается на 14).
        {"channel": "whatsapp", "value": "971528553814", "confirmed": True},
        # Telegram-username из конфига проекта (CONTACT_TG_USERNAME), подтверждён Николь.
        {"channel": "telegram", "value": "nikol_hillton", "confirmed": True},
    ],
    # SLA — согласовано с уже обещанным в кабинете (transfer/seed/bot): час в
    # рабочее время. Подтверждено Николь 2026-05-28.
    "sla": {
        "ru": "Отвечаем по вашему клиенту в течение часа в рабочее время.",
        "en": "We reply about your client within an hour during business hours.",
    },
}


def partner_manager(lang: str = "ru") -> dict:
    """Данные партнёрского менеджера для шаблонов (единый источник, Фаза E).
    Возвращает локализованные строки, список готовых кликабельных контактов
    (links — только confirmed) и список каналов на утверждении (pending_channels),
    чтобы UI пометил их «на утверждении Николь» и не выдавал выдуманные ПД за
    живой контакт. Мягко деградирует на неизвестный канал (пропускаем)."""
    lang = lang if lang in ("ru", "en") else "ru"
    m = PARTNER_MANAGER
    links: list[dict] = []
    pending_channels: list[str] = []
    for c in m["contacts"]:
        ch = c.get("channel")
        if c.get("confirmed") and c.get("value"):
            v = str(c["value"]).strip()
            if ch == "whatsapp":
                digits = v.lstrip("+")
                links.append({"channel": ch, "href": f"https://wa.me/{digits}", "display": f"+{digits}"})
            elif ch == "telegram":
                uname = v.lstrip("@")
                links.append({"channel": ch, "href": f"https://t.me/{uname}", "display": f"@{uname}"})
            elif ch == "email":
                links.append({"channel": ch, "href": f"mailto:{v}", "display": v})
            # неизвестный канал — пропускаем (мягкая деградация)
        elif ch in ("whatsapp", "telegram", "email"):
            pending_channels.append(ch)
    return {
        "photo": m["photo"],
        "name": m["name"][lang],
        "name_pending": not m["name_confirmed"],
        "role": m["role"][lang],
        "sla": m["sla"][lang],
        "links": links,
        "pending_channels": pending_channels,
    }


# Доступно во всех шаблонах кабинета (DRY): leads.html, dashboard.html.
templates.env.globals["lead_stage"] = lead_stage
templates.env.globals["payout_label"] = payout_label
templates.env.globals["partner_type_label"] = partner_type_label
templates.env.globals["partner_manager"] = partner_manager

app = FastAPI(title="ONCOUNT Partner Platform")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


_RL_HITS: dict[str, "deque"] = {}
_RL_PATHS = ("/auth/", "/login", "/invite/")
_RL_MAX = 30          # запросов с одного IP
_RL_WINDOW = 60       # за столько секунд


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    """Простой per-IP rate-limit на чувствительные роуты (вход/инвайт) — против
    брутфорса токенов/ключей и енумерации (security-review 2026-05-26). In-memory,
    sliding window; за прокси Railway берём первый IP из X-Forwarded-For."""
    path = request.url.path
    if any(path.startswith(p) for p in _RL_PATHS):
        from collections import deque
        import time as _t
        xff = request.headers.get("x-forwarded-for")
        ip = (xff.split(",")[0].strip() if xff else
              (request.client.host if request.client else "?"))
        now = _t.time()
        dq = _RL_HITS.setdefault(ip, deque())
        while dq and now - dq[0] > _RL_WINDOW:
            dq.popleft()
        if len(dq) >= _RL_MAX:
            from starlette.responses import PlainTextResponse
            return PlainTextResponse("Too many requests", status_code=429)
        dq.append(now)
    return await call_next(request)


@app.middleware("http")
async def persist_lang_cookie(request: Request, call_next):
    """Делает выбор языка «липким»: ?lang=en|ru → кука lang на год. Без этого язык
    терялся при первом же переходе по ссылке (ссылки не таскают ?lang)."""
    response = await call_next(request)
    q = request.query_params.get("lang")
    if q in ("en", "ru"):
        response.set_cookie("lang", q, max_age=60 * 60 * 24 * 365, samesite="lax")
    return response


log = logging.getLogger("oncount.startup")


@app.on_event("startup")
async def on_startup() -> None:
    Base.metadata.create_all(engine)
    # One-off DDL: расширяем price_aed с VARCHAR(64) до TEXT — туда теперь идёт HTML.
    # Идемпотентно: если колонка уже TEXT, ALTER пройдёт без эффекта.
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE product_blocks ALTER COLUMN price_aed TYPE TEXT"))
        # Онбординг-поля партнёра — добавляются при первом деплое после изменения модели.
        for col in (
            "onboarded_at",
            "links_viewed_at",
            "products_viewed_at",
            "checklist_dismissed_at",
        ):
            conn.execute(text(f"ALTER TABLE partners ADD COLUMN IF NOT EXISTS {col} TIMESTAMP"))
        # Язык интерфейса бота (план 2026-05-23). Идемпотентно.
        conn.execute(text("ALTER TABLE partners ADD COLUMN IF NOT EXISTS lang VARCHAR(2)"))
        # Фаза 0.7 (план 2026-05-26): связь Partner ↔ Kommo-агент + ref_slug инвайта.
        conn.execute(text("ALTER TABLE partners ADD COLUMN IF NOT EXISTS kommo_agent_enum_id BIGINT"))
        conn.execute(text("ALTER TABLE partners ADD COLUMN IF NOT EXISTS kommo_agent_name VARCHAR(128)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_partners_kommo_agent_enum_id ON partners (kommo_agent_enum_id)"))
        conn.execute(text("ALTER TABLE login_sessions ADD COLUMN IF NOT EXISTS ref_slug VARCHAR(16)"))
        conn.execute(text("ALTER TABLE email_login_tokens ADD COLUMN IF NOT EXISTS ref_slug VARCHAR(16)"))
        # EN-колонки контент-таблиц (план 2026-05-22). create_all не делает ALTER,
        # а таблицы уже существуют в проде — добавляем идемпотентно.
        en_cols = {
            "product_blocks": ("title_en", "price_aed_en", "summary_md_en", "full_md_en"),
            "message_templates": ("segment_en", "title_en", "body_md_en"),
            "faq_items": ("category_en", "question_en", "answer_md_en"),
        }
        for tbl, cols in en_cols.items():
            for col in cols:
                conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS {col} TEXT"))
        # Вход по email (план 2026-05-23). Идемпотентно:
        # 1) telegram_id больше не обязателен — email-партнёр может быть без TG.
        conn.execute(text("ALTER TABLE partners ALTER COLUMN telegram_id DROP NOT NULL"))
        # 2) Уникальность email регистронезависимо, только для непустых значений
        #    (частичный индекс). create_all не создаёт частичных/выражательных индексов.
        #    ПРЕД-УСЛОВИЕ: на проде не должно быть дублей lower(email) — иначе упадёт;
        #    проверять перед первым деплоем (см. план, Фаза 1, пред-шаг).
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_partners_email_lower "
            "ON partners (lower(email)) WHERE email IS NOT NULL"
        ))
        # 3) Гигиена: чистим протухшие невостребованные email-токены (старше суток).
        conn.execute(text(
            "DELETE FROM email_login_tokens "
            "WHERE consumed_at IS NULL AND created_at < now() - interval '1 day'"
        ))
        # Вход по номеру телефона (план 2026-05-27). Таблицу создаёт create_all;
        # здесь только гигиена — чистим протухшие коды (старше суток), чтобы не
        # копить хэши и телефоны. Идемпотентно: нет таблицы на самом первом запуске
        # быть не может (create_all уже отработал выше).
        conn.execute(text(
            "DELETE FROM phone_login_tokens "
            "WHERE created_at < now() - interval '1 day'"
        ))
        # Статус вознаграждения по выигранному лиду (Фаза B, план 2026-05-27).
        # Аддитивно и идемпотентно: одна nullable-колонка, без DB-default —
        # дефолт «в расчёте» выводит payout_label. Существующие строки/колонки
        # не трогаются. create_all не делает ALTER, а leads уже есть в проде.
        conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS payout_state VARCHAR(16)"))
        # Тип партнёра у шаблона-материала (Фаза C, план 2026-05-27). Аддитивно и
        # идемпотентно: одна nullable-колонка + индекс. NULL = генерик /messages
        # (старые строки не трогаются). create_all не делает ALTER, а
        # message_templates уже есть в проде.
        conn.execute(text("ALTER TABLE message_templates ADD COLUMN IF NOT EXISTS partner_type VARCHAR(32)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_message_templates_partner_type ON message_templates (partner_type)"))
    with SessionLocal() as session:
        seed_if_empty(session)

    # Run the Telegram bot as an asyncio task in the same process as uvicorn.
    # Free Railway plan caps the number of services, so we co-locate web + bot.
    if settings.BOT_TOKEN:
        from app.bot import main as bot_main  # local import to avoid circular issues
        log.info("Launching bot polling as background task")
        asyncio.create_task(bot_main())
    else:
        log.info("BOT_TOKEN empty -> bot polling skipped, web only")

    # Периодический синк лидов агентов из Kommo в локальный Lead (кабинет читает его).
    # Фаза 1/кабинет (план 2026-05-26). Запускается в отдельном потоке APScheduler.
    if settings.KOMMO_TOKEN:
        from datetime import datetime as _dt
        from apscheduler.schedulers.background import BackgroundScheduler
        from app.kommo_sync import sync_agent_leads
        sched = BackgroundScheduler(timezone="UTC")
        sched.add_job(sync_agent_leads, "interval", minutes=60, id="kommo_sync",
                      next_run_time=_dt.utcnow(), max_instances=1, coalesce=True)
        # Дайджест партнёрам 5 и 20 числа, 05:00 UTC = 09:00 по Дубаю (Фаза 4).
        # Реально шлёт только при DIGEST_ENABLED, иначе dry (превью в лог).
        from app.digest import scheduled_digest
        sched.add_job(scheduled_digest, "cron", day="5,20", hour=5, minute=0,
                      id="partner_digest", max_instances=1, coalesce=True)
        sched.start()
        app.state.scheduler = sched
        log.info("scheduler started: kommo_sync hourly + digest 5/20 (enabled=%s)",
                 settings.DIGEST_ENABLED)


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "ts": datetime.utcnow().isoformat()}

# Разовые admin-эндпоинты seed/stats (Фаза 0.7) удалены после использования
# (security-review 2026-05-26: ключ=JWT_SECRET в query — риск утечки). seed/синк
# теперь только через CLI scripts/seed_agent_partners.py + APScheduler-синк.


@app.get("/debug/event-stats")
def debug_event_stats(session: Session = Depends(get_session)) -> dict:
    from sqlalchemy import func
    rows = (
        session.query(EventRegistration.event_slug, func.count(EventRegistration.id))
        .group_by(EventRegistration.event_slug)
        .all()
    )
    by_event = {slug: count for slug, count in rows}
    total = sum(by_event.values())
    from_lending = (
        session.query(func.count(EventRegistration.id))
        .filter(EventRegistration.meta["source"].as_string() == "lending")
        .scalar()
    )
    return {"total": total, "by_event": by_event, "from_lending": from_lending}


def _lang(request: Request) -> str:
    # Выбор языка интерфейса: ?lang= имеет приоритет, иначе кука lang
    # (её ставит persist_lang_cookie), иначе русский по умолчанию.
    lang_raw = request.query_params.get("lang") or request.cookies.get("lang")
    return "en" if lang_raw == "en" else "ru"


def _ctx(request: Request, partner: Partner | None, **extra) -> dict:
    return {
        "request": request,
        "partner": partner,
        "bot_username": settings.BOT_USERNAME,
        "webapp_url": settings.WEBAPP_URL,
        "year": datetime.utcnow().year,
        "lang": _lang(request),
        **extra,
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    partner = current_partner(request, session)
    if partner:
        return RedirectResponse("/dashboard", status_code=302)
    return RedirectResponse("/login", status_code=302)


@app.get("/join")
def join_partner_program() -> RedirectResponse:
    """Marketing-friendly URL: oncount-partners-production.up.railway.app/join
    → opens Telegram bot with the `partner` deep-link payload."""
    return RedirectResponse(
        f"https://t.me/{settings.BOT_USERNAME}?start=partner",
        status_code=302,
    )


INVITE_COOKIE = "invite_ref"


@app.get("/invite/{slug}")
def invite_link(slug: str, session: Session = Depends(get_session)) -> RedirectResponse:
    """Персональная инвайт-ссылка агента (Фаза 0.7). Кладёт ref_slug в cookie и ведёт
    на /login. На входе (TG/email) этот ref привяжет telegram_id/email к пред-созданному
    Partner-агенту — чтобы не плодить дубли. Неизвестный slug просто ведёт на /login."""
    resp = RedirectResponse("/login", status_code=302)
    exists = session.query(Partner).filter_by(ref_slug=slug).first() is not None
    if exists:
        resp.set_cookie(INVITE_COOKIE, slug, httponly=True, secure=True,
                        samesite="lax", max_age=3600)
    return resp


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    partner = current_partner(request, session)
    if partner:
        return RedirectResponse("/dashboard", status_code=302)
    state = secrets.token_urlsafe(24)
    ref = request.cookies.get(INVITE_COOKIE)
    session.add(LoginSession(state=state, ref_slug=ref))
    session.commit()
    return templates.TemplateResponse("login.html", _ctx(request, None, state=state))


@app.get("/auth/bot-callback")
def auth_bot_callback(state: str, next: str | None = None, session: Session = Depends(get_session)):
    """Завершение deep-link авторизации. Бот уже записал telegram_id для state.

    next — необязательная внутренняя страница, на которую кабинет откроется сразу
    после входа (например, курс-практикум). Разрешаем только локальные пути под
    /courses/, чтобы исключить open-redirect."""
    rec = session.get(LoginSession, state)
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Login session not found")
    if rec.consumed_at is not None:
        raise HTTPException(status.HTTP_410_GONE, "Login session already used")
    if rec.telegram_id is None:
        raise HTTPException(status.HTTP_425_TOO_EARLY, "Click the button inside the bot first")
    if datetime.utcnow() - rec.created_at > LOGIN_SESSION_TTL:
        raise HTTPException(status.HTTP_410_GONE, "Login session expired, /login again")

    telegram_id = rec.telegram_id
    rec.consumed_at = datetime.utcnow()
    session.commit()

    partner = None
    # Фаза 0.7: вход по инвайт-ссылке → привязать telegram_id к пред-созданному
    # Partner-агенту. Привязываем ТОЛЬКО не активированного агента (status="invited")
    # и ТОЛЬКО если канал свободен — иначе чужой по той же ссылке перехватил бы
    # кабинет агента (security-review 2026-05-26, одноразовость инвайта).
    if rec.ref_slug:
        invited = session.query(Partner).filter_by(ref_slug=rec.ref_slug).first()
        if invited and invited.status == "invited" and invited.telegram_id is None:
            stray = session.query(Partner).filter_by(telegram_id=telegram_id).first()
            if stray and stray.id != invited.id:
                stray.telegram_id = None  # освободить уникальный telegram_id
                stray.status = "merged"
                session.flush()
            invited.telegram_id = telegram_id
            invited.status = "active"  # инвайт «погашен»: повторная привязка невозможна
            partner = invited

    if partner is None:
        partner = session.query(Partner).filter_by(telegram_id=telegram_id).first()
    if not partner:
        # бот к этому моменту уже создал партнёра в БД, но на всякий случай
        partner = Partner(
            telegram_id=telegram_id,
            ref_slug=generate_ref_slug(),
            status="pending",
        )
        session.add(partner)
        session.commit()
        session.refresh(partner)

    partner.last_login_at = datetime.utcnow()
    session.commit()

    token = issue_jwt(partner.id)
    dest = next if (next and next.startswith("/courses/")) else "/dashboard"
    response = RedirectResponse(dest, status_code=302)
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=settings.JWT_TTL_DAYS * 86400,
    )
    return response


def _fresh_login_state(session: Session) -> str:
    """Свежий state для Telegram-кнопки на странице входа (как в login_page)."""
    state = secrets.token_urlsafe(24)
    session.add(LoginSession(state=state))
    session.commit()
    return state


@app.post("/auth/email/request", response_class=HTMLResponse)
def auth_email_request(
    request: Request,
    email: str = Form(...),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Шаг 1 магической ссылки: принять email, отправить письмо со ссылкой входа.

    Анти-энумерация: ответ всегда одинаковый — «проверьте почту» — есть такой
    адрес или нет. Rate-limit: не больше EMAIL_RATE_LIMIT запросов на email за TTL.
    """
    email_norm = (email or "").strip().lower()
    lang = _lang(request)

    if EMAIL_RE.match(email_norm):
        window_start = datetime.utcnow() - EMAIL_TOKEN_TTL
        recent = (
            session.query(EmailLoginToken)
            .filter(
                EmailLoginToken.email == email_norm,
                EmailLoginToken.created_at >= window_start,
            )
            .count()
        )
        if recent < EMAIL_RATE_LIMIT:
            token = secrets.token_urlsafe(32)
            session.add(EmailLoginToken(
                token=token, email=email_norm,
                ref_slug=request.cookies.get(INVITE_COOKIE),
            ))
            session.commit()
            url = f"{settings.WEBAPP_URL}/auth/email/callback?token={token}"
            send_magic_link(email_norm, url, lang)

    return templates.TemplateResponse(
        "login.html",
        _ctx(request, None, state=_fresh_login_state(session), email_sent=True),
    )


@app.get("/auth/email/callback")
def auth_email_callback(token: str, session: Session = Depends(get_session)):
    """Шаг 2: клик по магической ссылке → выдаём JWT-cookie и заводим ЛК."""
    from sqlalchemy import func

    rec = session.get(EmailLoginToken, token)
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Login link not found")
    if rec.consumed_at is not None:
        raise HTTPException(status.HTTP_410_GONE, "Login link already used")
    if datetime.utcnow() - rec.created_at > EMAIL_TOKEN_TTL:
        raise HTTPException(status.HTTP_410_GONE, "Login link expired, request a new one")

    rec.consumed_at = datetime.utcnow()
    session.commit()

    partner = None
    # Фаза 0.7: вход по инвайт-ссылке → привязать email к Partner-агенту. Только
    # не активированного (status="invited") и со свободным email — защита от
    # перехвата кабинета по чужой ссылке (security-review 2026-05-26).
    if rec.ref_slug:
        invited = session.query(Partner).filter_by(ref_slug=rec.ref_slug).first()
        if invited and invited.status == "invited" and invited.email is None:
            stray = (
                session.query(Partner)
                .filter(func.lower(Partner.email) == rec.email)
                .first()
            )
            if stray and stray.id != invited.id:
                stray.email = None
                stray.status = "merged"
                session.flush()
            invited.email = rec.email
            invited.status = "active"  # инвайт «погашен»
            partner = invited

    if partner is None:
        partner = (
            session.query(Partner)
            .filter(func.lower(Partner.email) == rec.email)
            .first()
        )
    if not partner:
        # Новый партнёр без Telegram: заводим по email. first_name = локальная
        # часть адреса, чтобы плашка пользователя в шапке не была пустой.
        partner = Partner(
            email=rec.email,
            first_name=rec.email.split("@")[0],
            ref_slug=generate_ref_slug(),
            status="pending",
        )
        session.add(partner)
        try:
            session.commit()
            session.refresh(partner)
        except IntegrityError:
            # Гонка: партнёр с этим email появился между запросом и вставкой.
            session.rollback()
            partner = (
                session.query(Partner)
                .filter(func.lower(Partner.email) == rec.email)
                .first()
            )
            if partner is None:
                raise

    partner.last_login_at = datetime.utcnow()
    session.commit()

    response = RedirectResponse("/dashboard", status_code=302)
    response.set_cookie(
        COOKIE_NAME,
        issue_jwt(partner.id),
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=settings.JWT_TTL_DAYS * 86400,
    )
    return response


@app.post("/auth/phone/request", response_class=HTMLResponse)
def auth_phone_request(
    request: Request,
    phone: str = Form(...),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Шаг 1 входа по номеру: принять телефон → отправить 6-значный код в WhatsApp.

    Главный способ входа (телефон — сквозной идентификатор агента, план 2026-05-27).
    Анти-энумерация: ответ всегда одинаковый (показываем шаг ввода кода), есть
    такой агент в базе или нет. Код шлём ТОЛЬКО известному агенту (Partner.phone).
    Rate-limit: не больше PHONE_RATE_LIMIT кодов на номер за TTL.
    """
    norm = normalize_phone(phone)
    lang = _lang(request)

    if len(norm) >= PHONE_MIN_DIGITS:
        window_start = datetime.utcnow() - PHONE_CODE_TTL
        recent = (
            session.query(PhoneLoginToken)
            .filter(
                PhoneLoginToken.phone == norm,
                PhoneLoginToken.created_at >= window_start,
            )
            .count()
        )
        if recent < PHONE_RATE_LIMIT:
            # Пускаем только известных агентов: номер должен быть привязан к кабинету
            # (PartnerIdentity kind='phone' или Partner.phone). Неизвестный → код не шлём.
            partner = find_partner_by_phone(session, norm)
            if partner is not None:
                code = f"{secrets.randbelow(900_000) + 100_000}"  # 6 цифр, 100000–999999
                session.add(PhoneLoginToken(phone=norm, code_hash=hash_login_code(code)))
                session.commit()
                send_wa_code(norm, code, lang)

    return templates.TemplateResponse(
        "login.html",
        _ctx(request, None, state=_fresh_login_state(session),
             code_sent=True, code_phone=norm),
    )


@app.post("/auth/phone/verify", response_class=HTMLResponse)
def auth_phone_verify(
    request: Request,
    phone: str = Form(...),
    code: str = Form(...),
    session: Session = Depends(get_session),
):
    """Шаг 2 входа по номеру: проверить код → выдать JWT-cookie → кабинет агента.

    Брутфорс закрыт TTL (10 мин) + лимитом попыток (≤5) + rate-limit запросов кода
    + per-IP middleware. Все провалы (нет кода / просрочен / неверный / попытки
    кончились) дают ОДИН и тот же нейтральный ответ — иначе по тексту ошибки можно
    было бы отличить «номер в базе» от «номера нет» (анти-энумерация)."""
    norm = normalize_phone(phone)
    code = (code or "").strip()

    def reject() -> HTMLResponse:
        return templates.TemplateResponse(
            "login.html",
            _ctx(request, None, state=_fresh_login_state(session),
                 code_sent=True, code_phone=norm, code_error=True),
        )

    rec = (
        session.query(PhoneLoginToken)
        .filter(
            PhoneLoginToken.phone == norm,
            PhoneLoginToken.consumed_at.is_(None),
        )
        .order_by(PhoneLoginToken.created_at.desc())
        .first()
    )
    if rec is None or datetime.utcnow() - rec.created_at > PHONE_CODE_TTL:
        return reject()
    if rec.attempts >= PHONE_CODE_MAX_ATTEMPTS:
        return reject()

    rec.attempts += 1
    session.commit()
    if not verify_login_code(code, rec.code_hash):
        return reject()

    rec.consumed_at = datetime.utcnow()
    session.commit()

    partner = find_partner_by_phone(session, norm)
    if partner is None:
        # Код выдаётся только известному агенту; partner=None здесь означает, что
        # агента/привязку удалили между request и verify — трактуем как просроченный.
        return reject()

    # Объединение каналов: телефон-Partner каноничен. Если у того же Kommo-агента
    # есть «осиротевшие» Partner из других каналов (бот/почта) — помечаем merged,
    # чтобы дедуп/дайджест считали их вытесненными (по аналогии с ref-привязкой).
    if partner.kommo_agent_enum_id is not None:
        strays = (
            session.query(Partner)
            .filter(
                Partner.kommo_agent_enum_id == partner.kommo_agent_enum_id,
                Partner.id != partner.id,
            )
            .all()
        )
        for stray in strays:
            stray.status = "merged"

    partner.last_login_at = datetime.utcnow()
    partner.status = "active"
    session.commit()

    response = RedirectResponse("/dashboard", status_code=302)
    response.set_cookie(
        COOKIE_NAME,
        issue_jwt(partner.id),
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=settings.JWT_TTL_DAYS * 86400,
    )
    return response


@app.get("/logout")
def logout() -> RedirectResponse:
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    return response


# (slug, RU-подпись, EN-подпись) — шаблон онбординга выбирает подпись по lang.
SEGMENTS = [
    ("lawyer", "Юрист / юр. фирма", "Lawyer / law firm"),
    ("freezone", "Free-zone agent", "Free-zone agent"),
    ("banker", "Банкир / RM", "Banker / RM"),
    ("coworking", "Коворкинг / бизнес-сервис", "Coworking / business services"),
    ("accountant", "Бухгалтер-фрилансер", "Freelance accountant"),
    ("entrepreneur", "Предприниматель", "Entrepreneur"),
    ("other", "Другое", "Other"),
]


@app.get("/onboarding", response_class=HTMLResponse)
def onboarding_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    partner = current_partner(request, session)
    if not partner:
        return RedirectResponse("/login", status_code=302)
    if partner.onboarded_at:
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(
        "onboarding.html",
        _ctx(request, partner, segments=SEGMENTS, message=None),
    )


@app.post("/onboarding", response_class=HTMLResponse)
def onboarding_submit(
    request: Request,
    segment: str = Form(...),
    phone: str = Form(...),
    email: str = Form(...),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    partner = current_partner(request, session)
    if not partner:
        return RedirectResponse("/login", status_code=302)

    segment = (segment or "").strip().lower()
    phone = (phone or "").strip()
    email = (email or "").strip().lower()
    en = _lang(request) == "en"

    if segment not in {s[0] for s in SEGMENTS}:
        msg = "Choose a segment from the list." if en else "Выбери сегмент из списка."
        return templates.TemplateResponse(
            "onboarding.html",
            _ctx(request, partner, segments=SEGMENTS, message=msg),
            status_code=400,
        )
    if not phone or len(phone) < 5:
        msg = "Enter your phone or WhatsApp." if en else "Укажи телефон или WhatsApp."
        return templates.TemplateResponse(
            "onboarding.html",
            _ctx(request, partner, segments=SEGMENTS, message=msg),
            status_code=400,
        )
    if "@" not in email or "." not in email:
        msg = "The email is invalid." if en else "Email указан некорректно."
        return templates.TemplateResponse(
            "onboarding.html",
            _ctx(request, partner, segments=SEGMENTS, message=msg),
            status_code=400,
        )

    partner.segment = segment
    partner.phone = phone
    partner.email = email
    partner.onboarded_at = datetime.utcnow()
    try:
        session.commit()
    except IntegrityError:
        # Уникальный индекс по lower(email) (вход по email, план 2026-05-23):
        # этот адрес уже привязан к другому партнёру.
        session.rollback()
        msg = (
            "This email is already linked to another account."
            if en else
            "Этот email уже привязан к другому аккаунту."
        )
        return templates.TemplateResponse(
            "onboarding.html",
            _ctx(request, partner, segments=SEGMENTS, message=msg),
            status_code=409,
        )
    return RedirectResponse("/dashboard", status_code=302)


@app.post("/checklist/dismiss")
def checklist_dismiss(request: Request, session: Session = Depends(get_session)):
    partner = current_partner(request, session)
    if not partner:
        return RedirectResponse("/login", status_code=302)
    partner.checklist_dismissed_at = datetime.utcnow()
    session.commit()
    return RedirectResponse("/dashboard", status_code=302)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    partner = current_partner(request, session)
    if not partner:
        return RedirectResponse("/login", status_code=302)
    if not partner.onboarded_at:
        return RedirectResponse("/onboarding", status_code=302)

    leads_q = session.query(Lead).filter_by(partner_id=partner.id)
    leads_count = leads_q.count()
    successful = leads_q.filter(Lead.status == "won").count()
    in_progress = leads_q.filter(Lead.status.in_(["new", "in_progress"])).count()
    rejected = leads_q.filter(Lead.status == "lost").count()
    conversion = round(successful / leads_count * 100, 1) if leads_count else 0.0

    won_rows = leads_q.filter(Lead.status == "won").all()
    total_aed = sum((l.amount_aed or 0) for l in won_rows)
    # Сводка по вознаграждению (Фаза B): из тех же won-лидов, без доп. запроса.
    # Дефолт «в расчёте» = won без явного payout_state — как в payout_label.
    payout_to_pay = sum(1 for l in won_rows if l.payout_state == "to_pay")
    payout_paid = sum(1 for l in won_rows if l.payout_state == "paid")

    checklist_steps = [
        {
            "label": "Скопируй свою партнёрскую ссылку",
            "label_en": "Copy your partner link",
            "done": partner.links_viewed_at is not None,
            "href": "/links",
        },
        {
            "label": "Передай первого клиента",
            "label_en": "Introduce your first client",
            "done": leads_count > 0,
            "href": "/transfer",
        },
        {
            "label": "Изучи тарифы и вознаграждение",
            "label_en": "Explore plans and rewards",
            "done": partner.products_viewed_at is not None,
            "href": "/products",
        },
    ]
    show_checklist = (
        partner.checklist_dismissed_at is None
        and not all(s["done"] for s in checklist_steps)
    )

    return templates.TemplateResponse(
        "dashboard.html",
        _ctx(
            request,
            partner,
            kpi={
                "conversion": conversion,
                "leads": leads_count,
                "successful": successful,
                "rejected": rejected,
                "in_progress": in_progress,
                "earned_aed": float(total_aed),
                # Сводка вознаграждения (Фаза B): к выплате / выплачено.
                "payout_to_pay": payout_to_pay,
                "payout_paid": payout_paid,
                # Ожидаемая комиссия: $300 (мин) … $1000 (средн) с каждого лида.
                "expected_usd_low": leads_count * 300,
                "expected_usd_high": leads_count * 1000,
            },
            checklist_steps=checklist_steps,
            show_checklist=show_checklist,
        ),
    )


@app.get("/leads", response_class=HTMLResponse)
def leads(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    partner = current_partner(request, session)
    if not partner:
        return RedirectResponse("/login", status_code=302)
    rows = (
        session.query(Lead)
        .filter_by(partner_id=partner.id)
        .order_by(Lead.created_at.desc())
        .limit(100)
        .all()
    )
    return templates.TemplateResponse("leads.html", _ctx(request, partner, rows=rows))


CONSULT_TEXT_TPL = (
    "Здравствуйте! Хочу записаться на бесплатную консультацию "
    "с бухгалтером ONCOUNT. Код партнёра: {slug}"
)
MCLASS_TEXT_TPL = (
    "Здравствуйте! Хочу попасть на мастер-класс с бухгалтером ONCOUNT. "
    "Код партнёра: {slug}"
)

# Невидимая метка в WA/TG-сообщении: код партнёра, закодированный
# zero-width Unicode. Переживает удаление видимого «Код партнёра: …».
# Парсер на стороне inbox-intercom-backend (см. encode_slug_invisible ниже):
#   1) найти подстроку между ZW_START и ZW_END
#   2) каждый ZW_ZERO → '0', ZW_ONE → '1'
#   3) собрать байты по 8 бит, ord→chr → slug
ZW_ZERO = "​"   # zero-width space
ZW_ONE = "‌"    # zero-width non-joiner
ZW_START = "‍"  # zero-width joiner
ZW_END = "⁠"    # word joiner


def encode_slug_invisible(slug: str) -> str:
    bits = "".join(format(ord(c), "08b") for c in slug)
    body = "".join(ZW_ZERO if b == "0" else ZW_ONE for b in bits)
    return ZW_START + body + ZW_END


def _build_text(template: str, slug: str) -> str:
    return template.format(slug=slug) + encode_slug_invisible(slug)


def _redirect_to_chat(channel: str, text: str) -> RedirectResponse:
    encoded = quote(text)
    if channel == "tg":
        url = f"https://t.me/{settings.CONTACT_TG_USERNAME}?text={encoded}"
    elif channel == "wa":
        url = f"https://wa.me/{settings.CONTACT_WA_NUMBER}?text={encoded}"
    else:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown channel")
    return RedirectResponse(url, status_code=302)


@app.get("/ct/{slug}")
def short_consult_tg(slug: str) -> RedirectResponse:
    return _redirect_to_chat("tg", _build_text(CONSULT_TEXT_TPL, slug))


@app.get("/cw/{slug}")
def short_consult_wa(slug: str) -> RedirectResponse:
    return _redirect_to_chat("wa", _build_text(CONSULT_TEXT_TPL, slug))


@app.get("/mt/{slug}")
def short_mclass_tg(slug: str) -> RedirectResponse:
    return _redirect_to_chat("tg", _build_text(MCLASS_TEXT_TPL, slug))


@app.get("/mw/{slug}")
def short_mclass_wa(slug: str) -> RedirectResponse:
    return _redirect_to_chat("wa", _build_text(MCLASS_TEXT_TPL, slug))


@app.get("/p/{slug}")
def short_partner_bot(slug: str) -> RedirectResponse:
    return RedirectResponse(
        f"https://t.me/{settings.BOT_USERNAME}?start=ref_{slug}",
        status_code=302,
    )


@app.get("/links", response_class=HTMLResponse)
def links(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    partner = current_partner(request, session)
    if not partner:
        return RedirectResponse("/login", status_code=302)
    if partner.links_viewed_at is None:
        partner.links_viewed_at = datetime.utcnow()
        session.commit()

    ref = partner.ref_slug
    base = str(request.base_url).rstrip("/")

    return templates.TemplateResponse(
        "links.html",
        _ctx(
            request,
            partner,
            ref_slug=ref,
            link_consult_tg=f"{base}/ct/{ref}",
            link_consult_wa=f"{base}/cw/{ref}",
            link_mclass_tg=f"{base}/mt/{ref}",
            link_mclass_wa=f"{base}/mw/{ref}",
            link_partner_bot=f"{base}/p/{ref}",
        ),
    )


@app.get("/transfer", response_class=HTMLResponse)
def transfer_get(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    partner = current_partner(request, session)
    if not partner:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse("transfer.html", _ctx(request, partner, message=None))


@app.post("/transfer", response_class=HTMLResponse)
def transfer_post(
    request: Request,
    client_name: str = Form(...),
    client_phone: str = Form(""),
    client_telegram: str = Form(""),
    company_name: str = Form(""),
    task_description: str = Form(""),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    partner = current_partner(request, session)
    if not partner:
        return RedirectResponse("/login", status_code=302)

    lead = Lead(
        partner_id=partner.id,
        client_name=client_name.strip(),
        client_phone=client_phone.strip() or None,
        client_telegram=client_telegram.strip() or None,
        company_name=company_name.strip() or None,
        task_description=task_description.strip() or None,
        status="new",
    )
    session.add(lead)
    session.commit()

    msg = (
        "Client referred. A manager will be in touch within 24 hours."
        if _lang(request) == "en"
        else "Клиент передан. Менеджер свяжется в течение 24 часов."
    )
    return templates.TemplateResponse(
        "transfer.html",
        _ctx(request, partner, message=msg),
    )


@app.get("/products", response_class=HTMLResponse)
@app.get("/kb/products", response_class=HTMLResponse)
def products(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    partner = current_partner(request, session)
    if not partner:
        return RedirectResponse("/login", status_code=302)
    if partner.products_viewed_at is None:
        partner.products_viewed_at = datetime.utcnow()
        session.commit()
    items = (
        session.query(ProductBlock)
        .filter_by(is_active=True)
        .order_by(ProductBlock.order_index)
        .all()
    )
    return templates.TemplateResponse("products.html", _ctx(request, partner, items=items))


@app.get("/messages", response_class=HTMLResponse)
def messages(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    partner = current_partner(request, session)
    if not partner:
        return RedirectResponse("/login", status_code=302)
    # Только генерик-крючки (partner_type IS NULL). Материалы с типом партнёра
    # живут в /kits — иначе черновики-киты протекли бы сюда с кнопкой «Скопировать».
    items = (
        session.query(MessageTemplate)
        .filter(MessageTemplate.is_active.is_(True))
        .filter(MessageTemplate.partner_type.is_(None))
        .order_by(MessageTemplate.order_index)
        .all()
    )
    return templates.TemplateResponse("messages.html", _ctx(request, partner, items=items))


@app.get("/kits", response_class=HTMLResponse)
def kits(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    """Раздел «Материалы / Партнёрский кит» (Фаза C, план 2026-05-27).

    Готовые ассеты, сегментированные по ТИПУ ПАРТНЁРА (PARTNER_TYPES). Партнёр сам
    выбирает свой тип вкладкой (?type=), видит карточки этого типа с кнопкой
    «Скопировать». Материалы = MessageTemplate с непустым partner_type (генерик
    /messages с partner_type IS NULL сюда не попадают — другая ось).
    """
    partner = current_partner(request, session)
    if not partner:
        return RedirectResponse("/login", status_code=302)
    lang = _lang(request)
    items = (
        session.query(MessageTemplate)
        .filter(MessageTemplate.is_active.is_(True))
        .filter(MessageTemplate.partner_type.isnot(None))
        # id — стабильный тай-брейк: при равных order_index в одном типе порядок
        # карточек иначе не определён (Николь добавит несколько ассетов на тип).
        .order_by(MessageTemplate.partner_type, MessageTemplate.order_index, MessageTemplate.id)
        .all()
    )
    # Группируем по типу партнёра, сохраняя порядок PARTNER_TYPES (для вкладок).
    grouped: dict[str, list] = {}
    for it in items:
        grouped.setdefault(it.partner_type, []).append(it)
    # Вкладки = только типы, у которых есть материалы, в порядке PARTNER_TYPES.
    type_keys = [k for k in PARTNER_TYPES if k in grouped]
    # Выбранный тип: ?type= из числа доступных, иначе первый доступный (если есть).
    requested = request.query_params.get("type")
    selected = requested if requested in type_keys else (type_keys[0] if type_keys else None)
    return templates.TemplateResponse(
        "kits.html",
        _ctx(
            request,
            partner,
            type_keys=type_keys,
            selected=selected,
            items=grouped.get(selected, []),
        ),
    )


@app.get("/faq", response_class=HTMLResponse)
@app.get("/kb/faq", response_class=HTMLResponse)
def faq(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    partner = current_partner(request, session)
    if not partner:
        return RedirectResponse("/login", status_code=302)
    items = (
        session.query(FaqItem)
        .filter_by(is_active=True)
        .order_by(FaqItem.category, FaqItem.order_index)
        .all()
    )
    categories: dict[str, list[FaqItem]] = {}
    for item in items:
        categories.setdefault(item.category, []).append(item)
    return templates.TemplateResponse("faq.html", _ctx(request, partner, categories=categories))


@app.get("/courses", response_class=HTMLResponse)
@app.get("/kb/courses", response_class=HTMLResponse)
def courses(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    partner = current_partner(request, session)
    if not partner:
        return RedirectResponse("/login", status_code=302)
    items = (
        session.query(Course)
        .filter_by(is_active=True)
        .order_by(Course.order_index)
        .all()
    )
    mastermind_details = [
        p.strip() for p in settings.MASTERMIND_DETAILS.split(";") if p.strip()
    ]
    mastermind_details_en = [
        p.strip() for p in settings.MASTERMIND_DETAILS_EN.split(";") if p.strip()
    ]
    return templates.TemplateResponse(
        "courses.html",
        _ctx(
            request,
            partner,
            items=items,
            mastermind_title=settings.MASTERMIND_TITLE,
            mastermind_details=mastermind_details,
            mastermind_footer=settings.MASTERMIND_FOOTER,
            mastermind_title_en=settings.MASTERMIND_TITLE_EN,
            mastermind_details_en=mastermind_details_en,
            mastermind_footer_en=settings.MASTERMIND_FOOTER_EN,
            # Стрелка ведёт на будущую страницу программы Mastermind (пока заглушка).
            mastermind_url="#",
        ),
    )


# Богатые страницы уроков курса. Контент — редакторский (этапы, промпты, тайм-коды),
# поэтому живёт в отдельных Jinja-шаблонах, а не в БД (гибрид, план
# 2026-05-22-kabinet-kursy-uroki-i18n). Маппинг (slug, день) → шаблон. Незнакомая пара
# → редирект на витрину, чтобы не плодить 404 на «локед»/будущих днях.
LESSON_TEMPLATES: dict[tuple[str, int], str] = {
    ("ai-employees-setup", 1): "course-ai-setup-day1.html",
    ("ai-employees-setup", 2): "course-ai-setup-day2.html",
}


@app.get("/courses/{slug}", response_class=HTMLResponse)
def course_entry(slug: str, request: Request, session: Session = Depends(get_session)):
    """CTA «Начать/Продолжить» ведёт сюда → редирект на первый день, если у курса
    есть уроки; иначе обратно на витрину (slug в шаблоне не хардкодим — решает роут)."""
    partner = current_partner(request, session)
    if not partner:
        return RedirectResponse("/login", status_code=302)
    if any(s == slug for (s, _d) in LESSON_TEMPLATES):
        return RedirectResponse(f"/courses/{slug}/day/1", status_code=302)
    return RedirectResponse("/courses", status_code=302)


@app.get("/courses/{slug}/day/{day}", response_class=HTMLResponse)
def course_lesson(
    slug: str, day: int, request: Request, session: Session = Depends(get_session)
):
    partner = current_partner(request, session)
    if not partner:
        return RedirectResponse("/login", status_code=302)
    template = LESSON_TEMPLATES.get((slug, day))
    if not template:
        return RedirectResponse("/courses", status_code=302)
    return templates.TemplateResponse(template, _ctx(request, partner))
