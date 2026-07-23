"""Тесты монитора здоровья ссылок (план 2026-07-23, Фаза 3).

Чистые функции + SQLite (compute_signals) + мок отправки (send/dedup) — без сети и Postgres.
Запуск:  python tests/test_health.py   |   pytest tests/test_health.py
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("JWT_SECRET", "test-secret-not-the-default-value-000")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://t:t@localhost:5432/t")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app import health  # noqa: E402
from app import mk_config  # noqa: E402
from app.config import settings  # noqa: E402
from app.models import Base, HealthAlert, LinkClick, QuizSubmission  # noqa: E402


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


# ─── classify_up ─────────────────────────────────────────────────────────────
def test_classify_up():
    assert health.classify_up(200) is True
    assert health.classify_up(302) is True   # штатный редирект-лендинг
    assert health.classify_up(429) is True   # rate-limit ответил → жив
    assert health.classify_up(404) is False
    assert health.classify_up(500) is False
    assert health.classify_up(503) is False
    assert health.classify_up(None) is False  # нет ответа


# ─── check_targets ───────────────────────────────────────────────────────────
def test_check_targets_default_ok():
    # Дефолтный конфиг (nikol_hillton / 971589217784) — цели валидны.
    by = {t["name"]: t for t in health.check_targets()}
    assert by["Telegram-контакт"]["ok"] is True
    assert by["WhatsApp-номер"]["ok"] is True


def test_check_targets_detects_broken_contact():
    saved_tg, saved_wa = settings.CONTACT_TG_USERNAME, settings.CONTACT_WA_NUMBER
    try:
        settings.CONTACT_TG_USERNAME = ""      # поломка: пустой контакт
        settings.CONTACT_WA_NUMBER = "123"     # поломка: слишком короткий
        by = {t["name"]: t for t in health.check_targets()}
        assert by["Telegram-контакт"]["ok"] is False
        assert by["WhatsApp-номер"]["ok"] is False
    finally:
        settings.CONTACT_TG_USERNAME, settings.CONTACT_WA_NUMBER = saved_tg, saved_wa


# ─── compute_signals ─────────────────────────────────────────────────────────
def test_stale_detected_when_baseline_but_no_recent():
    s = _session()
    old = datetime.utcnow() - timedelta(days=5)   # в базлайне (30д), вне tail (72ч)
    for _ in range(settings.LINK_MIN_BASELINE_CLICKS + 3):
        s.add(LinkClick(content_key="mk", surface="quiz", created_at=old))
    s.commit()
    sig = health.compute_signals(s)
    stale_keys = {x["content"] for x in sig["stale"]}
    assert "mk" in stale_keys


def test_not_stale_when_recent_clicks_exist():
    s = _session()
    now = datetime.utcnow()
    for _ in range(settings.LINK_MIN_BASELINE_CLICKS + 3):
        s.add(LinkClick(content_key="mk", surface="quiz", created_at=now))
    s.commit()
    sig = health.compute_signals(s)
    assert "mk" not in {x["content"] for x in sig["stale"]}


def test_conversion_drop_when_clicks_no_leads():
    s = _session()
    now = datetime.utcnow()
    for _ in range(settings.LINK_MIN_BASELINE_CLICKS + 2):
        s.add(LinkClick(content_key="mk", surface="quiz", created_at=now))
    # заявок по mk нет → провал конверсии
    s.commit()
    sig = health.compute_signals(s)
    assert "mk" in {x["content"] for x in sig["conv_drop"]}


def test_no_conversion_drop_when_leads_present():
    s = _session()
    now = datetime.utcnow()
    for _ in range(settings.LINK_MIN_BASELINE_CLICKS + 2):
        s.add(LinkClick(content_key="mk", surface="quiz", created_at=now))
    s.add(QuizSubmission(phone="971500000001", event_slug=mk_config.EVENT_SLUG,
                         kommo_status="dry", created_at=now))
    s.commit()
    sig = health.compute_signals(s)
    assert "mk" not in {x["content"] for x in sig["conv_drop"]}


# ─── дедуп + отправка ────────────────────────────────────────────────────────
def test_alerted_today_dedup_logic():
    s = _session()
    now = datetime.utcnow()
    s.add(HealthAlert(issue_key="landings_down:/mk:500", created_at=now))
    s.commit()
    assert health._alerted_today(s, "landings_down:/mk:500", now) is True
    assert health._alerted_today(s, "landings_down:/consultation:404", now) is False
    # старше 24ч — уже можно слать снова
    assert health._alerted_today(s, "landings_down:/mk:500", now + timedelta(hours=25)) is False


def test_run_sends_once_then_dedups():
    s = _session()
    calls = []
    saved_flag = settings.LINK_HEALTH_ALERTS
    orig_land, orig_tgt, orig_alert = (health.check_landings_up, health.check_targets, health.alert_admin)
    try:
        settings.LINK_HEALTH_ALERTS = True
        health.check_landings_up = lambda now=None, http_get=None: [
            {"path": "/mk", "status": 500, "ok": False}]
        health.check_targets = lambda: []
        health.alert_admin = lambda text: (calls.append(text) or True)

        r1 = health.run_health_check(s)
        assert r1["alerts_sent"] == ["landings_down:/mk:500"]
        assert len(calls) == 1 and "🔴" in calls[0]

        # повтор в пределах суток → не шлём снова
        r2 = health.run_health_check(s)
        assert r2["alerts_sent"] == []
        assert len(calls) == 1
    finally:
        settings.LINK_HEALTH_ALERTS = saved_flag
        health.check_landings_up, health.check_targets, health.alert_admin = (orig_land, orig_tgt, orig_alert)


def test_dry_run_never_sends():
    s = _session()
    calls = []
    saved_flag = settings.LINK_HEALTH_ALERTS
    orig_land, orig_tgt, orig_alert = (health.check_landings_up, health.check_targets, health.alert_admin)
    try:
        settings.LINK_HEALTH_ALERTS = True
        health.check_landings_up = lambda now=None, http_get=None: [
            {"path": "/mk", "status": 500, "ok": False}]
        health.check_targets = lambda: []
        health.alert_admin = lambda text: (calls.append(text) or True)
        r = health.run_health_check(s, dry=True)
        assert r["alerts_sent"] == []
        assert calls == []
        assert r["breakage"]  # но проблема в summary видна
    finally:
        settings.LINK_HEALTH_ALERTS = saved_flag
        health.check_landings_up, health.check_targets, health.alert_admin = (orig_land, orig_tgt, orig_alert)


def test_flag_off_no_send_even_with_breakage():
    s = _session()
    calls = []
    saved_flag = settings.LINK_HEALTH_ALERTS
    orig_land, orig_tgt, orig_alert = (health.check_landings_up, health.check_targets, health.alert_admin)
    try:
        settings.LINK_HEALTH_ALERTS = False   # предохранитель выключен (дефолт)
        health.check_landings_up = lambda now=None, http_get=None: [
            {"path": "/mk", "status": 500, "ok": False}]
        health.check_targets = lambda: []
        health.alert_admin = lambda text: (calls.append(text) or True)
        r = health.run_health_check(s)
        assert calls == []
        assert r["alerts_sent"] == []
        assert r["breakage"]  # видно в summary/логе, но наружу молчок
    finally:
        settings.LINK_HEALTH_ALERTS = saved_flag
        health.check_landings_up, health.check_targets, health.alert_admin = (orig_land, orig_tgt, orig_alert)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} тестов пройдено.")
