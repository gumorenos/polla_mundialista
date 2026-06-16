"""Admin session authentication — login/logout/status/change-password via httpOnly cookie.

Login uses ADMIN_PASSWORD (friendly passphrase, set in .env).
API scripts continue to use ADMIN_TOKEN via X-Admin-Token header.
"""

from __future__ import annotations

import hashlib
import secrets
import threading

from fastapi import APIRouter, Cookie, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.logging import get_logger

router = APIRouter(tags=["auth"])
logger = get_logger(__name__)

# Session store: { token_hash: { "must_change_password": bool } }
_active_sessions: dict[str, dict] = {}
_sessions_lock = threading.Lock()


class LoginRequest(BaseModel):
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=128)


def _hash_password(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# Keep old name as alias so dependencies.py import doesn't break
_hash_token = _hash_password


def _create_session(must_change_password: bool = False) -> str:
    token = secrets.token_hex(32)
    token_hash = _hash_password(token)
    with _sessions_lock:
        _active_sessions[token_hash] = {"must_change_password": must_change_password}
    return token


def _is_placeholder(password: str) -> bool:
    return password in ("", "change_me_in_production") or len(password) < 6


@router.post("/api/auth/login")
async def login(body: LoginRequest, response: Response) -> dict:
    """Verify ADMIN_PASSWORD and set an httpOnly session cookie.

    Returns must_change_password=true when the password looks like a default
    placeholder, prompting the user to set a real one.
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

    must_change = _is_placeholder(body.password)
    session_token = _create_session(must_change_password=must_change)

    response.set_cookie(
        key="admin_session",
        value=session_token,
        httponly=True,
        secure=settings.ENVIRONMENT == "production",
        samesite="strict",
        max_age=86400,
        path="/",
    )
    logger.info("Admin login successful (must_change_password=%s)", must_change)
    return {"status": "ok", "must_change_password": must_change}


@router.post("/api/auth/change-password")
async def change_password(
    body: ChangePasswordRequest,
    admin_session: str = Cookie(default=""),
) -> dict:
    """Register a password change in the audit log.

    The new password only takes effect after updating ADMIN_PASSWORD in .env
    and restarting the container. This endpoint records the intent and audits
    the old hash.
    """
    token_hash = _hash_password(admin_session) if admin_session else ""
    with _sessions_lock:
        session = _active_sessions.get(token_hash)
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
        insert_password_history(conn, "admin_ui", _hash_password(body.old_password))
        conn.commit()

    # Mark session as no longer requiring a password change
    with _sessions_lock:
        if token_hash in _active_sessions:
            _active_sessions[token_hash]["must_change_password"] = False

    logger.info("Admin password change registered — update ADMIN_PASSWORD in .env and restart")
    return {
        "status": "ok",
        "message": (
            "Cambio registrado. Actualiza ADMIN_PASSWORD en .env "
            "y reinicia el contenedor para que tome efecto."
        ),
    }


@router.post("/api/auth/logout")
async def logout(
    response: Response,
    admin_session: str = Cookie(default=""),
) -> dict:
    """Invalidate the current session cookie."""
    if admin_session:
        token_hash = _hash_password(admin_session)
        with _sessions_lock:
            _active_sessions.pop(token_hash, None)
    response.delete_cookie("admin_session", path="/")
    return {"status": "ok"}


@router.get("/api/auth/status")
async def auth_status(admin_session: str = Cookie(default="")) -> dict:
    """Return whether the current request has a valid admin session."""
    if not admin_session:
        return {"authenticated": False, "must_change_password": False}
    token_hash = _hash_password(admin_session)
    with _sessions_lock:
        session = _active_sessions.get(token_hash)
    if not session:
        return {"authenticated": False, "must_change_password": False}
    return {
        "authenticated": True,
        "must_change_password": session.get("must_change_password", False),
    }
