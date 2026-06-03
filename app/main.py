import asyncio
import logging
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import httpx
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
    PartnerIdentity,
    PhoneLoginToken,
    ProductBlock,
    QuizSubmission,
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
    "new":         {"icon": "📥", "ru": "Принят",   "en": "Received"},
    "in_progress": {"icon": "🧮", "ru": "В работе", "en": "In progress"},
    "won":         {"icon": "✅", "ru": "Оплачено", "en": "Paid"},
    "lost":        {"icon": "",   "ru": "Отказ",    "en": "Declined"},
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


# ─── Способы привлечения — ось вкладок /tools (план 2026-06-02) ──────────────
# Партнёр выбирает не «кто я» (тип), а «каким действием привожу» (способ).
# Порядок METHODS = порядок вкладок (Интро / Рассылка / Пост / Чек-лист /
# События — решение Николь 2026-06-02). hint = строка-фильтр «для кого» в шапке
# блока. Названия КОРОТКИЕ — чтобы 5 вкладок влезли в одну строку. Отдельного
# блока «прямые ссылки» нет: персональная ссылка уже вшита в каждый текст через
# {link}, дублировать список не нужно. EN-ярлыки тут же (ось внутренняя).
METHODS: dict[str, dict[str, str]] = {
    "intro":      {"icon": "💬", "ru": "Интро",     "en": "Intro",
                   "hint_ru": "Тёплый клиент 1-на-1 — представьте нас в переписке готовым шаблоном со своей ссылкой.",
                   "hint_en": "A warm 1-on-1 client — introduce us in chat with a ready template that has your link."},
    "broadcast":  {"icon": "📨", "ru": "Рассылка",  "en": "Broadcast",
                   "hint_ru": "У вас есть база контактов (WhatsApp / Telegram) — отправьте готовый текст со своей ссылкой.",
                   "hint_en": "You have a contact base (WhatsApp / Telegram) — send a ready text with your link."},
    "social":     {"icon": "📱", "ru": "Пост",      "en": "Post",
                   "hint_ru": "У вас есть канал, блог или аккаунт — опубликуйте готовый пост со своей ссылкой.",
                   "hint_en": "You have a channel, blog or account — publish a ready post with your link."},
    "leadmagnet": {"icon": "📋", "ru": "Чек-лист",  "en": "Checklist",
                   "hint_ru": "Подарите чек-лист в обмен на интерес — мягкий повод привести клиента.",
                   "hint_en": "Offer a checklist in exchange for interest — a soft way to bring a client."},
    "event":      {"icon": "🤝", "ru": "События",   "en": "Events",
                   "hint_ru": "Проводите совместное мероприятие — пригласите аудиторию на разбор с бухгалтером.",
                   "hint_en": "Running a joint event — invite the audience to a session with an accountant."},
}
METHODS_ORDER: list[str] = list(METHODS.keys())

# Старые якоря /tools → новые способы (bot.py и закладки не ломаем). directlinks
# больше нет отдельной вкладкой — ссылки переехали в `intro`, туда же #links.
LEGACY_TOOL_ANCHORS: dict[str, str] = {
    "links": "intro",
    "directlinks": "intro",
    "messages": "broadcast",
    "kits": "intro",
}

# Сертифицированные бухгалтеры — блок доверия в кружочках (решение Николь
# 2026-06-02): на квиз-лендинге /consultation и в кабинете у приглашения на
# консультацию. Только визуал доверия (без клика). Майя — реальное имя/роль
# (главбух, фото 391), Омер — ведущий бухгалтер (фото 394, с волосами и очками);
# Радж — условное индийское имя (по просьбе Николь); Майя/Омер/Леся — реальные.
# Языки — текстовыми кодами RU/EN/AR (флаг-эмодзи не рендерятся на Windows).
# Фото в static/img/accountants/.
ACCOUNTANTS: list[dict] = [
    {"photo": "/static/img/accountants/maya.jpg", "name": "Майя Мандзюк",
     "name_en": "Maya Mandziuk", "role": "Главный бухгалтер",
     "role_en": "Chief accountant", "langs": ["ru", "gb"],
     "exp": "10+ лет опыта", "exp_en": "10+ yrs"},
    {"photo": "/static/img/accountants/omer.jpg", "name": "Омер",
     "name_en": "Omer", "role": "Ведущий бухгалтер",
     "role_en": "Lead accountant", "langs": ["gb", "ae"],
     "exp": "5+ лет опыта", "exp_en": "5+ yrs"},
    {"photo": "/static/img/accountants/raj.jpg", "name": "Радж",
     "name_en": "Raj", "role": "Бухгалтер", "role_en": "Accountant",
     "langs": ["gb"], "exp": "3+ лет опыта", "exp_en": "3+ yrs"},
    {"photo": "/static/img/accountants/lesia.jpg", "name": "Леся",
     "name_en": "Lesia", "role": "Ведущий бухгалтер", "role_en": "Lead accountant",
     "langs": ["ru", "gb"], "exp": "8+ лет опыта", "exp_en": "8+ yrs"},
]


def method_label(key: str, lang: str = "ru") -> dict[str, str]:
    """Способ → {key, label, icon, hint} для вкладок/шапки блока /tools.
    Неизвестный/пустой ключ деградирует мягко: сырое значение без иконки."""
    lang = lang if lang in ("ru", "en") else "ru"
    meta = METHODS.get(key or "")
    if not meta:
        return {"key": key or "", "label": key or "—", "icon": "", "hint": ""}
    return {
        "key": key,
        "label": meta[lang],
        "icon": meta["icon"],
        "hint": meta["hint_en" if lang == "en" else "hint_ru"],
    }


def _personal_links(ref: str, base: str) -> dict[str, str]:
    """Все персональные ссылки партнёра по ключам link_key. Один источник истины
    для вкладок /tools и для подстановки плейсхолдера {link} в тело текста.
    Квизы /consultation и /mk — наш домен, ?ref= метит лида нативно; TG/WA —
    редиректы /ct,/cw,/mt,/mw; partner_bot — приглашение нового партнёра."""
    return {
        "consult_quiz": f"{base}/consultation?ref={ref}",
        "consult_tg":   f"{base}/ct/{ref}",
        "consult_wa":   f"{base}/cw/{ref}",
        "mk_quiz":      f"{base}/mk?ref={ref}",
        "mk_tg":        f"{base}/mt/{ref}",
        "mk_wa":        f"{base}/mw/{ref}",
        "partner_bot":  f"{base}/p/{ref}",
    }


# ─── Анкета партнёра (Фаза L, план 2026-05-27) ──────────────────────────────
# ⚠️ ТЕКСТЫ ВОПРОСОВ/ВАРИАНТОВ — ЧЕРНОВИК на утверждении Николь (НЕ выдаём за
# финальные, урок Фаз E/F). Правятся ЗДЕСЬ без миграции — ответы лежат в JSON
# по ключу варианта, а не по тексту. Снять флаг SURVEY_DRAFT после утверждения.
#
# Структура решена Николь 2026-06-01:
#   • список «сфера» — из плана Фазы L (НЕ переиспользуем SEGMENTS/PARTNER_TYPES);
#   • «опыт» — по рынку ОАЭ; «поток B2B» — да/нет + диапазон; «соцсети» —
#     каналы (мультивыбор) + ориентир аудитории;
#   • «выплаты» — ТОЛЬКО ТИП канала (белый список). Номера карт/кошельков/IBAN
#     в БД НЕ пишем — критерий безопасности (ПД, «опасная тройка»).
SURVEY_DRAFT = False  # тексты утверждены Николь 2026-06-02 (Фаза 4 go-live)

