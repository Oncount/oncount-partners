"""Трекинг использования портала агентами (план 2026-06-03), Фаза 1.

Здесь — чистая, тестируемая часть: классификация пути запроса в (нормализованный
путь, секция). Запись в БД и middleware — Фаза 2. Вынесено из main.py намеренно,
чтобы юнит-тест не тянул bot/wazzup/email через импорт main.

Принцип — БЕЛЫЙ список: трекаем только известные страницы кабинета. Всё прочее
(лендинги, /admin, /auth, /static, реф-редиректы, неизвестное) → None, не пишется.
Так случайно не затрекаем путь с токеном и не раздуем словарь секций мусором.
"""

# Секция → человекочитаемый ярлык для админ-дашборда (RU). Порядок = порядок
# показа. "onboarding" держим отдельной группой: это вынужденный путь входа,
# а не добровольный интерес (см. разбор «что не учли», план 2026-06-03).
SECTION_LABELS: dict[str, str] = {
    "dashboard": "Главная",
    "leads": "Мои лиды",
    "tools": "Инструменты",
    "kb": "База знаний",
    "courses": "Курсы",
    "transfer": "Передать клиента",
    "account": "Профиль",
    "onboarding": "Вход / анкета",
}

# Одно-сегментные страницы кабинета: head → (нормализованный путь, секция).
_STATIC_PAGES: dict[str, tuple[str, str]] = {
    "dashboard": ("/dashboard", "dashboard"),
    "leads": ("/leads", "leads"),
    "tools": ("/tools", "tools"),
    "products": ("/products", "kb"),
    "faq": ("/faq", "kb"),
    "transfer": ("/transfer", "transfer"),
    "account": ("/account", "account"),
    "onboarding": ("/onboarding", "onboarding"),
    "onboarding-survey": ("/onboarding-survey", "onboarding"),
}


def classify_path(raw_path: str) -> tuple[str, str] | None:
    """raw_path (без query) → (нормализованный путь, секция) или None если не трекаем.

    Динамические сегменты схлопываются: /courses/abc/day/2 → /courses/:slug/day/:day,
    иначе каждый курс/день был бы отдельной строкой и агрегаты рассыпались бы.
    """
    p = (raw_path or "").rstrip("/") or "/"
    segs = [s for s in p.split("/") if s]
    if not segs:
        return None  # "/" — публичная главная (лендинг), не кабинет агента
    head = segs[0]

    # Курсы: список + страница курса + конкретный день
    if head == "courses":
        if len(segs) == 1:
            return ("/courses", "courses")
        if len(segs) == 2:
            return ("/courses/:slug", "courses")
        if len(segs) == 4 and segs[2] == "day":
            return ("/courses/:slug/day/:day", "courses")
        return None

    # Алиасы базы знаний под /kb/*
    if head == "kb" and len(segs) == 2:
        sub = segs[1]
        if sub in ("products", "faq"):
            return (f"/kb/{sub}", "kb")
        if sub == "courses":
            return ("/kb/courses", "courses")
        return None

    if len(segs) == 1 and head in _STATIC_PAGES:
        return _STATIC_PAGES[head]

    return None


# ── Фаза 2: буфер заходов + фоновый сброс в БД ──────────────────────────────
# Заходы копим в памяти и пишем пачкой (фоновый APScheduler-джоб), чтобы не
# блокировать ответ агенту записью в БД на каждый запрос. BackgroundScheduler
# крутится в отдельном потоке → доступ к буферу под Lock. Потеря при крахе =
# максимум заходы за последние секунды; для аналитики поведения приемлемо.
import logging
import threading
from datetime import datetime

_log = logging.getLogger("oncount.usage")
_buffer: list[tuple[int, str, str, datetime]] = []
_lock = threading.Lock()
_MAX_BUFFER = 1000          # предохранитель от утечки памяти, если сброс не идёт
_admin_pid_cache: int | None = None   # -1 = админ-партнёр не найден


def _is_excluded(partner_id: int) -> bool:
    """Шум, который не трекаем: тестовые партнёры (конфиг) + сама Николь (по
    ADMIN_TG_ID). admin partner_id вычисляем один раз и кэшируем на процесс."""
    from app.config import settings
    if partner_id in settings.USAGE_EXCLUDE_PARTNER_IDS:
        return True
    global _admin_pid_cache
    if _admin_pid_cache is None:
        from app.db import SessionLocal
        from app.models import Partner
        s = SessionLocal()
        try:
            row = (
                s.query(Partner.id)
                .filter(Partner.telegram_id == settings.ADMIN_TG_ID)
                .first()
            )
            _admin_pid_cache = int(row[0]) if row else -1
        except Exception:
            _admin_pid_cache = -1  # не нашли — не блокируем трекинг
        finally:
            s.close()
    return partner_id == _admin_pid_cache


def record_view(partner_id: int, path: str, section: str) -> None:
    """Поставить заход в очередь на запись. Дёшево: только append под Lock."""
    if _is_excluded(partner_id):
        return
    with _lock:
        _buffer.append((partner_id, path, section, datetime.utcnow()))
        overflow = len(_buffer) >= _MAX_BUFFER
    if overflow:        # аварийный синхронный сброс, чтобы не течь в память
        flush_page_views()


