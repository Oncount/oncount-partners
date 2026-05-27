"""Telegram Login Widget verification + JWT cookie session.

Поток:
1. Партнёр на /login видит TG Login Widget с data-auth-url=/auth/callback.
2. TG редиректит на /auth/callback?id=...&first_name=...&username=...&auth_date=...&hash=...
3. Мы пересчитываем HMAC от BOT_TOKEN и сверяем с hash.
4. Если ок — находим/создаём partner, выдаём JWT в HttpOnly cookie.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException, Request, status
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Partner, PartnerIdentity

COOKIE_NAME = "oncount_session"


def verify_telegram_auth(payload: dict) -> bool:
    """Проверка HMAC по протоколу Telegram Login Widget.

    https://core.telegram.org/widgets/login#checking-authorization
    """
    if "hash" not in payload:
        return False
    received_hash = payload["hash"]
    data = {k: v for k, v in payload.items() if k != "hash"}
    data_check_string = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    secret_key = hashlib.sha256(settings.BOT_TOKEN.encode()).digest()
    computed_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(computed_hash, received_hash):
        return False
    try:
        auth_date = int(payload.get("auth_date", "0"))
    except ValueError:
        return False
    if time.time() - auth_date > 86400:
        return False
    return True


def normalize_phone(raw: str) -> str:
    """Приводит телефон к каноничному виду для матчинга — только цифры, без `+`,
    пробелов, скобок и дефисов.

    Телефоны агентов в базе хранятся digits-only с кодом страны
    (`971505306356`), встречаются и российские. Сравнение идёт по цифрам, поэтому
    `+971 50 530 63 56`, `971505306356` и `00971505306356` сводятся к одному.
    Ведущие нули международного префикса (`00`) срезаются. Возвращает "" для мусора.
    """
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if digits.startswith("00"):
        digits = digits[2:]
    return digits


def phone_match_candidates(norm: str) -> list[str]:
    """Варианты хранения номера в Partner.phone для устойчивого матчинга.

    Partner.phone не нормализуется на лету в SQL, поэтому подбираем кандидатов:
    сами цифры и тот же номер с ведущим `+` (на случай, если где-то сохранён в
    E.164 с плюсом)."""
    if not norm:
        return []
    return [norm, f"+{norm}"]


def normalize_tg_username(raw: str) -> str:
    """tg_username для матчинга: lower, без ведущего `@` и пробелов."""
    return (raw or "").strip().lstrip("@").lower()


def find_partner_by_phone(session: Session, norm: str) -> Optional[Partner]:
    """Кабинет по нормализованному номеру (план 2026-05-27, Вариант А).

    Сначала ищем в `PartnerIdentity` (kind='phone', один кабинет → много номеров) —
    основной путь. Fallback на `Partner.phone` (основной номер/совместимость), оба
    формата хранения. Возвращает None для неизвестного номера — кабинет НЕ создаём."""
    if not norm:
        return None
    link = (
        session.query(PartnerIdentity)
        .filter(PartnerIdentity.kind == "phone", PartnerIdentity.value == norm)
        .first()
    )
    if link is not None:
        return session.get(Partner, link.partner_id)
    return (
        session.query(Partner)
        .filter(Partner.phone.in_(phone_match_candidates(norm)))
        .first()
    )


def hash_login_code(code: str) -> str:
    """hmac-sha256(code) с JWT_SECRET в роли перца. В базе лежит только хэш —
    утечка таблицы не отдаёт коды напрямую (а TTL+лимит попыток режут перебор)."""
    return hmac.new(
        settings.JWT_SECRET.encode(), code.encode(), hashlib.sha256
    ).hexdigest()


def verify_login_code(code: str, code_hash: str) -> bool:
    return hmac.compare_digest(hash_login_code(code), code_hash)


def issue_jwt(partner_id: int) -> str:
    expire = datetime.utcnow() + timedelta(days=settings.JWT_TTL_DAYS)
    return jwt.encode(
        {"sub": str(partner_id), "exp": expire},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGO,
    )


def decode_jwt(token: str) -> Optional[int]:
    try:
        data = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGO])
        return int(data["sub"])
    except (JWTError, KeyError, ValueError):
        return None


def current_partner(request: Request, session: Session) -> Optional[Partner]:
    """Возвращает Partner или None — НЕ кидает 401, шаблоны сами решают."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    partner_id = decode_jwt(token)
    if not partner_id:
        return None
    return session.get(Partner, partner_id)


def require_partner(partner: Optional[Partner]) -> Partner:
    if partner is None:
        raise HTTPException(status_code=status.HTTP_307_TEMPORARY_REDIRECT, headers={"Location": "/login"})
    return partner
