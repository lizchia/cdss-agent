from __future__ import annotations

import asyncio

import asyncpg
import pytest
from fastapi.testclient import TestClient

from cdss.api.main import create_app
from cdss.config import Settings


class FakePool:
    def __init__(
        self, result: object = 1, exc: BaseException | None = None, delay: float = 0.0
    ) -> None:
        self.delay = delay
        self.result = result
        self.exc = exc
        self.closed = False

    async def fetchval(self, query: str, *args: object) -> object:
        assert query == "SELECT 1"
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc is not None:
            raise self.exc
        return self.result

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        bedrock_model_id="test-model",
        db_password="pw",  # type: ignore[arg-type]  # noqa: S106
    )


def _client(settings: Settings, pool: FakePool) -> TestClient:
    async def factory(_: Settings) -> FakePool:
        return pool

    return TestClient(create_app(settings=settings, pool_factory=factory))


def test_health_is_dependency_free(settings: Settings) -> None:
    pool = FakePool(exc=OSError("db down"))
    with _client(settings, pool) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ready_ok(settings: Settings) -> None:
    with _client(settings, FakePool()) as client:
        resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "checks": {"database": True}}


@pytest.mark.parametrize("exc", [OSError("refused"), TimeoutError(), asyncpg.PostgresError("boom")])
def test_ready_degraded_when_db_unreachable(settings: Settings, exc: BaseException) -> None:
    with _client(settings, FakePool(exc=exc)) as client:
        resp = client.get("/ready")
    assert resp.status_code == 503
    assert resp.json()["checks"]["database"] is False


def test_pool_closed_on_shutdown(settings: Settings) -> None:
    pool = FakePool()
    with _client(settings, pool):
        assert not pool.closed
    assert pool.closed


async def test_ping_times_out_on_hung_db() -> None:
    from cdss.infra.postgres import ping

    assert await ping(FakePool(delay=1.0), timeout_seconds=0.05) is False
