"""Валидатор «money-words» для китов партнёра (Фаза J, план 2026-05-27).

Тексты китов (`MessageTemplate.partner_type IS NOT NULL`) партнёр КОПИРУЕТ и шлёт
КЛИЕНТУ. В них не должно быть слов о заработке партнёра («комиссия / commission /
referral fee / партнёрское вознаграждение»): ресёч ЦА2 (ca2-partners-atypica-
2026-05-27.md) показал, что это отпугивает клиента и компрометирует партнёра.
Валидатор — машинная страховка на сидинге (и при будущем ручном upsert):
финальный кит со стоп-словом не попадёт в `body_md` / `body_md_en`.

⚠️ ТОЛЬКО ДЛЯ КИТОВ. НЕ для генерик `/messages` (partner_type IS NULL), НЕ для
текстов кабинета/дайджеста/win-пуша — там «партнёрское вознаграждение / partner
reward» РАЗРЕШЕНО (это видит сам партнёр, Фаза K). Иначе сломается Фаза K.

Подход (согласован 2026-06-02):
  • RU — case-insensitive substring по СТЕМАМ (русские склонения дёшево не берутся
    word-boundary: комиссия/комиссии/комиссию/комиссионные — один стем «комисси»).
  • EN — case-insensitive word-boundary regex (не путает «commission» с
    «commissioner»/«commissioned»; ловит формы мн.ч. через `s?`).
Разрешено и НЕ триггерит: рекомендация / introduce / introducer / знакомство /
ONCOUNT / partnership (одиночный «introducer» — ок; «introducer reward» — нет,
блокируется как фраза целиком).
"""
import logging
import re

log = logging.getLogger(__name__)

# ─── Стоп-лист money-words в ОДНОМ месте (как LEAD_STAGES / PARTNER_TYPES) ───
# RU: стемы для substring-проверки по тексту в нижнем регистре.
MONEY_WORDS_BLOCKED_RU: tuple[str, ...] = (
    "комисси",                      # комиссия/комиссии/комиссию/комиссионные/комиссионных
    "реферал",                      # реферал/реферальная/рефералов
    "референц",                     # референция (рус. калька reference fee)
    "референс",                     # референс
    "реф-ссылк",                    # реф-ссылка/реф-ссылки
    "реф-код",                      # реф-код/реф-кода
    "откат",                        # = kickback (откат/откатом)
    "партнёрское вознаграждение",   # запрещено в тексте ДЛЯ КЛИЕНТА (в кабинете — ок)
    "партнерское вознаграждение",   # вариант без ё
)

# EN: альтернативы для одного word-boundary regex (плюрал через `s?`).
MONEY_WORDS_BLOCKED_EN: tuple[str, ...] = (
    r"commissions?",
    r"affiliates?",
    r"referral fees?",
    r"kickbacks?",
    r"introducer rewards?",
    r"partner rewards?",
    r"finder'?s fees?",
    r"revenue shares?",
    r"side income",
)

_EN_RE = re.compile(r"\b(?:" + "|".join(MONEY_WORDS_BLOCKED_EN) + r")\b", re.IGNORECASE)


def find_money_words(body_md: str | None, body_md_en: str | None) -> list[tuple[str, str]]:
    """Найти все стоп-слова. Вернуть [(field, matched), ...]; пустой список = чисто.

    field ∈ {'body_md', 'body_md_en'}. Не бросает — это «сырая» проверка,
    переиспользуется и валидатором-страховкой, и READ-ONLY скриптом менеджера.
    """
    found: list[tuple[str, str]] = []
    for field, text in (("body_md", body_md), ("body_md_en", body_md_en)):
        if not text:
            continue
        low = text.lower()
        for stem in MONEY_WORDS_BLOCKED_RU:
            if stem in low:
                found.append((field, stem))
        for m in _EN_RE.finditer(text):
            found.append((field, m.group(0)))
    return found


def _kit_body_clean(body_md: str | None, body_md_en: str | None, slug: str) -> bool:
    """Страховка для тела кита. True если чисто.

    • non-draft кит со стоп-словом → `raise ValueError` (сидер падает явно, чем
      тихо записать в БД текст с «комиссией» под копирование клиенту).
    • draft-кит (`slug` оканчивается на `-draft`) → `log.warning` + ПРОПУСК:
      черновики уже защищены (плашка + блок копирования, Фаза C), а в их теле
      слова стоп-листа валидны как описание-рыба (напр. Фаза G «без единого
      слова про мотив»).
    """
    violations = find_money_words(body_md, body_md_en)
    if not violations:
        return True
    detail = "; ".join(f"{field}: «{word}»" for field, word in violations)
    if (slug or "").endswith("-draft"):
        log.warning(
            "kind=kit_validator action=skip_draft slug=%s found=%s", slug, detail
        )
        return True
    log.error("kind=kit_validator action=block slug=%s found=%s", slug, detail)
    raise ValueError(
        f"Кит '{slug}': money-words в тексте для клиента — {detail}. "
        f"Перепиши на партнёрский тон (рекомендация / introduce), "
        f"либо это должен быть черновик (slug *-draft)."
    )
