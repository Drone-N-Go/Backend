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
    # In production, set CORS_ORIGINS to a comma-separated list of allowed
    # origins, e.g. "https://app.droneandgo.io,https://admin.droneandgo.io".
    # Wildcard ("*") is rejected in production because allow_credentials=True
    # is incompatible with a wildcard origin (CORS spec §3.2.2) and creates a
    # broad attack surface. In development the default remains "*" for convenience.
    cors_origins: str = "*"

    @property
    def cors_origins_list(self) -> List[str]:
        if self.cors_origins == "*":
            if self.is_production:
                raise ValueError(
                    "CORS_ORIGINS must be explicitly configured in production. "
                    "Set CORS_ORIGINS to a comma-separated list of allowed origins."
                )
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # ------------------------------------------------------------------ #
    # Firebase Storage
    # ------------------------------------------------------------------ #
    firebase_storage_bucket: str | None = None
    # Base64-encoded Firebase service account JSON (set as FIREBASE_CREDENTIALS_JSON).
    firebase_credentials_json: str | None = None

    # ------------------------------------------------------------------ #
    # Resend (contact form email)
    # ------------------------------------------------------------------ #
    resend_api_key: str | None = None
    # Verified-domain sender address for outbound Resend mail.
    contact_from_email: str = "DroneAndGo Website <noreply@droneandgo.io>"
    # Inbox that receives contact-form submissions.
    contact_notify_email: str = "contact@droneandgo.io"

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
            "firebase_storage_bucket": self.firebase_storage_bucket,
            "resend_api_key": self.resend_api_key,
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

    def require_resend_api_key(self) -> str:
        if not self.resend_api_key:
            raise ValueError("RESEND_API_KEY is required to send contact form emails.")
        return self.resend_api_key

    def require_firebase_settings(self) -> tuple[str, str]:
        """Return (credentials_json_b64, bucket_name), raising if either is missing."""
        missing = [
            name
            for name, value in {
                "FIREBASE_CREDENTIALS_JSON": self.firebase_credentials_json,
                "FIREBASE_STORAGE_BUCKET": self.firebase_storage_bucket,
            }.items()
            if not value
        ]
        if missing:
            raise ValueError(f"{', '.join(missing)} required for Firebase Storage uploads.")
        return self.firebase_credentials_json, self.firebase_storage_bucket


@lru_cache()
def get_settings() -> Settings:
    """
    Return a cached singleton Settings instance.
    Import and call this wherever you need config values.
    """
    app_env = os.environ.get("APP_ENV", "development").lower()
    env_file = ".env" if app_env == "development" else None
    return Settings(_env_file=env_file)
