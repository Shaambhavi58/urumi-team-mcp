import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient

APP_PATH = Path(__file__).parents[1] / "app.py"
spec = importlib.util.spec_from_file_location("urumi_mcp_service", APP_PATH)
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)

client = TestClient(service.app)


def invoke(name: str, arguments: dict | None = None):
    return client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        },
    )


def test_woocommerce_demo_products_and_orders(monkeypatch):
    monkeypatch.setattr(service, "SERVICE", "woocommerce")
    listed = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    assert len(listed.json()["result"]["tools"]) == 5
    created = invoke("create_product", {"name": "Test Mug", "price": 299})
    assert created.json()["result"]["structuredContent"]["name"] == "Test Mug"
    order = invoke("get_order", {"order_id": 5001})
    assert order.json()["result"]["structuredContent"]["status"] == "processing"
    updated = invoke("update_order_status", {"order_id": 5001, "status": "completed"})
    assert updated.json()["result"]["structuredContent"]["status"] == "completed"


def test_inventory_and_shipping_tools(monkeypatch):
    monkeypatch.setattr(service, "SERVICE", "inventory")
    stock = invoke("check_stock", {"sku": "SKU-TSHIRT"})
    assert stock.json()["result"]["structuredContent"]["available"] == 25
    monkeypatch.setattr(service, "SERVICE", "shipping")
    shipping = invoke("estimate_shipping", {"postal_code": "110001", "weight_kg": 1})
    assert shipping.json()["result"]["structuredContent"]["currency"] == "INR"


def test_initialized_notification_uses_accepted_status():
    response = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert response.status_code == 202


def test_invalid_status_is_rejected_before_store_call(monkeypatch):
    monkeypatch.setattr(service, "SERVICE", "woocommerce")
    response = invoke("list_orders", {"status": "{}"})
    assert response.json()["error"]["code"] == -32602


def test_upstream_auth_rejects_missing_token(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token")
    assert invoke("list_orders").status_code == 401
    response = client.post("/mcp", headers={"Authorization": "Bearer test-token"}, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 200


def test_today_filter_and_private_order_fields(monkeypatch):
    monkeypatch.setattr(service, "SERVICE", "woocommerce")
    monkeypatch.setattr(service, "WOO_URL", "http://wordpress")
    monkeypatch.setattr(service, "WOO_KEY", "ck_test")
    monkeypatch.setattr(service, "WOO_SECRET", "cs_test")
    seen = {}
    async def woo(method, endpoint, data=None, params=None):
        seen.update(params)
        return [{"id": 17, "order_key": "private", "billing": {"email": "private"}, "line_items": []}]
    monkeypatch.setattr(service, "woo", woo)
    response = invoke("list_orders", {"today": True})
    assert "after" in seen and "before" in seen
    assert seen["per_page"] == 100
    assert response.json()["result"]["structuredContent"]["items"][0]["id"] == 17
    assert "private" not in response.text
