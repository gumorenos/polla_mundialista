"""Shared FastAPI dependency functions."""

from __future__ import annotations

import secrets

from fastapi import Cookie, Header, HTTPException, status

from app.core.config import settings


def require_admin(
    x_admin_token: str = Header(default=""),
    admin_session: str = Cookie(default=""),
) -> None:
    """Accept admin auth via either:
    1. Cookie session set by POST /api/auth/login (frontend after login)
    2. X-Admin-Token header (scripts, curl, direct API access)

    Raises 503 if ADMIN_TOKEN is not configured (fail-closed).
    Raises 403 if neither auth method is valid.
    """
    if not settings.ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin token not configured. Set ADMIN_TOKEN in environment.",
        )

    # Header-based auth (scripts / curl)
    if x_admin_token and secrets.compare_digest(x_admin_token, settings.ADMIN_TOKEN):
        return

    # Cookie-based auth (frontend after login)
    if admin_session:
        from app.api.routes.auth import is_session_valid
        if is_session_valid(admin_session):
            return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="No autorizado",
    )
