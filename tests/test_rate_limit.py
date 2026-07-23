"""Тест per-IP rate-limit и извлечения клиентского IP (security-fix 2026-07-23).

Проверяем два свойства правки:
  1. _client_ip берёт ЛЕВЫЙ IP из X-Forwarded-For (рекомендация Railway),
     не правый (внутренний балансировщик), и мягко деградирует на peer-адрес.
  2. _RL_HITS не растёт без предела: протухшие бакеты подчищаются свипом,
     а при достижении потолка ключей новый IP не заводится (fail-open).
Плюс — что сам лимит по-прежнему срабатывает на _RL_MAX и сбрасывается за окно.

Запуск без pytest:  python tests/test_rate_limit.py
Под pytest:         pytest tests/test_rate_limit.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# app.config требует непустой JWT_SECRET; app.db создаёт engine лениво (без
# коннекта на импорте), поэтому фиктивный DATABASE_URL безопасен — к БД в этом
# тесте не ходим. Ставим ДО импорта app.main.
os.environ.setdefault("JWT_SECRET", "test-secret-not-the-default-value-000")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://t:t@localhost:5432/t")

from app import main as m  # noqa: E402


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    """Мини-заглушка Request: только .headers.get(...) и .client.host."""
    def __init__(self, xff=None, peer="9.9.9.9"):
        self.headers = {}
        if xff is not None:
            self.headers["x-forwarded-for"] = xff
        self.client = _FakeClient(peer) if peer is not None else None

    # main._client_ip зовёт request.headers.get(...)
    # dict уже это умеет — отдельного метода не нужно.


def _reset():
    m._RL_HITS.clear()
    m._RL_SWEEP_AT[0] = 0.0


def test_client_ip_takes_leftmost():
    # Клиент подделал левый IP, Railway дописал реальный справа — но на прямом
    # railway-домене edge затирает клиентский XFF, поэтому левый = доверенный.
    # Важно: берём ЛЕВЫЙ, а не правый (правый — общий IP балансировщика).
    req = _FakeRequest(xff="203.0.113.7, 100.64.0.1")
    assert m._client_ip(req) == "203.0.113.7"


def test_client_ip_trims_whitespace_and_single():
    assert m._client_ip(_FakeRequest(xff="  198.51.100.4  ")) == "198.51.100.4"
    assert m._client_ip(_FakeRequest(xff="198.51.100.9")) == "198.51.100.9"


def test_client_ip_fallback_to_peer():
    assert m._client_ip(_FakeRequest(xff=None, peer="9.9.9.9")) == "9.9.9.9"
    # пустой/мусорный XFF → тоже peer
    assert m._client_ip(_FakeRequest(xff="   ", peer="9.9.9.9")) == "9.9.9.9"


def test_client_ip_no_client_no_xff():
    assert m._client_ip(_FakeRequest(xff=None, peer=None)) == "?"


def test_limit_triggers_and_resets():
    _reset()
    now = 1000.0
    # первые _RL_MAX запросов проходят
    for i in range(m._RL_MAX):
        assert m._rl_register("1.1.1.1", now) is True, f"запрос {i} должен пройти"
    # следующий — заблокирован
    assert m._rl_register("1.1.1.1", now) is False
    # спустя окно — снова можно
    assert m._rl_register("1.1.1.1", now + m._RL_WINDOW + 1) is True


def test_distinct_ips_independent():
    _reset()
    now = 2000.0
    for _ in range(m._RL_MAX):
        assert m._rl_register("2.2.2.2", now) is True
    # другой IP не затронут лимитом первого
    assert m._rl_register("3.3.3.3", now) is True


def test_sweep_removes_expired_buckets():
    _reset()
    now = 3000.0
    m._rl_register("4.4.4.4", now)
    m._rl_register("5.5.5.5", now)
    assert len(m._RL_HITS) == 2
    # свип спустя больше окна — оба бакета протухли и удалены
    m._rl_sweep(now + m._RL_WINDOW + 1)
    assert len(m._RL_HITS) == 0


def test_sweep_keeps_active_buckets():
    _reset()
    now = 4000.0
    m._rl_register("6.6.6.6", now)              # протухнет
    m._rl_register("7.7.7.7", now + m._RL_WINDOW)  # ещё живой
    m._rl_sweep(now + m._RL_WINDOW + 1)
    assert "6.6.6.6" not in m._RL_HITS
    assert "7.7.7.7" in m._RL_HITS


def test_key_cap_fail_open():
    _reset()
    now = 5000.0
    saved = m._RL_MAX_KEYS
    try:
        m._RL_MAX_KEYS = 3
        for ip in ("a", "b", "c"):
            assert m._rl_register(ip, now) is True
        assert len(m._RL_HITS) == 3
        # потолок достигнут: новый IP не заводится (fail-open — пропускаем),
        # словарь не растёт → защита памяти.
        assert m._rl_register("d", now) is True
        assert "d" not in m._RL_HITS
        assert len(m._RL_HITS) == 3
        # уже известный IP продолжает лимитироваться штатно
        assert m._rl_register("a", now) is True
    finally:
        m._RL_MAX_KEYS = saved


def test_debug_event_stats_is_admin_gated():
    # Публичный ранее эндпоинт закрыт: в сигнатуре появился require_admin.
    import inspect
    src = inspect.getsource(m.debug_event_stats)
    assert "require_admin(request, session)" in src


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} тестов пройдено.")
