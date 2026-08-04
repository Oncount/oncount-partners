"""Клиент Lava (gate.lava.top) — выставление счёта и проверка оплаты.

План: plans/2026-08-03-bot-oplat-intensiva.md, Фаза 2.

Зачем именно персональный счёт, а не общая ссылка на витрину: по общей ссылке
приходит платёж «от кого-то», и «кто из Ивановых оплатил» приходится выяснять
по выписке. Счёт, созданный под конкретного человека, возвращает id, по которому
статус проверяется однозначно — на этом держится автовыдача доступа в чат.

Проверено вживую 03.08.2026:
- `GET /api/v2/products?feedVisibility=ALL` → 200. ⚠️ БЕЗ `feedVisibility=ALL`
  наш продукт НЕ возвращается: легко решить, что его в Lava нет.
- `GET /api/v1/sales` → 200 (продажи), `GET /api/v1/invoices` → 200 (счета).
- Оффер «Интенсив: AI Бизнес-ассистент» = 85dc8277-8980-4cb1-9fd1-ab4ed12215fb,
  цены 375.00 USD / 324.71 EUR / 29711.66 RUB (после того, как комиссию 8%
  переложили на нас — раньше клиент видел эквивалент $407 при цене лендинга $375).

Безопасность: ключ берётся ТОЛЬКО из окружения (LAVA_API_KEY), в код не попадает.
Все ошибки сети/API проглатываются и логируются — платёжный контур не должен
ронять бота; при недоступности Lava остаётся ручное подтверждение (Фаза 5).
"""
from __future__ import annotations

import logging

import httpx

from app.config import settings

log = logging.getLogger("oncount.lava")

BASE_URL = "https://gate.lava.top"

# Офферы в кассе. Правило репо №1: id живут здесь, не в хендлерах бота.
#
# ⚠️ ГРАБЛЯ 04.08.2026: id `85dc8277…` раньше был «Интенсив» за $375, а Николь
# ПЕРЕИМЕНОВАЛА его в «Первый день» и поставила $20 — id при этом не изменился.
# Бот продолжал считать его интенсивом и сутки выставлял счета на $20 вместо
# полной программы. Отсюда правило: после любых правок в кассе сверять НЕ ТОЛЬКО
# цену, но и то, что id по-прежнему указывает на нужный оффер (`check_offers`).
OFFER_FIRST_DAY = "85dc8277-8980-4cb1-9fd1-ab4ed12215fb"   # «Первый день», $20
OFFER_INTENSIVE = "2449b65d-b100-4d76-8d0b-c0dd4882e53e"   # «Интенсив», $1000
OFFER_DFY = "effe38ce-e866-46d0-89ab-5397e94f66ec"         # «Под ключ», $2500

# Подписка на клуб — ОТДЕЛЬНЫЙ продукт (`Subscription nikol_hillton`), не оффер
# внутри интенсива. Тип SUBSCRIPTION: счёт создаётся с периодичностью, дальше
# Lava списывает сама.
OFFER_CLUB = "ff7ec308-8ec2-44df-a3f5-41ce5a23b799"

# Периоды подписки: код → (значение для API, сколько дней даём доступ).
#
# ⚠️ ГЛАВНАЯ ГРАБЛЯ КЛУБА (проверено 04.08.2026): `GET /api/v2/products` отдаёт
# у этого оффера ТОЛЬКО цену MONTHLY, и по одному этому ответу кажется, что
# квартала и полугодия нет. Они есть: счёт с PERIOD_90_DAYS / PERIOD_180_DAYS
# создаётся на тот же offerId и возвращает верную сумму. Заводить отдельные
# офферы не нужно — и не надо, увидев один MONTHLY, «чинить» это в кассе.
#
# Дней даём чуть больше календарного периода (31/92/183): человек платит утром,
# а списание проходит вечером — сутки запаса дешевле, чем выгнать платящего.
CLUB_PERIODS: dict[str, tuple[str, int]] = {
    "month": ("MONTHLY", 31),
    "quarter": ("PERIOD_90_DAYS", 92),
    "half": ("PERIOD_180_DAYS", 183),
    "year": ("PERIOD_YEAR", 366),
}

# Допустимые значения periodicity — из ответа самой Lava на неверное значение:
# ONE_TIME, MONTHLY, PERIOD_90_DAYS, PERIOD_180_DAYS, PERIOD_YEAR.
PERIODICITY_ONE_TIME = "ONE_TIME"

# Что бот предлагает купить: код → (id оффера, как назвать человеку).
# «Под ключ» здесь намеренно нет: он продаётся в личном разговоре, а не кнопкой.
PRODUCTS: dict[str, tuple[str, str]] = {
    # Слова те же, что на лендинге: человек приходит с кнопки «курс», и увидеть
    # в боте «интенсив» — повод засомневаться, то ли он покупает. Код продукта
    # (`intensive`) не трогаем: он уже лежит в `intensive_leads.product_code`.
    "first_day": (OFFER_FIRST_DAY, "Первый день — соберём вам ассистента"),
    "intensive": (OFFER_INTENSIVE, "Весь курс — 12 встреч"),
}

