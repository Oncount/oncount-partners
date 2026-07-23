"""Тест классификации путей трекинга (план 2026-06-03, Фаза 1).

Запуск без pytest:  python tests/test_usage.py
Под pytest (когда поставят):  pytest tests/test_usage.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.usage import classify_path, SECTION_LABELS


def test_tracked_static_pages():
    assert classify_path("/dashboard") == ("/dashboard", "dashboard")
    assert classify_path("/leads") == ("/leads", "leads")
    assert classify_path("/tools") == ("/tools", "tools")
    assert classify_path("/products") == ("/products", "kb")
    assert classify_path("/faq") == ("/faq", "kb")
    assert classify_path("/transfer") == ("/transfer", "transfer")
    assert classify_path("/account") == ("/account", "account")


def test_onboarding_grouped():
    assert classify_path("/onboarding") == ("/onboarding", "onboarding")
    assert classify_path("/onboarding-survey") == ("/onboarding-survey", "onboarding")


def test_kb_aliases():
    assert classify_path("/kb/products") == ("/kb/products", "kb")
    assert classify_path("/kb/faq") == ("/kb/faq", "kb")
    assert classify_path("/kb/courses") == ("/kb/courses", "courses")


def test_courses_dynamic_collapse():
    assert classify_path("/courses") == ("/courses", "courses")
    assert classify_path("/courses/ai-setup") == ("/courses/:slug", "courses")
    assert classify_path("/courses/ai-setup/day/2") == ("/courses/:slug/day/:day", "courses")
    # мусорная глубина под /courses не трекается
    assert classify_path("/courses/a/b/c/d") is None


def test_trailing_slash_and_root():
    assert classify_path("/dashboard/") == ("/dashboard", "dashboard")
    assert classify_path("/") is None
    assert classify_path("") is None


def test_blacklisted_paths_not_tracked():
    # Лендинги, служебка, вход, реф-редиректы, админка — НЕ трекаем (белый список).
    for p in (
        "/", "/static/css/oncount.css", "/healthz", "/debug/event-stats",
        "/admin/partner-stats", "/admin/partner/7", "/auth/email/callback",
        "/login", "/logout", "/invite/abc", "/join", "/consultation", "/mk",
        "/guide/corp-tax", "/ct/xyz", "/cw/xyz", "/mt/xyz", "/mw/xyz", "/p/xyz",
        "/links", "/messages", "/kits",
    ):
        assert classify_path(p) is None, f"{p} не должен трекаться"


def test_every_section_has_label():
    sections = set()
    for p in ("/dashboard", "/leads", "/tools", "/products", "/courses",
              "/transfer", "/account", "/onboarding"):
        res = classify_path(p)
        assert res is not None
        sections.add(res[1])
    for s in sections:
        assert s in SECTION_LABELS, f"секция {s} без ярлыка"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} тестов пройдено.")
