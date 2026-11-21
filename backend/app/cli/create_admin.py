import argparse
import getpass
import sys

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.permissions import ROLE_SUPER_ADMIN
from app.core.security import hash_password
from app.models.auth import Role, StaffProfile, User, UserRole
from app.services.seed_service import ensure_roles_and_permissions


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap a CollegeBites Super Administrator account.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--employee-code", default="ADMIN-001")
    args = parser.parse_args()

    password = getpass.getpass("Enter administrator password (min 12 chars): ")
    if len(password) < 12:
        print("Error: Password must be at least 12 characters.", file=sys.stderr)
        sys.exit(1)

    with SessionLocal() as db:
        ensure_roles_and_permissions(db)
        existing = db.scalar(select(User).where(User.email == args.email.lower()))
        if existing:
            print(f"Error: User {args.email} already exists.", file=sys.stderr)
            sys.exit(1)
        role = db.scalar(select(Role).where(Role.name == ROLE_SUPER_ADMIN))
        user = User(
            email=args.email.lower(),
            full_name=args.name,
            password_hash=hash_password(password),
            user_kind="admin",
            is_active=True,
            is_verified=True,
        )
        db.add(user)
        db.flush()
        db.add(UserRole(user_id=user.id, role_id=role.id))
        db.add(StaffProfile(user_id=user.id, employee_code=args.employee_code, designation="Super Administrator"))
        db.commit()
        print(f"Created Super Administrator: {user.email} (id={user.id})")


if __name__ == "__main__":
    main()
