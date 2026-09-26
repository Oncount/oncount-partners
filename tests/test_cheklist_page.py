# -*- coding: utf-8 -*-
"""Страница чек-листа: отдаётся, кнопки ведут к форме записи, после записи кнопки оплаты, счёт перехода пишется."""
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
check("ardorium.eu/ru/oplata/#" in t and "sendBeacon" in t and "start=zayavka-cheklist" not in t, "после записи человек уходит на страницу оплаты ARDORIUM, заявка фоном (слово Николь 26.09)")
check(c.get("/cheklist/ai-sotrudnik/oplata", follow_redirects=False).status_code == 404, "страницы оплаты на ONCOUNT больше нет (удалена по слову Николь 26.09)")
check(c.post("/cheklist/ai-sotrudnik/schet", json={}).status_code in (404, 405), "приёма запроса счёта на ONCOUNT больше нет")
check(all(f'name="{n}"' in t for n in ("email", "phone", "consent", "website")) and 'name="name"' not in t, "поля формы: почта и телефон, без имени; ловушка для роботов")
check("ardorium.eu/ru/legal/privacy/" in t and "ardorium.eu/ru/legal/offer/" in t, "ссылки на политику и оферту")
check("oncount.co/assistant?utm_source=cheklist" not in t, "старых ссылок на лендинг не осталось")
check("Даша" in t and "Сергей" in t, "оба отзыва на месте")
check("<span class=\"zapis-evro\">€</span>20" in t and "2.000<span class=\"zapis-rubl\">₽</span>" in t, "цена интенсива: €20 и 2.000₽ (слово Николь 26.09)")
check(sum(1 for x in записано if x[0] == "cheklist_ai_sotrudnik") == 1, "переход на чек-лист записан один раз")

# Приёмник формы: отказы до записи в базу (запись и Kommo здесь не проверяются — их ядро общее с лид-магнитами).
r1 = c.post("/cheklist/ai-sotrudnik/submit", json={"name": "Тест", "email": "a@b.co", "phone": "+971501234567"})
check(r1.json() == {"ok": False, "error": "consent"}, "без галочки согласия заявка не принимается")
r2 = c.post("/cheklist/ai-sotrudnik/submit", json={"name": "Тест", "email": "не почта", "phone": "+971501234567", "consent": True})
check(r2.json() == {"ok": False, "error": "email"}, "кривая почта — отказ")
r3 = c.post("/cheklist/ai-sotrudnik/submit", json={"name": "Тест", "email": "a@b.co", "phone": "+971501234567", "consent": "yes"})
check(r3.json() == {"ok": False, "error": "consent"}, "согласие только настоящей галочкой")
print("ВСЁ ЗЕЛЁНОЕ" if ok else "ЕСТЬ ПАДЕНИЯ")
sys.exit(0 if ok else 1)
