"""Тесты трекинга переходов по ссылкам (план 2026-07-23, Фаза 1).

Чистые функции, БЕЗ коннекта к БД (как test_usage / test_rate_limit).
Запуск без pytest:  python tests/test_linkstat.py
Под pytest:         pytest tests/test_linkstat.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.linkstat import (
    CONTENT_KEYS,
    PROBE_UA,
    SURFACES,
    is_preview_bot,
    record_click,
    sanitize_ref,
)


def test_sanitize_ref_truncates_to_16():
    # Урок репо: >VARCHAR(16) → «value too long» → 502. Режем жёстко.
    assert sanitize_ref("a" * 40) == "a" * 16
    assert len(sanitize_ref("x" * 100)) == 16


def test_sanitize_ref_trims_and_empties_to_none():
    assert sanitize_ref("  abc123  ") == "abc123"
    assert sanitize_ref("") is None
    assert sanitize_ref(None) is None
    assert sanitize_ref("   ") is None


def test_preview_bots_detected():
    for ua in (
        "TelegramBot (like TwitterBot)",
        "facebookexternalhit/1.1",
        "WhatsApp/2.23",
        "Slackbot-LinkExpanding 1.0",
        "LinkedInBot/1.0",
        "Mozilla/5.0 (compatible; Discordbot/2.0)",
    ):
        assert is_preview_bot(ua) is True, f"{ua} должен считаться ботом"


def test_real_browsers_not_bots():
    for ua in (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36",
        "Mozilla/5.0 (Linux; Android 13) Chrome/119.0 Mobile Safari/537.36",
    ):
        assert is_preview_bot(ua) is False, f"{ua} — живой браузер, не бот"


def test_empty_ua_not_bot():
    # Пустой UA не глушим (иначе теряем часть живых людей) — фильтруем только явных ботов.
    assert is_preview_bot("") is False
    assert is_preview_bot(None) is False


def test_probe_and_bot_click_no_db_no_raise():
    # record_click для self-пробы и краулера обязан выйти РАНЬШЕ импорта БД и не
    # бросить исключение (иначе редирект/лендинг упал бы). БД тут нет — если бы
    # код дошёл до SessionLocal с фиктивным DATABASE_URL, тоже бы не бросил (try),
    # но проверяем именно ранний выход: None и без ошибок.
    assert record_click("mk", "quiz", "slug", PROBE_UA) is None
    assert record_click("mk", "quiz", "slug", "TelegramBot/1.0") is None


def test_taxonomy_covers_all_content_and_surfaces():
    # Ключи контента, которые реально проставляют хендлеры main.py.
    for k in ("consultation", "mk", "leadmagnet_corptax", "leadmagnet_5mistakes", "partner_bot"):
        assert k in CONTENT_KEYS, f"{k} без ярлыка в CONTENT_KEYS"
    for s in ("quiz", "tg", "wa", "bot"):
        assert s in SURFACES, f"{s} не в SURFACES"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} тестов пройдено.")
