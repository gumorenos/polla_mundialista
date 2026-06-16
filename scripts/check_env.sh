#!/usr/bin/env bash
# Validates required environment variables before starting the Docker stack.
# Usage: bash scripts/check_env.sh [--env-file <path>]
set -euo pipefail

ENV_FILE=".env"
if [[ "${1:-}" == "--env-file" && -n "${2:-}" ]]; then
  ENV_FILE="$2"
fi

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m'

errors=0
warnings=0

log_ok()   { echo -e "  ${GREEN}✓${NC}  $1"; }
log_warn() { echo -e "  ${YELLOW}⚠${NC}  $1"; warnings=$((warnings+1)); }
log_err()  { echo -e "  ${RED}✗${NC}  $1"; errors=$((errors+1)); }

echo ""
echo "Oráculo Mundial 2026 — pre-deploy env check"
echo "============================================"
echo "Env file: $ENV_FILE"
echo ""

# Load .env — parse manually to handle values with spaces (e.g. cron expressions)
if [[ ! -f "$ENV_FILE" ]]; then
  echo -e "${RED}ERROR: $ENV_FILE not found. Copy .env.example to .env and fill in values.${NC}"
  exit 1
fi

get_env() {
  # Extract value for a key from the env file, stripping inline comments and quotes.
  # Returns empty string if key not found (grep exit 1 is suppressed).
  local key="$1"
  grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | tail -1 | sed "s/^${key}=//" | sed 's/[[:space:]]*#.*//' | sed "s/^['\"]//;s/['\"]$//" || true
}

PLACEHOLDERS=("change_me_in_production" "your_api_football_key_here" "your_openrouter_key_here" "")

is_placeholder() {
  local val="$1" p
  for p in "${PLACEHOLDERS[@]}"; do
    if [[ "$val" == "$p" ]]; then return 0; fi
  done
  return 1
}

# Lee ENVIRONMENT primero — antes de cualquier validación de seguridad
ENVIRONMENT="$(get_env ENVIRONMENT)"; ENVIRONMENT="${ENVIRONMENT:-development}"

echo "Entorno detectado: $ENVIRONMENT"
echo ""
echo "--- Seguridad (bloqueante en producción) ---"

ADMIN_TOKEN="$(get_env ADMIN_TOKEN)"
if [[ -z "$ADMIN_TOKEN" ]]; then
  log_err "ADMIN_TOKEN está vacío — requerido"
elif is_placeholder "$ADMIN_TOKEN"; then
  if [[ "$ENVIRONMENT" == "production" ]]; then
    log_err "ADMIN_TOKEN tiene valor placeholder — reemplazar con: openssl rand -hex 32"
  else
    log_warn "ADMIN_TOKEN tiene valor placeholder (OK en desarrollo, NO en producción)"
  fi
elif [[ ${#ADMIN_TOKEN} -lt 32 ]]; then
  log_warn "ADMIN_TOKEN tiene menos de 32 caracteres — se recomienda openssl rand -hex 32"
else
  log_ok "ADMIN_TOKEN configurado (${#ADMIN_TOKEN} chars)"
fi

ADMIN_PASSWORD="$(get_env ADMIN_PASSWORD)"
if [[ -z "$ADMIN_PASSWORD" ]]; then
  log_err "ADMIN_PASSWORD está vacío — requerido para el login web"
elif is_placeholder "$ADMIN_PASSWORD"; then
  if [[ "$ENVIRONMENT" == "production" ]]; then
    log_err "ADMIN_PASSWORD tiene valor placeholder — cámbialo antes de deploy"
  else
    log_warn "ADMIN_PASSWORD tiene valor placeholder (OK en desarrollo)"
  fi
elif [[ ${#ADMIN_PASSWORD} -lt 6 ]]; then
  log_warn "ADMIN_PASSWORD tiene menos de 6 caracteres — se recomienda al menos 8"
else
  log_ok "ADMIN_PASSWORD configurado (${#ADMIN_PASSWORD} chars)"
fi

echo ""
echo "--- APIs externas (requeridas para datos live) ---"

API_FOOTBALL_KEY="$(get_env API_FOOTBALL_KEY)"
if is_placeholder "$API_FOOTBALL_KEY"; then
  log_warn "API_FOOTBALL_KEY no configurada — ingesta de fixtures desde API deshabilitada (CSV seed disponible)"
else
  log_ok "API_FOOTBALL_KEY configurada"
fi

OPENROUTER_API_KEY="$(get_env OPENROUTER_API_KEY)"
if is_placeholder "$OPENROUTER_API_KEY"; then
  log_warn "OPENROUTER_API_KEY no configurada — clasificador LLM de lesiones deshabilitado"
else
  log_ok "OPENROUTER_API_KEY configurada"
fi

echo ""
echo "--- Infraestructura ---"

REDIS_URL="$(get_env REDIS_URL)"
if [[ -z "$REDIS_URL" ]]; then
  log_err "REDIS_URL está vacía — el worker RQ no puede arrancar"
else
  log_ok "REDIS_URL: $REDIS_URL"
fi

SQLITE_PATH="$(get_env SQLITE_PATH)"
if [[ -z "$SQLITE_PATH" ]]; then
  log_err "SQLITE_PATH está vacía — la base de datos no puede inicializarse"
else
  log_ok "SQLITE_PATH: $SQLITE_PATH"
fi

echo ""
echo "--- Entorno ---"

if [[ "$ENVIRONMENT" == "production" ]]; then
  log_ok "ENVIRONMENT=production"
else
  log_warn "ENVIRONMENT=$ENVIRONMENT (no es 'production' — rate limiting y validaciones de seguridad relajadas)"
fi

CORS_ORIGINS="$(get_env CORS_ORIGINS)"
if [[ -z "$CORS_ORIGINS" ]]; then
  log_warn "CORS_ORIGINS vacío — usando default permisivo (localhost)"
else
  log_ok "CORS_ORIGINS: $CORS_ORIGINS"
fi

echo ""
echo "============================================"
if [[ $errors -gt 0 ]]; then
  echo -e "${RED}RESULTADO: $errors error(s), $warnings aviso(s) — corregir errores antes del deploy${NC}"
  echo ""
  exit 1
elif [[ $warnings -gt 0 ]]; then
  echo -e "${YELLOW}RESULTADO: 0 errores, $warnings aviso(s) — revisar avisos antes de producción${NC}"
  echo ""
  exit 0
else
  echo -e "${GREEN}RESULTADO: todo OK — puedes levantar el stack${NC}"
  echo ""
  exit 0
fi
