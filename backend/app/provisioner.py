"""Recoverable Kubernetes reconciler. Run separately from the public gateway."""

import base64
import json
import logging
import os
import secrets
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from sqlalchemy import select, text

from app.database import SessionLocal, engine, init_database
from app.models import Store, UpstreamServer, utc_now
from app.secret_store import encrypt_credentials
from app.store_resources import bootstrap_job, resources

log = logging.getLogger("provisioner")
KINDS = {
    "StorageClass": ("/apis/storage.k8s.io/v1", "storageclasses"),
    "PersistentVolume": ("/api/v1", "persistentvolumes"),
    "Namespace": ("/api/v1", "namespaces"),
    "Secret": ("/api/v1", "secrets"),
    "Service": ("/api/v1", "services"),
    "PersistentVolumeClaim": ("/api/v1", "persistentvolumeclaims"),
    "ResourceQuota": ("/api/v1", "resourcequotas"),
    "LimitRange": ("/api/v1", "limitranges"),
    "Deployment": ("/apis/apps/v1", "deployments"),
    "Job": ("/apis/batch/v1", "jobs"),
    "Ingress": ("/apis/networking.k8s.io/v1", "ingresses"),
    "NetworkPolicy": ("/apis/networking.k8s.io/v1", "networkpolicies"),
}


class Kube:
    def __init__(self):
        root = Path("/var/run/secrets/kubernetes.io/serviceaccount")
        self.token_path = root / "token"
        self.client = httpx.Client(
            base_url="https://kubernetes.default.svc",
            verify=ssl.create_default_context(cafile=str(root / "ca.crt")),
            timeout=20,
            trust_env=False,
        )

    def path(self, kind, name, ns=None):
        base, plural = KINDS[kind]
        return base + (f"/namespaces/{ns}" if ns else "") + f"/{plural}/{name}"

    def request(self, method, path, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = "Bearer " + self.token_path.read_text().strip()
        r = self.client.request(method, path, headers=headers, **kwargs)
        if r.status_code not in (200, 201, 202, 404, 409) or (
            r.status_code == 404 and method not in ("GET", "DELETE")
        ):
            # Never log response bodies/requests; Secret payloads are sensitive.
            raise RuntimeError(f"Kubernetes {method} {path} returned HTTP {r.status_code}")
        return r

    def list(self, kind):
        base, plural = KINDS[kind]
        return self.request("GET", base + "/" + plural).json().get("items", [])

    def get(self, kind, name, ns=None):
        r = self.request("GET", self.path(kind, name, ns))
        return None if r.status_code == 404 else r.json()

    def apply(self, resource):
        m = resource["metadata"]
        r = self.request(
            "PATCH",
            self.path(resource["kind"], m["name"], m.get("namespace")),
            params={"fieldManager": "urumi-store-controller"},
            content=json.dumps(resource),
            headers={"Content-Type": "application/apply-patch+yaml"},
        )
        if r.status_code == 409:
            raise RuntimeError("Kubernetes resource ownership conflict; refusing to take over")
        return r.json()

    def create(self, resource):
        m = resource["metadata"]
        path = self.path(resource["kind"], m["name"], m.get("namespace"))
        return self.request("POST", path.rsplit("/", 1)[0], json=resource)

    def delete(self, kind, name, ns=None):
        return self.request(
            "DELETE", self.path(kind, name, ns), json={"propagationPolicy": "Foreground"}
        )


def phase(store_id, value):
    with SessionLocal() as db:
        s = db.get(Store, store_id)
        if s.status != "Provisioning":
            return False
        s.phase = value
        db.commit()
        return True


def claim_namespace(kube, s):
    existing = kube.get("Namespace", s.namespace)
    if existing:
        if existing["metadata"].get("labels", {}).get("urumi.io/store-id") != s.id:
            raise RuntimeError("Namespace ownership mismatch; refusing to modify it")
        if existing["metadata"].get("deletionTimestamp"):
            raise RuntimeError("Namespace is terminating; wait before retrying")
    else:
        r = kube.create(
            {
                "apiVersion": "v1",
                "kind": "Namespace",
                "metadata": {
                    "name": s.namespace,
                    "labels": {"urumi.io/store-id": s.id, "urumi.io/managed": "true"},
                },
            }
        )
        if r.status_code == 409:
            return claim_namespace(kube, s)


def store_secret(kube, s):
    secret = kube.get("Secret", "store-secrets", s.namespace)
    if not secret:
        values = {
            "DB_PASSWORD": secrets.token_hex(24),
            "DB_ROOT_PASSWORD": secrets.token_hex(24),
            "ADMIN_PASSWORD": secrets.token_urlsafe(32),
            "WOO_CONSUMER_KEY": "ck_" + secrets.token_hex(20),
            "WOO_CONSUMER_SECRET": "cs_" + secrets.token_hex(20),
            "MCP_AUTH_TOKEN": secrets.token_urlsafe(32),
        }
        r = kube.create(
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": "store-secrets", "namespace": s.namespace},
                "type": "Opaque",
                "stringData": values,
            }
        )
        if r.status_code == 409:
            return store_secret(kube, s)
        secret = kube.get("Secret", "store-secrets", s.namespace)
    return {k: base64.b64decode(v).decode() for k, v in secret["data"].items()}


