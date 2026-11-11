"""FastAPI application factory and process lifecycle."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response, status

from cdss.config import Settings, get_settings
from cdss.infra.postgres import create_pool, ping

logger = logging.getLogger(__name__)

PoolFactory = Callable[[Settings], Awaitable[Any]]


def create_app(
    settings: Settings | None = None, pool_factory: PoolFactory = create_pool
) -> FastAPI:
    """Build the app. ``pool_factory`` is injectable so tests can avoid a real database."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        cfg = settings or get_settings()
        logging.basicConfig(level=cfg.log_level)
        app.state.settings = cfg
        app.state.db_pool = await pool_factory(cfg)
        logger.info("startup_complete", extra={"app_env": cfg.app_env})
        try:
            yield
        finally:
            await app.state.db_pool.close()

    app = FastAPI(title="CDSS Agent", version="0.1.0", lifespan=lifespan)

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:
        """Liveness: the process is up. Does not touch dependencies."""
        return {"status": "ok"}

    @app.get("/ready", tags=["ops"])
    async def ready(request: Request, response: Response) -> dict[str, Any]:
        """Readiness: dependencies are reachable. Used by the load balancer."""
        db_ok = await ping(request.app.state.db_pool)
        if not db_ok:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "ok" if db_ok else "degraded", "checks": {"database": db_ok}}

    return app


app = create_app()
