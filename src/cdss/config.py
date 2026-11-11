"""Application settings loaded from environment variables (and an optional ``.env`` file).

AWS credentials are intentionally absent: boto3 resolves them through its default
provider chain (``AWS_PROFILE`` locally, the ECS task role in production).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["local", "dev", "staging", "prod"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
SslMode = Literal["disable", "prefer", "require", "verify-ca", "verify-full"]

_SECURE_SSL_MODES: frozenset[str] = frozenset({"require", "verify-ca", "verify-full"})
_HARDENED_ENVS: frozenset[str] = frozenset({"staging", "prod"})


class Settings(BaseSettings):
    """Typed, immutable runtime configuration. All variables use the ``CDSS_`` prefix."""

    model_config = SettingsConfigDict(
        env_prefix="CDSS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    app_env: AppEnv = "local"
    log_level: LogLevel = "INFO"

    # --- AWS / Bedrock -------------------------------------------------------
    aws_region: str = Field(default="us-east-1", min_length=1)
    bedrock_model_id: str = Field(min_length=1)
    bedrock_embedding_model_id: str = Field(default="amazon.titan-embed-text-v2:0", min_length=1)
    llm_temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    llm_max_tokens: int = Field(default=2048, ge=256, le=8192)

    # --- PostgreSQL ----------------------------------------------------------
    db_host: str = Field(default="localhost", min_length=1)
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = Field(default="cdss", min_length=1)
    db_user: str = Field(default="cdss_app", min_length=1)
    db_password: SecretStr
    db_ssl_mode: SslMode = "prefer"
    db_pool_min_size: int = Field(default=1, ge=1, le=100)
    db_pool_max_size: int = Field(default=10, ge=1, le=100)
    db_statement_timeout_ms: int = Field(default=5000, ge=100, le=60_000)

    # --- RAG / ML artifacts --------------------------------------------------
    faiss_index_dir: Path = Path("data/faiss_index")
    rag_top_k: int = Field(default=4, ge=1, le=10)
    risk_model_path: Path = Path("models/icu_los.pt")

    # --- Agent resilience ----------------------------------------------------
    tool_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    max_tool_retries: int = Field(default=2, ge=0, le=5)

    @model_validator(mode="after")
    def _check_consistency(self) -> Settings:
        if self.db_pool_min_size > self.db_pool_max_size:
            raise ValueError("db_pool_min_size must be <= db_pool_max_size")
        if self.app_env in _HARDENED_ENVS and self.db_ssl_mode not in _SECURE_SSL_MODES:
            raise ValueError(
                f"db_ssl_mode must be one of {sorted(_SECURE_SSL_MODES)} "
                f"when app_env={self.app_env}"
            )
        return self

    def db_connect_kwargs(self) -> dict[str, Any]:
        """Keyword arguments for ``asyncpg.create_pool``.

        Connections are read-only by default and bounded by a server-side statement
        timeout, as a second line of defence behind the allow-listed query templates.
        """
        return {
            "host": self.db_host,
            "port": self.db_port,
            "database": self.db_name,
            "user": self.db_user,
            "password": self.db_password.get_secret_value(),
            "ssl": self.db_ssl_mode,
            "min_size": self.db_pool_min_size,
            "max_size": self.db_pool_max_size,
            "server_settings": {
                "application_name": "cdss-agent",
                "default_transaction_read_only": "on",
                "statement_timeout": str(self.db_statement_timeout_ms),
            },
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton; tests reset it with ``get_settings.cache_clear()``."""
    return Settings()  # required fields are populated from the environment
