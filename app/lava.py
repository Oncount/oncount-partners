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

# Что бот предлагает купить: код → (id оффера, как назвать человеку).
# «Под ключ» здесь намеренно нет: он продаётся в личном разговоре, а не кнопкой.
PRODUCTS: dict[str, tuple[str, str]] = {
    "first_day": (OFFER_FIRST_DAY, "Первый день — соберём вам ассистента"),
    "intensive": (OFFER_INTENSIVE, "Весь интенсив — 12 встреч"),
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
                   offer_id: str = OFFER_INTENSIVE) -> dict | None:
    """Выставить счёт на тариф «Интенсив» конкретному человеку.

    Возвращает {'id': ..., 'url': ...} либо None. email обязателен на стороне
    Lava — это же адрес, на который придёт чек, поэтому спрашиваем его у человека,
    а не подставляем служебный.
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
        "periodicity": "ONE_TIME",   # интенсив — разовая покупка, не подписка
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
        return {"id": str(inv_id), "url": url}
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
                    return (not status) or status in paid_states
    except Exception as exc:
        log.warning("lava sales error: %s", type(exc).__name__)
    return False


def check_offers() -> list[str]:
    """Сверить, что зашитые id указывают на те офферы, за которые мы их держим.

    Появилась после 04.08.2026: в кассе переименовали оффер, не меняя id, и бот
    сутки продавал интенсив по цене первого дня. Возвращает список расхождений
    (пустой — всё в порядке); вызывается при старте бота.
    """
    if not is_configured():
        return []
    expect = {OFFER_FIRST_DAY: "перв", OFFER_INTENSIVE: "интенсив", OFFER_DFY: "ключ"}
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