def reconcile(store_id):
    # Session advisory locks survive db.commit() and are released if the process dies.
    # Keep one dedicated connection so another replica cannot reconcile this store concurrently.
    with engine.connect() as lock:
        if engine.dialect.name != "postgresql":
            raise RuntimeError("The provisioning worker requires PostgreSQL")
        locked = lock.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": "urumi:" + store_id}
        ).scalar()
        lock.commit()
        if not locked:
            return
        try:
            with SessionLocal() as db:
                s = db.get(Store, store_id)
            kube = Kube()
            try:
                if s.status == "Deleting":
                    ns = kube.get("Namespace", s.namespace)
                    if ns:
                        if ns["metadata"].get("labels", {}).get("urumi.io/store-id") != s.id:
                            raise RuntimeError("Namespace ownership mismatch; refusing deletion")
                        kube.delete("Namespace", s.namespace)
                        return  # Observe deletion on next pass; namespace finalizers may take time.
                    remaining = [
                        pv
                        for pv in kube.list("PersistentVolume")
                        if pv.get("spec", {}).get("claimRef", {}).get("namespace") == s.namespace
                    ]
                    if remaining:
                        return
                    with SessionLocal() as db:
                        current = db.get(Store, s.id)
                        upstream = db.scalar(
                            select(UpstreamServer).where(UpstreamServer.slug == "store-" + s.id)
                        )
                        if upstream:
                            db.delete(upstream)
                        current.status, current.phase, current.error = (
                            "Deleted",
                            "Resources removed",
                            None,
                        )
                        db.commit()
                    return
                if s.status != "Provisioning":
                    return
                start = s.attempt_started_at
                if start.tzinfo is None:
                    start = start.replace(tzinfo=utc_now().tzinfo)
                if (utc_now() - start).total_seconds() > int(
                    os.getenv("STORE_TIMEOUT_SECONDS", "900")
                ):
                    raise RuntimeError(
                        "Provisioning timeout; inspect the store namespace events, then Retry or Delete"
                    )
                classes = kube.list("StorageClass")
                configured = os.getenv("STORE_STORAGE_CLASS", "")
                selected = (
                    [c for c in classes if c["metadata"]["name"] == configured]
                    if configured
                    else [
                        c
                        for c in classes
                        if c["metadata"]
                        .get("annotations", {})
                        .get("storageclass.kubernetes.io/is-default-class")
                        == "true"
                    ]
                )
                if not selected or any(
                    c.get("reclaimPolicy", "Delete") != "Delete" for c in selected
                ):
                    raise RuntimeError(
                        "Store storage class must exist and use Delete reclaim policy for clean teardown"
                    )
                claim_namespace(kube, s)
                if not phase(s.id, "Applying isolated resources"):
                    return
                # Apply deny/quota rules before workloads. Secrets are create-once to preserve DB credentials.
                manifests = list(resources(s))
                for item in manifests[:7]:
                    kube.apply(item)
                credentials = store_secret(kube, s)
                for item in manifests[7:]:
                    kube.apply(item)
                if not phase(s.id, "Waiting for database and WordPress"):
                    return
                for name in ("database", "wordpress"):
                    dep = kube.get("Deployment", name, s.namespace)
                    if not dep or dep.get("status", {}).get("availableReplicas", 0) < 1:
                        return
                job = kube.get("Job", "bootstrap", s.namespace)
                if not job:
                    kube.create(bootstrap_job(s))
                    return
                if job.get("status", {}).get("failed", 0) >= 4 or any(
                    c.get("type") == "Failed" and c.get("status") == "True"
                    for c in job.get("status", {}).get("conditions", [])
                ):
                    from datetime import datetime

                    created = datetime.fromisoformat(job["metadata"]["creationTimestamp"])
                    if created < start:
                        kube.delete("Job", "bootstrap", s.namespace)
                        return
                    raise RuntimeError(
                        "WordPress bootstrap failed; inspect bootstrap Job logs, then Retry"
                    )
                if job.get("status", {}).get("succeeded", 0) < 1:
                    phase(s.id, "Installing WooCommerce and configuring checkout")
                    return
                dep = kube.get("Deployment", "mcp", s.namespace)
                if dep.get("status", {}).get("availableReplicas", 0) < 1:
                    phase(s.id, "Waiting for MCP server")
                    return
                url = f"http://mcp.{s.namespace}.svc.cluster.local:8010/mcp"
                with SessionLocal() as db:
                    current = db.scalar(select(Store).where(Store.id == s.id).with_for_update())
                    if current.status != "Provisioning":
                        return  # Delete won the race; never register it again.
                    slug = "store-" + s.id
                    upstream = db.scalar(select(UpstreamServer).where(UpstreamServer.slug == slug))
                    if not upstream:
                        upstream = UpstreamServer(name=s.name, slug=slug, url=url)
                        db.add(upstream)
                    upstream.credential_ciphertext = encrypt_credentials(
                        {"authorization": "Bearer " + credentials["MCP_AUTH_TOKEN"]}
                    )
                    upstream.is_enabled, upstream.status = True, "ready"
                    current.status, current.phase, current.error = (
                        "Ready",
                        "Store and MCP ready",
                        None,
                    )
                    db.commit()
            finally:
                kube.client.close()
        except Exception as exc:  # noqa: BLE001 -- persist worker failures instead of losing requests
            # Persist a safe reason. No exception text from httpx, URLs or Secret bodies is returned.
            reason = (
                str(exc)
                if isinstance(exc, RuntimeError)
                else f"{type(exc).__name__}: retry after checking controller logs and namespace events"
            )
            log.warning("Store %s reconciliation: %s", store_id, reason)
            with SessionLocal() as db:
                current = db.get(Store, store_id)
                if current and current.status == "Provisioning":
                    current.status, current.phase, current.error = (
                        "Failed",
                        "Provisioning failed",
                        reason,
                    )
                elif current and current.status == "Deleting":
                    current.error = reason
                db.commit()
        finally:
            lock.execute(
                text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": "urumi:" + store_id}
            )
            lock.commit()


def main():
    logging.basicConfig(level=logging.INFO)
    init_database()
    pending = {}
    with ThreadPoolExecutor(max_workers=int(os.getenv("STORE_CONCURRENCY", "2"))) as pool:
        while True:
            Path("/tmp/provisioner-heartbeat").touch()
            pending = {k: f for k, f in pending.items() if not f.done()}
            with SessionLocal() as db:
                ids = list(
                    db.scalars(
                        select(Store.id).where(Store.status.in_(["Provisioning", "Deleting"]))
                    )
                )
            for sid in ids:
                if sid not in pending and len(pending) < int(os.getenv("STORE_CONCURRENCY", "2")):
                    pending[sid] = pool.submit(reconcile, sid)
            time.sleep(5)


if __name__ == "__main__":
    main()
