from uuid import uuid4

from app.api_keys import create_api_key
from app.database import SessionLocal
from app.models import ApiKey, User


def create_user_and_key(role: str = "member") -> tuple[int, str]:
    with SessionLocal() as db:
        user = User(email=f"{uuid4()}@example.test", full_name="Test User", role=role)
        db.add(user)
        db.flush()
        raw_key, key_prefix, key_hash = create_api_key()
        db.add(ApiKey(user_id=user.id, key_prefix=key_prefix, key_hash=key_hash))
        db.commit()
        return user.id, raw_key
