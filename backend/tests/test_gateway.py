from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import UpstreamServer
from tests.helpers import create_user_and_key


def test_gateway_lists_namespaced_tools_and_audits_calls(monkeypatch):
    _, key = create_user_and_key("admin")
    headers = {"Authorization": f"Bearer {key}"}
    slug = f"teststock-{uuid4().hex[:8]}"
    with TestClient(app) as client:
        created = client.post(
            "/admin/servers",
            headers=headers,
            json={"name": "Mock Inventory", "slug": slug, "url": "http://mock/mcp"},
        )
        assert created.status_code == 201

        async def fake_call(server, payload):
            if payload["method"] == "tools/list":
                return {
                    "jsonrpc": "2.0",
                    "id": "discover",
                    "result": {
                        "tools": [
                            {
                                "name": "list_inventory",
                                "description": "List",
                                "inputSchema": {"type": "object", "properties": {}},
                            }
                        ]
                    },
                }
            return {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {"content": [{"type": "text", "text": "ok"}]},
            }

        monkeypatch.setattr("app.gateway._call", fake_call)
        listed = client.post(
            "/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        assert listed.status_code == 200
        assert any(
            tool["name"] == f"{slug}__list_inventory" for tool in listed.json()["result"]["tools"]
        )
        called = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": f"{slug}__list_inventory", "arguments": {}},
            },
        )
        assert called.json()["result"]["content"][0]["text"] == "ok"
        rows = client.get("/audit", headers=headers).json()
        assert any(row["server_slug"] == slug and row["outcome"] == "success" for row in rows)
        disabled = client.patch(
            f"/admin/servers/{created.json()['id']}", headers=headers, json={"is_enabled": False}
        )
        assert disabled.status_code == 200
        remaining = client.post(
            "/api/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "id": 9, "method": "tools/list", "params": {}},
        )
        assert all(
            tool["name"] != f"{slug}__list_inventory"
            for tool in remaining.json()["result"]["tools"]
        )
        duplicate = client.post(
            "/admin/servers",
            headers=headers,
            json={"name": "Duplicate", "slug": slug, "url": "http://mock"},
        )
        assert duplicate.status_code == 409
        removed = client.delete(f"/admin/servers/{created.json()['id']}", headers=headers)
        assert removed.status_code == 204


def test_gateway_requires_api_key():
    with TestClient(app) as client:
        response = client.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        )
    assert response.status_code == 401


def test_upstream_credentials_are_encrypted_and_not_returned(monkeypatch):
    _, key = create_user_and_key("admin")
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    secret = "Bearer very-secret-token"
    with TestClient(app) as client:
        created = client.post(
            "/admin/servers",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "name": "Secret Service",
                "slug": f"secret-{uuid4().hex[:8]}",
                "url": "http://mock/mcp",
                "credentials": {"authorization": secret},
            },
        )
        assert created.status_code == 201
        assert created.json()["has_credentials"] is True
        assert "credential_ciphertext" not in created.json()
        with SessionLocal() as db:
            server = db.get(UpstreamServer, created.json()["id"])
            assert server is not None
            assert server.credential_ciphertext != secret
            assert secret not in server.credential_ciphertext


def test_gateway_initializes_upstream_and_does_not_forward_client_key(monkeypatch):
    import httpx

    from app import gateway

    calls = []

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, json, headers):
            calls.append((json, dict(headers)))
            if json["method"] == "initialize":
                data = {
                    "jsonrpc": "2.0",
                    "id": "gateway-init",
                    "result": {"protocolVersion": "2025-03-26"},
                }
            elif json["method"] == "notifications/initialized":
                return httpx.Response(202, request=httpx.Request("POST", url))
            else:
                data = {"jsonrpc": "2.0", "id": json["id"], "result": {"tools": []}}
            return httpx.Response(200, json=data, request=httpx.Request("POST", url))

    monkeypatch.setattr(gateway.httpx, "AsyncClient", Client)
    monkeypatch.setattr(
        gateway, "decrypt_credentials", lambda _: {"authorization": "Bearer upstream-only"}
    )
    import asyncio

    result = asyncio.run(
        gateway._call(
            UpstreamServer(url="http://upstream/mcp"),
            {"jsonrpc": "2.0", "id": 5, "method": "tools/list"},
        )
    )
    assert result["result"]["tools"] == []
    assert [c[0]["method"] for c in calls] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
    ]
    assert all(c[1]["Authorization"] == "Bearer upstream-only" for c in calls)
