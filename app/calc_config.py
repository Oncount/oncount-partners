"""Калькулятор партнёрского вознаграждения — блок #calc на дашборде.

Единственный источник цифр: тарифы бухгалтерии, разовые услуги и вознаграждение
по каждой. В шаблоне и в JS цифр нет — они приезжают отсюда (правило репо №1:
динамику не хардкодим).

Решения Николь 2026-07-23:
- Комиссия по бухгалтерии = один месяц обслуживания по тарифу:
  NEW 550, START 1 450, GROW 3 100, PROFI 4 563 AED; PROFI+ — индивидуально.
- Всё в дирхамах. Долларовые суммы разовых услуг пересчитаны по фиксированному
  курсу USD→AED 3,6725 с округлением ВНИЗ до десятков: партнёру не обещаем
  больше, чем платим ($300 → 1 100, $600 → 2 200, $1 000 → 3 670).
"""

USD_AED = 3.6725


def usd_to_aed(usd: int) -> int:
    """Доллары → дирхамы, округление вниз до десятков (в пользу компании)."""
    return int(usd * USD_AED // 10 * 10)


# ── Тарифы бухгалтерии ───────────────────────────────────────────────────────
# max_tx — верхняя граница транзакций в месяц; у PROFI+ границы нет (None).
# «Что входит» — три группы: каждый месяц / каждый квартал / каждый год.
# Источник состава: .business/products/pricing.md, .business/knowledge/ceny-buhgalteriya.md.

_QUARTERLY = [
    "Отчёт по НДС (VAT report)",
    "Отчёт о движении денежных средств",
    "Акт сверки взаиморасчётов",
    "Отчёт по дебиторской и кредиторской задолженности",
]
_QUARTERLY_EN = [
    "VAT report",
    "Cash flow statement",
    "Reconciliation statement",
    "Accounts receivable and payable report",
]
_YEARLY = [
    "Отчёт по корпоративному налогу",
    "Бухгалтерский баланс (Balance sheet)",
    "Отчёт о прибылях и убытках (P&L)",
    "Отчёт о движении денежных средств за год",
    "Годовая сверка взаиморасчётов",
]
_YEARLY_EN = [
    "Corporate tax return",
    "Balance sheet",
    "Profit and loss statement (P&L)",
    "Annual cash flow statement",
    "Annual reconciliation of settlements",
]


TARIFFS = [
    {
        "key": "new",
        "name": "NEW",
        "max_tx": 10,
        "commission_aed": 550,
        "range": "до 10 транзакций в месяц",
        "range_en": "up to 10 transactions a month",
        "monthly": [
            "Ведение учёта до 10 транзакций",
            "Онлайн-чат с бухгалтером, ответ в течение 24 часов",
            "Хранение документов",
        ],
        "monthly_en": [
            "Bookkeeping for up to 10 transactions",
            "Online chat with an accountant, reply within 24 hours",
            "Document storage",
        ],
        "quarterly": [],
        "quarterly_en": [],
        "yearly": [],
        "yearly_en": [],
        "note": "",
        "note_en": "",
    },
    {
        "key": "start",
        "name": "START",
        "max_tx": 50,
        "commission_aed": 1450,
        "range": "до 50 транзакций в месяц",
        "range_en": "up to 50 transactions a month",
        "monthly": [
            "Ведение учёта до 50 транзакций",
            "Безлимитные инвойсы",
            "Загрузка документов в Google Drive",
            "Безлимитные платежи в банке",
            "Консультация с бухгалтером 60 минут — раз в месяц",
            "Payroll и трудовые договоры до 3 сотрудников",
        ],
        "monthly_en": [
            "Bookkeeping for up to 50 transactions",
            "Unlimited invoices",
            "Document upload to Google Drive",
            "Unlimited bank payments",
            "A 60-minute consultation with an accountant once a month",
            "Payroll and employment contracts for up to 3 employees",
        ],
        "quarterly": _QUARTERLY,
        "quarterly_en": _QUARTERLY_EN,
        "yearly": _YEARLY,
        "yearly_en": _YEARLY_EN,
        "note": "Хит продаж. Корпоративный налог и НДС уже включены.",
        "note_en": "Best seller. Corporate tax and VAT are already included.",
    },
    {
        "key": "grow",
        "name": "GROW",
        "max_tx": 120,
        "commission_aed": 3100,
        "range": "до 120 транзакций в месяц",
        "range_en": "up to 120 transactions a month",
        "monthly": [
            "Ведение учёта до 120 транзакций",
            "Всё из START",
            "Payroll и трудовые договоры до 10 сотрудников",
        ],
        "monthly_en": [
            "Bookkeeping for up to 120 transactions",
            "Everything from START",
            "Payroll and employment contracts for up to 10 employees",
        ],
        "quarterly": _QUARTERLY,
        "quarterly_en": _QUARTERLY_EN,
        "yearly": _YEARLY,
        "yearly_en": _YEARLY_EN,
        "note": "Корпоративный налог и НДС уже включены.",
        "note_en": "Corporate tax and VAT are already included.",
    },
    {
        "key": "profi",
        "name": "PROFI",
        "max_tx": 200,
        "commission_aed": 4563,
        "range": "до 200 транзакций в месяц",
        "range_en": "up to 200 transactions a month",
        "monthly": [
            "Ведение учёта до 200 транзакций",
            "Всё из GROW",
            "Payroll и трудовые договоры до 20 сотрудников",
        ],
        "monthly_en": [
            "Bookkeeping for up to 200 transactions",
            "Everything from GROW",
            "Payroll and employment contracts for up to 20 employees",
        ],
        "quarterly": _QUARTERLY,
        "quarterly_en": _QUARTERLY_EN,
        "yearly": _YEARLY,
        "yearly_en": _YEARLY_EN,
        "note": "Корпоративный налог и НДС уже включены.",
        "note_en": "Corporate tax and VAT are already included.",
    },
    {
        "key": "profi_plus",
        "name": "PROFI+",
        "max_tx": None,
        # Решение Николь 2026-07-23: показываем нижнюю границу «более 8 000 AED»
        # (is_min), точную сумму считает менеджер после встречи с клиентом.
        "commission_aed": 8000,
        "is_min": True,
        "range": "свыше 200 транзакций в месяц",
        "range_en": "more than 200 transactions a month",
        "monthly": [
            "Полностью кастомный пакет под объём клиента",
            "Всё из PROFI",
            "Payroll и трудовые договоры до 30 сотрудников",
        ],
        "monthly_en": [
            "A fully custom package built around the client's volume",
            "Everything from PROFI",
            "Payroll and employment contracts for up to 30 employees",
        ],
        "quarterly": _QUARTERLY,
        "quarterly_en": _QUARTERLY_EN,
        "yearly": _YEARLY,
        "yearly_en": _YEARLY_EN,
        "note": "Цена и вознаграждение считаются индивидуально — обсудите с менеджером.",
        "note_en": "Price and reward are calculated individually — talk to your manager.",
    },
]

# ── Разовые услуги ───────────────────────────────────────────────────────────
# is_from — вознаграждение «от» (точная сумма зависит от объёма работы).
# Количество (−/+) есть у каждой услуги — см. строки .calc-qty в шаблоне.
SERVICES = [
    {
        "key": "audit",
        "label": "Аудит",
        "label_en": "Audit",
        "hint": "Отчётность проверяет лицензированный аудитор ОАЭ",
        "hint_en": "Statements audited by a licensed UAE auditor",
        "commission_aed": usd_to_aed(300),
        "is_from": True,
    },
    {
        "key": "company",
        "label": "Открытие компании",
        "label_en": "Company setup",
        "hint": "Мейнленд или фризона",
        "hint_en": "Mainland or free zone",
        "commission_aed": usd_to_aed(1000),
        "is_from": False,
    },
    {
        "key": "corp_account",
        "label": "Корпоративный счёт",
        "label_en": "Corporate bank account",
        "hint": "NBD, Wio, FAB, ADCB",
        "hint_en": "NBD, Wio, FAB, ADCB",
        "commission_aed": usd_to_aed(1000),
        "is_from": False,
    },
    {
        "key": "work_visa",
        "label": "Рабочая виза",
        "label_en": "Work visa",
        "hint": "Резидентская виза сотрудника или владельца",
        "hint_en": "Residence visa for an employee or owner",
        "commission_aed": usd_to_aed(300),
        "is_from": False,
    },
    {
        "key": "property_visa",
        "label": "Виза за недвижимость",
        "label_en": "Property visa",
        "hint": "Золотая, серебряная, зелёная",
        "hint_en": "Golden, silver, green",
        "commission_aed": usd_to_aed(600),
        "is_from": False,
    },
    {
        "key": "personal_account",
        "label": "Личный счёт нерезидента",
        "label_en": "Personal account for non-residents",
        "hint": "NBD, без резидентства и Emirates ID",
        "hint_en": "NBD, no residency or Emirates ID required",
        "commission_aed": usd_to_aed(1000),
        "is_from": False,
    },
]

QTY_MAX = 20  # потолок счётчика — дальше это уже разговор с менеджером


# ── «Что входит в тарифы» — общий список тремя группами (решение Николь
# 2026-07-23): месяц / квартал / год, без вложенных свёрток по тарифам.
# Состав — START и выше; NEW описан отдельной строкой-примечанием.
INCLUDES = {
    "monthly": [
        "Ведение бухгалтерского учёта — объём транзакций по тарифу",
        "Безлимитные инвойсы",
        "Загрузка документов в Google Drive",
        "Безлимитные платежи в банке",
        "Консультация с бухгалтером 60 минут — раз в месяц",
        "Payroll и трудовые договоры: START до 3, GROW до 10, PROFI до 20, PROFI+ до 30 сотрудников",
    ],
    "monthly_en": [
        "Bookkeeping — transaction volume per plan",
        "Unlimited invoices",
        "Document upload to Google Drive",
        "Unlimited bank payments",
        "A 60-minute consultation with an accountant once a month",
        "Payroll and employment contracts: START up to 3, GROW up to 10, PROFI up to 20, PROFI+ up to 30 employees",
    ],
    "quarterly": _QUARTERLY,
    "quarterly_en": _QUARTERLY_EN,
    "yearly": _YEARLY,
    "yearly_en": _YEARLY_EN,
    "note": "Тариф NEW — минимальный: ведение до 10 транзакций, онлайн-чат с бухгалтером и хранение документов.",
    "note_en": "The NEW plan is minimal: bookkeeping for up to 10 transactions, online chat with an accountant and document storage.",
}


def _localize(row: dict, lang: str, fields: tuple[str, ...]) -> dict:
    """Русская запись → запись под нужный язык: поле_en при lang=en, иначе поле."""
    out = {k: v for k, v in row.items() if not k.endswith("_en")}
    if lang == "en":
        for f in fields:
            if row.get(f + "_en"):
                out[f] = row[f + "_en"]
    return out


def calc_data(lang: str = "ru") -> dict:
    """Данные калькулятора под язык — уезжают в шаблон и в JS одним объектом."""
    tariff_fields = ("range", "monthly", "quarterly", "yearly", "note")
    service_fields = ("label", "hint")
    return {
        "tariffs": [_localize(t, lang, tariff_fields) for t in TARIFFS],
        "services": [_localize(s, lang, service_fields) for s in SERVICES],
        "includes": _localize(INCLUDES, lang, ("monthly", "quarterly", "yearly", "note")),
        # Курс для долларовой суммы справа от итога (решение Николь 2026-07-23):
        # доллары округляем вниз — не обещаем больше, чем платим.
        "usd_rate": USD_AED,
        "qty_max": QTY_MAX,
    }
