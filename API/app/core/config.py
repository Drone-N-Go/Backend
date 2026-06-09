"""
app/core/config.py
------------------
Centralized application configuration using pydantic-settings.
All values are read from environment variables / .env file.
"""

from functools import lru_cache
from typing import List

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------ #
    # Application
    # ------------------------------------------------------------------ #
    app_env: str = "development"
    port: int = 8000

    # ------------------------------------------------------------------ #
    # Database
    # ------------------------------------------------------------------ #
    database_url: str

    # ------------------------------------------------------------------ #
    # JWT
    # ------------------------------------------------------------------ #
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # ------------------------------------------------------------------ #
    # Admin seed account
    # ------------------------------------------------------------------ #
    admin_email: str = "james@droneandgo.io"
    admin_password: str

    # ------------------------------------------------------------------ #
    # Smiota webhook
    # ------------------------------------------------------------------ #
    smiota_api_key: str

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
    aws_access_key_id: str
    aws_secret_access_key: str
    aws_region: str = "us-east-1"
    aws_s3_bucket: str

    # ------------------------------------------------------------------ #
    # Brute-force protection
    # ------------------------------------------------------------------ #
    max_login_attempts: int = 5
    lockout_minutes: int = 15

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @model_validator(mode="after")
    def validate_production_safety(self):
        placeholders = (
            "REPLACE_WITH",
            "YOUR_",
            "USER:PASSWORD",
        )
        sensitive_values = {
            "database_url": self.database_url,
            "jwt_secret": self.jwt_secret,
            "admin_password": self.admin_password,
            "smiota_api_key": self.smiota_api_key,
            "aws_access_key_id": self.aws_access_key_id,
            "aws_secret_access_key": self.aws_secret_access_key,
            "aws_s3_bucket": self.aws_s3_bucket,
        }
        for name, value in sensitive_values.items():
            if any(marker in value for marker in placeholders):
                raise ValueError(f"{name} still contains a placeholder value.")

        if len(self.jwt_secret) < 64:
            raise ValueError("JWT_SECRET must be at least 64 characters.")

        if self.is_production and self.cors_origins == "*":
            raise ValueError("CORS_ORIGINS cannot be '*' when APP_ENV=production.")

        return self


@lru_cache()
def get_settings() -> Settings:
    """
    Return a cached singleton Settings instance.
    Import and call this wherever you need config values.
    """
    return Settings()
