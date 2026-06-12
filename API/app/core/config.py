"""
app/core/config.py
------------------
Centralized application configuration using pydantic-settings.
Production values are read from environment variables. Local development may
load a gitignored .env file.
"""

from functools import lru_cache
import os
from typing import List

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------ #
    # Application
    # ------------------------------------------------------------------ #
    app_env: str
    port: int = 8000

    # ------------------------------------------------------------------ #
    # Database
    # ------------------------------------------------------------------ #
    database_url: str

    # ------------------------------------------------------------------ #
    # JWT
    # ------------------------------------------------------------------ #
    secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # ------------------------------------------------------------------ #
    # Smiota webhook
    # ------------------------------------------------------------------ #
    smiota_api_key: str | None = None

    # ------------------------------------------------------------------ #
    # CORS
    # ------------------------------------------------------------------ #
    cors_origins: str = "*"

    @property
    def cors_origins_list(self) -> List[str]:
        if self.cors_origins == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",")]

    # ------------------------------------------------------------------ #
    # AWS S3
    # ------------------------------------------------------------------ #
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_region: str = "us-east-1"
    aws_s3_bucket: str | None = None

    # ------------------------------------------------------------------ #
    # Brute-force protection
    # ------------------------------------------------------------------ #
    max_login_attempts: int = 5
    lockout_minutes: int = 15

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @model_validator(mode="after")
    def validate_required_settings(self):
        self.app_env = self.app_env.lower()
        placeholders = (
            "REPLACE_WITH",
            "YOUR_",
            "USER:PASSWORD",
        )
        sensitive_values = {
            "database_url": self.database_url,
            "secret_key": self.secret_key,
            "smiota_api_key": self.smiota_api_key,
            "aws_access_key_id": self.aws_access_key_id,
            "aws_secret_access_key": self.aws_secret_access_key,
            "aws_s3_bucket": self.aws_s3_bucket,
        }
        for name, value in sensitive_values.items():
            if value and any(marker in value for marker in placeholders):
                raise ValueError(f"{name} still contains a placeholder value.")

        if len(self.secret_key) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters.")

        return self

    @property
    def jwt_secret(self) -> str:
        """Backward-compatible alias for older internal callers."""
        return self.secret_key

    def require_smiota_api_key(self) -> str:
        if not self.smiota_api_key:
            raise ValueError("SMIOTA_API_KEY is required for Smiota webhook requests.")
        return self.smiota_api_key

    def require_s3_settings(self) -> tuple[str, str, str]:
        missing = [
            name
            for name, value in {
                "AWS_ACCESS_KEY_ID": self.aws_access_key_id,
                "AWS_SECRET_ACCESS_KEY": self.aws_secret_access_key,
                "AWS_S3_BUCKET": self.aws_s3_bucket,
            }.items()
            if not value
        ]
        if missing:
            raise ValueError(f"{', '.join(missing)} required for S3 uploads.")
        return self.aws_access_key_id, self.aws_secret_access_key, self.aws_s3_bucket


@lru_cache()
def get_settings() -> Settings:
    """
    Return a cached singleton Settings instance.
    Import and call this wherever you need config values.
    """
    app_env = os.environ.get("APP_ENV", "development").lower()
    env_file = ".env" if app_env == "development" else None
    return Settings(_env_file=env_file)
