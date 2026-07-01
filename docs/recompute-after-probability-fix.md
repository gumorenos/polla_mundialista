# Recalcular simulaciones después del fix de probabilidades (P0)

## Contexto

El commit `f697bde` corrigió un bug en `monte_carlo.py` donde
`reach_round_of_32` podía superar 1.0 (doble conteo) y `reach_round_of_16`/
`reach_quarter_final` rompían la monotonicidad esperada. **El fix es de
código, no retroactivo**: todo `simulation_runs` completado ANTES del
deploy de ese commit sigue en la base de datos con valores inválidos.

Diagnóstico post-deploy (2026-07-01): los 34 runs `completed` que había en
producción en ese momento — **el 100%** — fueron generados antes del fix y
son inválidos. El backend ya tiene guardrails (`app/services/simulation/validation.py`)
que evitan servir estos runs como "latest" o usarlos en consensus, pero
**mientras no se recalculen, `/api/simulations/latest` y
`/api/public/v1/simulations/latest` responderán `404 no_valid_simulation`**
en vez de datos — es el comportamiento correcto y esperado hasta recalcular.

## 1. Auditar runs actuales (solo lectura, no modifica nada)

```fish
docker exec oraculo-prod-api-1 python3 scripts/audit_simulation_runs.py
echo $status
```

Reporta total/válidos/inválidos por modelo y los últimos runs inválidos con
la razón exacta de la violación.

## 2. Marcar inválidos — dry-run primero (no modifica nada)

```fish
docker exec oraculo-prod-api-1 python3 scripts/mark_invalid_simulation_runs.py --dry-run
echo $status
```

Lista los `run_id` que serían marcados, sin tocar la base de datos.

## 3. Aplicar — marca status='invalid' con auditoría

```fish
docker exec oraculo-prod-api-1 python3 scripts/mark_invalid_simulation_runs.py --apply
echo $status
```

No borra ninguna fila — solo cambia `status` a `'invalid'` y escribe
`error_message = 'Invalid simulation probabilities detected after validation audit'`.
Los runs marcados quedan excluidos de toda consulta `WHERE status='completed'`
(latest, consensus, comparison), pero siguen en la tabla para auditoría.

## 4. Recalcular los modelos

Necesitas un `ADMIN_TOKEN` válido (variable de entorno del servicio `api`).

```fish
set -x ADMIN_TOKEN "tu-admin-token-real"
```

### Opción A — desde la UI (recomendado)

Dashboard → sección "Simulaciones Monte Carlo" → botón por modelo. Corre
`baseline`, `elo`, `poisson`, `poisson_context`, `ml_calibrated` primero, y
`consensus` al final (agrega los anteriores, no corre Monte Carlo propio).

### Opción B — vía API con curl

```fish
curl -s -X POST \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model_name":"poisson","iterations":30000}' \
  https://oraculo.todoestaaca.com/api/simulations/run
echo $status
```

Repite cambiando `model_name` por `baseline`, `elo`, `poisson_context`,
`ml_calibrated`. Al final, `consensus`:

```fish
curl -s -X POST \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model_name":"consensus"}' \
  https://oraculo.todoestaaca.com/api/simulations/run
echo $status
```

**No corras los 6 modelos en paralelo** — el worker de producción procesa
`long` con un solo proceso; encolarlos en orden (base primero, consensus al
final) garantiza que consensus agregue resultados frescos, no los recién
invalidados.

### Opción C — run-all-models (dispara los 5 base a la vez, no consensus)

```fish
curl -s -X POST -H "X-Admin-Token: $ADMIN_TOKEN" \
  https://oraculo.todoestaaca.com/api/pipelines/run-all-models
echo $status
```

Corre consensus por separado después de confirmar que los 5 terminaron
(ver Jobs UI o `GET /api/jobs`).

## 5. Verificar que quedó bien

```fish
docker exec oraculo-prod-api-1 python3 scripts/audit_simulation_runs.py
echo $status
```

Debe reportar 0 inválidos para los runs recién creados. Luego:

```fish
curl -s -H "X-API-Key: $ORACULO_API_KEY" \
  https://oraculo.todoestaaca.com/api/public/v1/simulations/latest?model=consensus \
  | python3 -m json.tool
```

Confirma que `reach_round_of_32 <= 1.0` y la cadena de monotonicidad se
cumple para todos los equipos.

## No hacer

- No borrar filas de `simulation_runs` ni `simulation_team_results` —
  siempre usar status controlado (`invalid`/`failed`) para mantener
  auditoría.
- No correr los 30k-iteración de los 6 modelos en paralelo en un servidor
  con un solo worker `long` — se sirven en cola, tomará ~10-15 min
  secuencial (ver tiempos históricos en `simulation_runs.finished_at -
  started_at`).
- No ejecutar `--apply` sin haber corrido `--dry-run` antes y revisado la
  lista.
