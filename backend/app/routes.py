from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api_keys import create_api_key
from app.auth import get_current_user, require_admin
from app.database import get_db
from app.models import ApiKey, User, utc_now
from app.schemas import ApiKeyCreated, ApiKeyRead, UserCreate, UserRead

router = APIRouter()


def _new_api_key_for_user(user_id: int, db: Session) -> dict[str, object]:
    raw_key, key_prefix, key_hash = create_api_key()
    api_key = ApiKey(user_id=user_id, key_prefix=key_prefix, key_hash=key_hash)
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return {**ApiKeyRead.model_validate(api_key).model_dump(), "raw_key": raw_key}


@router.get("/me", response_model=UserRead, tags=["team"])
def get_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.get("/users", response_model=list[UserRead], tags=["admin"])
def list_users(_: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[User]:
    return list(db.scalars(select(User).order_by(User.id)).all())


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED, tags=["admin"])
def create_member(
    payload: UserCreate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> User:
    email = payload.email.strip().lower()
    full_name = payload.full_name.strip()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(status_code=422, detail="A valid email address is required")
    if not full_name:
        raise HTTPException(status_code=422, detail="A non-empty full name is required")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="A user with this email already exists")
    user = User(email=email, full_name=full_name, role="member")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/users/{user_id}/api-keys", response_model=list[ApiKeyRead], tags=["admin"])
def list_member_api_keys(
    user_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)
) -> list[ApiKey]:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    statement = select(ApiKey).where(ApiKey.user_id == user_id).order_by(ApiKey.id)
    return list(db.scalars(statement).all())


@router.post(
    "/users/{user_id}/api-keys", response_model=ApiKeyCreated, status_code=201, tags=["admin"]
)
def issue_member_api_key(
    user_id: int,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=404, detail="Active user not found")
    return _new_api_key_for_user(user.id, db)


@router.delete(
    "/users/{user_id}/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["admin"],
)
def revoke_member_api_key(
    user_id: int,
    key_id: int,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    api_key = db.scalar(select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user_id))
    if api_key is None:
        raise HTTPException(status_code=404, detail="API key not found")
    if api_key.revoked_at is None:
        api_key.revoked_at = utc_now()
        db.commit()


@router.get("/api-keys", response_model=list[ApiKeyRead], tags=["team"])
def list_api_keys(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[ApiKey]:
    statement = select(ApiKey).where(ApiKey.user_id == current_user.id).order_by(ApiKey.id)
    return list(db.scalars(statement).all())


@router.post("/api-keys", response_model=ApiKeyCreated, status_code=201, tags=["team"])
def issue_api_key(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict[str, object]:
    return _new_api_key_for_user(current_user.id, db)


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["team"])
def revoke_api_key(
    key_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    api_key = db.scalar(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == current_user.id)
    )
    if api_key is None:
        raise HTTPException(status_code=404, detail="API key not found")
    if api_key.revoked_at is None:
        api_key.revoked_at = utc_now()
        db.commit()
