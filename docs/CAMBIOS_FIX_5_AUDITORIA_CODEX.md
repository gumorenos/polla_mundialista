# Cambios Fix-5 Auditoria Codex

Fecha: 2026-06-17

## Resumen

Se corrigieron los hallazgos reportados en la auditoria Codex posterior a Fix-4b, manteniendo el alcance en seguridad de autenticacion, exposicion de metadata operativa, observabilidad de jobs y configuracion de despliegue.

## Cambios aplicados

| Hallazgo | Estado | Cambio |
|---|---|---|
| AUD-001 | Corregido | La contrasena admin cambiada desde la UI ahora queda persistida en SQLite en `admin_credentials`; `ADMIN_PASSWORD` queda como bootstrap inicial. |
| AUD-002 | Corregido | `GET /api/ml/models` y `GET /api/ml/models/active` ya no exponen `model_path`; el historial admin conserva el detalle operativo. |
| AUD-003 | Corregido | `run_ml_training_task`, `run_news_task` y `run_daily_update_task` usan `_HeartbeatUpdater` y manejan cancelacion cooperativa. |
| AUD-004 | Corregido | `.env.example` documenta rutas de datos/export, URL base API-Football, fallback LLM, ruta/retencion de modelos, ELO y `SCHEDULER_ENABLED`. |
| AUD-005 | Corregido | La cookie `admin_session` usa `Secure` automaticamente cuando `ENVIRONMENT=production`. |
| AUD-006 | Corregido | El servicio `scheduler` en `docker-compose.prod.yml` tiene healthcheck basado en ping a Redis. |
| AUD-007 | Corregido | `_parse_response(None)` ya no rompe en logging de debug. |
| AUD-008 | Corregido | `_safe_load_model()` valida pertenencia de ruta con `Path.is_relative_to()` y fallback portable. |

## Detalles tecnicos

- Se agrego migracion `_m006_admin_credentials` para crear la tabla `admin_credentials`.
- La credencial admin durable usa PBKDF2-HMAC-SHA256 con salt e iteraciones versionadas en el string persistido.
- `X-Admin-Token` se mantiene sin cambios para scripts y `curl`.
- Las sesiones admin siguen guardandose en Redis con prefijo `session:`.
- `docs/DEUDA_TECNICA.md` marca `DT-015` como resuelto y reemplaza la nota antigua de sesiones en memoria.

## Verificacion esperada

- `cd backend && pytest -v --tb=short`
- `cd frontend && npm run typecheck`
- `bash scripts/check_env.sh --env-file .env.example`
- `docker compose -f docker-compose.prod.yml config`

Nota: en la auditoria previa, el entorno local no tenia `pytest`, `node_modules` ni WSL bash disponible; si sigue igual, validar con dependencias instaladas o dentro de Docker.
