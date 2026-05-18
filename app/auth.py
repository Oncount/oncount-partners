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

from fastapi import Cookie, HTTPException, Request, status
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Partner

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


def current_partner(
    request: Request,
    session: Session,
    session_cookie: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
) -> Optional[Partner]:
    """Возвращает Partner или None — НЕ кидает 401, шаблоны сами решают."""
    token = session_cookie or request.cookies.get(COOKIE_NAME)
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
