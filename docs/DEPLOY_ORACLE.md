# Deploy en Oracle Cloud Free ARM

## Requisitos

- VM Oracle Cloud Free ARM (Ampere A1, 4 OCPUs / 24 GB RAM disponibles en el tier free)
- Ubuntu 22.04 LTS ARM64
- Dominio o Cloudflare Tunnel (opcional pero recomendado)

---

## 1. Preparar la VM

```bash
# Actualizar sistema
sudo apt update && sudo apt upgrade -y

# Instalar Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker

# Verificar
docker --version
docker compose version
```

---

## 2. Clonar el repositorio

```bash
git clone https://github.com/gumorenos/polla_mundialista.git
cd polla_mundialista
```

---

## 3. Configurar variables de entorno

```bash
cp .env.example .env
nano .env
```

Variables críticas a rellenar:

| Variable | Descripción |
|---|---|
| `ADMIN_TOKEN` | `openssl rand -hex 32` — protege /admin y /pipelines |
| `API_FOOTBALL_KEY` | API key de api-sports.io |
| `OPENROUTER_API_KEY` | API key de OpenRouter (LLM lesiones) |
| `CORS_ORIGINS` | URL pública del frontend (Cloudflare Tunnel) |
| `ENVIRONMENT` | Cambiar a `production` |

---

## 4. Build y arranque

```bash
# Build de todas las imágenes
docker compose -f docker-compose.prod.yml build

# Arrancar en background
docker compose -f docker-compose.prod.yml up -d
```

---

## 5. Verificar estado

```bash
# Estado de todos los servicios
docker compose -f docker-compose.prod.yml ps

# Logs en tiempo real
docker compose -f docker-compose.prod.yml logs -f api

# Healthcheck manual
curl -s http://localhost:8000/api/health | python3 -m json.tool
```

Todos los servicios deben mostrar `healthy` en `STATUS`.

---

## 6. Full refresh inicial

Carga todos los datos históricos, calcula ELO, entrena ML y corre simulaciones:

```bash
curl -X POST \
  -H "X-Admin-Token: $(grep ADMIN_TOKEN .env | cut -d= -f2)" \
  http://localhost:8000/api/pipelines/full-refresh
```

Monitorear progreso (polling hasta `status=completed`):

```bash
watch -n 10 'curl -s http://localhost:8000/api/metrics | python3 -m json.tool'
```

---

## 7. Configurar Cloudflare Tunnel (opcional)

```bash
# Instalar cloudflared
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb
sudo dpkg -i cloudflared-linux-arm64.deb

# Autenticar y crear tunnel
cloudflared tunnel login
cloudflared tunnel create oraculo-2026

# Configurar en ~/.cloudflared/config.yml:
# tunnel: <TUNNEL_ID>
# credentials-file: /root/.cloudflared/<TUNNEL_ID>.json
# ingress:
#   - hostname: oraculo.tu-dominio.com
#     service: http://localhost:3000
#   - hostname: api.oraculo.tu-dominio.com
#     service: http://localhost:8000
#   - service: http_status:404

# Arrancar como servicio
sudo cloudflared service install
sudo systemctl start cloudflared
```

Actualizar `CORS_ORIGINS` en `.env` con el dominio público y reiniciar:

```bash
docker compose -f docker-compose.prod.yml restart api
```

---

## 8. Backups automáticos (cron)

```bash
# Editar crontab del usuario
crontab -e
```

Añadir (backup diario a las 4am):

```
0 4 * * * cd /path/to/polla_mundialista && bash backend/scripts/backup_sqlite.sh >> data/backups/backup.log 2>&1
```

Backup manual:

```bash
bash backend/scripts/backup_sqlite.sh
ls -lh data/backups/
```

---

## 9. Actualizar la aplicación

```bash
git pull
docker compose -f docker-compose.prod.yml build api worker frontend
docker compose -f docker-compose.prod.yml up -d --no-deps api worker frontend
```

---

## 10. Resolver problemas comunes

| Síntoma | Causa probable | Solución |
|---|---|---|
| `api` unhealthy | Migraciones fallidas | `docker logs oraculo-prod-api-1` |
| `worker` sin procesar jobs | Redis no accesible | Verificar red interna con `docker compose exec worker redis-cli -h redis ping` |
| 403 en /api/admin | ADMIN_TOKEN incorrecto | Verificar `.env` y reiniciar API |
| 429 en endpoints | Rate limit alcanzado | Esperar 1 minuto o ajustar `RATE_LIMIT_PUBLIC` |
| Frontend carga pero API falla | CORS mal configurado | Revisar `CORS_ORIGINS` en `.env` |
