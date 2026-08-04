"""Бот оплат: приход с кнопки «купить» и «ответ никогда не бывает без кнопок».

Почему такой тест. 04.08.2026 человек с сайта попадал в бота, отправлял
подставленный ссылкой текст — и получал ответ БЕЗ единой кнопки: оплатить было
неоткуда. Здесь закрепляем два правила, чтобы это не вернулось:

1. `/start pay` (кнопка «купить» на лендинге) сразу показывает тарифы, а если
   касса молчит — обычное меню. Тупика нет ни в одной ветке.
2. Любой текст в ответ получает клавиатуру.

Плюс проверка ссылок лендинга: покупка ведёт в бота, разговор — в личку.

БД — in-memory SQLite (модели на дженерик-типах SQLAlchemy). Сети нет: цены
кассы и уведомления Николь подменены.

Запуск:  python tests/test_paybot_deeplink.py   |   pytest tests/test_paybot_deeplink.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("JWT_SECRET", "test-secret-not-the-default-value-000")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://t:t@localhost:5432/t")
# Пустой токен: Bot() не создаётся, в сеть модуль не ходит.
os.environ["PAY_BOT_TOKEN"] = ""

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app import club_config  # noqa: E402
from app import paybot as pb  # noqa: E402
from app import paybot_config as T  # noqa: E402
from app.models import Base  # noqa: E402

FAILED = []


def check(ok, what):
    # Вывод без символов вне cp1251: консоль Windows иначе роняет сам тест.
    print(("  ok      " if ok else "  ПАДАЕТ  ") + what)
    if not ok:
        FAILED.append(what)


# ─── стенд: сессия SQLite и фейковые объекты Telegram ────────────────────────

def _sessionmaker():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


class FakeUser:
    id = 777
    username = "someone"
    first_name = "Кто-то"


class FakeMessage:
    """Собирает то, что бот отправил: список пар (текст, клавиатура)."""

    def __init__(self):
        self.sent = []
        self.from_user = FakeUser()
        self.text = "Здравствуйте! Вопрос по оплате"
        self.chat = type("C", (), {"id": 777, "type": "private"})()

    async def answer(self, text, reply_markup=None, **kw):
        self.sent.append((text, reply_markup))


class FakeCommand:
    def __init__(self, args):
        self.args = args


def _kb_texts(markup):
    if markup is None:
        return []
    return [b.text for row in markup.inline_keyboard for b in row]


# Третья кнопка — платный клуб (план 2026-08-04): он продаётся тем же людям,
# что покупают курс, поэтому живёт в общем меню, а не в отдельном боте.
MENU = [T.BTN_PAY, T.BTN_ASK, club_config.BTN_CLUB_JOIN]


# ─── 1. разбор payload ───────────────────────────────────────────────────────

def test_parse_payload():
    print("\n[1] parse_payload")
    cases = [
        ("pay", (True, None), "кнопка покупки с лендинга"),
        ("pay_ref_ag1", (True, "ag1"), "кнопка агента: и оплата, и атрибуция"),
        ("ref_ag1", (False, "ag1"), "старая ссылка агента - как была"),
        ("", (False, None), "пустой payload"),
        ("channel", (False, None), "канал - не про оплату"),
        ("payment", (False, None), "похожее слово не считается командой"),
    ]
    for payload, expected, what in cases:
        check(pb.parse_payload(payload) == expected, f"{what}: {payload!r}")
    # Слаг режется до ширины колонки intensive_leads.ref_slug (VARCHAR(16)):
    # длинный хвост из чужой ссылки не должен ронять вставку в базу.
    _, ref = pb.parse_payload("pay_ref_" + "x" * 40)
    check(len(ref) == 16, "слишком длинный ref обрезан до 16 символов")


# ─── 2. клавиатура тарифов ───────────────────────────────────────────────────

def test_products_kb(monkey_prices):
    print("\n[2] клавиатура тарифов")
    monkey_prices({"USD": 20.0})
    texts = _kb_texts(asyncio.run(pb._products_kb()))
    check(len(texts) == len(pb.lava.PRODUCTS), "кнопка на каждый тариф из кассы")
    check(all("$20" in t for t in texts), "в подписи стоит живая цена кассы")

    monkey_prices({})           # касса молчит
    check(asyncio.run(pb._products_kb()) is None,
          "нет цен - None, а не пустая клавиатура")


# ─── 3. /start pay ───────────────────────────────────────────────────────────

def test_start_deep_pay(monkey_prices):
    print("\n[3] /start pay - приход с кнопки покупки")
    monkey_prices({"USD": 20.0})
    msg = FakeMessage()
    asyncio.run(pb.start_deep(msg, FakeCommand("pay")))
    check(len(msg.sent) == 2, "два сообщения: приветствие и выбор тарифа")
    check(msg.sent[0][0] == T.GREETING, "первое - приветствие, без ожидания кассы")
    check(msg.sent[1][0] == T.PRODUCT_TITLE, "второе - что берём")
    check(len(_kb_texts(msg.sent[1][1])) == len(pb.lava.PRODUCTS), "тарифы кнопками")

    print("\n[3b] /start pay при молчащей кассе")
    monkey_prices({})
    msg = FakeMessage()
    asyncio.run(pb.start_deep(msg, FakeCommand("pay")))
    check(msg.sent[-1][0] == T.PRICES_UNAVAILABLE, "честно говорим, что цен нет")
    check(_kb_texts(msg.sent[-1][1]) == MENU,
          "человек всё равно с кнопками, а не в тупике")

    print("\n[3c] /start ref_<slug> - старое поведение цело")
    msg = FakeMessage()
    asyncio.run(pb.start_deep(msg, FakeCommand("ref_ag1")))
    check(len(msg.sent) == 1 and msg.sent[0][0] == T.GREETING,
          "приветствие одним сообщением")
    check(_kb_texts(msg.sent[0][1]) == MENU, "с обычным меню")


# ─── 4. ответ на текст - всегда с кнопками ───────────────────────────────────

def test_text_answer_has_buttons():
    print("\n[4] ответ на вопрос - с кнопками")
    msg = FakeMessage()
    asyncio.run(pb.on_text(msg))
    check(msg.sent[0][0] == T.ASK_RECEIVED, "вопрос принят")
    check(_kb_texts(msg.sent[0][1]) == MENU,
          "и сразу кнопка оплаты - это и был баг 04.08.2026")


def test_start_resets_awaiting(monkey_prices):
    print("\n[4b] новый заход сбрасывает брошенный шаг с e-mail")
    monkey_prices({"USD": 20.0})
    msg = FakeMessage()
    pb._awaiting[msg.from_user.id] = "email"       # вчера бросил оплату тут
    asyncio.run(pb.start_deep(msg, FakeCommand("pay")))
    check(msg.from_user.id not in pb._awaiting, "ожидание e-mail снято")

    msg2 = FakeMessage()
    asyncio.run(pb.on_text(msg2))                  # пишет вопрос, а не почту
    check(msg2.sent[0][0] == T.ASK_RECEIVED,
          "текст читается как вопрос, а не как кривой e-mail")

    msg3 = FakeMessage()
    pb._awaiting[msg3.from_user.id] = "email"
    asyncio.run(pb.start(msg3))                    # то же для голого /start
    check(msg3.from_user.id not in pb._awaiting, "/start тоже сбрасывает")


# ─── 5. сквозной путь покупки ────────────────────────────────────────────────

class FakeCall:
    def __init__(self, data):
        self.data = data
        self.from_user = FakeUser()
        self.message = FakeMessage()

    async def answer(self, *a, **kw):
        return None


def test_full_purchase_path():
    """С кнопки на сайте до счёта: тариф, валюта и offerId не должны разъехаться."""
    print("\n[5] сквозной путь: сайт -> тариф -> валюта -> e-mail -> счёт")
    from app.models import IntensiveLead

    prices = {
        pb.lava.OFFER_FIRST_DAY: {"USD": 20.0, "RUB": 1608.0},
        pb.lava.OFFER_INTENSIVE: {"USD": 1000.0, "RUB": 80400.0},
    }
    pb.lava.offer_prices = lambda offer_id=None: dict(prices.get(offer_id, {}))
    created = {}

    def fake_invoice(email, currency, offer_id=None):
        created.update(email=email, currency=currency, offer_id=offer_id)
        return {"id": "inv-1", "url": "https://app.lava.top/pay/inv-1"}
    pb.lava.create_invoice = fake_invoice

    msg = FakeMessage()
    asyncio.run(pb.start_deep(msg, FakeCommand("pay")))
    check(len(_kb_texts(msg.sent[1][1])) == 2, "оба тарифа кнопками")

    call = FakeCall("pay:prod:intensive")
    asyncio.run(pb.cb_product(call))
    check(any("$1 000" in t for t in _kb_texts(call.message.sent[0][1])),
          "валюты показаны с ценами ИМЕННО выбранного тарифа")

    call2 = FakeCall("pay:cur:USD")
    asyncio.run(pb.cb_currency(call2))
    check(call2.message.sent[0][0] == T.EMAIL_ASK, "просим e-mail")

    mail = FakeMessage()
    mail.text = "buyer@example.com"
    asyncio.run(pb.on_text(mail))
    check("$1 000" in mail.sent[0][0], "счёт на цену курса, а не первого дня")
    check(created.get("offer_id") == pb.lava.OFFER_INTENSIVE,
          "счёт ушёл на offerId выбранного тарифа")
    check(created.get("currency") == "USD", "валюта счёта — выбранная человеком")

    with pb.SessionLocal() as s:
        lead = s.query(IntensiveLead).filter_by(telegram_id=FakeUser.id).first()
    check(lead.product_code == "intensive" and lead.status == "invoiced",
          "в базе тариф и статус счёта")


# ─── 6. ссылки лендинга ──────────────────────────────────────────────────────

def test_landing_links():
    print("\n[5] кнопки лендинга /assistant")
    from app import assistant_config as ac
    from app.config import settings

    expected = "https://t.me/" + settings.PAY_BOT_USERNAME + "?start=pay"
    check(ac.CTA_BUY == expected, "ссылка покупки ведёт в бота с payload pay")
    buy = [ac.HERO["cta_url"], ac.FINAL["cta_url"], ac.PRICING["tiers"][0]["cta_url"]]
    check(all(u == ac.CTA_BUY for u in buy),
          "герой, финал и тариф курса - в бота")
    talk = [ac.TEAM["cta_url"], ac.PRICING["tiers"][1]["cta_url"]]
    check(all(ac.TG_USERNAME in u for u in talk),
          "кого собрать и под ключ - по-прежнему в личку")
    # Классическая опечатка этой связки: у бота hilton с одной l, у личного
    # аккаунта Николь - hillton с двумя. Перепутать = увести покупателя в никуда.
    uname = settings.PAY_BOT_USERNAME.lower()
    check("hilton" in uname and "hillton" not in uname,
          "username бота - hilton с одной l, не личный hillton")
    check(ac.TG_USERNAME.lower() != uname, "личка и бот - разные адресаты")


def main():
    pb.SessionLocal = _sessionmaker()        # БД бота - SQLite стенда

    async def _no_admin(_text):              # уведомления Николь не шлём
        return None
    pb._notify_admin = _no_admin

    def monkey_prices(prices):
        pb.lava.offer_prices = lambda offer_id=None: dict(prices)

    test_parse_payload()
    test_products_kb(monkey_prices)
    test_start_deep_pay(monkey_prices)
    test_text_answer_has_buttons()
    test_start_resets_awaiting(monkey_prices)
    test_full_purchase_path()
    test_landing_links()

    print("\n" + ("ВСЁ ЗЕЛЁНОЕ" if not FAILED else "ПАДАЕТ: %d" % len(FAILED)))
    for f in FAILED:
        print("  -", f)
    return 1 if FAILED else 0


def test_all():
    """Точка входа для pytest."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
