"""PostgreSQL connection-pool lifecycle helpers."""

from __future__ import annotations

import asyncio
from typing import Protocol

import asyncpg

from cdss.config import Settings


class SupportsFetchval(Protocol):
    async def fetchval(self, query: str, *args: object) -> object: ...


async def create_pool(settings: Settings) -> asyncpg.Pool:
    """Create the shared pool using the hardened connection settings."""
    pool = await asyncpg.create_pool(**settings.db_connect_kwargs())
    if pool is None:  # asyncpg types this as Optional
        raise RuntimeError("asyncpg.create_pool returned no pool")
    return pool


async def ping(pool: SupportsFetchval, timeout_seconds: float = 2.0) -> bool:
    """Return True if the database answers a trivial query within the timeout."""
    try:
        async with asyncio.timeout(timeout_seconds):
            return await pool.fetchval("SELECT 1") == 1
    except (OSError, TimeoutError, asyncpg.PostgresError):
        return False
