import base64
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Store, UpstreamServer
from app.provisioner import claim_namespace, store_secret
from app.store_resources import bootstrap_job, resources
from tests.helpers import create_user_and_key


def test_store_ownership_idempotency_quota_retry_delete(monkeypatch):
    monkeypatch.setenv("STORE_PROVISIONING_ENABLED", "true")
    monkeypatch.setenv("MAX_STORES_PER_USER", "1")
    owner_id, key = create_user_and_key()
    _, other = create_user_and_key()
    headers = {"Authorization": "Bearer " + key}
    body = {"name": "North Store", "request_id": uuid4().hex}
    with TestClient(app) as client:
        response = client.post("/stores", headers=headers, json=body)
        assert response.status_code == 202
        s = response.json()
        assert s["status"] == "Provisioning" and "password" not in str(s).lower()
        assert client.post("/stores", headers=headers, json=body).json()["id"] == s["id"]
        assert (
            client.post("/stores", headers=headers, json={**body, "name": "Different"}).status_code
            == 409
        )
        assert (
            client.post(
                "/stores", headers=headers, json={**body, "request_id": uuid4().hex}
            ).status_code
            == 409
        )
        assert client.get("/stores", headers={"Authorization": "Bearer " + other}).json() == []
        assert (
            client.delete(
                "/stores/" + s["id"], headers={"Authorization": "Bearer " + other}
            ).status_code
            == 404
        )
        with SessionLocal() as db:
            row = db.get(Store, s["id"])
            row.status = "Failed"
            row.error = "test failure"
            db.commit()
        retried = client.post(f"/stores/{s['id']}/retry", headers=headers)
        assert retried.json()["status"] == "Provisioning"
        assert retried.json()["error"] is None
        with SessionLocal() as db:
            db.add(
                UpstreamServer(
                    slug="store-" + s["id"], name="North", url="http://mcp/mcp", is_enabled=True
                )
            )
            db.commit()
        assert client.delete(f"/stores/{s['id']}", headers=headers).json()["status"] == "Deleting"
        with SessionLocal() as db:
            upstream = db.query(UpstreamServer).filter_by(slug="store-" + s["id"]).one()
            assert upstream.is_enabled is False
            assert db.get(Store, s["id"]).owner_id == owner_id


def test_store_feature_flag_and_auth(monkeypatch):
    _, key = create_user_and_key()
    monkeypatch.delenv("STORE_PROVISIONING_ENABLED", raising=False)
    with TestClient(app) as client:
        assert client.get("/stores").status_code == 401
        assert (
            client.post(
                "/stores",
                headers={"Authorization": "Bearer " + key},
                json={"name": "Shop", "request_id": uuid4().hex},
            ).status_code
            == 503
        )


def test_store_resources_enforce_network_boundaries_and_guards(monkeypatch):
    monkeypatch.setenv("STORE_WORDPRESS_IMAGE", "wp:test")
    monkeypatch.setenv("STORE_MCP_IMAGE", "mcp:test")
    s = SimpleNamespace(
        id="abc123",
        namespace="urumi-store-abc123",
        url="http://shop-abc123.127.0.0.1.nip.io:8088",
        name="North",
    )
    manifests = list(resources(s))
    assert all(m["metadata"]["namespace"] == s.namespace for m in manifests)
    by_name = {(m["kind"], m["metadata"]["name"]): m for m in manifests}
    deny = by_name["NetworkPolicy", "default-deny"]["spec"]
    assert deny["ingress"] == deny["egress"] == []
    mcp = by_name["NetworkPolicy", "mcp-only-gateway"]["spec"]
    assert (
        mcp["ingress"][0]["from"][0]["namespaceSelector"]["matchLabels"][
            "kubernetes.io/metadata.name"
        ]
        == "urumi"
    )
    assert mcp["egress"][1]["to"] == [{"podSelector": {"matchLabels": {"app": "wordpress"}}}]
    assert ("ResourceQuota", "store-budget") in by_name
    assert ("LimitRange", "store-defaults") in by_name
    assert len([m for m in manifests if m["kind"] == "PersistentVolumeClaim"]) == 2
    for m in manifests:
        if m["kind"] == "Deployment":
            pod = m["spec"]["template"]["spec"]
            assert pod["automountServiceAccountToken"] is False
            assert all(
                "readinessProbe" in c and "livenessProbe" in c and "resources" in c
                for c in pod["containers"]
            )
    assert bootstrap_job(s)["spec"]["activeDeadlineSeconds"] == 600