def flush_page_views() -> int:
    """Сбросить накопленные заходы в БД одной пачкой. Возвращает число записей.
    Вызывается фоновым джобом раз в ~30с и на shutdown."""
    with _lock:
        if not _buffer:
            return 0
        batch = _buffer[:]
        _buffer.clear()
    from app.db import SessionLocal
    from app.models import PageView
    s = SessionLocal()
    try:
        s.add_all([
            PageView(partner_id=pid, path=p, section=sec, created_at=ts)
            for (pid, p, sec, ts) in batch
        ])
        s.commit()
        return len(batch)
    except Exception:
        s.rollback()
        # БД недоступна — теряем пачку (аналитика не критична), но не падаем и не
        # зацикливаемся на возврате в буфер.
        _log.warning("flush_page_views: не записали %d заходов", len(batch))
        return 0
    finally:
        s.close()


# ── Просмотры наружу (ТЗ маркетолога 2026-09-07, задача 2) ──────────────────
# Читающая часть той же таблицы: маршрут /admin/api/page-views отдаёт ARDORIUM
# только числа по запрошенным путям. Считается здесь, а не в main.py, чтобы
# форму ответа проверял тест без веб-стенда, а запись и чтение жили рядом:
# путь нормализует одна и та же classify_path, и что записано, то и найдётся.

# Сколько путей можно спросить одним запросом. Двадцать значений в IN — ещё
# запрос; тысяча — уже нагрузка, а открывает адрес статический токен.
PAGE_VIEW_PATHS_MAX = 20
# Путь длиннее столбца (PageView.path — String(128)) не совпадёт ни с чем;
# режем, чтобы не гонять километровый IN.
PAGE_VIEW_PATH_MAX = 128


def _has_control_chars(text: str) -> bool:
    """Любой символ ниже пробела (NUL, перевод строки, табуляция) или DEL (0x7f)."""
    return any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in text)


def normalize_view_path(raw: str | None) -> str | None:
    """Путь из query-строки → вид, в котором он лежит в page_views; None, если
    пусто. Известные страницы кабинета проходят через classify_path, как при
    записи (`/courses/ai-setup/day/2` → `/courses/:slug/day/:day`, хвостовой
    «/» снимается); незнакомый путь остаётся как есть — в таблице его нет, и
    строка с нулями честно это покажет.

    Путь с управляющими символами (NUL, перевод строки, табуляция, DEL) —
    тоже None, как пустой (приёмка 07.09): в таблице такого пути быть не
    может (браузер его не пришлёт), в IN-списке ему делать нечего, а NUL в
    строке — это ещё и повод для отказа драйвера Postgres. Проверка идёт по
    сырому значению, ДО strip: иначе «/a» с переводом строки на конце прошёл
    бы как «/a»."""
    raw = raw or ""
    if _has_control_chars(raw):
        return None
    p = raw.strip()[:PAGE_VIEW_PATH_MAX]
    if not p:
        return None
    hit = classify_path(p)
    if hit:
        return hit[0]
    return p.rstrip("/") or "/"


def day_iso(value) -> str:
    """Ключ дня из func.date(): SQLite (стенд) отдаёт строку 'YYYY-MM-DD',
    Postgres (бой) — date. Десять знаков одинаковы у обоих."""
    return str(value)[:10]


def page_view_counts(session, paths: list[str],
                     since: datetime | None = None) -> list[dict]:
    """Просмотры по каждому из `paths`: views, unique (разных partner_id), by_day.

    Строка на каждый запрошенный путь и в том же порядке, повторы схлопнуты:
    путь без единого захода даёт нули, а не пропадает — иначе читающая сторона
    не отличит «никто не открывал» от «не спросили». Два запроса на весь список,
    а не два на путь: `unique` за период не складывается из дневных, поэтому
    итог и дни считаются раздельно.

    Наружу — только путь и числа: ни partner_id, ни секции. Только чтение.
    """
    from sqlalchemy import distinct, func, select
    from app.models import PageView
    wanted = list(dict.fromkeys(paths))
    rows = {p: {"path": p, "views": 0, "unique": 0, "by_day": {}} for p in wanted}
    if not wanted:
        return []
    pv = PageView
    day = func.date(pv.created_at)
    totals = (select(pv.path, func.count(pv.id), func.count(distinct(pv.partner_id)))
              .where(pv.path.in_(wanted)).group_by(pv.path))
    days = (select(pv.path, day, func.count(pv.id))
            .where(pv.path.in_(wanted)).group_by(pv.path, day).order_by(pv.path, day))
    if since is not None:
        totals = totals.where(pv.created_at >= since)
        days = days.where(pv.created_at >= since)
    for path, views, unique in session.execute(totals):
        rows[path]["views"], rows[path]["unique"] = int(views), int(unique)
    for path, d, views in session.execute(days):
        rows[path]["by_day"][day_iso(d)] = int(views)
    return [rows[p] for p in wanted]
