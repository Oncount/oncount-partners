"""Интеграционный тест build_attribution на SQLite (план 2026-07-23, Фаза 2).

Проверяем математику отчёта на синтетике: конверсия ≤100% (одно окно для кликов и
заявок), разбивка по surface, partner_bot через Referral. БД — in-memory SQLite (модели
на дженерик-типах SQLAlchemy, Postgres-специфики нет).

Запуск:  python tests/test_attribution.py   |   pytest tests/test_attribution.py
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Как в test_rate_limit: непустой JWT_SECRET + фиктивный DATABASE_URL (engine ленив) ДО импорта main.
os.environ.setdefault("JWT_SECRET", "test-secret-not-the-default-value-000")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://t:t@localhost:5432/t")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app import main as m  # noqa: E402
from app import mk_config  # noqa: E402
from app.models import Base, LinkClick, Partner, QuizSubmission, Referral  # noqa: E402


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed(s):
    s.add(Partner(id=1, ref_slug="ag1", first_name="Агент1", status="active"))
    base = datetime.utcnow() - timedelta(days=1)
    # mk: 5 переходов на лендинг + 2 в чат (tg), 1 заявка → конверсия 20% (1/5).
    for i in range(5):
        s.add(LinkClick(content_key="mk", surface="quiz", ref_slug="ag1", partner_id=1, created_at=base))
    for i in range(2):
        s.add(LinkClick(content_key="mk", surface="tg", ref_slug="ag1", partner_id=1, created_at=base))
    s.add(QuizSubmission(phone="971500000001", event_slug=mk_config.EVENT_SLUG,
                         ref_slug="ag1", partner_id=1, kommo_status="dry", created_at=base))
    # consultation: 4 перехода на лендинг, 2 заявки (event_slug=None) → 50%.
    for i in range(4):
        s.add(LinkClick(content_key="consultation", surface="quiz", ref_slug="ag1", partner_id=1, created_at=base))
    for i in range(2):
        s.add(QuizSubmission(phone=f"97150000010{i}", event_slug=None,
                             ref_slug="ag1", partner_id=1, kommo_status="dry", created_at=base))
    # partner_bot: 3 перехода в бота + 1 приход (Referral).
    for i in range(3):
        s.add(LinkClick(content_key="partner_bot", surface="bot", ref_slug="ag1", partner_id=1, created_at=base))
    s.add(Referral(partner_id=1, ref_slug="ag1", source="tg", created_at=base))
    s.commit()


def test_empty_when_no_clicks():
    s = _session()
    res = m.build_attribution(s)
    assert res["since"] is None
    assert res["by_content"] == []
    assert res["by_agent_content"] == []


def test_conversion_and_breakdown():
    s = _session()
    _seed(s)
    res = m.build_attribution(s)
    assert isinstance(res["since"], datetime)
    by = {r["key"]: r for r in res["by_content"]}

    assert by["mk"]["quiz_clicks"] == 5
    assert by["mk"]["chat_clicks"] == 2
    assert by["mk"]["leads"] == 1
    assert by["mk"]["conv"] == 20.0

    assert by["consultation"]["quiz_clicks"] == 4
    assert by["consultation"]["leads"] == 2
    assert by["consultation"]["conv"] == 50.0

    # partner_bot: переходы в бота есть, конверсии нет, приходы из Referral.
    assert by["partner_bot"]["bot_clicks"] == 3
    assert by["partner_bot"]["conv"] is None
    assert by["partner_bot"]["arrivals"] == 1
    assert by["partner_bot"]["leads"] == 0


def test_conversion_never_over_100():
    # Историческая заявка ДО первого клика не должна раздувать конверсию: окно
    # якорится на первый клик, всё раньше — вне окна.
    s = _session()
    old = datetime.utcnow() - timedelta(days=90)
    s.add(Partner(id=1, ref_slug="ag1", first_name="A", status="active"))
    # 100 старых заявок ДО кликов
    for i in range(100):
        s.add(QuizSubmission(phone=f"9715000{i:05d}", event_slug=mk_config.EVENT_SLUG,
                             ref_slug="ag1", partner_id=1, kommo_status="dry", created_at=old))
    # клики появились только сейчас
    now = datetime.utcnow()
    for i in range(4):
        s.add(LinkClick(content_key="mk", surface="quiz", ref_slug="ag1", partner_id=1, created_at=now))
    s.commit()
    res = m.build_attribution(s)
    by = {r["key"]: r for r in res["by_content"]}
    # заявки из-до-окна не считаются → конверсия 0%, не 2500%
    assert by["mk"]["leads"] == 0
    assert by["mk"]["conv"] == 0.0


def test_agent_content_rows():
    s = _session()
    _seed(s)
    res = m.build_attribution(s)
    ac = res["by_agent_content"]
    assert ac, "должны быть строки агент×контент"
    mk_row = next((r for r in ac if r["content"].startswith("Мастер")), None)
    assert mk_row is not None
    assert mk_row["clicks"] == 7  # 5 quiz + 2 tg
    assert mk_row["leads"] == 1


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} тестов пройдено.")
