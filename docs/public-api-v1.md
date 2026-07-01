# API Pública Oráculo Mundial 2026 — v1

Base URL: `https://tu-dominio.com/api/public/v1`

Namespace de **solo lectura**, completamente separado del sistema admin
interno (`/api/*` con `require_admin`, cookies de sesión). Pensado para
consumo server-to-server desde otro proyecto propio (web app u orquestador
LLM) — no hay endpoint de self-signup, ni CORS especial, porque no se
accede desde un navegador con credenciales de usuario.

## Autenticación

Header requerido en **todas** las requests, incluyendo `/health`:

```
X-API-Key: <tu-api-key>
```

Generar una key nueva:

- Desde la UI admin: sección "API Keys" (Admin → API Keys).
- Desde el servidor: `python3 backend/scripts/create_api_key.py "nombre-del-proyecto"`

La key completa (`om26_...`) se muestra **una sola vez** al crearla — solo
se persiste su hash SHA-256 y un prefijo corto (`om26_ab12cd3...`) para
mostrarla en listados. No hay forma de recuperar la key completa después;
si se pierde, hay que revocarla y crear una nueva.

## Endpoints

Todos son `GET`. No hay endpoints de escritura ni de disparo de
simulaciones en este namespace — eso sigue siendo exclusivo de `/api/*`
con `require_admin`.

### Nuevos (contrato con envelope `{data, meta}` / `{error}`)

| Endpoint | Descripción |
|---|---|
| `GET /health` | Liveness check (requiere API key igual que el resto) |
| `GET /metadata` | Modelos válidos, rondas, rate limit — sin secretos |
| `GET /simulations/latest?model=consensus` | Última simulación completa de un modelo |
| `GET /simulations/comparison` | % de campeón por equipo, comparando los 6 modelos |
| `GET /bracket/latest?model=consensus` | Último bracket en vivo (histórico) de un modelo |
| `GET /bracket/runs?model=consensus&limit=20` | Historial de corridas del bracket en vivo |

Formato de éxito:

```json
{
  "data": { "...": "..." },
  "meta": {
    "generated_at": "2026-07-01T09:15:00Z",
    "timezone": "America/Lima",
    "model": "consensus",
    "source_run_id": "abc123",
    "cache_ttl_seconds": 300,
    "stale": false
  }
}
```

Formato de error:

```json
{
  "error": {
    "code": "not_found",
    "message": "No completed simulation for model consensus",
    "details": {}
  }
}
```

`bracket/latest` y `bracket/{model_name}` no usan `{error:...}` para el caso
"no hay bracket todavía" — devuelven `200` con `status` indicando el motivo
(ver más abajo), ya que no es un error sino un estado esperado del torneo.

### Legacy (mantener compatibilidad — forma plana, sin envelope)

| Endpoint | Descripción |
|---|---|
| `GET /teams` | Los 48 equipos clasificados |
| `GET /groups` | Los 12 grupos con sus equipos |
| `GET /fixtures` | Calendario de partidos WC2026 con resultados cuando están disponibles |
| `GET /simulations/{model_name}` | Alias legacy de `/simulations/latest?model=` |
| `GET /bracket/{model_name}` | Alias legacy de `/bracket/latest?model=` |

Estos endpoints predatan el envelope `{data, meta}` y se mantienen tal
cual para no romper integraciones existentes. Las integraciones nuevas
deberían usar los endpoints de la sección anterior.

### Modelos válidos

```
baseline | elo | poisson | poisson_context | ml_calibrated | consensus
```

### Respuesta de `bracket/latest` cuando SÍ hay datos

```json
{
  "model": "consensus",
  "run_id": "abc123",
  "status": "completed",
  "rounds": {
    "round_of_32": [
      {
        "team_id": "ARG", "team_name": "Argentina",
        "advance_prob": 0.72, "opponent_id": "MEX", "opponent_name": "México",
        "match_win_prob": 0.64, "is_eliminated": false
      }
    ]
  },
  "computed_at": "2026-07-01T09:05:00Z",
  "meta": { "iterations": 10000, "r32_source": "wc2026_standings",
            "r32_fetched_at": "2026-07-01T08:32:00Z", "cache_ttl_seconds": 300 }
}
```

### Respuesta cuando aún no hay bracket (no es un error — 200 OK)

```json
{
  "model": "consensus", "run_id": null, "status": "no_r32",
  "rounds": {}, "computed_at": null,
  "message": "No hay 32 clasificados definidos todavía. Se actualizó standings, pero la fase de grupos sigue incompleta."
}
```

`status` puede ser `"completed"`, `"no_r32"` (se intentó correr pero el
torneo no llegó a fase eliminatoria) o `null` (nunca se corrió el bracket
para ese modelo).

## Reglas para consumo externo

1. Usa `consensus` como modelo default salvo que necesites comparar modelos.
2. Usa `/simulations/comparison` si tu app quiere mostrar acuerdo/desacuerdo entre modelos.
3. No dispares simulaciones desde la API pública — no existen endpoints para eso aquí.
4. No uses los endpoints internos `/api/*` — requieren admin token/cookies que no debes compartir.
5. Cachea las respuestas 5–15 minutos (`cache_ttl_seconds` en `meta` es la guía).
6. No hagas polling agresivo — con datos que se actualizan una vez al día, no aporta nada.
7. Si recibes `429`, espera al menos 60 segundos antes de reintentar.
8. Horarios de actualización (hora Perú, UTC-5):
   - Daily update: 03:30 Perú (08:30 UTC)
   - Simulaciones nocturnas: 04:00 Perú (09:00 UTC)
   - Datos recomendados para consumo externo: desde las 07:00–08:00 Perú en adelante.
9. Durante partidos en vivo, `fixtures` y `bracket` pueden refrescarse cada 5–15 minutos —
   fuera de eso, una vez al día es suficiente.
10. La API pública es de **solo lectura** — punto.

## Rate limiting

`RATE_LIMIT_PUBLIC_API` en `config.py`, default `60/minute` por IP.

## Ejemplos curl

```bash
curl -H "X-API-Key: $ORACULO_API_KEY" \
  https://tu-dominio.com/api/public/v1/simulations/latest?model=consensus

curl -H "X-API-Key: $ORACULO_API_KEY" \
  https://tu-dominio.com/api/public/v1/bracket/latest?model=consensus

curl -H "X-API-Key: $ORACULO_API_KEY" \
  https://tu-dominio.com/api/public/v1/metadata
```

## Códigos de error

- `401` — falta el header `X-API-Key` o la key no existe
- `403` — la key existe pero fue revocada
- `404` — (solo en endpoints legacy) no hay datos para el `model_name` pedido
- `400` — `model` inválido (endpoints nuevos devuelven `{"error":{"code":"invalid_model",...}}`)
- `429` — rate limit excedido — espera 60s mínimo antes de reintentar
