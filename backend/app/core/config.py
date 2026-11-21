from functools import lru_cache
from typing import List
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
    PUBLIC_BASE_URL: str = "http://localhost:5173"
    API_BASE_URL: str = "http://localhost:8000"

    DATABASE_URL: str = "postgresql+psycopg://postgres@127.0.0.1:5432/collegebites"
    TEST_DATABASE_URL: str = "postgresql+psycopg://postgres@127.0.0.1:5432/collegebites_test"
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 30

    REDIS_URL: str = "memory://"

    SECRET_KEY: str = "dev-only-change-me-collegebites-secret-key-at-least-64-characters-long"
    QR_SIGNING_SECRET: str = "dev-only-change-me-collegebites-qr-hmac-secret-at-least-64-characters"
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
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "noreply@collegebites.edu"
    SMS_PROVIDER: str = "log"
    WHATSAPP_PROVIDER: str = "log"
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_FROM_NUMBER: str = ""
    TWILIO_WHATSAPP_FROM: str = ""
    SMS_WEBHOOK_URL: str = ""

    NETWORK_PRINTER_ENABLED: bool = False
    DEFAULT_PRINTER_IP: str = "192.168.1.200"
    DEFAULT_PRINTER_PORT: int = 9100

    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8081"
    RATE_LIMIT_DEFAULT: str = "120/minute"

    @property
    def cors_origin_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
