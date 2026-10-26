import argparse

from sqlalchemy import select

from app.api_keys import create_api_key
from app.database import SessionLocal, init_database
from app.models import ApiKey, User


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the first Urumi gateway admin")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()

    email = args.email.strip().lower()
    full_name = args.name.strip()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        parser.error("--email must be a valid email address")
    if not full_name:
        parser.error("--name must not be empty")

    init_database()
    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.email == email))
        if existing:
            parser.error(f"User {email} already exists; no new key was issued")

        user = User(email=email, full_name=full_name, role="admin")
        db.add(user)
        db.flush()
        raw_key, key_prefix, key_hash = create_api_key()
        db.add(ApiKey(user_id=user.id, key_prefix=key_prefix, key_hash=key_hash))
        db.commit()

    print(f"Admin created: {email}")
    print("Copy this API key now; it is shown only once:")
    print(raw_key)


if __name__ == "__main__":
    main()
