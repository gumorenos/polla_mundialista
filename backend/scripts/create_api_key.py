"""Generate a new API key for the public API namespace.

Usage: python3 scripts/create_api_key.py "mi-otro-proyecto" [scopes] [rate_limit]

Uses the same ApiKeyRepository.create_with_prefix() as the admin UI
(POST /api/admin/api-keys), so keys created here show up identically in
the admin API keys listing (prefix, scopes, rate limit, notes).
"""
from __future__ import annotations

import hashlib
import secrets
import sys

sys.path.insert(0, ".")

from app.db.connection import db_transaction  # noqa: E402
from app.db.migrations import run_migrations  # noqa: E402

_PREFIX_LEN = 12


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/create_api_key.py <label> [scopes=read] [rate_limit=60]")
        sys.exit(1)

    label = sys.argv[1]
    scopes = sys.argv[2] if len(sys.argv) > 2 else "read"
    rate_limit = int(sys.argv[3]) if len(sys.argv) > 3 else 60

    raw_key = f"om26_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    prefix = raw_key[:_PREFIX_LEN]

    run_migrations()
    with db_transaction() as conn:
        from app.db.repositories.api_keys import ApiKeyRepository
        ApiKeyRepository(conn).create_with_prefix(
            key_hash, prefix, label, scopes=scopes, rate_limit_per_minute=rate_limit,
        )

    print(f"API key creada para '{label}' (scopes={scopes}, rate_limit={rate_limit}/min):")
    print(f"  {raw_key}")
    print("\nGuárdala ahora — no se puede recuperar después (solo se guarda el hash).")


if __name__ == "__main__":
    main()
