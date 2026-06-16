"""Admin session authentication — login/logout/status/change-password via httpOnly cookie.

Login uses ADMIN_PASSWORD (friendly passphrase, set in .env).
API scripts continue to use ADMIN_TOKEN via X-Admin-Token header.
"""

from __future__ import annotations

import hashlib
import json
import secrets

from fastapi import APIRouter, Cookie, HTTPException, Response, status
from pydantic import BaseModel, Field
from redis import Redis

from app.core.config import settings
from app.core.logging import get_logger

router = APIRouter(tags=["auth"])
logger = get_logger(__name__)

# Kept only as a compatibility hook for older tests/imports. Sessions are
# persisted in Redis so they survive API container restarts.
_active_sessions: dict[str, dict] = {}
SESSION_TTL_SECONDS = 86400 * 7
SESSION_KEY_PREFIX = "session:"


class LoginRequest(BaseModel):
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=128)


def _hash_password(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# Keep old name as alias so dependencies.py import doesn't break
_hash_token = _hash_password


def _session_key(token_hash: str) -> str:
    return f"{SESSION_KEY_PREFIX}{token_hash}"


def _session_redis():
    return Redis.from_url(settings.REDIS_URL, decode_responses=True)


def _create_session(must_change_password: bool = False) -> str:
    token = secrets.token_hex(32)
    token_hash = _hash_password(token)
    payload = json.dumps({"must_change_password": must_change_password})
    try:
        _session_redis().setex(
            _session_key(token_hash),
            SESSION_TTL_SECONDS,
            payload,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Could not create Redis-backed admin session: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo crear la sesión",
        ) from exc
    return token


def _get_session(admin_session: str) -> dict | None:
    if not admin_session:
        return None
    token_hash = _hash_password(admin_session)
    try:
        raw = _session_redis().get(_session_key(token_hash))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read Redis-backed admin session: %s", exc)
        return None
    if not raw:
        return None
    try:
        session = json.loads(raw)
    except json.JSONDecodeError:
        session = {"must_change_password": False}
    return session if isinstance(session, dict) else None


def _update_session(admin_session: str, must_change_password: bool) -> None:
    token_hash = _hash_password(admin_session)
    payload = json.dumps({"must_change_password": must_change_password})
    _session_redis().setex(
        _session_key(token_hash),
        SESSION_TTL_SECONDS,
        payload,
    )


def _delete_session(admin_session: str) -> None:
    token_hash = _hash_password(admin_session)
    try:
        _session_redis().delete(_session_key(token_hash))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not delete Redis-backed admin session: %s", exc)


def is_session_valid(admin_session: str) -> bool:
    return _get_session(admin_session) is not None


@router.post("/api/auth/login")
async def login(body: LoginRequest, response: Response) -> dict:
    """Verify ADMIN_PASSWORD and set an httpOnly session cookie.

    Returns must_change_password=true when no successful password change has
    ever been recorded, prompting the user to set the first real password.
    """
    if not settings.ADMIN_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin password not configured. Set ADMIN_PASSWORD in environment.",
        )
    if not secrets.compare_digest(body.password, settings.ADMIN_PASSWORD):
        logger.warning("Failed admin login attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Contraseña incorrecta",
        )

    from app.db.connection import db_transaction
    from app.db.repositories.auth import has_password_change_history

    with db_transaction() as conn:
        must_change = not has_password_change_history(conn)

    session_token = _create_session(must_change_password=must_change)

    response.set_cookie(
        key="admin_session",
        value=session_token,
        httponly=True,
        secure=False,  # Cloudflare terminates HTTPS; backend sees internal HTTP.
        samesite="lax",
        max_age=SESSION_TTL_SECONDS,
        path="/",
    )
    logger.info("Admin login successful (must_change_password=%s)", must_change)
    return {"status": "ok", "must_change_password": must_change}


@router.post("/api/auth/change-password")
async def change_password(
    body: ChangePasswordRequest,
    admin_session: str = Cookie(default=""),
) -> dict:
    """Change the admin password immediately and record it in the audit log."""
    session = _get_session(admin_session)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesión no válida",
        )
    if not secrets.compare_digest(body.old_password, settings.ADMIN_PASSWORD):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Contraseña actual incorrecta",
        )

    from app.db.connection import db_transaction
    from app.db.repositories.auth import insert_password_history
    with db_transaction() as conn:
        insert_password_history(
            conn,
            "admin_ui",
            _hash_password(body.old_password),
            note="admin password changed from web UI",
        )
        conn.commit()

    settings.ADMIN_PASSWORD = body.new_password
    _update_session(admin_session, must_change_password=False)

    logger.info("Admin password changed successfully")
    return {
        "status": "ok",
        "message": "Contraseña cambiada exitosamente",
    }


@router.post("/api/auth/logout")
async def logout(
    response: Response,
    admin_session: str = Cookie(default=""),
) -> dict:
    """Invalidate the current session cookie."""
    if admin_session:
        _delete_session(admin_session)
    response.delete_cookie("admin_session", path="/")
    return {"status": "ok"}


@router.get("/api/auth/status")
async def auth_status(admin_session: str = Cookie(default="")) -> dict:
    """Return whether the current request has a valid admin session."""
    session = _get_session(admin_session)
    if not session:
        return {"authenticated": False, "must_change_password": False}
    return {
        "authenticated": True,
        "must_change_password": session.get("must_change_password", False),
    }


@router.get("/api/auth/password-changed")
async def password_changed() -> dict:
    """Return whether at least one admin password change has been recorded."""
    from app.db.connection import db_transaction
    from app.db.repositories.auth import has_password_change_history

    with db_transaction() as conn:
        changed = has_password_change_history(conn)
    return {"password_changed": changed}
