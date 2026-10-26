"""Persistent provisioning requests. Kubernetes credentials never enter the API/browser."""

import os
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Store, UpstreamServer, User, utc_now

router = APIRouter(prefix="/stores", tags=["stores"])


class StoreCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9-]+$")


def public(s):
    return {
        k: getattr(s, k)
        for k in (
            "id",
            "owner_id",
            "name",
            "namespace",
            "url",
            "status",
            "phase",
            "error",
            "created_at",
        )
    }


def owned(db, store_id, user):
    s = db.get(Store, store_id)
    if not s or (s.owner_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Store not found")
    return s


@router.get("")
def list_stores(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = select(Store).where(Store.status != "Deleted").order_by(Store.created_at.desc())
    if user.role != "admin":
        q = q.where(Store.owner_id == user.id)
    return [public(s) for s in db.scalars(q)]


@router.post("", status_code=202)
def create_store(
    payload: StoreCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if os.getenv("STORE_PROVISIONING_ENABLED", "false").lower() != "true":
        raise HTTPException(503, "Store provisioning is not enabled")
    # Serialize quota decisions for this owner, including concurrent requests.
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    request_key = f"{user.id}:{payload.request_id}"
    existing = db.scalar(select(Store).where(Store.request_key == request_key))
    if existing:
        if existing.name != payload.name.strip():
            raise HTTPException(409, "Request ID already used with another name")
        return public(existing)
    count = len(
        list(
            db.scalars(select(Store.id).where(Store.owner_id == user.id, Store.status != "Deleted"))
        )
    )
    if count >= int(os.getenv("MAX_STORES_PER_USER", "3")):
        raise HTTPException(409, "Store limit reached; delete an existing store first")
    if not payload.name.strip():
        raise HTTPException(422, "Store name cannot be blank")
    sid = uuid4().hex[:12]
    domain = os.getenv("STORE_BASE_DOMAIN", "127.0.0.1.nip.io")
    port = os.getenv("STORE_PUBLIC_PORT", "8088")
    scheme = os.getenv("STORE_PUBLIC_SCHEME", "http")
    url = f"{scheme}://shop-{sid}.{domain}" + (f":{port}" if port else "")
    s = Store(
        id=sid,
        owner_id=user.id,
        name=payload.name.strip(),
        request_key=request_key,
        namespace=f"urumi-store-{sid}",
        url=url,
        status="Provisioning",
    )
    db.add(s)
    db.commit()
    return public(s)


@router.post("/{store_id}/retry", status_code=202)
def retry_store(
    store_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    s = owned(db, store_id, user)
    if s.status != "Failed":
        raise HTTPException(409, "Only failed stores can be retried")
    s.status, s.phase, s.error = "Provisioning", "Queued for retry", None
    s.attempt_started_at = utc_now()
    db.commit()
    return public(s)


@router.delete("/{store_id}", status_code=202)
def delete_store(
    store_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    s = owned(db, store_id, user)
    if s.status != "Deleted":
        s.status, s.phase, s.error = "Deleting", "Removing resources", None
        upstream = db.scalar(select(UpstreamServer).where(UpstreamServer.slug == f"store-{s.id}"))
        if upstream:
            upstream.is_enabled = False
            upstream.status = "disabled"
        db.commit()
    return public(s)
