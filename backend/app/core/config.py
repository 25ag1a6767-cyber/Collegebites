import os
from functools import lru_cache
from typing import List
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ENVIRONMENT: str = "development"
    APP_NAME: str = "CollegeBites"
    API_PREFIX: str = "/api/v1"
    COLLEGE_TIMEZONE: str = "Asia/Kolkata"
    PUBLIC_BASE_URL: str = "http://localhost:5173"
    PUBLIC_FRONTEND_URL: str = ""
    API_BASE_URL: str = "http://localhost:8000"

    DATABASE_URL: str = "postgresql+psycopg://postgres@127.0.0.1:5432/collegebites"
    TEST_DATABASE_URL: str = "postgresql+psycopg://postgres@127.0.0.1:5432/collegebites_test"
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 30

    REDIS_URL: str = "memory://"

    @model_validator(mode="after")
    def _apply_cloud_env_fallbacks(self) -> "Settings":
        # Map Vercel Marketplace Postgres / Upstash KV / Vercel URL variables when explicit overrides are unset
        cloud_db = os.environ.get("POSTGRES_URL") or os.environ.get("POSTGRES_PRISMA_URL") or os.environ.get("NEON_DATABASE_URL")
        if cloud_db and "127.0.0.1" in self.DATABASE_URL and not os.environ.get("DATABASE_URL"):
            self.DATABASE_URL = cloud_db
        cloud_redis = os.environ.get("KV_URL") or os.environ.get("UPSTASH_REDIS_URL")
        if cloud_redis and self.REDIS_URL == "memory://" and not os.environ.get("REDIS_URL"):
            self.REDIS_URL = cloud_redis
        vercel_host = os.environ.get("VERCEL_PROJECT_PRODUCTION_URL") or os.environ.get("VERCEL_URL")
        if vercel_host and "localhost" in self.PUBLIC_BASE_URL and not os.environ.get("PUBLIC_BASE_URL"):
            self.PUBLIC_BASE_URL = f"https://{vercel_host}"
        return self

    @property
    def public_frontend_url(self) -> str:
        explicit = self.PUBLIC_FRONTEND_URL.strip()
        if explicit:
            return explicit.rstrip("/")
        if os.environ.get("PUBLIC_BASE_URL"):
            return os.environ["PUBLIC_BASE_URL"].strip().rstrip("/")
        vercel_prod = os.environ.get("VERCEL_PROJECT_PRODUCTION_URL", "").strip()
        if vercel_prod:
            return f"https://{vercel_prod}".rstrip("/")
        return self.PUBLIC_BASE_URL.strip().rstrip("/")

    SECRET_KEY: str = "dev-only-change-me-collegebites-secret-key-at-least-64-characters-long"
    QR_SIGNING_SECRET: str = "dev-only-change-me-collegebites-qr-hmac-secret-at-least-64-characters"
    BACKUP_ENCRYPTION_KEY: str = ""
    CRON_SECRET: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    OTP_EXPIRY_MINUTES: int = 5
    OTP_MAX_ATTEMPTS: int = 5
    OTP_TEST_ECHO: bool = True

    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""
    RAZORPAY_TEST_MODE: bool = True

    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_TEST_MODE: bool = True

    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_SECURE: bool = False
    SMTP_FROM_EMAIL: str = "noreply@collegebites.edu"

    @property
    def effective_smtp_user(self) -> str:
        return (self.SMTP_USER or self.SMTP_USERNAME or "").strip()

    @property
    def effective_smtp_from(self) -> str:
        if self.SMTP_FROM_EMAIL and self.SMTP_FROM_EMAIL != "noreply@collegebites.edu":
            return self.SMTP_FROM_EMAIL.strip()
        if "@" in self.effective_smtp_user:
            return self.effective_smtp_user
        return self.SMTP_FROM_EMAIL
    SMS_PROVIDER: str = "log"
    WHATSAPP_PROVIDER: str = "log"
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_FROM_NUMBER: str = ""
    TWILIO_WHATSAPP_FROM: str = ""
    SMS_WEBHOOK_URL: str = ""

    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""
    VAPID_SUBJECT: str = "mailto:admin@collegebites.edu"

    NETWORK_PRINTER_ENABLED: bool = False
    DEFAULT_PRINTER_IP: str = "192.168.1.200"
    DEFAULT_PRINTER_PORT: int = 9100

    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8081"
    RATE_LIMIT_DEFAULT: str = "300/minute"
    RATE_LIMIT_ENABLED: bool = True

    @property
    def cors_origin_list(self) -> List[str]:
        origins = [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]
        for env_key in ("VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL", "VERCEL_BRANCH_URL"):
            host = os.environ.get(env_key)
            if host:
                origin = f"https://{host}"
                if origin not in origins:
                    origins.append(origin)
        return origins

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
