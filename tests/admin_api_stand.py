"""Общий стенд для машинных адресов /admin/api/* (page-views, intensive-leads).

Повторяет стенд tests/test_channel_tags.py, чтобы три соседних адреса
проверялись одним и тем же способом: in-memory SQLite, сессия подменена через
dependency_overrides, токен подставлен в настройки, лимит частоты очищен.
Сети и живой базы тут нет. Не тест сам по себе: pytest его не собирает
(имя без `test_`), а тестовые файлы импортируют его из своей папки.
"""
import logging
import os
import sys
from contextlib import contextmanager

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("JWT_SECRET", "test-secret-not-the-default-value-000")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://t:t@localhost:5432/t")
# Пустой токен: бот оплат не поднимается, в сеть импорт приложения не ходит.
os.environ["PAY_BOT_TOKEN"] = ""

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import auth  # noqa: E402
from app import main as web  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Partner  # noqa: E402

TOKEN = "test-token-ardorium-0000000000"
API_METHODS_CLOSED = ("POST", "PUT", "PATCH", "DELETE", "OPTIONS")


@contextmanager
def stand(*rows, token=TOKEN):
    # Один общий коннект на все потоки: маршрут FastAPI выполняется в
    # threadpool, а in-memory SQLite живёт в том потоке, где создан.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all(rows)
    session.commit()
    had = get_session in app.dependency_overrides
    saved_dep = app.dependency_overrides.get(get_session)
    app.dependency_overrides[get_session] = lambda: session
    saved = settings.CHANNEL_TAGS_TOKEN
    settings.CHANNEL_TAGS_TOKEN = token
    web._RL_HITS.clear()
    try:
        yield TestClient(app), session
    finally:
        settings.CHANNEL_TAGS_TOKEN = saved
        if had:
            app.dependency_overrides[get_session] = saved_dep
        else:
            app.dependency_overrides.pop(get_session, None)
        web._RL_HITS.clear()
        session.close()


@contextmanager
def logs():
    """Журнал приложения за время блока."""
    written = []

    class Catch(logging.Handler):
        def emit(self, record):
            written.append(f"{record.levelname} {record.getMessage()}")

    handler, root = Catch(), logging.getLogger()
    level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        yield written
    finally:
        root.removeHandler(handler)
        root.setLevel(level)


@contextmanager
def sql_seen(session):
    """Первые слова всех запросов, ушедших в базу за время блока."""
    seen = []

    @event.listens_for(session.get_bind(), "before_cursor_execute")
    def catch(conn, cursor, statement, *a):    # noqa: ANN001
        seen.append(statement.strip().split()[0].upper())

    try:
        yield seen
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", catch)


def owner_cookie(session, client, telegram_id=None):
    """Настоящая кука владельца: партнёр в своей же базе + подписанный JWT.
    Ставится на клиента навсегда: всё анонимное проверять ДО неё."""
    partner = Partner(telegram_id=telegram_id if telegram_id is not None
                      else settings.ADMIN_TG_ID,
                      ref_slug=f"ref{telegram_id or 'adm'}"[:16], status="active")
    session.add(partner)
    session.commit()
    client.cookies.set(auth.COOKIE_NAME, auth.issue_jwt(partner.id))


def fingerprint(r):
    """Отпечаток ответа: код, все заголовки кроме меняющихся, тело."""
    return (r.status_code,
            sorted((k.lower(), v) for k, v in r.headers.items()
                   if k.lower() not in ("date", "server")),
            r.content)


def assert_refusal_indistinguishable(client, session, url, missing_url):
    """Отказ байт в байт как у несуществующего адреса: аноним, чужой токен,
    закрытые методы (с токеном и без), чужая кука. Снимается ДО куки владельца."""
    etalon = fingerprint(client.get(missing_url))
    assert etalon[0] == 404, "эталонный адрес вдруг существует"
    for who, headers in (("аноним", {}),
                         ("неверный токен", {"X-Api-Token": "sovsem-ne-tot"}),
                         ("пустой токен", {"X-Api-Token": ""}),
                         ("почти тот токен", {"X-Api-Token": TOKEN[:-1]})):
        assert fingerprint(client.get(url, headers=headers)) == etalon, who
    assert fingerprint(client.head(url)) == fingerprint(client.head(missing_url)), "HEAD"
    for method in API_METHODS_CLOSED:
        own = fingerprint(client.request(method, missing_url))
        for who, headers in (("аноним", {}), ("с токеном", {"X-Api-Token": TOKEN})):
            assert fingerprint(client.request(method, url, headers=headers)) == own, \
                f"{method} / {who}"
    owner_cookie(session, client, telegram_id=settings.ADMIN_TG_ID + 1)
    assert fingerprint(client.get(url)) == etalon, "чужая кука"


def assert_success_headers_and_short_head(client, session, url, name):
    """Успех: no-store + nosniff на GET и HEAD, у HEAD нет тела, базы и журнала."""
    get = client.get(url, headers={"X-Api-Token": TOKEN})
    assert get.status_code == 200, get.text
    assert get.headers.get("cache-control") == "no-store"
    assert get.headers.get("x-content-type-options") == "nosniff"
    with sql_seen(session) as seen, logs() as written:
        head = client.head(url, headers={"X-Api-Token": TOKEN})
    assert head.status_code == 200 and len(head.content) == 0, "на HEAD уехало тело"
    for h in ("cache-control", "x-content-type-options"):
        assert head.headers.get(h) == get.headers.get(h), h
    assert seen == [], f"короткий HEAD сходил в базу: {seen}"
    assert not [w for w in written if name in w], "HEAD залил журнал"


def run_as_script(namespace):
    fns = [v for k, v in sorted(namespace.items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} тестов пройдено.")