# Валюты, которые Lava принимает для этого оффера. RUB и EUR видны на витрине,
# USD есть только через API — в боте предлагаем все три.
CURRENCIES: tuple[str, ...] = ("RUB", "EUR", "USD")

# Человеческие подписи валют для кнопок бота (цены подтягиваются из API, не хардкод).
CURRENCY_LABELS = {"RUB": "₽ рубли", "EUR": "€ евро", "USD": "$ доллары"}

# Способ оплаты у Lava ЗАВИСИТ ОТ ВАЛЮТЫ (документация lava.top): рубли проводит
# BANK131, евро и доллары — UNLIMINT (также бывают STRIPE/PAYPAL). Один
# BANK131 на все валюты, как казалось сначала, дал бы отказ на EUR/USD.
CURRENCY_METHOD = {"RUB": "BANK131", "EUR": "UNLIMINT", "USD": "UNLIMINT"}

_TIMEOUT = 25


def _key() -> str | None:
    return getattr(settings, "LAVA_API_KEY", "") or None


def _headers() -> dict:
    return {"X-Api-Key": _key() or "", "Content-Type": "application/json"}


def is_configured() -> bool:
    """Ключ на месте? Без него бот работает, но оплату подтверждает человек."""
    return bool(_key())


def offer_prices(offer_id: str = OFFER_INTENSIVE) -> dict[str, float]:
    """Актуальные цены оффера из Lava: {'RUB': 80400.0, ...}.

    Тянем из API, а не храним у себя: цену меняют в кассе, и расхождение между
    тем, что человек видит в боте, и тем, что просит касса, — прямой путь к
    спору с человеком, который уже заплатил. Пустой словарь = Lava недоступна.
    """
    if not is_configured():
        return {}
    try:
        r = httpx.get(f"{BASE_URL}/api/v2/products", headers=_headers(),
                      params={"feedVisibility": "ALL"}, timeout=_TIMEOUT)
        if r.status_code != 200:
            log.warning("lava products http=%s", r.status_code)
            return {}
        for product in r.json().get("items", []):
            for offer in product.get("offers", []):
                if offer.get("id") == offer_id:
                    return {p["currency"]: float(p["amount"])
                            for p in offer.get("prices", []) if p.get("currency")}
        log.warning("lava: оффер %s не найден (проверьте feedVisibility)", offer_id)
    except Exception as exc:  # сеть/формат — не валим бота
        log.warning("lava products error: %s", type(exc).__name__)
    return {}


def create_invoice(email: str, currency: str = "RUB",
                   offer_id: str = OFFER_INTENSIVE,
                   periodicity: str = PERIODICITY_ONE_TIME) -> dict | None:
    """Выставить счёт конкретному человеку.

    Возвращает {'id': ..., 'url': ..., 'amount': ..., 'currency': ...} либо None.
    email обязателен на стороне Lava — это же адрес, на который придёт чек,
    поэтому спрашиваем его у человека, а не подставляем служебный.

    `periodicity`: ONE_TIME для разовых покупок (интенсив), MONTHLY /
    PERIOD_90_DAYS / PERIOD_180_DAYS для подписки на клуб. Сумму Lava считает
    сама и возвращает в ответе — её и показываем человеку, чтобы бот и касса не
    разошлись в цене.
    """
    if not is_configured():
        return None
    if currency not in CURRENCIES:
        currency = "RUB"
    payload = {
        "email": email,
        "offerId": offer_id,
        "currency": currency,
        "paymentMethod": CURRENCY_METHOD[currency],
        "periodicity": periodicity,
        "buyerLanguage": "RU",
    }
    try:
        r = httpx.post(f"{BASE_URL}/api/v2/invoice", headers=_headers(),
                       json=payload, timeout=_TIMEOUT)
        if r.status_code not in (200, 201):
            # Тело ответа Lava — техническое, ПД в нём нет; логируем, чтобы было
            # что показать поддержке при разборе.
            log.error("lava invoice http=%s body=%s", r.status_code, r.text[:300])
            return None
        data = r.json()
        inv_id = data.get("id") or data.get("invoiceId")
        url = data.get("paymentUrl") or data.get("url")
        if not (inv_id and url):
            log.error("lava invoice: в ответе нет id/url, ключи=%s", list(data)[:8])
            return None
        # Сумма, которую касса реально попросит. Для подписки это единственный
        # способ узнать цену периода: в /products лежит только MONTHLY.
        total = data.get("amountTotal") or {}
        amount = total.get("amount") if isinstance(total, dict) else None
        return {"id": str(inv_id), "url": url,
                "amount": float(amount) if amount is not None else None,
                "currency": (total.get("currency") if isinstance(total, dict)
                             else None) or currency}
    except Exception as exc:
        log.error("lava invoice error: %s", type(exc).__name__)
        return None


