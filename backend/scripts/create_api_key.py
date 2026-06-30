"""Generate a new API key for the public API namespace.

Usage: python3 scripts/create_api_key.py "mi-otro-proyecto"
"""
from __future__ import annotations

import hashlib
import secrets
import sys

sys.path.insert(0, ".")

from app.db.connection import db_transaction  # noqa: E402
from app.db.migrations import run_migrations  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/create_api_key.py <label>")
        sys.exit(1)

    label = sys.argv[1]
    raw_key = f"om26_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    run_migrations()
    with db_transaction() as conn:
        from app.db.repositories.api_keys import ApiKeyRepository
        ApiKeyRepository(conn).create(key_hash, label)

    print(f"API key creada para '{label}':")
    print(f"  {raw_key}")
    print("\nGuárdala ahora — no se puede recuperar después (solo se guarda el hash).")


if __name__ == "__main__":
    main()
