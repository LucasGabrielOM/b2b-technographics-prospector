from __future__ import annotations

import base64
import hmac
import json
import os
import time
from dataclasses import dataclass
from hashlib import pbkdf2_hmac, sha256

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .models import PortalUser

SESSION_COOKIE = "leadpilot_session"
PASSWORD_ITERATIONS = 390_000


@dataclass(frozen=True)
class PortalIdentity:
    username: str
    display_name: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def as_dict(self) -> dict[str, str | bool]:
        return {
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role,
            "is_admin": self.is_admin,
        }


def _session_payload(identity: PortalIdentity, expires_at: int) -> bytes:
    return json.dumps(
        {
            "u": identity.username,
            "n": identity.display_name,
            "r": identity.role,
            "exp": expires_at,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def create_session_token(identity: PortalIdentity, secret: str, ttl_seconds: int) -> str:
    expires_at = int(time.time()) + ttl_seconds
    payload = _session_payload(identity, expires_at)
    signature = hmac.new(secret.encode("utf-8"), payload, sha256).hexdigest()
    encoded = base64.urlsafe_b64encode(payload).decode("ascii")
    return f"{encoded}.{signature}"


def verify_session_token(token: str | None, secret: str) -> PortalIdentity | None:
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
    username = str(data.get("u") or "").strip()
    if not username:
        return None
    role = str(data.get("r") or "user")
    display_name = str(data.get("n") or username)
    return PortalIdentity(username=username, display_name=display_name, role=role)


def portal_settings(settings: Settings) -> tuple[str, str, str, int, bool]:
    username = settings.portal_username or "admin"
    password = settings.portal_password or "demo1234"
    secret = settings.portal_secret or "change-me-in-production"
    ttl_days = max(1, int(settings.portal_session_days or 7))
    secure_cookie = bool(settings.portal_cookie_secure)
    return username, password, secret, ttl_days * 86400, secure_cookie


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    derived = pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(derived).decode("ascii"),
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, encoded_salt, encoded_hash = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(encoded_salt.encode("ascii"))
        expected = base64.urlsafe_b64decode(encoded_hash.encode("ascii"))
        derived = pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(derived, expected)
    except (ValueError, TypeError):
        return False


def authenticate(username: str, password: str, settings: Settings, db: Session) -> PortalIdentity | None:
    normalized_username = username.strip().lower()
    expected_username, expected_password, _, _, _ = portal_settings(settings)
    if (
        hmac.compare_digest(normalized_username, expected_username.strip().lower())
        and hmac.compare_digest(password, expected_password)
    ):
        return PortalIdentity(
            username=expected_username,
            display_name=settings.portal_admin_display_name or "Administrador",
            role="admin",
        )
    user = db.scalar(select(PortalUser).where(PortalUser.username == normalized_username))
    if not user or not user.active or not verify_password(password, user.password_hash):
        return None
    return PortalIdentity(username=user.username, display_name=user.display_name, role=user.role)


def require_portal_user(request: Request, settings: Settings) -> PortalIdentity:
    _, _, secret, _, _ = portal_settings(settings)
    identity = verify_session_token(request.cookies.get(SESSION_COOKIE), secret)
    if not identity:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Acesso não autenticado")
    return identity


def require_portal_admin(request: Request, settings: Settings) -> PortalIdentity:
    identity = require_portal_user(request, settings)
    if not identity.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso exclusivo do administrador")
    return identity
