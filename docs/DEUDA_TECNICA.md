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
| DT-004 | P1 | backend/app/scheduler/scheduler.py | Placeholder con `sleep(3600)`; APScheduler real se implementa en Prompt 10 | Media | No | Pendiente |
| DT-005 | P2 | backend/app/db/repositories/ | Repositorios usan plain dicts; considerar dataclasses tipados si crece la complejidad | Baja | No | Pendiente |
| DT-006 | P2 | backend/app/db/migrations.py | Sin sistema de versioning de migraciones (ej. número de versión en tabla); aceptable mientras sea solo dev | Baja | No | Pendiente |

## Notas

- Los ítems resueltos no se eliminan; se marcan como **Resuelto** para trazabilidad.
- Si una deuda se convierte en bloqueante, escalarla inmediatamente.
