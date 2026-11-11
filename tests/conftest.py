from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from cdss.config import get_settings


@pytest.fixture(autouse=True)
def _isolated_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[None]:
    """Strip CDSS_* vars and run from an empty dir so a developer's real .env never leaks in."""
    for key in list(os.environ):
        if key.startswith("CDSS_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Minimal valid environment."""
    monkeypatch.setenv("CDSS_BEDROCK_MODEL_ID", "test-model-id")
    monkeypatch.setenv("CDSS_DB_PASSWORD", "s3cret-test-pw")