# Каждый вариант: (value, ru, en). value — стабильный ключ в JSON-ответах.
SURVEY_OPTIONS: dict[str, list[tuple[str, str, str]]] = {
    "sphere": [
        ("consulting",        "Консалтинг",                   "Consulting"),
        ("bank_accounts",     "Открытие банковских счетов",   "Bank account opening"),
        ("real_estate",       "Недвижимость",                 "Real estate"),
        ("company_formation", "Регистрация компаний",         "Company formation"),
        ("golden_visa",       "Golden Visa / визы",           "Golden Visa / visas"),
        ("finance_insurance", "Финансы и страхование",        "Finance & insurance"),
        ("marketing_pr",      "Маркетинг и PR",               "Marketing & PR"),
        ("events",            "События и сообщества",         "Events & community"),
        ("media_influencer",  "Медиа / инфлюенсер",           "Media / influencer"),
        ("other",             "Другое",                       "Other"),
    ],
    "uae_experience": [
        ("lt1", "До 1 года",   "Under 1 year"),
        ("lt3", "До 3 лет",    "Under 3 years"),
        ("lt5", "До 5 лет",    "Under 5 years"),
        ("gt5", "Свыше 5 лет", "Over 5 years"),
    ],
    "b2b_flow": [
        ("steady",     "Да, постоянно",      "Yes, steady"),
        ("occasional", "Время от времени",   "From time to time"),
        ("none",       "Пока нет",           "Not yet"),
    ],
    "b2b_volume": [
        ("1-5",    "1–5 в месяц",    "1–5 a month"),
        ("5-20",   "5–20 в месяц",   "5–20 a month"),
        ("20-50",  "20–50 в месяц",  "20–50 a month"),
        ("50plus", "50+ в месяц",    "50+ a month"),
    ],
    "base_size": [
        ("lt50",     "До 50",     "Under 50"),
        ("50-200",   "50–200",    "50–200"),
        ("200-1000", "200–1000",  "200–1000"),
        ("1000plus", "1000+",     "1000+"),
    ],
    "social_channels": [
        ("instagram", "Instagram",       "Instagram"),
        ("telegram",  "Telegram",        "Telegram"),
        ("linkedin",  "LinkedIn",        "LinkedIn"),
        ("youtube",   "YouTube",         "YouTube"),
        ("tiktok",    "TikTok",          "TikTok"),
        ("facebook",  "Facebook",        "Facebook"),
        ("none",      "Нет соцсетей",    "No social channels"),
        ("other",     "Другое",          "Other"),
    ],
    "social_audience": [
        ("lt1k",    "До 1 000",   "Under 1k"),
        ("1-10k",   "1–10 тыс.",  "1–10k"),
        ("10-50k",  "10–50 тыс.", "10–50k"),
        ("50kplus", "50 тыс.+",   "50k+"),
    ],
    "payout_method": [
        ("card",   "Банковская карта",       "Bank card"),
        ("bank",   "Банковский счёт (IBAN)", "Bank account (IBAN)"),
        ("crypto", "Криптовалюта (USDT)",    "Crypto (USDT)"),
    ],
}

# Заголовок вопроса (ru, en). Порядок отображения и для менеджер-сводки —
# SURVEY_FIELD_ORDER ниже.
SURVEY_LABELS: dict[str, tuple[str, str]] = {
    "sphere":          ("В какой сфере вы работаете?",
                        "What's your field?"),
    "uae_experience":  ("Как давно вы в B2B-сфере?",
                        "How long have you been in B2B?"),
    "b2b_flow":        ("Есть ли у вас поток клиентов-предпринимателей?",
                        "Do you have a flow of business clients?"),
    "b2b_volume":      ("Сколько примерно клиентов в месяц?",
                        "Roughly how many clients a month?"),
    "base_size":       ("Насколько большая у вас база контактов?",
                        "How large is your contact base?"),
    "social_channels": ("У вас есть соцсети, в которых можно продвигать услугу бухгалтерии?",
                        "Do you have social media where you could promote accounting services?"),
    "social_audience": ("Ориентир по размеру аудитории",
                        "Approximate audience size"),
    "payout_method":   ("Как удобнее получать партнёрское вознаграждение?",
                        "How would you prefer to receive partner rewards?"),
}

# Порядок вопросов в форме и в сводке для менеджера.
SURVEY_FIELD_ORDER = [
    "sphere", "uae_experience", "b2b_flow", "b2b_volume",
    "base_size", "social_channels", "social_audience", "payout_method",
]
# Поля, обязательные на сервере (остальные — условные/опциональные).
SURVEY_REQUIRED = {"sphere", "uae_experience", "b2b_flow", "base_size", "payout_method"}
# Свободный текст к варианту «other» — длину режем, ПД не предполагается.
SURVEY_OTHER_MAXLEN = 120


def _survey_values(field: str) -> set[str]:
    """Белый список value по полю анкеты."""
    return {o[0] for o in SURVEY_OPTIONS.get(field, [])}


def partner_onboarding(partner: Partner, lang: str = "ru") -> dict:
    """Единый источник по анкете партнёра (Фаза L): статус + человекочитаемые
    ответы. Используется баннером (`completed`), GET-формой (`answers` для
    предзаполнения) и админ-просмотром менеджера (`summary`).
    Мягко деградирует: пустые/неизвестные значения не валят рендер."""
    lang = lang if lang in ("ru", "en") else "ru"
    li = 2 if lang == "en" else 1  # индекс ru/en в кортеже варианта
    answers: dict = partner.onboarding_answers or {}
    completed = partner.survey_completed_at is not None

    def label(field: str, val: str) -> str:
        for o in SURVEY_OPTIONS.get(field, []):
            if o[0] == val:
                return o[li]
        return val  # текст «other» или неизвестный ключ — как есть

    summary: list[dict] = []
    for field in SURVEY_FIELD_ORDER:
        raw = answers.get(field)
        if not raw:
            continue
        if isinstance(raw, list):
            value_label = ", ".join(label(field, v) for v in raw)
        else:
            value_label = label(field, raw)
        # «other»-текст хранится отдельным ключом <field>_other.
        extra = answers.get(f"{field}_other")
        if extra:
            value_label = f"{value_label}: {extra}"
        summary.append({
            "field": field,
            "question": SURVEY_LABELS.get(field, ("", ""))[0 if lang == "ru" else 1],
            "value": value_label,
        })
    return {"completed": completed, "answers": answers, "summary": summary}


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
templates.env.globals["method_label"] = method_label
templates.env.globals["partner_manager"] = partner_manager
# Дата выплаты по won-лиду (Фаза K) — единый источник для leads.html.
from app.notifications import payout_due_date as _payout_due_date  # noqa: E402
templates.env.globals["payout_due_date"] = _payout_due_date
# Контакты для футера — из конфига (правило репо №1: не хардкодить ссылки).
# Тот же источник, что и короткие ссылки /ct /cw (settings.CONTACT_*).
templates.env.globals["contact_tg"] = settings.CONTACT_TG_USERNAME
templates.env.globals["contact_wa"] = settings.CONTACT_WA_NUMBER
# Telegram-id админа (Николь) — чтобы шаблон показывал пункт меню «Аналитика»
# только ей (раздел /admin/*). Гейт всё равно на сервере (require_admin).
templates.env.globals["admin_tg_id"] = settings.ADMIN_TG_ID

app = FastAPI(title="ONCOUNT Partner Platform")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


