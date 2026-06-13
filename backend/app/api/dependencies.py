"""Shared FastAPI dependency functions."""

from __future__ import annotations

from fastapi import Header, HTTPException, status

from app.core.config import settings


def require_admin(x_admin_token: str = Header(default="")) -> None:
    """Fail-closed admin auth dependency.

    Raises 503 if ADMIN_TOKEN is not configured (force-open would be a security hole).
    Raises 403 if the header doesn't match.
    """
    if not settings.ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin token not configured. Set ADMIN_TOKEN in environment.",
        )
    if x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing admin token.",
        )
