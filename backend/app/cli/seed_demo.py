from app.core.database import SessionLocal
from app.services.seed_service import seed_initial_college_data


def main() -> None:
    with SessionLocal() as db:
        result = seed_initial_college_data(db, create_demo_users=True)
        print("Seeded CollegeBites initial data:", result)


if __name__ == "__main__":
    main()