_RL_HITS: dict[str, "deque"] = {}
_RL_PATHS = ("/auth/", "/login", "/invite/", "/consultation/submit", "/mk/submit",
             "/guide/corp-tax/submit")
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
        # «Что НЕ предлагать клиенту» — обязательное поле формы /transfer (Фаза F,
        # план 2026-05-27): защищает репутацию партнёра. Аддитивно, идемпотентно,
        # nullable: старые лиды и лиды из kommo_sync/бота — без этого поля.
        conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS do_not_offer TEXT"))
        # Якорь выплаты + идемпотентность win-пуша (Фаза K, план 2026-05-27).
        # Аддитивно и идемпотентно: две nullable-колонки без DB-default. won_at —
        # стабильный момент перехода в won (дата выплаты), won_notified_at — что
        # пуш уже обработан. create_all не делает ALTER, а leads уже есть в проде.
        conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS won_at TIMESTAMP"))
        conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS won_notified_at TIMESTAMP"))
        # Модуль выплат (план 2026-06-02, замена Excel). Аддитивно и идемпотентно:
        # nullable-колонки без DB-default (кроме payout_urgent). create_all не делает
        # ALTER, а leads уже есть в проде. Заполняет менеджер на /admin/payouts.
        conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS fee_aed NUMERIC(12,2)"))
        conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS payout_urgent BOOLEAN DEFAULT FALSE"))
        conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS agreement_url TEXT"))
        conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS bank_details TEXT"))
        conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS payout_receipt_url TEXT"))
        conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS payout_paid_on VARCHAR(32)"))
        # Тип партнёра у шаблона-материала (Фаза C, план 2026-05-27). Аддитивно и
        # идемпотентно: одна nullable-колонка + индекс. NULL = генерик /messages
        # (старые строки не трогаются). create_all не делает ALTER, а
        # message_templates уже есть в проде.
        conn.execute(text("ALTER TABLE message_templates ADD COLUMN IF NOT EXISTS partner_type VARCHAR(32)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_message_templates_partner_type ON message_templates (partner_type)"))
        # Способ привлечения + ключ персональной ссылки (план 2026-06-02
        # «переборка /tools по способам»). Аддитивно и идемпотентно: две
        # nullable-колонки + индекс по method. NULL = текст не в новых вкладках.
        # create_all не делает ALTER, а message_templates уже есть в проде.
        conn.execute(text("ALTER TABLE message_templates ADD COLUMN IF NOT EXISTS method VARCHAR(32)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_message_templates_method ON message_templates (method)"))
        conn.execute(text("ALTER TABLE message_templates ADD COLUMN IF NOT EXISTS link_key VARCHAR(16)"))
        # Анкета партнёра (Фаза L, план 2026-05-27). Аддитивно и идемпотентно:
        # две nullable-колонки, без DB-default. onboarding_answers (JSON) — ответы
        # белого списка; survey_completed_at — отметка прохождения (NULL = не
        # пройдена → баннер показан). Существующие партнёры остаются без значений.
        # Тип JSON совпадает с моделью (как Referral.visitor_meta) — нет
        # расхождения dev/prod. ПД: номера карт/кошельков в JSON НЕ пишем.
        conn.execute(text("ALTER TABLE partners ADD COLUMN IF NOT EXISTS onboarding_answers JSON"))
        conn.execute(text("ALTER TABLE partners ADD COLUMN IF NOT EXISTS survey_completed_at TIMESTAMP"))
        # Дискриминатор лендинга у заявок квиза (план 2026-06-02): отделяет
        # регистрации мастер-класса от заявок /consultation. Аддитивно и
        # идемпотентно: одна nullable-колонка + индекс. NULL = /consultation
        # (старые строки не трогаются). create_all создаёт колонку на чистой БД,
        # ALTER — на случай уже существующей таблицы quiz_submissions.
        conn.execute(text("ALTER TABLE quiz_submissions ADD COLUMN IF NOT EXISTS event_slug VARCHAR(64)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_quiz_submissions_event_slug ON quiz_submissions (event_slug)"))
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
        # Старый месячный digest (Фаза 4, 5/20) погашен Фазой K: единый канал
        # уведомлений наружу — недельный digest_job ниже, под предохранителем
        # NOTIFICATIONS_LIVE. Модуль app/digest.py не удалён (build_digest как
        # библиотека), но в планировщик больше не регистрируется — чтобы нельзя
        # было случайно запустить две рассылки двумя разными флагами.
        # Еженедельный digest партнёру (Фаза K): ежедневно 12:00 UTC = 16:00
        # Asia/Dubai; внутри сам отбирает партнёров «чей сегодня день» (id % 7) и
        # молчит, если за неделю изменений нет. Реально шлёт только при
        # NOTIFICATIONS_LIVE, иначе dry (запись в notification_attempts).
        from app.notifications import digest_job
        sched.add_job(digest_job, "cron", hour=12, minute=0,
                      id="weekly_digest", max_instances=1, coalesce=True)
        sched.start()
        app.state.scheduler = sched
        log.info("scheduler started: kommo_sync hourly + weekly_digest 16:00 Dubai (notifications_live=%s)",
                 settings.NOTIFICATIONS_LIVE)


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


def require_admin(request: Request, session: Session) -> Partner:
    """Гейт раздела /admin/* — ТОЛЬКО Николь по её Telegram (settings.ADMIN_TG_ID).
    Чужой партнёр или аноним → 404 (не 403: не раскрываем существование раздела).
    Здесь видны чувствительные данные по ВСЕМ агентам + финансовые ПД (реквизиты),
    поэтому доступ строго один аккаунт ([[plans/2026-06-02-partner-analytics-dashboard]])."""
    partner = current_partner(request, session)
    if partner is None or partner.telegram_id != settings.ADMIN_TG_ID:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return partner


KOMMO_LEAD_URL = "https://primeadvice.kommo.com/leads/detail/"


def _humanize_survey(answers: dict) -> list[tuple[str, str]]:
    """Ответы анкеты L → [(вопрос, человекочитаемый ответ)] по белым спискам."""
    out: list[tuple[str, str]] = []
    for field in SURVEY_FIELD_ORDER:
        if field not in answers:
            continue
        label = SURVEY_LABELS.get(field, (field, field))[0]
        opts = {o[0]: o[1] for o in SURVEY_OPTIONS.get(field, [])}
        val = answers[field]
        if isinstance(val, list):
            human = ", ".join(opts.get(v, v) for v in val)
        else:
            human = opts.get(val, str(val))
        out.append((label, human))
    if answers.get("sphere_other"):
        out.append(("Сфера (другое)", str(answers["sphere_other"])))
    return out


