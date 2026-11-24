import os
import re
from collections.abc import Generator
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# Point tests at dedicated collegebites_test PostgreSQL database (or SQLite override)
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/collegebites_test?sslmode=disable",
)
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["REDIS_URL"] = os.environ.get("TEST_REDIS_URL", "memory://")
os.environ["RAZORPAY_TEST_MODE"] = "true"
# Keep unit/integration test suite deterministic offline regardless of local .env keys
os.environ["RAZORPAY_KEY_ID"] = ""
os.environ["RAZORPAY_KEY_SECRET"] = ""
os.environ["RAZORPAY_WEBHOOK_SECRET"] = ""
os.environ["SMTP_HOST"] = ""
os.environ["SMTP_USER"] = ""
os.environ["SMTP_USERNAME"] = ""
os.environ["SMTP_PASSWORD"] = ""
os.environ["RESEND_API_KEY"] = ""
os.environ["SENDGRID_API_KEY"] = ""
os.environ["OTP_PROVIDER"] = ""
os.environ["OTP_SMS_ENABLED"] = "false"
os.environ["SMS_PROVIDER"] = "none"
os.environ["TWILIO_ACCOUNT_SID"] = ""
os.environ["TWILIO_AUTH_TOKEN"] = ""
os.environ["TWILIO_FROM_NUMBER"] = ""
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

from app.core.config import settings  # noqa: E402
from app.core.database import get_db  # noqa: E402
from app.core.redis_client import get_redis_manager  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.services import auth_service  # noqa: E402
from app.services.seed_service import seed_initial_college_data  # noqa: E402

test_engine = create_engine(TEST_DB_URL, pool_pre_ping=True)
TestingSessionLocal = sessionmaker(bind=test_engine, autocommit=False, autoflush=False, expire_on_commit=False)


@dataclass
class OTPOutbox:
    """Server-side outbound OTP capture for integration tests (never exposed in HTTP responses)."""

    messages: list[dict[str, str]] = field(default_factory=list)

    def record(self, target: str, code: str, channel: str, purpose: str) -> None:
        self.messages.append(
            {
                "target": target.strip().lower(),
                "digits": "".join(ch for ch in target if ch.isdigit()),
                "code": code,
                "channel": channel,
                "purpose": purpose,
            }
        )

    def latest_code(self, target: str) -> str:
        norm = target.strip().lower()
        digits = "".join(ch for ch in target if ch.isdigit())
        for item in reversed(self.messages):
            if item["target"] == norm:
                return item["code"]
            if digits and item["digits"] and (item["digits"] == digits or item["digits"].endswith(digits[-10:])):
                return item["code"]
        raise AssertionError(f"No outbound OTP captured for target={target!r}")


@pytest.fixture()
def otp_capture(monkeypatch: pytest.MonkeyPatch) -> OTPOutbox:
    """Opt-in server-side OTP provider sandbox for legacy integration suites."""
    outbox = OTPOutbox()
    monkeypatch.setattr(settings, "OTP_RESEND_COOLDOWN_SECONDS", 0)
    monkeypatch.setattr(settings, "OTP_RATE_LIMIT_PER_DEST_15M", 50)
    monkeypatch.setattr(settings, "OTP_RATE_LIMIT_PER_IP_15M", 200)
    monkeypatch.setattr(settings, "OTP_RATE_LIMIT_PER_USER_15M", 50)
    monkeypatch.setattr(auth_service, "resolve_email_otp_provider", lambda: "smtp")
    monkeypatch.setattr(auth_service, "resolve_sms_otp_provider", lambda: "twilio")

    def _fake_email(to_email: str, subject: str, body: str):
        m = re.search(r"\b(\d{6})\b", body)
        assert m, f"Expected 6-digit OTP in email body: {body!r}"
        outbox.record(to_email, m.group(1), "email", subject)
        return True, "smtp"

    def _fake_sms(to_phone: str, message: str):
        m = re.search(r"\b(\d{6})\b", message)
        assert m, f"Expected 6-digit OTP in SMS body: {message!r}"
        outbox.record(to_phone, m.group(1), "sms", "sms")
        return True, "twilio"

    monkeypatch.setattr(auth_service, "deliver_otp_email", _fake_email)
    monkeypatch.setattr(auth_service, "deliver_otp_sms", _fake_sms)
    return outbox


@pytest.fixture(scope="session", autouse=True)
def setup_test_database() -> Generator[None, None, None]:
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(autouse=True)
def clean_db_and_seed() -> Generator[Session, None, None]:
    # Truncate all tables cleanly between tests so every test gets an isolated seeded college
    with test_engine.begin() as conn:
        table_names = [t.name for t in reversed(Base.metadata.sorted_tables)]
        if table_names:
            if test_engine.dialect.name == "sqlite":
                conn.execute(text("PRAGMA foreign_keys = OFF"))
                for name in table_names:
                    conn.execute(text(f'DELETE FROM "{name}"'))
                conn.execute(text("PRAGMA foreign_keys = ON"))
            else:
                conn.execute(text("TRUNCATE TABLE " + ", ".join(f'"{name}"' for name in table_names) + " RESTART IDENTITY CASCADE"))
    get_redis_manager().reset_for_tests()

    db = TestingSessionLocal()
    try:
        seed_initial_college_data(db, create_demo_users=True)
        yield db
    finally:
        db.close()


@pytest.fixture()
def client(clean_db_and_seed: Session) -> Generator[TestClient, None, None]:
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def login_as(client: TestClient, identifier: str, password: str) -> dict:
    resp = client.post("/api/v1/auth/login", json={"identifier": identifier, "password": password})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    return {
        "headers": {"Authorization": f"Bearer {data['access_token']}"},
        "token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "user": data["user"],
    }
