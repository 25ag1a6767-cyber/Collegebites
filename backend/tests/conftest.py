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
os.environ["EMAIL_PROVIDER"] = "none"
os.environ["SMS_PROVIDER"] = "none"
os.environ["TWILIO_ACCOUNT_SID"] = ""
os.environ["TWILIO_AUTH_TOKEN"] = ""
os.environ["TWILIO_FROM_NUMBER"] = ""
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

from app.core.database import get_db  # noqa: E402
from app.core.redis_client import get_redis_manager  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.services.seed_service import seed_initial_college_data  # noqa: E402

test_engine = create_engine(TEST_DB_URL, pool_pre_ping=True)
TestingSessionLocal = sessionmaker(bind=test_engine, autocommit=False, autoflush=False, expire_on_commit=False)


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
