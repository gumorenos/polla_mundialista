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
ADMIN_HASH_ALGORITHM = "pbkdf2_sha256"
ADMIN_HASH_ITERATIONS = 200_000


class LoginRequest(BaseModel):
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=128)


def _hash_password(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# Keep old name as alias so dependencies.py import doesn't break
_hash_token = _hash_password


def _hash_admin_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt.encode(),
        ADMIN_HASH_ITERATIONS,
    ).hex()
    return f"{ADMIN_HASH_ALGORITHM}${ADMIN_HASH_ITERATIONS}${salt}${digest}"


def _verify_admin_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt, expected = stored_hash.split("$", 3)
        iterations = int(iterations_raw)
    except ValueError:
        # Backward-compatible support for legacy sha256 hex rows.
        return secrets.compare_digest(_hash_password(password), stored_hash)
    if algorithm != ADMIN_HASH_ALGORITHM:
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt.encode(),
        iterations,
    ).hex()
    return secrets.compare_digest(actual, expected)


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


def _verify_password(password: str, stored_hash: str | None) -> bool:
    if stored_hash is not None:
        return _verify_admin_password(password, stored_hash)
    if not settings.ADMIN_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin password not configured. Set ADMIN_PASSWORD in environment.",
        )
    return secrets.compare_digest(password, settings.ADMIN_PASSWORD)


@router.post("/api/auth/login")
async def login(body: LoginRequest, response: Response) -> dict:
    """Verify ADMIN_PASSWORD and set an httpOnly session cookie.

    Returns must_change_password=true when no durable admin credential exists,
    prompting the user to set the first real password.
    """
    from app.db.connection import db_transaction
    from app.db.repositories.auth import get_admin_password_hash

    with db_transaction() as conn:
        stored_hash = get_admin_password_hash(conn)
        must_change = stored_hash is None

    if not _verify_password(body.password, stored_hash):
        logger.warning("Failed admin login attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Contraseña incorrecta",
        )

    session_token = _create_session(must_change_password=must_change)

    response.set_cookie(
        key="admin_session",
        value=session_token,
        httponly=True,
        secure=settings.ENVIRONMENT == "production",
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

    from app.db.connection import db_transaction
    from app.db.repositories.auth import (
        get_admin_password_hash,
        insert_password_history,
        upsert_admin_credential,
    )

    with db_transaction() as conn:
        stored_hash = get_admin_password_hash(conn)

    if not _verify_password(body.old_password, stored_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Contraseña actual incorrecta",
        )

    with db_transaction() as conn:
        insert_password_history(
            conn,
            "admin_ui",
            _hash_admin_password(body.old_password),
            note="admin password changed from web UI",
        )
        upsert_admin_credential(conn, _hash_admin_password(body.new_password))
        conn.commit()

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
    """Return whether the web admin password has a durable credential."""
    from app.db.connection import db_transaction
    from app.db.repositories.auth import has_admin_credential

    with db_transaction() as conn:
        changed = has_admin_credential(conn)
    return {"password_changed": changed}
