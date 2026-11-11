from __future__ import annotations

import pytest
from pydantic import ValidationError

from cdss.config import Settings, get_settings


@pytest.mark.usefixtures("base_env")
def test_loads_from_env_with_defaults() -> None:
    s = get_settings()
    assert s.bedrock_model_id == "test-model-id"
    assert s.app_env == "local"
    assert s.db_port == 5432
    assert s.max_tool_retries == 2


def test_missing_required_fields_fail_fast() -> None:
    with pytest.raises(ValidationError) as exc:
        Settings()  # type: ignore[call-arg]
    missing = {e["loc"][0] for e in exc.value.errors()}
    assert {"bedrock_model_id", "db_password"} <= missing


@pytest.mark.usefixtures("base_env")
def test_password_is_not_exposed_in_repr() -> None:
    s = get_settings()
    assert "s3cret-test-pw" not in repr(s)
    assert "s3cret-test-pw" not in s.model_dump_json()


@pytest.mark.usefixtures("base_env")
def test_db_connect_kwargs_are_read_only_and_time_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CDSS_DB_STATEMENT_TIMEOUT_MS", "2500")
    kwargs = get_settings().db_connect_kwargs()
    assert kwargs["password"] == "s3cret-test-pw"  # noqa: S105
    assert kwargs["server_settings"]["default_transaction_read_only"] == "on"
    assert kwargs["server_settings"]["statement_timeout"] == "2500"


@pytest.mark.usefixtures("base_env")
@pytest.mark.parametrize("env", ["staging", "prod"])
def test_hardened_envs_require_tls(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    monkeypatch.setenv("CDSS_APP_ENV", env)
    monkeypatch.setenv("CDSS_DB_SSL_MODE", "prefer")
    with pytest.raises(ValidationError, match="db_ssl_mode"):
        Settings()  # type: ignore[call-arg]

    monkeypatch.setenv("CDSS_DB_SSL_MODE", "verify-full")
    assert Settings().db_ssl_mode == "verify-full"  # type: ignore[call-arg]


@pytest.mark.usefixtures("base_env")
def test_pool_bounds_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CDSS_DB_POOL_MIN_SIZE", "20")
    monkeypatch.setenv("CDSS_DB_POOL_MAX_SIZE", "5")
    with pytest.raises(ValidationError, match="db_pool_min_size"):
        Settings()  # type: ignore[call-arg]


@pytest.mark.usefixtures("base_env")
def test_settings_are_immutable() -> None:
    s = get_settings()
    with pytest.raises(ValidationError):
        s.app_env = "prod"  # type: ignore[misc]
