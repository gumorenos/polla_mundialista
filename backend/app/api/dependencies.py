"""Shared FastAPI dependency functions."""

from __future__ import annotations

import hashlib
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


def require_api_key(x_api_key: str = Header(default="")) -> str:
    """Validate X-API-Key header against the api_keys table.

    Separate from require_admin — used only by the public read-only
    namespace (/api/public/v1/*), never accepts admin tokens or cookies.

    Returns the key's label on success (for logging). Raises 401 if
    missing/invalid, 403 if revoked.
    """
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )

    key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()

    from app.db.connection import db_transaction
    from app.db.repositories.api_keys import ApiKeyRepository

    with db_transaction() as conn:
        repo = ApiKeyRepository(conn)
        row = repo.get_by_hash(key_hash)
        if not row:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )
        if row["revoked"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="API key revoked",
            )
        repo.touch_last_used(row["id"])

    return row["label"]