def test_recovery_preserves_secrets_and_refuses_foreign_namespace():
    s = SimpleNamespace(id="abc", namespace="urumi-store-abc")

    class Kube:
        def get(self, kind, name, ns=None):
            if kind == "Secret":
                return {"data": {"DB_PASSWORD": base64.b64encode(b"unchanged").decode()}}
            return {"metadata": {"labels": {"urumi.io/store-id": "someone-else"}}}

        def create(self, _):
            raise AssertionError("Existing secret must not be replaced")

    assert store_secret(Kube(), s)["DB_PASSWORD"] == "unchanged"
    import pytest

    with pytest.raises(RuntimeError, match="ownership mismatch"):
        claim_namespace(Kube(), s)


def test_controller_recovery_registration_and_observed_teardown(monkeypatch):
    """Simulate a restart after resources exist, then a deletion and delayed namespace removal."""
    from cryptography.fernet import Fernet

    from app import provisioner
    from app.models import utc_now

    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("STORE_WORDPRESS_IMAGE", "wp:test")
    monkeypatch.setenv("STORE_MCP_IMAGE", "mcp:test")
    owner, _ = create_user_and_key()
    sid = uuid4().hex[:12]
    with SessionLocal() as db:
        db.add(
            Store(
                id=sid,
                owner_id=owner,
                name="Recover",
                request_key=uuid4().hex,
                namespace="urumi-store-" + sid,
                url="http://recover.test",
                status="Provisioning",
                phase="Installing WooCommerce",
                attempt_started_at=utc_now(),
            )
        )
        db.commit()

    class Lock:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, *args):
            return SimpleNamespace(scalar=lambda: True)

        def commit(self):
            pass

    monkeypatch.setattr(
        provisioner,
        "engine",
        SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), connect=Lock),
    )
    state = {"namespace": True, "delete_requested": False}

    class Kube:
        client = SimpleNamespace(close=lambda: None)

        def get(self, kind, name, ns=None):
            if kind == "Namespace":
                return (
                    {"metadata": {"labels": {"urumi.io/store-id": sid}}}
                    if state["namespace"]
                    else None
                )
            if kind == "Secret":
                return {"data": {"MCP_AUTH_TOKEN": base64.b64encode(b"stable-token").decode()}}
            if kind == "Deployment":
                return {"status": {"availableReplicas": 1}}
            if kind == "Job":
                return {"status": {"succeeded": 1}}

        def list(self, kind):
            if kind == "StorageClass":
                return [
                    {
                        "metadata": {
                            "name": "standard",
                            "annotations": {"storageclass.kubernetes.io/is-default-class": "true"},
                        },
                        "reclaimPolicy": "Delete",
                    }
                ]
            return []

        def apply(self, resource):
            return resource

        def delete(self, kind, name, ns=None):
            state["delete_requested"] = True

    monkeypatch.setattr(provisioner, "Kube", Kube)
    provisioner.reconcile(sid)
    provisioner.reconcile(sid)
    with SessionLocal() as db:
        s = db.get(Store, sid)
        assert s.status == "Ready"
        assert db.query(UpstreamServer).filter_by(slug="store-" + sid).count() == 1
        s.status = "Deleting"
        db.commit()
    provisioner.reconcile(sid)
    with SessionLocal() as db:
        assert (
            db.get(Store, sid).status == "Deleting"
        )  # Must not claim cleanup before deletion observed.
    assert state["delete_requested"]
    state["namespace"] = False
    provisioner.reconcile(sid)
    with SessionLocal() as db:
        assert db.get(Store, sid).status == "Deleted"
        assert db.query(UpstreamServer).filter_by(slug="store-" + sid).count() == 0
