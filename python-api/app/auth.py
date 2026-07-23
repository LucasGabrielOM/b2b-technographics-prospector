from __future__ import annotations

import base64
import hmac
import json
import time
from hashlib import sha256

from fastapi import HTTPException, Request, status

from .config import Settings

SESSION_COOKIE = "leadpilot_session"


def _session_payload(username: str, expires_at: int) -> bytes:
    return json.dumps({"u": username, "exp": expires_at}, separators=(",", ":"), sort_keys=True).encode("utf-8")


def create_session_token(username: str, secret: str, ttl_seconds: int) -> str:
    expires_at = int(time.time()) + ttl_seconds
    payload = _session_payload(username, expires_at)
    signature = hmac.new(secret.encode("utf-8"), payload, sha256).hexdigest()
    encoded = base64.urlsafe_b64encode(payload).decode("ascii")
    return f"{encoded}.{signature}"


def verify_session_token(token: str | None, secret: str) -> str | None:
    if not token or "." not in token:
        return None
    encoded, signature = token.rsplit(".", 1)
    try:
        payload = base64.urlsafe_b64decode(encoded.encode("ascii"))
        data = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    expected = hmac.new(secret.encode("utf-8"), payload, sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None
    if int(data.get("exp", 0)) < int(time.time()):
        return None
    username = data.get("u")
    return str(username) if username else None


def portal_settings(settings: Settings) -> tuple[str, str, str, int, bool]:
    username = settings.portal_username or "admin"
    password = settings.portal_password or "demo1234"
    secret = settings.portal_secret or "change-me-in-production"
    ttl_days = max(1, int(settings.portal_session_days or 7))
    secure_cookie = bool(settings.portal_cookie_secure)
    return username, password, secret, ttl_days * 86400, secure_cookie


def authenticate(username: str, password: str, settings: Settings) -> bool:
    expected_username, expected_password, _, _, _ = portal_settings(settings)
    return hmac.compare_digest(username, expected_username) and hmac.compare_digest(password, expected_password)


def require_portal_user(request: Request, settings: Settings) -> str:
    _, _, secret, _, _ = portal_settings(settings)
    username = verify_session_token(request.cookies.get(SESSION_COOKIE), secret)
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Acesso nao autenticado")
    return username
