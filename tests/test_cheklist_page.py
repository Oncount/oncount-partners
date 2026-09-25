# -*- coding: utf-8 -*-
"""Страница чек-листа: отдаётся, кнопки ведут к форме записи, форма уводит в бота, счёт перехода пишется."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("JWT_SECRET", "test-secret-not-the-default-value-000")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://t:t@localhost:5432/t")
os.environ["PAY_BOT_TOKEN"] = ""

from fastapi.testclient import TestClient
from app.main import app
from app import linkstat

записано = []
linkstat.record_click = lambda *a, **k: записано.append(a)

c = TestClient(app)
r = c.get("/cheklist/ai-sotrudnik")
ok = True


def check(cond, what):
    global ok
    print(("  ok      " if cond else "  ПАДАЕТ  ") + what)
    if not cond:
        ok = False


check(r.status_code == 200, "страница отдаётся")
t = r.text
check("AI-сотрудник" in t, "заголовок на месте")
check(t.count('href="#zapis"') == 4, "четыре кнопки «Собрать своего» ведут к форме внизу страницы")
check('id="zapis-forma"' in t and ">Записаться</button>" in t and "100% возврат" in t and "Нужны компьютер" not in t, "форма записи внизу страницы (слово Николь 25.09)")
check(t.count("start=zayavka-cheklist") == 1, "после отправки формы человек уходит в бота заявкой")
check(all(f'name="{n}"' in t for n in ("name", "email", "phone", "consent", "website")), "поля формы и ловушка для роботов")
check("ardorium.eu/ru/legal/privacy/" in t and "ardorium.eu/ru/legal/offer/" in t, "ссылки на политику и оферту")
check("oncount.co/assistant?utm_source=cheklist" not in t, "старых ссылок на лендинг не осталось")
check("Даша" in t and "Сергей" in t, "оба отзыва на месте")
check("20 €" in t, "цена интенсива в евро")
check(len(записано) == 1, "переход записан один раз")

# Приёмник формы: отказы до записи в базу (запись и Kommo здесь не проверяются — их ядро общее с лид-магнитами).
r1 = c.post("/cheklist/ai-sotrudnik/submit", json={"name": "Тест", "email": "a@b.co", "phone": "+971501234567"})
check(r1.json() == {"ok": False, "error": "consent"}, "без галочки согласия заявка не принимается")
r2 = c.post("/cheklist/ai-sotrudnik/submit", json={"name": "Тест", "email": "не почта", "phone": "+971501234567", "consent": True})
check(r2.json() == {"ok": False, "error": "email"}, "кривая почта — отказ")
r3 = c.post("/cheklist/ai-sotrudnik/submit", json={"name": "Тест", "email": "a@b.co", "phone": "+971501234567", "consent": "yes"})
check(r3.json() == {"ok": False, "error": "consent"}, "согласие только настоящей галочкой")
print("ВСЁ ЗЕЛЁНОЕ" if ok else "ЕСТЬ ПАДЕНИЯ")
sys.exit(0 if ok else 1)
