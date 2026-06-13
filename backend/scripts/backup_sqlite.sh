#!/usr/bin/env bash
# backup_sqlite.sh — Online SQLite backup using .backup command (WAL-safe).
# Compresses with gzip and retains only the last MAX_BACKUPS archives.
#
# Usage:
#   bash backend/scripts/backup_sqlite.sh
#   SQLITE_PATH=/custom/path.db bash backend/scripts/backup_sqlite.sh
set -euo pipefail

DB_PATH="${SQLITE_PATH:-data/sqlite/oraculo.db}"
BACKUP_DIR="data/backups"
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
TMP_FILE="${BACKUP_DIR}/oraculo_${TIMESTAMP}.db"
FINAL_FILE="${TMP_FILE}.gz"
MAX_BACKUPS=7

# -- Validate source -------------------------------------------------------
if [[ ! -f "$DB_PATH" ]]; then
    echo "ERROR: database not found at '$DB_PATH'" >&2
    exit 1
fi

if ! command -v sqlite3 &>/dev/null; then
    echo "ERROR: sqlite3 not found in PATH" >&2
    exit 1
fi

# -- Create backup dir if needed -------------------------------------------
mkdir -p "$BACKUP_DIR"

# -- Online backup (safe while writers hold WAL locks) ---------------------
sqlite3 "$DB_PATH" ".backup '${TMP_FILE}'"

# -- Compress --------------------------------------------------------------
gzip --best "$TMP_FILE"

echo "[backup] Created: $FINAL_FILE ($(du -h "$FINAL_FILE" | cut -f1))"

# -- Prune old backups (keep last MAX_BACKUPS) -----------------------------
mapfile -t OLD < <(ls -t "${BACKUP_DIR}"/oraculo_*.db.gz 2>/dev/null | tail -n +$((MAX_BACKUPS + 1)))
if [[ ${#OLD[@]} -gt 0 ]]; then
    rm -- "${OLD[@]}"
    echo "[backup] Removed ${#OLD[@]} old backup(s); keeping last ${MAX_BACKUPS}."
fi