def invoice_paid(invoice_id: str) -> bool:
    """Счёт оплачен? Спрашиваем Lava, а не верим человеку на слово.

    Идём двумя путями, потому что формат ответа у Lava исторически плавал:
    сначала прямой запрос счёта, затем поиск в списке продаж. Любая ошибка —
    False (лучше не выдать доступ и разобрать вручную, чем выдать по ошибке).
    """
    if not (is_configured() and invoice_id):
        return False
    paid_states = {"completed", "paid", "success", "subscription-active"}
    try:
        r = httpx.get(f"{BASE_URL}/api/v1/invoices/{invoice_id}",
                      headers=_headers(), timeout=_TIMEOUT)
        if r.status_code == 200:
            status = str(r.json().get("status", "")).lower()
            if status:
                return status in paid_states
    except Exception as exc:
        log.warning("lava invoice status error: %s", type(exc).__name__)

    # Фолбэк: ищем счёт среди продаж.
    try:
        r = httpx.get(f"{BASE_URL}/api/v1/sales", headers=_headers(),
                      params={"size": 100}, timeout=_TIMEOUT)
        if r.status_code == 200:
            for item in r.json().get("items", []):
                ident = str(item.get("id") or item.get("invoiceId") or "")
                if ident == str(invoice_id):
                    status = str(item.get("status", "")).lower()
                    if not status:
                        # Раньше здесь стояло «нет статуса — считаем оплаченным».
                        # Это выдача доступа по молчанию кассы: любой ответ
                        # неожиданного формата открывал бы платный продукт. Не
                        # знаем — значит не оплачено, разберём руками.
                        log.warning("lava sales: у счёта нет статуса — "
                                    "оплаченным не считаю")
                        return False
                    return status in paid_states
    except Exception as exc:
        log.warning("lava sales error: %s", type(exc).__name__)
    return False


def subscriptions() -> list[dict] | None:
    """Активные подписки из кассы — источник правды по продлениям клуба.

    None означает «Lava не ответила» и это НЕ то же самое, что пустой список:
    молчание кассы никогда не должно приводить к удалению из канала (план
    2026-08-04, принцип 4). Пустой список — «подписок действительно нет».

    ⚠️ Формат ответа на 04.08.2026 не проверен на живых данных: подписок в кассе
    ещё не было (`total: 0`). Поэтому при первой же записи логируем НАБОР КЛЮЧЕЙ
    (не значения — там ПД покупателя), чтобы разбор поля «оплачено до» не
    пришлось угадывать.
    """
    if not is_configured():
        return None
    collected: list[dict] = []
    try:
        page, total = 1, None
        while True:
            r = httpx.get(f"{BASE_URL}/api/v1/subscriptions", headers=_headers(),
                          params={"size": 100, "page": page}, timeout=_TIMEOUT)
            if r.status_code != 200:
                log.warning("lava subscriptions http=%s", r.status_code)
                return None
            data = r.json()
            items = data.get("items", [])
            collected.extend(items)
            total = data.get("total", total)
            if page == 1 and items and isinstance(items[0], dict):
                log.info("lava subscriptions: total=%s, ключи записи=%s",
                         total, sorted(items[0].keys())[:20])
            # Страницы обходим до конца. Со 101-го подписчика «первая страница»
            # означала бы, что все остальные для бота не существуют — то есть
            # платящих начали бы выгонять из канала.
            if not items or (total is not None and len(collected) >= int(total)) \
                    or page >= 20:
                break
            page += 1
        if total is not None and len(collected) < int(total):
            # Не собрали всё — работать с обрывком опаснее, чем не работать.
            log.warning("lava subscriptions: собрано %s из %s — считаю ответ "
                        "недостоверным", len(collected), total)
            return None
        return collected
    except Exception as exc:  # noqa: BLE001 — сеть/формат: молчание, не пустота
        log.warning("lava subscriptions error: %s", type(exc).__name__)
        return None


def check_offers() -> list[str]:
    """Сверить, что зашитые id указывают на те офферы, за которые мы их держим.

    Появилась после 04.08.2026: в кассе переименовали оффер, не меняя id, и бот
    сутки продавал интенсив по цене первого дня. Возвращает список расхождений
    (пустой — всё в порядке); вызывается при старте бота.
    """
    if not is_configured():
        return []
    expect = {OFFER_FIRST_DAY: "перв", OFFER_INTENSIVE: "интенсив", OFFER_DFY: "ключ",
              OFFER_CLUB: "клуб"}
    problems: list[str] = []
    try:
        r = httpx.get(f"{BASE_URL}/api/v2/products", headers=_headers(),
                      params={"feedVisibility": "ALL"}, timeout=_TIMEOUT)
        if r.status_code != 200:
            return [f"касса недоступна (http {r.status_code})"]
        found = {o["id"]: o.get("name", "") for p in r.json().get("items", [])
                 for o in p.get("offers", [])}
        for oid, marker in expect.items():
            name = found.get(oid)
            if name is None:
                problems.append(f"оффер {oid[:8]}… пропал из кассы")
            elif marker not in name.lower():
                problems.append(f"оффер {oid[:8]}… теперь называется {name!r} — "
                                f"ожидали «{marker}»")
    except Exception as exc:  # noqa: BLE001
        return [f"сверка офферов не удалась: {type(exc).__name__}"]
    return problems
