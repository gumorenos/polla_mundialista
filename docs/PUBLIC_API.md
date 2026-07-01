# API Pública Oráculo Mundial 2026

> Ver [`docs/public-api-v1.md`](./public-api-v1.md) para el contrato completo
> y actualizado (envelope `{data,meta}`, endpoints nuevos, gestión de keys
> desde la UI admin). Este archivo se mantiene solo por compatibilidad de
> enlaces existentes.

Base URL: `https://tu-dominio.com/api/public/v1`

Namespace de solo lectura, separado del sistema admin interno (`/api/*`
con `require_admin`). Pensado para consumo server-to-server desde otros
proyectos propios — no hay endpoint de self-signup ni CORS especial,
ya que no se accede desde un navegador.

## Autenticación

Header requerido en todas las requests:

```
X-API-Key: <tu-api-key>
```

Generar una key nueva (en el servidor, una sola vez por consumidor):

```bash
python3 backend/scripts/create_api_key.py "nombre-del-proyecto"
```

La key se muestra una sola vez al crearla — solo se persiste su hash
SHA-256 en la tabla `api_keys`. Para revocar una key, marca
`revoked = 1` en esa fila.

## Endpoints

Todos son `GET`. No hay endpoints de escritura en este namespace.

| Endpoint | Descripción |
|---|---|
| `GET /teams` | Los 48 equipos clasificados (id, nombre, código, confederación) |
| `GET /groups` | Los 12 grupos con sus equipos |
| `GET /simulations/{model_name}` | Resultados de la última simulación completa de un modelo |
| `GET /bracket/{model_name}` | Probabilidades del bracket en vivo (knockout) para un modelo |
| `GET /fixtures` | Calendario de partidos WC2026 con resultados cuando están disponibles |

`model_name` acepta: `baseline`, `elo`, `poisson`, `poisson_context`,
`ml_calibrated`, `consensus`.

## Rate limiting

60 requests/minuto por IP (`RATE_LIMIT_PUBLIC_API` en `config.py`).

## Ejemplo

```bash
curl -H "X-API-Key: om26_xxxxx" https://tu-dominio.com/api/public/v1/simulations/consensus
```

## Códigos de error

- `401` — falta el header `X-API-Key` o la key no existe
- `403` — la key existe pero fue revocada
- `404` — no hay datos para el `model_name` pedido (ej. el bracket en vivo
  todavía no existe porque el torneo no llegó a fase eliminatoria)
- `429` — rate limit excedido
