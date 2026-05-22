import asyncio
import logging
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import (
    COOKIE_NAME,
    current_partner,
    issue_jwt,
)
from app.config import settings
from app.db import SessionLocal, engine, get_session
from app.models import (
    Base,
    Course,
    EventRegistration,
    FaqItem,
    Lead,
    LoginSession,
    MessageTemplate,
    Partner,
    ProductBlock,
    Referral,
)
from app.refgen import generate_ref_slug
from app.seed import seed_if_empty

LOGIN_SESSION_TTL = timedelta(minutes=10)

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

app = FastAPI(title="ONCOUNT Partner Platform")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


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


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "ts": datetime.utcnow().isoformat()}


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


def _ctx(request: Request, partner: Partner | None, **extra) -> dict:
    # lang — выбор языка интерфейса: ?lang= имеет приоритет, иначе кука lang
    # (её ставит persist_lang_cookie), иначе русский по умолчанию.
    lang_raw = request.query_params.get("lang") or request.cookies.get("lang")
    lang = "en" if lang_raw == "en" else "ru"
    return {
        "request": request,
        "partner": partner,
        "bot_username": settings.BOT_USERNAME,
        "webapp_url": settings.WEBAPP_URL,
        "year": datetime.utcnow().year,
        "lang": lang,
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


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    partner = current_partner(request, session)
    if partner:
        return RedirectResponse("/dashboard", status_code=302)
    state = secrets.token_urlsafe(24)
    session.add(LoginSession(state=state))
    session.commit()
    return templates.TemplateResponse("login.html", _ctx(request, None, state=state))


@app.get("/auth/bot-callback")
def auth_bot_callback(state: str, session: Session = Depends(get_session)):
    """Завершение deep-link авторизации. Бот уже записал telegram_id для state."""
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
    response = RedirectResponse("/dashboard", status_code=302)
    response.set_cookie(
        COOKIE_NAME,
        token,
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


SEGMENTS = [
    ("lawyer", "Юрист / юр. фирма"),
    ("freezone", "Free-zone agent"),
    ("banker", "Банкир / RM"),
    ("coworking", "Коворкинг / бизнес-сервис"),
    ("accountant", "Бухгалтер-фрилансер"),
    ("entrepreneur", "Предприниматель"),
    ("other", "Другое"),
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

    if segment not in {s[0] for s in SEGMENTS}:
        return templates.TemplateResponse(
            "onboarding.html",
            _ctx(request, partner, segments=SEGMENTS, message="Выбери сегмент из списка."),
            status_code=400,
        )
    if not phone or len(phone) < 5:
        return templates.TemplateResponse(
            "onboarding.html",
            _ctx(request, partner, segments=SEGMENTS, message="Укажи телефон или WhatsApp."),
            status_code=400,
        )
    if "@" not in email or "." not in email:
        return templates.TemplateResponse(
            "onboarding.html",
            _ctx(request, partner, segments=SEGMENTS, message="Email указан некорректно."),
            status_code=400,
        )

    partner.segment = segment
    partner.phone = phone
    partner.email = email
    partner.onboarded_at = datetime.utcnow()
    session.commit()
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

    total_aed = sum((l.amount_aed or 0) for l in leads_q.filter(Lead.status == "won").all())

    checklist_steps = [
        {
            "label": "Скопируй свою реф-ссылку",
            "done": partner.links_viewed_at is not None,
            "href": "/links",
        },
        {
            "label": "Передай первого клиента",
            "done": leads_count > 0,
            "href": "/transfer",
        },
        {
            "label": "Изучи тарифы и комиссии",
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

    return templates.TemplateResponse(
        "transfer.html",
        _ctx(request, partner, message="Клиент передан. Менеджер свяжется в течение 24 часов."),
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
    items = (
        session.query(MessageTemplate)
        .filter_by(is_active=True)
        .order_by(MessageTemplate.order_index)
        .all()
    )
    return templates.TemplateResponse("messages.html", _ctx(request, partner, items=items))


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
