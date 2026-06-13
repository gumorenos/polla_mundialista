# Deuda Técnica

Registro de deuda técnica no bloqueante detectada durante el desarrollo.
Actualizar con cada prompt completado.

## Convenciones

- **Severidad**: Alta / Media / Baja
- **Bloqueante**: Sí / No (si es Sí, debe resolverse antes de avanzar)
- **Estado**: Pendiente / En progreso / Resuelto

## Tabla de deuda

| ID | Prompt origen | Módulo afectado | Descripción | Severidad | Bloqueante | Estado |
|----|--------------|-----------------|-------------|-----------|------------|--------|
| DT-001 | P1 | backend/requirements.txt | `httpx` con `starlette.testclient` genera `StarletteDeprecationWarning`; migrar a `httpx2` cuando sea estable o usar `requests` en tests | Baja | No | Pendiente |
| DT-002 | P1 | docker/Dockerfile.backend | El CMD usa `uvicorn --reload` implícitamente en dev; en producción añadir `--workers 4` y eliminar `--reload` | Baja | No | Pendiente |
| DT-003 | P1 | backend/app/db/migrations.py | Solo crea tabla `jobs`; las restantes 19 tablas se añaden en Prompts 2-9 | Media | No | Pendiente |
| DT-004 | P1 | backend/app/scheduler/scheduler.py | Placeholder con `sleep(3600)`; APScheduler real se implementa en Prompt 11 | Media | No | Resuelto |
| DT-005 | P2 | backend/app/db/repositories/ | Repositorios usan plain dicts; considerar dataclasses tipados si crece la complejidad | Baja | No | Pendiente |
| DT-006 | P2 | backend/app/db/migrations.py | Sin sistema de versioning de migraciones (ej. número de versión en tabla); aceptable mientras sea solo dev | Baja | No | Pendiente |
| DT-007 | P12 | docker-compose.prod.yml | SQLite con WAL es suficiente para MVP; migrar a PostgreSQL+asyncpg si el tráfico supera ~50 req/s concurrentes | Media | No | Pendiente |
| DT-008 | P12 | backend/scripts/backup_sqlite.sh | Backup local en el mismo servidor; añadir sincronización a Object Storage (Oracle OCI) para disaster recovery real | Media | No | Pendiente |
| DT-009 | P11 | backend/app/api/routes/metrics.py | `GET /api/metrics` hace 6 queries SQLite en serie; agrupar en una query o cachear resultado 60s | Baja | No | Pendiente |
| DT-013 | Fix-1 | frontend/src/api/client.ts | `VITE_ADMIN_TOKEN` se inyecta en build time (baked en el bundle JS); rotar token requiere rebuild del frontend | Baja | No | Pendiente |
| DT-010 | P10 | frontend/src/pages/Calibration.tsx | `ResponsiveContainer` de Recharts requiere `ResizeObserver`; entornos SSR o tests sin polyfill fallan | Baja | No | Pendiente |
| DT-011 | P6 | backend/app/services/news/scraper.py | Sin retry exponencial; fuentes pueden bloquear el scraper en ejecuciones frecuentes | Media | No | Resuelto |
| DT-012 | P9 | backend/app/services/ml/ | Modelos ML entrenados no tienen versionado persistente; reentrenar sobreescribe el modelo anterior en `data/models/` | Media | No | Resuelto |

## Notas

- Los ítems resueltos no se eliminan; se marcan como **Resuelto** para trazabilidad.
- Si una deuda se convierte en bloqueante, escalarla inmediatamente.
