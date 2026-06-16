"""Admin session authentication — login/logout/status via httpOnly cookie.

The same ADMIN_TOKEN secret is used as the password. After login the client
receives a signed session cookie that is not readable from JavaScript.
"""

from __future__ import annotations

import hashlib
import secrets

from fastapi import APIRouter, Cookie, HTTPException, Response, status
from pydantic import BaseModel

from app.core.config import settings
from app.core.logging import get_logger

router = APIRouter(tags=["auth"])
logger = get_logger(__name__)

# In-memory session store — sufficient for single-server personal use.
# Sessions are lost on container restart; users must log in again after deploys.
_active_sessions: set[str] = set()


class LoginRequest(BaseModel):
    password: str


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.post("/api/auth/login")
async def login(body: LoginRequest, response: Response) -> dict:
    """Verify admin password and set an httpOnly session cookie."""
    if not settings.ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin not configured",
        )
    if not secrets.compare_digest(body.password, settings.ADMIN_TOKEN):
        logger.warning("Failed admin login attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Contraseña incorrecta",
        )

    session_token = secrets.token_hex(32)
    _active_sessions.add(_hash_token(session_token))

    response.set_cookie(
        key="admin_session",
        value=session_token,
        httponly=True,
        secure=settings.ENVIRONMENT == "production",
        samesite="strict",
        max_age=86400,
        path="/",
    )
    logger.info("Admin login successful")
    return {"status": "ok"}


@router.post("/api/auth/logout")
async def logout(
    response: Response,
    admin_session: str = Cookie(default=""),
) -> dict:
    """Invalidate the current session cookie."""
    if admin_session:
        _active_sessions.discard(_hash_token(admin_session))
    response.delete_cookie("admin_session", path="/")
    return {"status": "ok"}


@router.get("/api/auth/status")
async def auth_status(admin_session: str = Cookie(default="")) -> dict:
    """Return whether the current request has a valid admin session."""
    is_auth = (
        bool(admin_session) and _hash_token(admin_session) in _active_sessions
    )
    return {"authenticated": is_auth}
