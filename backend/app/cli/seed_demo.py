from app.core.config import settings
from app.core.database import SessionLocal
from app.services.seed_service import seed_initial_college_data


def main() -> None:
    if settings.is_production:
        raise RuntimeError("Refusing to run demo account seed in production environment")
    with SessionLocal() as db:
        result = seed_initial_college_data(db, create_demo_users=True)
        print("Seeded CollegeBites initial data:", result)


if __name__ == "__main__":
    main()