@app.get("/admin/partner-stats", response_class=HTMLResponse)
def admin_partner_stats(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    """Дашборд лидеров (Фаза 2, план 2026-06-02). Только админ (Telegram-гейт)."""
    admin = require_admin(request, session)
    from sqlalchemy import case, func

    agg = (
        session.query(
            Lead.partner_id.label("pid"),
            func.count(Lead.id).label("total"),
            func.sum(case((Lead.status.in_(("new", "in_progress")), 1), else_=0)).label("active"),
            func.sum(case((Lead.status == "won", 1), else_=0)).label("won"),
            func.sum(case((Lead.status == "lost", 1), else_=0)).label("lost"),
            func.coalesce(func.sum(case((Lead.status == "won", Lead.amount_aed), else_=0)), 0).label("paid_sum"),
        )
        .group_by(Lead.partner_id)
        .all()
    )
    pids = [r.pid for r in agg if r.pid is not None]
    partners = (
        {p.id: p for p in session.query(Partner).filter(Partner.id.in_(pids)).all()}
        if pids else {}
    )
    rows = []
    for r in agg:
        p = partners.get(r.pid)
        if p is None:
            continue
        total, won = r.total or 0, r.won or 0
        rows.append({
            "id": p.id,
            "name": p.first_name or p.kommo_agent_name or f"#{p.id}",
            "ref_slug": p.ref_slug or "—",
            "total": total,
            "active": r.active or 0,
            "won": won,
            "lost": r.lost or 0,
            "paid_sum": float(r.paid_sum or 0),
            "conv": round(won / total * 100) if total else 0,
            "last_login_at": p.last_login_at,
            "onboarded": p.survey_completed_at is not None,
        })
    rows.sort(key=lambda x: (x["won"], x["total"], x["paid_sum"]), reverse=True)
    totals = {
        "agents": len(rows),
        "total": sum(x["total"] for x in rows),
        "active": sum(x["active"] for x in rows),
        "won": sum(x["won"] for x in rows),
        "lost": sum(x["lost"] for x in rows),
        "paid_sum": sum(x["paid_sum"] for x in rows),
    }
    return templates.TemplateResponse(
        "admin_partner_stats.html", _ctx(request, admin, rows=rows, totals=totals)
    )


@app.get("/admin/partner/{pid}", response_class=HTMLResponse)
def admin_partner_detail(pid: int, request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    """Карточка агента (Фазы 2б/3/7): клиенты со ссылками на Kommo, профиль из
    анкеты и точный предпросмотр digest/win-отчёта. Только админ."""
    admin = require_admin(request, session)
    agent = session.get(Partner, pid)
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    leads = (
        session.query(Lead)
        .filter_by(partner_id=pid)
        .order_by(Lead.created_at.desc())
        .all()
    )
    from app.notifications import build_digest_text, build_win_text

    digest_preview = build_digest_text(agent, session, datetime.utcnow())
    last_won = next((l for l in leads if l.status == "won"), None)
    win_preview = build_win_text(agent, last_won, session) if last_won else None
    return templates.TemplateResponse(
        "admin_partner_detail.html",
        _ctx(
            request, admin,
            agent=agent, leads=leads, kommo_url=KOMMO_LEAD_URL,
            profile=_humanize_survey(agent.onboarding_answers or {}),
            digest_preview=digest_preview, win_preview=win_preview,
        ),
    )


@app.get("/admin/sources", response_class=HTMLResponse)
def admin_sources(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    """Аналитика источников (Фаза 4): заявки по UTM / мероприятию / ссылке агента.
    Считаем КОНВЕРСИИ (заявки квиза + регистрации), не сырые клики. Только админ."""
    admin = require_admin(request, session)
    from sqlalchemy import func

    # 1) По UTM (source + campaign) — заявки квиза.
    utm = [
        {"src": r.src, "camp": r.camp, "n": r.n}
        for r in session.query(
            func.coalesce(QuizSubmission.utm_source, "—").label("src"),
            func.coalesce(QuizSubmission.utm_campaign, "—").label("camp"),
            func.count(QuizSubmission.id).label("n"),
        )
        .group_by(QuizSubmission.utm_source, QuizSubmission.utm_campaign)
        .order_by(func.count(QuizSubmission.id).desc())
        .all()
    ]

    # 2) По мероприятию: заявки квиза (NULL event_slug = консультация) + регистрации бота.
    events_quiz = [
        {"ev": r.ev, "n": r.n}
        for r in session.query(
            func.coalesce(QuizSubmission.event_slug, "consultation").label("ev"),
            func.count(QuizSubmission.id).label("n"),
        ).group_by(QuizSubmission.event_slug).order_by(func.count(QuizSubmission.id).desc()).all()
    ]
    events_reg = [
        {"ev": r.ev, "n": r.n}
        for r in session.query(
            EventRegistration.event_slug.label("ev"),
            func.count(EventRegistration.id).label("n"),
        ).group_by(EventRegistration.event_slug).order_by(func.count(EventRegistration.id).desc()).all()
    ]

    # 3) По ссылке агента: заявки квиза с привязкой к партнёру + сколько лидов won.
    quiz_by_p = dict(
        session.query(QuizSubmission.partner_id, func.count(QuizSubmission.id))
        .filter(QuizSubmission.partner_id.isnot(None))
        .group_by(QuizSubmission.partner_id)
        .all()
    )
    won_by_p = dict(
        session.query(Lead.partner_id, func.count(Lead.id))
        .filter(Lead.status == "won", Lead.partner_id.isnot(None))
        .group_by(Lead.partner_id)
        .all()
    )
    pids = list(quiz_by_p.keys())
    pmap = (
        {p.id: p for p in session.query(Partner).filter(Partner.id.in_(pids)).all()}
        if pids else {}
    )
    links = []
    for pid, n in quiz_by_p.items():
        p = pmap.get(pid)
        if p is None:
            continue
        links.append({
            "id": pid,
            "name": p.first_name or p.kommo_agent_name or f"#{pid}",
            "ref_slug": p.ref_slug or "—",
            "quiz": n,
            "won": won_by_p.get(pid, 0),
        })
    links.sort(key=lambda x: (x["quiz"], x["won"]), reverse=True)

    return templates.TemplateResponse(
        "admin_sources.html",
        _ctx(request, admin, utm=utm, events_quiz=events_quiz,
             events_reg=events_reg, links=links),
    )


# ─── Модуль выплат (план 2026-06-02, замена Excel менеджера) ─────────────────
# Менеджерский статус (4) → (агент-facing payout_state, payout_urgent). Агент в
# кабинете видит только дружелюбные in_calc/to_pay/paid; «срочно»/«уточняется» —
# внутренние для менеджера, агенту НЕ показываются.
PAYOUT_MGR_OPTIONS = [
    ("clarify", "Уточняется"),
    ("to_pay", "Под выплату"),
    ("urgent", "Срочно"),
    ("paid", "Оплачено"),
]
_MGR_TO_STATE = {
    "clarify": ("in_calc", False),
    "to_pay": ("to_pay", False),
    "urgent": ("to_pay", True),
    "paid": ("paid", False),
}


def _payout_mgr_value(lead: Lead) -> str:
    """Текущий менеджерский статус из (payout_state, payout_urgent)."""
    if getattr(lead, "payout_urgent", False):
        return "urgent"
    return {"in_calc": "clarify", "to_pay": "to_pay", "paid": "paid"}.get(
        lead.payout_state or "in_calc", "clarify"
    )


@app.get("/admin/payouts", response_class=HTMLResponse)
def admin_payouts(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    """Учёт выплат агентам (замена Excel). Только админ. Список won-лидов: авто из
    системы (клиент/Kommo/агент/сумма/дата) + ручные поля (комиссия, статус,
    договор, реквизиты, чек, дата выплаты)."""
    admin = require_admin(request, session)
    leads = (
        session.query(Lead)
        .filter(Lead.status == "won")
        .order_by(Lead.won_at.desc(), Lead.id.desc())
        .all()
    )
    pids = {l.partner_id for l in leads if l.partner_id}
    pmap = (
        {p.id: p for p in session.query(Partner).filter(Partner.id.in_(pids)).all()}
        if pids else {}
    )
    rows = [
        {"lead": l,
         "agent": (pmap[l.partner_id].first_name or pmap[l.partner_id].kommo_agent_name or "—")
                  if l.partner_id in pmap else "—",
         "mgr": _payout_mgr_value(l)}
        for l in leads
    ]
    fee_total = sum(float(l.fee_aed) for l in leads if l.fee_aed is not None)
    paid_total = sum(float(l.fee_aed) for l in leads
                     if l.fee_aed is not None and l.payout_state == "paid")
    return templates.TemplateResponse(
        "admin_payouts.html",
        _ctx(request, admin, rows=rows, kommo_url=KOMMO_LEAD_URL,
             mgr_options=PAYOUT_MGR_OPTIONS, fee_total=fee_total, paid_total=paid_total),
    )


@app.post("/admin/payouts/{lead_id}")
def admin_payout_save(
    lead_id: int,
    request: Request,
    fee_aed: str = Form(""),
    mgr_status: str = Form("clarify"),
    agreement_url: str = Form(""),
    bank_details: str = Form(""),
    receipt_url: str = Form(""),
    paid_on: str = Form(""),
    session: Session = Depends(get_session),
):
    """Сохранить выплату по won-лиду. Только админ. Менеджерский статус → агент-
    facing payout_state + флаг urgent. Реквизиты — финансовые ПД, в лог не пишем."""
    require_admin(request, session)
    lead = session.get(Lead, lead_id)
    if lead is None or lead.status != "won":
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    # Пробел и запятая — разделители тысяч (формат файла: «1,460», «2 320»,
    # «3,424.05»), точка — десятичная. Убираем тысячные, точку сохраняем.
    fee = (fee_aed or "").strip().replace(" ", "").replace(",", "")
    if fee:
        try:
            lead.fee_aed = float(fee)
        except ValueError:
            pass  # мусор в сумме игнорируем, остальное сохраняем
    else:
        lead.fee_aed = None
    state, urgent = _MGR_TO_STATE.get((mgr_status or "").strip(), ("in_calc", False))
    lead.payout_state = state
    lead.payout_urgent = urgent
    lead.agreement_url = (agreement_url or "").strip() or None
    lead.bank_details = (bank_details or "").strip() or None
    lead.payout_receipt_url = (receipt_url or "").strip() or None
    lead.payout_paid_on = (paid_on or "").strip() or None
    session.commit()
    return RedirectResponse("/admin/payouts", status_code=303)


def _balance_kpi(session: Session, partner: Partner) -> dict:
    """Минимум данных для верхней «балансовой» полосы (шаблон _balance.html):
    заработано + ожидаемое вознаграждение по числу заявок + код партнёра.
    Используется на /leads, /tools, /products. На дашборде те же ключи считаются
    вместе с полным kpi, поэтому полоса там работает на своём наборе данных."""
    leads_q = session.query(Lead).filter_by(partner_id=partner.id)
    leads_count = leads_q.count()
    won_rows = leads_q.filter(Lead.status == "won").all()
    total_aed = sum((l.amount_aed or 0) for l in won_rows)
    return {
        "leads": leads_count,
        "earned_aed": float(total_aed),
        "expected_usd_low": leads_count * 300,
        "expected_usd_high": leads_count * 1000,
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    partner = current_partner(request, session)
    if partner:
        return RedirectResponse("/dashboard", status_code=302)
    return RedirectResponse("/login", status_code=302)


# ─── Квиз-лендинг «Консультация» (план 2026-06-02) ───────────────────────────
# Публичный квиз: 3 вопроса → имя+телефон → лид в Kommo воронку 1.1 + Postgres.
# Атрибуция к агенту по ?ref=<ref_slug>. Запись в Kommo под предохранителем
# settings.QUIZ_KOMMO_LIVE (см. app/kommo_lead.py).

def _quiz_mask_phone(norm: str) -> str:
    return f"{norm[:4]}***{norm[-2:]}" if len(norm) > 6 else "***"


@app.get("/consultation", response_class=HTMLResponse)
def consultation_page(request: Request) -> HTMLResponse:
    from app import quiz_config
    return templates.TemplateResponse("quiz.html", {
        "request": request,
        "cover": quiz_config.COVER,
        "intro": quiz_config.INTRO,
        "questions": quiz_config.QUESTIONS,
        "final": quiz_config.FINAL,
        "thanks": quiz_config.THANKS,
        "socials": quiz_config.SOCIALS,
        "submit_url": "/consultation/submit",
        "accountants": ACCOUNTANTS,
    })


@app.post("/consultation/submit")
async def consultation_submit(request: Request,
                              session: Session = Depends(get_session)) -> dict:
    """Приём заявки квиза /consultation → лид в воронку 1.1 + Postgres + TG-пуш."""
    from app import quiz_config
    return await _handle_quiz_submit(
        request, session,
        valid_options=quiz_config.VALID_OPTIONS,
        question_titles=quiz_config.QUESTION_TITLES,
        event_slug=None,
        notify_header="🟢 Новая заявка с квиза /consultation",
        lead_prefix="Квиз-консультация",
        lead_tag="quiz",
        note_intro="Заявка с квиз-лендинга /consultation.",
    )


# ─── Мастер-класс с главбухом: обложка-оффер + те же 3 вопроса (план 2026-06-02) ──

@app.get("/mk", response_class=HTMLResponse)
def mk_page(request: Request) -> HTMLResponse:
    from app import mk_config
    return templates.TemplateResponse("quiz.html", {
        "request": request,
        "page_title": "ONCOUNT — мастер-класс с главбухом",
        "cover": mk_config.COVER,
        "intro": mk_config.INTRO,
        "questions": mk_config.QUESTIONS,
        "final": mk_config.FINAL,
        "thanks": mk_config.THANKS,
        "socials": mk_config.SOCIALS,
        "submit_url": "/mk/submit",
    })


@app.post("/mk/submit")
async def mk_submit(request: Request,
                    session: Session = Depends(get_session)) -> dict:
    """Приём регистрации на мастер-класс → лид в воронку 1.1 + Postgres + TG-пуш.
    Та же машинерия, что у /consultation, но с event_slug и своими текстами лида."""
    from app import mk_config
    return await _handle_quiz_submit(
        request, session,
        valid_options=mk_config.VALID_OPTIONS,
        question_titles=mk_config.QUESTION_TITLES,
        event_slug=mk_config.EVENT_SLUG,
        notify_header="🎓 Новая регистрация на мастер-класс (11 июня)",
        lead_prefix=mk_config.KOMMO_LEAD_PREFIX,
        lead_tag=mk_config.KOMMO_LEAD_TAG,
        note_intro=mk_config.KOMMO_NOTE_INTRO,
    )


# ─── Лид-магнит «0% Corporate Tax»: квиз → PDF чек-листа ссылкой в WhatsApp ──────
# (план 2026-06-02). Партнёрский канал: тизер + ссылка ?ref={код}. Те же 3 шага,
# но после заявки клиенту уходит WhatsApp-сообщение со ссылкой на PDF.

@app.get("/guide/corp-tax", response_class=HTMLResponse)
def guide_corp_tax_page(request: Request) -> HTMLResponse:
    from app import leadmagnet_config as lm
    return templates.TemplateResponse("quiz.html", {
        "request": request,
        "page_title": "ONCOUNT — чек-лист 0% Corporate Tax",
        "cover": lm.COVER,
        "intro": lm.INTRO,
        "questions": lm.QUESTIONS,
        "final": lm.FINAL,
        "thanks": lm.THANKS,
        "socials": lm.SOCIALS,
        "submit_url": "/guide/corp-tax/submit",
    })


@app.post("/guide/corp-tax/submit")
async def guide_corp_tax_submit(request: Request,
                                session: Session = Depends(get_session)) -> dict:
    """Приём заявки лид-магнита → лид в воронку 1.1 + PDF-ссылка в WhatsApp.
    Та же машинерия, что у /consultation и /mk, плюс доставка чек-листа ссылкой."""
    from app import leadmagnet_config as lm
    return await _handle_quiz_submit(
        request, session,
        valid_options=lm.VALID_OPTIONS,
        question_titles=lm.QUESTION_TITLES,
        event_slug=lm.EVENT_SLUG,
        notify_header="📥 Новая заявка с лид-магнита «0% Corporate Tax»",
        lead_prefix=lm.KOMMO_LEAD_PREFIX,
        lead_tag=lm.KOMMO_LEAD_TAG,
        note_intro=lm.KOMMO_NOTE_INTRO,
        deliver_wa_text=lm.WA_TEXT.format(link=lm.GUIDE_PDF_URL),
    )


async def _handle_quiz_submit(
    request: Request, session: Session, *,
    valid_options: dict, question_titles: dict,
    event_slug: str | None, notify_header: str,
    lead_prefix: str, lead_tag: str, note_intro: str,
    deliver_wa_text: str | None = None,
) -> dict:
    """Общее ядро приёма заявок квиз-лендингов (/consultation и /mk). Клиенту
    ВСЕГДА отвечаем ok (идемпотентно, без утечки внутренней логики). Порядок:
    валидация → honeypot/дедуп → Postgres → Kommo (под гардом) → TG-пуш админу.
    Сырой ввод НЕ рендерим обратно (анти-XSS)."""
    from app.kommo_lead import create_consultation_lead

    try:
        data = await request.json()
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}

    # Honeypot: поле website видно только ботам — заполнено → тихо «ok», ничего не пишем.
    if (data.get("website") or "").strip():
        return {"ok": True}

    name = (data.get("name") or "").strip()[:200] or None
    phone_norm = normalize_phone(data.get("phone") or "")
    if len(phone_norm) < PHONE_MIN_DIGITS:
        return {"ok": False, "error": "phone"}

    # Ответы — только белый список вариантов (анти-инъекция произвольных строк).
    raw_answers = data.get("answers") or {}
    answers = {}
    if isinstance(raw_answers, dict):
        for qid, valid in valid_options.items():
            v = raw_answers.get(qid)
            if isinstance(v, str) and v in valid:
                answers[qid] = v

    def _s(key, n=180):
        v = data.get(key)
        return v.strip()[:n] if isinstance(v, str) and v.strip() else None

    ref_slug = _s("ref", 16)
    utm = {k: _s(k) for k in ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")}

    # Дедуп в пределах ОДНОГО события: та же заявка (телефон+event_slug) за 2 минуты
    # → не плодим строку/лид. Разные события (МК vs консультация) не глушим.
    recent = (session.query(QuizSubmission)
              .filter(QuizSubmission.phone == phone_norm,
                      QuizSubmission.event_slug == event_slug,
                      QuizSubmission.created_at >= datetime.utcnow() - timedelta(minutes=2))
              .first())
    if recent is not None:
        return {"ok": True}

    # Атрибуция агента по ref_slug → Partner (строго по совпадению, не угадываем).
    partner = None
    if ref_slug:
        partner = session.query(Partner).filter_by(ref_slug=ref_slug).first()

    sub = QuizSubmission(
        name=name, phone=phone_norm, answers=answers or None, event_slug=event_slug,
        ref_slug=ref_slug, partner_id=partner.id if partner else None,
        referrer=_s("referrer", 400), landing_url=_s("landing_url", 400),
        kommo_status="pending", **{k: v for k, v in utm.items()},
    )
    session.add(sub)
    session.commit()

    # Kommo воронка 1.1 (под предохранителем). Лид не создаётся — заявка уже в БД.
    agent_enum_id = partner.kommo_agent_enum_id if partner else None
    result = create_consultation_lead(
        name=name, phone_norm=phone_norm, answers=answers,
        agent_enum_id=agent_enum_id, utm=utm, ref_slug=ref_slug,
        lead_prefix=lead_prefix, lead_tag=lead_tag, note_intro=note_intro,
        question_titles=question_titles,
    )
    sub.kommo_status = result["status"]
    sub.kommo_lead_id = result.get("kommo_lead_id")
    session.commit()

    # Доставка чек-листа клиенту в WhatsApp (лид-магнит). Best-effort: лид уже
    # создан, провал доставки не валит приём. Предохранители — внутри send_wa_text
    # (dev / WAZZUP_TEST_ONLY_NUMBER): на тесте PDF уходит только на тестовый номер.
    if deliver_wa_text:
        try:
            from app.wazzup import send_wa_text
            ok = send_wa_text(phone_norm, deliver_wa_text)
            log.info("leadmagnet PDF link → WA event=%s sent=%s", event_slug, ok)
        except Exception as exc:  # сеть/конфиг — не валим приём заявки
            log.warning("leadmagnet WA delivery error: %s", type(exc).__name__)

    # TG-пуш админу (Николь) — внутреннее уведомление в наш бот, не сторонний сервис.
    _notify_admin_new_quiz(sub, partner, answers,
                           header=notify_header, question_titles=question_titles)
    log.info("quiz submit event=%s phone=%s agent=%s kommo=%s",
             event_slug or "consultation", _quiz_mask_phone(phone_norm),
             partner.id if partner else "-", result["status"])
    return {"ok": True}


def _notify_admin_new_quiz(sub: "QuizSubmission", partner: "Partner | None",
                           answers: dict, *, header: str, question_titles: dict) -> None:
    """Уведомить Николь о новой заявке через наш бот. Best-effort: провал не
    влияет на приём (строка уже в БД). Шлём ПОЛНЫЙ телефон — это наш лид для звонка."""
    if not settings.BOT_TOKEN:
        return
    lines = [header, ""]
    lines.append(f"Имя: {sub.name or '—'}")
    lines.append(f"Телефон: +{sub.phone}")
    for qid, title in question_titles.items():
        if answers.get(qid):
            lines.append(f"• {title} — {answers[qid]}")
    if partner:
        lines.append("")
        lines.append(f"Агент: {partner.kommo_agent_name or partner.first_name or partner.ref_slug}")
    elif sub.ref_slug:
        lines.append(f"\nРеф-метка (агент не найден): {sub.ref_slug}")
    utm_src = sub.utm_source or sub.utm_campaign
    if utm_src:
        lines.append(f"UTM: source={sub.utm_source or '-'}, campaign={sub.utm_campaign or '-'}")
    lines.append(f"\nKommo: {sub.kommo_status}" + (f" (#{sub.kommo_lead_id})" if sub.kommo_lead_id else ""))
    try:
        httpx.post(
            f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage",
            json={"chat_id": settings.ADMIN_TG_ID, "text": "\n".join(lines)},
            timeout=10,
        )
    except Exception as exc:
        log.warning("quiz admin notify failed: %s", type(exc).__name__)


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
def auth_bot_callback(request: Request, state: str, next: str | None = None, session: Session = Depends(get_session)):
    """Завершение deep-link авторизации. Бот уже записал telegram_id для state.

    next — необязательная внутренняя страница, на которую кабинет откроется сразу
    после входа (например, курс-практикум). Разрешаем только локальные пути под
    /courses/, чтобы исключить open-redirect."""
    rec = session.get(LoginSession, state)
    expired = rec is not None and datetime.utcnow() - rec.created_at > LOGIN_SESSION_TTL
    # Ссылка одноразовая. Повторный тап по той же кнопке (частый кейс в Telegram
    # Web App — кнопка остаётся в чате) не должен пугать сырым JSON «already used»:
    # если в этой сессии уже есть кука — просто открываем кабинет; иначе показываем
    # аккуратную страницу со свежей рабочей кнопкой входа.
    if rec is None or rec.consumed_at is not None or expired:
        if current_partner(request, session):
            return RedirectResponse("/dashboard", status_code=302)
        return _relogin_notice(request, session)
    if rec.telegram_id is None:
        raise HTTPException(status.HTTP_425_TOO_EARLY, "Click the button inside the bot first")

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


def _relogin_notice(request: Request, session: Session) -> HTMLResponse:
    """Дружелюбная заглушка вместо сырого JSON, когда одноразовая ссылка входа
    уже использована/протухла, а активной сессии нет. Сразу даёт свежий deep-link
    в бота — один тап возвращает партнёра в кабинет."""
    state = _fresh_login_state(session)
    return templates.TemplateResponse(
        "relogin.html", _ctx(request, None, state=state)
    )


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

    # Телефон больше не спрашиваем в онбординге: раз вошли по номеру — знаем его.
    # Проставляем в Partner.phone, если пуст (запасной канал WhatsApp-уведомлений).
    if not (partner.phone or "").strip():
        partner.phone = norm
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


# ─── Аккаунт: каналы входа (план 2026-06-02) ────────────────────────────────
# Один кабинет ↔ много каналов: Telegram (telegram_id) + номера (PartnerIdentity
# kind='phone'). Авторизованный агент добавляет ещё номер к СВОЕМУ кабинету —
# подтверждение кодом в WhatsApp. Так вход с Telegram и с WhatsApp ведёт в один
# и тот же кабинет (требование Николь 2026-06-02).
def _account_render(request: Request, session: Session, partner: Partner, **extra) -> HTMLResponse:
    phones = (session.query(PartnerIdentity)
              .filter_by(partner_id=partner.id, kind="phone").all())
    code = 400 if extra.pop("_bad", False) else 200
    return templates.TemplateResponse(
        "account.html", _ctx(request, partner, phones=phones, **extra), status_code=code)


@app.get("/account", response_class=HTMLResponse)
def account_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    partner = current_partner(request, session)
    if not partner:
        return RedirectResponse("/login", status_code=302)
    return _account_render(request, session, partner, code_sent=False, message=None)


@app.post("/account/phone/request", response_class=HTMLResponse)
def account_phone_request(request: Request, phone: str = Form(...),
                          session: Session = Depends(get_session)) -> HTMLResponse:
    partner = current_partner(request, session)
    if not partner:
        return RedirectResponse("/login", status_code=302)
    en = _lang(request) == "en"
    norm = normalize_phone(phone)
    if len(norm) < PHONE_MIN_DIGITS:
        return _account_render(request, session, partner, code_sent=False, _bad=True,
                               message=("The phone looks invalid." if en else "Номер выглядит некорректным."))
    other = find_partner_by_phone(session, norm)
    if other is not None and other.id != partner.id:
        return _account_render(request, session, partner, code_sent=False, _bad=True,
                               message=("This number is already linked to another account." if en
                                        else "Этот номер уже привязан к другому кабинету. Напишите менеджеру для объединения."))
    window = datetime.utcnow() - PHONE_CODE_TTL
    recent = (session.query(PhoneLoginToken)
              .filter(PhoneLoginToken.phone == norm, PhoneLoginToken.created_at >= window).count())
    if recent < PHONE_RATE_LIMIT:
        code = f"{secrets.randbelow(900_000) + 100_000}"
        session.add(PhoneLoginToken(phone=norm, code_hash=hash_login_code(code)))
        session.commit()
        send_wa_code(norm, code, _lang(request))
    return _account_render(request, session, partner, code_sent=True, code_phone=norm, message=None)


@app.post("/account/phone/verify", response_class=HTMLResponse)
def account_phone_verify(request: Request, phone: str = Form(...), code: str = Form(...),
                         session: Session = Depends(get_session)):
    partner = current_partner(request, session)
    if not partner:
        return RedirectResponse("/login", status_code=302)
    en = _lang(request) == "en"
    norm = normalize_phone(phone)
    code = (code or "").strip()
    bad = ("Code is invalid or expired." if en else "Код неверный или истёк.")
    rec = (session.query(PhoneLoginToken)
           .filter(PhoneLoginToken.phone == norm, PhoneLoginToken.consumed_at.is_(None))
           .order_by(PhoneLoginToken.created_at.desc()).first())
    if (rec is None or datetime.utcnow() - rec.created_at > PHONE_CODE_TTL
            or rec.attempts >= PHONE_CODE_MAX_ATTEMPTS):
        return _account_render(request, session, partner, code_sent=True, code_phone=norm, _bad=True, message=bad)
    rec.attempts += 1
    session.commit()
    if not verify_login_code(code, rec.code_hash):
        return _account_render(request, session, partner, code_sent=True, code_phone=norm, _bad=True, message=bad)
    rec.consumed_at = datetime.utcnow()
    session.commit()
    other = find_partner_by_phone(session, norm)
    if other is not None and other.id != partner.id:
        return _account_render(request, session, partner, code_sent=False, _bad=True,
                               message=("This number is already linked to another account." if en
                                        else "Этот номер уже привязан к другому кабинету."))
    if session.query(PartnerIdentity).filter_by(kind="phone", value=norm).first() is None:
        session.add(PartnerIdentity(kind="phone", value=norm, partner_id=partner.id))
    if not (partner.phone or "").strip():
        partner.phone = norm
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
    return RedirectResponse("/account", status_code=303)


# (slug, RU-подпись, EN-подпись) — шаблон онбординга выбирает подпись по lang.
SEGMENTS = [
    ("owner", "Владелец компании", "Company owner"),
    ("freelancer", "Фрилансер", "Freelancer"),
    ("employee", "Сотрудник компании", "Company employee"),
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
    email: str = Form(...),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    partner = current_partner(request, session)
    if not partner:
        return RedirectResponse("/login", status_code=302)

    segment = (segment or "").strip().lower()
    email = (email or "").strip().lower()
    en = _lang(request) == "en"

    if segment not in {s[0] for s in SEGMENTS}:
        msg = "Choose a segment from the list." if en else "Выбери сегмент из списка."
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

    # Телефон в форме больше не спрашиваем — он известен из входа по номеру
    # (auth_phone_verify проставляет Partner.phone). Здесь только роль + email.
    partner.segment = segment
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
    # После базового онбординга — сразу на анкету партнёра (Фаза L),
    # если она ещё не пройдена. Анкета мягкая: партнёр может «Пропустить».
    if partner.survey_completed_at is None:
        return RedirectResponse("/onboarding-survey", status_code=302)
    return RedirectResponse("/dashboard", status_code=302)


# ─── Анкета партнёра (Фаза L) ───────────────────────────────────────────────
# МЯГКАЯ форма: НЕ блокирует кабинет. Отдельный маршрут /onboarding-survey
# (НЕ трогаем блокирующий /onboarding, который собирает базовый контакт).
SURVEY_SNOOZE_COOKIE = "survey_snooze"  # «Позже»: прячет баннер на время


@app.get("/onboarding-survey", response_class=HTMLResponse)
def onboarding_survey_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    partner = current_partner(request, session)
    if not partner:
        return RedirectResponse("/login", status_code=302)
    info = partner_onboarding(partner, _lang(request))
    return templates.TemplateResponse(
        "onboarding_survey.html",
        _ctx(
            request, partner,
            options=SURVEY_OPTIONS,
            labels=SURVEY_LABELS,
            answers=info["answers"],   # предзаполнение при повторном входе
            completed=info["completed"],
            survey_draft=SURVEY_DRAFT,
            message=None,
        ),
    )


@app.post("/onboarding-survey", response_class=HTMLResponse)
def onboarding_survey_submit(
    request: Request,
    sphere: str = Form(""),
    sphere_other: str = Form(""),
    uae_experience: str = Form(""),
    b2b_flow: str = Form(""),
    b2b_volume: str = Form(""),
    base_size: str = Form(""),
    social_channels: list[str] = Form(default=[]),
    social_audience: str = Form(""),
    payout_method: str = Form(""),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    partner = current_partner(request, session)
    if not partner:
        return RedirectResponse("/login", status_code=302)
    en = _lang(request) == "en"

    def clean_other(v: str) -> str:
        return (v or "").strip()[:SURVEY_OTHER_MAXLEN]

    # Сборка ответов СТРОГО по белым спискам (всё вне списка отбрасывается).
    answers: dict = {}
    single = {
        "sphere": sphere, "uae_experience": uae_experience, "b2b_flow": b2b_flow,
        "base_size": base_size, "social_audience": social_audience,
        "payout_method": payout_method,
    }
    for field, val in single.items():
        val = (val or "").strip()
        if val and val in _survey_values(field):
            answers[field] = val
    # b2b_volume — только если поток есть (не "none").
    bv = (b2b_volume or "").strip()
    if answers.get("b2b_flow") in ("steady", "occasional") and bv in _survey_values("b2b_volume"):
        answers["b2b_volume"] = bv
    # Соцсети — мультивыбор; фильтруем по белому списку, режем дубли, порядок храним.
    allowed_ch = _survey_values("social_channels")
    chans = [c.strip() for c in social_channels if c and c.strip() in allowed_ch]
    seen: set[str] = set()
    chans = [c for c in chans if not (c in seen or seen.add(c))]
    # «Нет соцсетей» несовместимо с реальными каналами: если выбрано и то и то,
    # реальные каналы важнее — убираем "none" (иначе менеджер видит противоречие).
    if "none" in chans and len(chans) > 1:
        chans = [c for c in chans if c != "none"]
    if chans:
        answers["social_channels"] = chans
    # Свободный текст «other» — только если выбран соответствующий вариант.
    if answers.get("sphere") == "other":
        txt = clean_other(sphere_other)
        if txt:
            answers["sphere_other"] = txt

    # Серверная валидация обязательных вопросов.
    missing = [f for f in SURVEY_REQUIRED if f not in answers]
    if missing:
        msg = ("Please answer the required questions (marked *)."
               if en else "Пожалуйста, ответьте на обязательные вопросы (со звёздочкой *).")
        return templates.TemplateResponse(
            "onboarding_survey.html",
            _ctx(
                request, partner,
                options=SURVEY_OPTIONS, labels=SURVEY_LABELS,
                answers=answers,  # сохраняем введённое для повторного показа
                completed=partner.survey_completed_at is not None,
                survey_draft=SURVEY_DRAFT, message=msg,
            ),
            status_code=400,
        )

    partner.onboarding_answers = answers
    partner.survey_completed_at = datetime.utcnow()
    session.commit()
    # После заполнения снуз больше не нужен — баннер и так скрыт по completed.
    resp = RedirectResponse("/dashboard", status_code=302)
    resp.delete_cookie(SURVEY_SNOOZE_COOKIE)
    return resp


@app.post("/onboarding-survey/later")
def onboarding_survey_later(request: Request, session: Session = Depends(get_session)):
    """«Позже»: мягко прячет баннер-приглашение на неделю (cookie, БЕЗ записи в
    БД и без блокировки кабинета). Анкета остаётся доступной из шапки/ссылки."""
    partner = current_partner(request, session)
    if not partner:
        return RedirectResponse("/login", status_code=302)
    resp = RedirectResponse("/dashboard", status_code=302)
    resp.set_cookie(
        SURVEY_SNOOZE_COOKIE, "1",
        max_age=7 * 24 * 3600, httponly=True, secure=True, samesite="lax",
    )
    return resp


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
            "href": "/tools#intro",
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
    # Баннер-приглашение пройти анкету (Фаза L). Мягкий: виден, пока анкета не
    # пройдена И партнёр не нажал «Позже» (cookie-снуз). Не блокирует кабинет.
    show_survey_banner = (
        partner.survey_completed_at is None
        and request.cookies.get(SURVEY_SNOOZE_COOKIE) != "1"
    )

    # FAQ перенесён в самый низ дашборда (раньше — отдельная страница /faq).
    faq_items = (
        session.query(FaqItem)
        .filter_by(is_active=True)
        .order_by(FaqItem.category, FaqItem.order_index)
        .all()
    )
    faq_categories: dict[str, list[FaqItem]] = {}
    for item in faq_items:
        faq_categories.setdefault(item.category, []).append(item)

    # ── Блок «Сообщество» — КУРАТОРСКАЯ соц-витрина: фиксированные цифры и имена,
    # утверждённые Николь (это НЕ живые данные из БД). Цель — соц-доказательство
    # масштаба партнёрской сети. В топе — только имя, по убыванию числа контактов.
    community = {
        "partners": 139,
        "total_contacts": 187,  # ⚠️ значение на подтверждении Николь
        "top": [
            {"name": "Евгений", "count": 45},
            {"name": "Ильяс", "count": 28},
            {"name": "Даниил", "count": 21},
            {"name": "Мари", "count": 16},
            {"name": "Ольга", "count": 12},
        ],
    }

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
            show_survey_banner=show_survey_banner,
            faq_categories=faq_categories,
            community=community,
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
    return templates.TemplateResponse(
        "leads.html",
        _ctx(request, partner, rows=rows, kpi=_balance_kpi(session, partner)),
    )


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


@app.get("/tools", response_class=HTMLResponse)
def tools(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    """Раздел «Инструменты → Тексты и ссылки» (переборка 2026-06-02): вкладки =
    СПОСОБЫ привлечения (METHODS), а не «ссылки/тексты/кит». Каждый блок
    самодостаточен: фильтр «для кого» + персональная ссылка + готовые тексты со
    вшитой (плейсхолдер {link}) персональной ссылкой. Ось partner_type как
    группировка убрана. directlinks — особый блок: карточки персональных ссылок.
    Глубокий вход по #broadcast/#social/#event/#leadmagnet/#intro/#directlinks;
    старые якоря #links/#messages/#kits мапятся на клиенте (LEGACY_TOOL_ANCHORS).
    """
    partner = current_partner(request, session)
    if not partner:
        return RedirectResponse("/login", status_code=302)
    # Чек-лист дашборда: «скопируй ссылку» = факт открытия инструментов.
    if partner.links_viewed_at is None:
        partner.links_viewed_at = datetime.utcnow()
        session.commit()

    ref = partner.ref_slug
    base = str(request.base_url).rstrip("/")
    links = _personal_links(ref, base)

    # Все активные тексты с непустым method, сгруппированы по способу. Порядок
    # внутри способа — order_index, id. Тексты без method (NULL) не показываем.
    rows = (
        session.query(MessageTemplate)
        .filter(MessageTemplate.is_active.is_(True))
        .filter(MessageTemplate.method.isnot(None))
        .order_by(MessageTemplate.method, MessageTemplate.order_index, MessageTemplate.id)
        .all()
    )
    method_groups: dict[str, list] = {}
    for it in rows:
        method_groups.setdefault(it.method, []).append(it)

    # Контакт партнёрского менеджера для CTA вкладки «События» (написать о
    # совместном мероприятии). Берём подтверждённый WhatsApp из PARTNER_MANAGER
    # (единый источник), fallback — общий контакт. Цифры номера: ссылку
    # wa.me + предзаполненный текст шаблон строит сам.
    manager_wa = next(
        (c["value"] for c in PARTNER_MANAGER["contacts"]
         if c["channel"] == "whatsapp" and c.get("confirmed")),
        settings.CONTACT_WA_NUMBER,
    )

    return templates.TemplateResponse(
        "tools.html",
        _ctx(
            request,
            partner,
            ref_slug=ref,
            methods_order=METHODS_ORDER,
            method_groups=method_groups,
            links=links,
            manager_wa=manager_wa,
            accountants=ACCOUNTANTS,
            kpi=_balance_kpi(session, partner),
        ),
    )


# Старые URL → объединённая страница (бот /links, /messages и закладки живут).
# Якоря переехали на способы (план 2026-06-02): ссылки теперь во вкладке intro.
@app.get("/links")
def links_redirect() -> RedirectResponse:
    return RedirectResponse("/tools#intro", status_code=302)


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
    client_phone: str = Form(...),
    task_description: str = Form(...),
    do_not_offer: str = Form(...),
    client_telegram: str = Form(""),
    company_name: str = Form(""),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    partner = current_partner(request, session)
    if not partner:
        return RedirectResponse("/login", status_code=302)

    client_name_v = client_name.strip()
    client_phone_v = client_phone.strip()
    task_v = task_description.strip()
    do_not_offer_v = do_not_offer.strip()
    client_telegram_v = client_telegram.strip()
    company_name_v = company_name.strip()

    lead = Lead(
        partner_id=partner.id,
        client_name=client_name_v,
        client_phone=client_phone_v,
        client_telegram=client_telegram_v or None,
        company_name=company_name_v or None,
        task_description=task_v,
        do_not_offer=do_not_offer_v,
        status="new",
    )
    session.add(lead)
    session.commit()

    # Уведомление в Telegram Николь (ADMIN_TG_ID). Менеджер заносит в Kommo
    # вручную (решение 2026-06-01). Лид уже в БД — если TG упал, ничего не
    # теряем: партнёр видит /leads, менеджер получит на следующей попытке.
    # ПД клиента летят во внутренний канал (свой бот → личка владельца), как
    # уже делает app/bot.py для ТГ-флоу.
    if settings.BOT_TOKEN and settings.ADMIN_TG_ID:
        partner_label = (
            (partner.first_name or "").strip()
            or (partner.kommo_agent_name or "").strip()
            or (partner.phone or "").strip()
            or (partner.email or "").strip()
            or f"#{partner.id}"
        )
        lines = [
            "🆕 Новый клиент от партнёра",
            f"Партнёр: {partner_label}",
            f"Телефон: {client_phone_v}",
            f"Имя клиента: {client_name_v}",
            f"Услуга: {task_v}",
            f"Что НЕ предлагать: {do_not_offer_v}",
        ]
        if client_telegram_v:
            lines.append(f"Telegram: {client_telegram_v}")
        if company_name_v:
            lines.append(f"Компания: {company_name_v}")
        try:
            httpx.post(
                f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage",
                json={"chat_id": settings.ADMIN_TG_ID, "text": "\n".join(lines)},
                timeout=10,
            )
        except Exception as e:
            # НЕ логируем ПД клиента — только тип ошибки.
            log.warning("/transfer telegram notify failed: %s", type(e).__name__)

    msg = (
        "Client referred. A manager will be in touch within an hour during business hours (9:00–18:00 Dubai time)."
        if _lang(request) == "en"
        else "Клиент передан. Менеджер свяжется в течение часа в рабочее время с 9-18.00 дубай."
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
    return templates.TemplateResponse(
        "products.html",
        _ctx(request, partner, items=items, kpi=_balance_kpi(session, partner)),
    )


# Тексты рассылок и партнёрский кит объединены в /tools (вкладки). Старые URL
# редиректят на соответствующий якорь — bot.py /messages и закладки не ломаем.
@app.get("/messages")
def messages_redirect() -> RedirectResponse:
    return RedirectResponse("/tools#broadcast", status_code=302)


@app.get("/kits")
def kits_redirect() -> RedirectResponse:
    return RedirectResponse("/tools#intro", status_code=302)


# FAQ переехал в самый низ дашборда. Старые ссылки (/faq, /kb/faq, футер бота)
# редиректим на якорь #faq, чтобы ничего не сломалось.
@app.get("/faq")
@app.get("/kb/faq")
def faq() -> RedirectResponse:
    return RedirectResponse("/dashboard#faq", status_code=302)


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
