from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api_keys import hash_api_key
from app.database import SessionLocal
from app.main import app
from app.models import ApiKey
from tests.helpers import create_user_and_key


def test_user_can_issue_and_revoke_own_key() -> None:
    _, original_key = create_user_and_key()
    headers = {"Authorization": f"Bearer {original_key}"}

    with TestClient(app) as client:
        created = client.post("/api-keys", headers=headers)
        assert created.status_code == 201
        new_key = created.json()["raw_key"]
        new_key_id = created.json()["id"]

        with SessionLocal() as db:
            saved_key = db.scalar(select(ApiKey).where(ApiKey.id == new_key_id))
            assert saved_key is not None
            assert saved_key.key_hash == hash_api_key(new_key)
            assert new_key not in saved_key.key_hash

        revoked = client.delete(f"/api-keys/{new_key_id}", headers=headers)
        assert revoked.status_code == 204
        rejected = client.get("/me", headers={"Authorization": f"Bearer {new_key}"})
        assert rejected.status_code == 401


def test_admin_can_create_member_and_issue_member_key() -> None:
    _, admin_key = create_user_and_key(role="admin")
    admin_headers = {"Authorization": f"Bearer {admin_key}"}

    with TestClient(app) as client:
        created_user = client.post(
            "/users",
            headers=admin_headers,
            json={"email": f"{uuid4()}@example.test", "full_name": "New Member"},
        )
        assert created_user.status_code == 201, created_user.text
        assert created_user.json()["role"] == "member"

        created_key = client.post(
            f"/users/{created_user.json()['id']}/api-keys", headers=admin_headers
        )
        assert created_key.status_code == 201, created_key.text
        listed_keys = client.get(
            f"/users/{created_user.json()['id']}/api-keys", headers=admin_headers
        )
        assert listed_keys.status_code == 200
        assert any(k["id"] == created_key.json()["id"] for k in listed_keys.json())
        assert all("raw_key" not in k for k in listed_keys.json())
        member_headers = {"Authorization": f"Bearer {created_key.json()['raw_key']}"}

        member_profile = client.get("/me", headers=member_headers)
        assert member_profile.status_code == 200
        assert member_profile.json()["role"] == "member"
        forbidden = client.get("/users", headers=member_headers)
        assert forbidden.status_code == 403

        revoked = client.delete(
            f"/users/{created_user.json()['id']}/api-keys/{created_key.json()['id']}",
            headers=admin_headers,
        )
        assert revoked.status_code == 204
        rejected = client.get("/me", headers=member_headers)
        assert rejected.status_code == 401
