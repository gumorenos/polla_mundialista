from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.api.routes.admin import router as admin_router
from app.api.routes.evaluations import router as evaluations_router
from app.api.routes.health import router as health_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.metrics import router as metrics_router
from app.api.routes.ml import router as ml_router
from app.api.routes.pipelines import router as pipelines_router
from app.api.routes.simulations import router as simulations_router
from app.api.routes.snapshots import router as snapshots_router
from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.migrations import run_migrations


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger = get_logger(__name__)
    logger.info("Oráculo Mundial 2026 — startup (env=%s)", settings.ENVIRONMENT)
    run_migrations()
    if settings.SCHEDULER_ENABLED:
        from app.scheduler.scheduler import start_scheduler
        start_scheduler()
    yield
    if settings.SCHEDULER_ENABLED:
        from app.scheduler.scheduler import stop_scheduler
        stop_scheduler()
    logger.info("Oráculo Mundial 2026 — shutdown")


limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.RATE_LIMIT_PUBLIC],
)

app = FastAPI(
    title="Oráculo Mundial 2026",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(admin_router)
app.include_router(simulations_router)
app.include_router(snapshots_router)
app.include_router(jobs_router)
app.include_router(ml_router)
app.include_router(pipelines_router)
app.include_router(evaluations_router)
app.include_router(metrics_router)
