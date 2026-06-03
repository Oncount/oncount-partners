"""Снимок комиссий партнёров из Google-таблицы (источник истины выплат).

Лист: https://docs.google.com/spreadsheets/d/1VFoYbUp3_WsVS5pWfzgy8w0IMeqUG0HBL6CCAHjpLDE
Тянуть живьём нельзя (CSV-экспорт отдаёт 401 без Google-авторизации), поэтому
держим СНИМОК — ровно как WON_BACKFILL в kommo_sync.py собран из этого же листа.
Регенерировать вручную при изменении листа: прочитать лист через Google Drive MCP
и пересобрать ROWS (колонка Lid → kommo_lead_id, колонка Fee AED → fee).

Один лид может иметь НЕСКОЛЬКО платежей (разные инвойсы) — храним строками, в
карточке агента показываем раздельно (решение Николь 2026-06-03: «разные платежи»).
status: paid = «комиссия оплачена»; onboarding = «онбординг прошёл» (ждёт выплаты);
not_rendered = «услуга не оказана / возврат».
"""
from collections import defaultdict

# (kommo_lead_id, fee_aed, status, client_label)
ROWS: list[tuple[int, int, str, str]] = [
    (15004438, 1338, "paid", "YOTA INTERNATIONAL"),
    (17794857, 6800, "paid", "Lumora Arc Ascension"),
    (20095641, 3100, "paid", "Shanyraq Cargo"),
    (20244435, 2320, "paid", "OLANTO INTERNATIONAL"),
    (19820817, 700, "paid", "PROFIT VIEW"),
    (20094653, 9500, "paid", "Vasco Pereiro"),
    (18805534, 1460, "paid", "LA FENICE TRADING"),
    (20874532, 660, "paid", "NORDLYS FUELS"),
    (20680617, 1460, "paid", "Innovation Management"),
    (19862707, 1450, "paid", "AVETRA"),
    (21020769, 3050, "paid", "Дмитрий (релокация)"),
    (22084042, 1450, "paid", "Игорь Колосап"),
    (19566821, 6000, "paid", "Plumpy"),
    (21390245, 5120, "paid", "SARADIP MARKETING"),
    (19916917, 1000, "paid", "MELETE - FZCO"),
    (21295713, 2190, "paid", "Maria Rybina"),
    (22188816, 3100, "paid", "MAGNAT FAMILY DMCC"),
    (21652955, 3670, "paid", "Olga Zhgenti"),
    (21798843, 3670, "paid", "Mariia Malakhova"),
    (22362692, 3510, "paid", "STEP BY STEP"),
    (22591576, 4587, "paid", "NATALLIA KALININA"),
    (22575846, 1450, "paid", "Shefer Aleksei"),
    (19176687, 2555, "paid", "Ilia Zalutskii (Golden visa)"),
    (22269880, 1100, "paid", "Кристина (FAB personal)"),
    (23412046, 3150, "paid", "Анна / SEACRAFT (583)"),
    (23476242, 2650, "paid", "Максим (WIO corp)"),
    (23069317, 2650, "paid", "Мария"),
    (23166707, 3000, "paid", "Сергей (audit)"),
    (20851299, 1891, "paid", "Екатерина"),
    (23357551, 3670, "paid", "Станислав"),
    (23163241, 550, "paid", "Надежда"),
    (23477216, 8811, "paid", "MEGACAMPUS / Avetov Grigory"),
    (24015149, 1450, "paid", "Анара"),
    (23983590, 2670, "paid", "Liudmila Novoselskaia"),
    (17166610, 470, "paid", "TALENTUMAI SERVICES"),
    (22824655, 1450, "paid", "SANDSTONE SOLUTIONS"),
    (21965547, 365, "paid", "Stingray (work visa)"),
    (20484903, 470, "paid", "Zoubi Steel Trading"),
    (20484903, 1670, "paid", "IMPERIAL ALFA REAL ESTATE"),
    (23983590, 1450, "paid", "MILASI COUTURE"),
    (24866910, 560, "paid", "FULLART FAKTORY"),
    (24032392, 3675, "not_rendered", "Anna (клиент вернул деньги)"),
    (21827517, 1467, "paid", "MIK Auto Trading"),
    (23187991, 4336, "paid", "Global Flying"),
    (23995422, 4500, "paid", "MEGACAMPUS (INV-207)"),
    (23995422, 2500, "paid", "MEGACAMPUS (INV-235, восстановление)"),
    (23412046, 3150, "paid", "Анна / SEACRAFT (INV-142)"),
    (23412046, 3150, "paid", "Анна / SEACRAFT (INV-142, Mar)"),
    (25880202, 1450, "paid", "GLOBAL REACH"),
    (25016652, 1450, "onboarding", "HEROS JOURNEY"),
    (25016652, 550, "onboarding", "TradeWave Projects"),
    (26311040, 550, "paid", "TERRA MOBILITY GROUP"),
]


def commissions_by_lead() -> dict[int, list[dict]]:
    """kommo_lead_id → список платежей [{fee, status, client}, ...]."""
    by: dict[int, list[dict]] = defaultdict(list)
    for lid, fee, st, cl in ROWS:
        by[lid].append({"fee": fee, "status": st, "client": cl})
    return dict(by)
