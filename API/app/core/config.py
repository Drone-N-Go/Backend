"""
app/core/config.py
------------------
Centralized application configuration using pydantic-settings.
Production values are read from environment variables. Local development may
load a gitignored .env file.
"""

from functools import lru_cache
import os
from decimal import Decimal
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
    # Stripe payments (added 2026-10-05)
    # ------------------------------------------------------------------ #
    # PAYMENTS_ENABLED is the master switch. While it is false, bookings are
    # created exactly as before (straight to `reserved`, nothing charged), so
    # deploying this code changes nothing for the website or older app
    # builds until it is deliberately turned on.
    payments_enabled: bool = False
    stripe_secret_key: str | None = None
    stripe_publishable_key: str | None = None
    stripe_webhook_secret: str | None = None
    # Optional flat price per rental, in dollars (e.g. "1.00" while testing,
    # "35.00" at launch). When unset, the price is the drone's hourly/daily
    # rate x duration, as before.
    rental_price_override: Decimal | None = None

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
            "stripe_secret_key": self.stripe_secret_key,
            "stripe_publishable_key": self.stripe_publishable_key,
            "stripe_webhook_secret": self.stripe_webhook_secret,
        }
        for name, value in sensitive_values.items():
            if value and any(marker in value for marker in placeholders):
                raise ValueError(f"{name} still contains a placeholder value.")

        if self.rental_price_override is not None and self.rental_price_override <= 0:
            raise ValueError("RENTAL_PRICE_OVERRIDE must be greater than zero when set.")

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

    def require_stripe_secret_key(self) -> str:
        if not self.stripe_secret_key:
            raise ValueError("STRIPE_SECRET_KEY is required for payments.")
        return self.stripe_secret_key

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
