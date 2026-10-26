"""Small MCP upstream used for WooCommerce, inventory, and shipping demo tools."""

import os
from typing import Any

import httpx
from fastapi import FastAPI, Request, HTTPException
from jsonschema import validate, ValidationError
from fastapi.responses import Response

SERVICE = os.getenv("SERVICE_NAME", "inventory")
WOO_URL = os.getenv("WOO_URL", "").rstrip("/")
WOO_KEY = os.getenv("WOO_CONSUMER_KEY", "")
WOO_SECRET = os.getenv("WOO_CONSUMER_SECRET", "")
app = FastAPI(title=f"{SERVICE.title()} MCP", version="1.0.0")
products = [{"id": 101, "name": "Urumi T-shirt", "price": 799.0, "stock": 25}]
orders = [
    {
        "id": 5001,
        "status": "processing",
        "total": 1598.0,
        "customer": "Demo Customer",
        "items": ["Urumi T-shirt", "Urumi T-shirt"],
    }
]
stock = {"SKU-TSHIRT": 25, "SKU-MUG": 60, "SKU-TOTE": 12}
shipments = {"ORD-5001": {"status": "in_transit", "carrier": "DemoShip", "eta": "2026-10-20"}}

PRODUCTS = [
    {
        "name": "list_products",
        "description": "List WooCommerce products",
        "inputSchema": {
            "type": "object",
            "properties": {"search": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "create_product",
        "description": "Create a product in WooCommerce",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "price": {"type": "number"},
                "sku": {"type": "string"},
                "image_ids": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1},
                    "maxItems": 5,
                    "description": "Image attachment IDs from this store Media Library; first image is the cover"
                },
            },
            "required": ["name", "price"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_orders",
        "description": "List recent WooCommerce orders",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["any", "pending", "processing", "on-hold", "completed", "cancelled", "refunded", "failed"]},
                "after": {"type": "string", "description": "ISO8601 UTC start date/time"},
                "before": {"type": "string", "description": "ISO8601 UTC end date/time"},
                "today": {"type": "boolean", "description": "Filter to today in the configured store timezone"},
                "page": {"type": "integer", "minimum": 1},
                "per_page": {"type": "integer", "minimum": 1, "maximum": 100}
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_order",
        "description": "Get an order by numeric ID",
        "inputSchema": {
            "type": "object",
            "properties": {"order_id": {"type": "integer"}},
            "required": ["order_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "update_order_status",
        "description": "Update an order status",
        "inputSchema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "integer"},
                "status": {
                    "type": "string",
                    "enum": [
                        "pending",
                        "processing",
                        "on-hold",
                        "completed",
                        "cancelled",
                        "refunded",
                    ],
                },
            },
            "required": ["order_id", "status"],
            "additionalProperties": False,
        },
    },
]
INVENTORY = [
    {
        "name": "list_inventory",
        "description": "List stock by SKU",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "check_stock",
        "description": "Check available quantity for a SKU",
        "inputSchema": {
            "type": "object",
            "properties": {"sku": {"type": "string"}},
            "required": ["sku"],
            "additionalProperties": False,
        },
    },
    {
        "name": "reserve_stock",
        "description": "Reserve stock for a SKU",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sku": {"type": "string"},
                "quantity": {"type": "integer", "minimum": 1},
            },
            "required": ["sku", "quantity"],
            "additionalProperties": False,
        },
    },
]
SHIPPING = [
    {
        "name": "track_shipment",
        "description": "Track the shipment for an order",
        "inputSchema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "estimate_shipping",
        "description": "Estimate shipping cost",
        "inputSchema": {
            "type": "object",
            "properties": {"postal_code": {"type": "string"}, "weight_kg": {"type": "number"}},
            "required": ["postal_code", "weight_kg"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_shipment",
        "description": "Create a shipment for an order",
        "inputSchema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}, "address": {"type": "string"}},
            "required": ["order_id", "address"],
            "additionalProperties": False,
        },
    },
]


def tools():
    return (
        PRODUCTS if SERVICE == "woocommerce" else SHIPPING if SERVICE == "shipping" else INVENTORY
    )


def result(value: Any):
    return {
        "content": [{"type": "text", "text": __import__("json").dumps(value, default=str)}],
        "structuredContent": value if isinstance(value, dict) else {"items": value},
        "isError": False,
    }


async def woo(method: str, endpoint: str, data: dict | None = None, params: dict | None = None):
    import base64
    import hashlib
    import hmac
    import secrets
    import time
    from urllib.parse import quote, urlencode

    if not (WOO_URL and WOO_KEY and WOO_SECRET):
        raise RuntimeError("WooCommerce credentials are not configured")

    path = f"/wp-json/wc/v3/{endpoint}"
    request_url = WOO_URL + path
    request_params = dict(params or {})
    if os.getenv("WOO_QUERY_ROUTE") == "true":
        path = "/"
        request_url = WOO_URL + path
        request_params["rest_route"] = f"/wc/v3/{endpoint}"
    auth = None

    if WOO_URL.startswith("https://"):
        auth = (WOO_KEY, WOO_SECRET)
    else:
        public_url = os.environ["WOO_PUBLIC_URL"].rstrip("/")
        signing_url = public_url + ("" if path == "/" else path)
        encode = lambda value: quote(str(value), safe="~")
        request_params.update({
            "oauth_consumer_key": WOO_KEY,
            "oauth_nonce": secrets.token_hex(16),
            "oauth_signature_method": "HMAC-SHA256",
            "oauth_timestamp": str(int(time.time())),
        })
        normalized = "&".join(
            encode(k) + "=" + encode(v)
            for k, v in sorted(request_params.items())
        )
        signature_base = (
            method.upper() + "&" + encode(signing_url) + "&" + encode(normalized)
        )
        request_params["oauth_signature"] = base64.b64encode(
            hmac.new(
                (WOO_SECRET + "&").encode(),
                signature_base.encode(),
                hashlib.sha256,
            ).digest()
        ).decode()

    async with httpx.AsyncClient(timeout=7) as client:
        res = await client.request(
            method,
            request_url + ("?" + urlencode(request_params) if request_params else ""),
            auth=auth,
            headers={
                "Host": httpx.URL(os.environ["WOO_PUBLIC_URL"]).netloc.decode(),
                "X-Forwarded-Proto": httpx.URL(os.environ["WOO_PUBLIC_URL"]).scheme,
            } if not WOO_URL.startswith("https://") else {},
            json=data,
        )
        if res.is_error:
            raise RuntimeError(f"WooCommerce API returned HTTP {res.status_code}")
        return res.json()


def compact_order(o):
    return {k: o.get(k) for k in ("id", "status", "total", "currency", "date_created", "date_created_gmt", "payment_method_title")} | {
        "items": [{k: i.get(k) for k in ("product_id", "name", "sku", "quantity", "total")} for i in o.get("line_items", [])]
    }


async def call(name: str, a: dict):
    if SERVICE == "woocommerce":
        if WOO_URL and not (WOO_KEY and WOO_SECRET):
            raise RuntimeError("WooCommerce credentials are not configured")
        if name == "list_products":
            if WOO_URL and WOO_KEY and WOO_SECRET:
                return result(await woo("GET", "products", params={"search": a.get("search", "")}))
            return result(
                [
                    p
                    for p in products
                    if not a.get("search") or a["search"].lower() in p["name"].lower()
                ]
            )
        if name == "create_product":
            data = {"name": a["name"], "regular_price": str(a["price"]), "sku": a.get("sku", "")}
            if a.get("image_ids"):
                data["images"] = [{"id": image_id} for image_id in a["image_ids"]]
            if WOO_URL:
                return result(await woo("POST", "products", data))
            item = {
                "id": max(p["id"] for p in products) + 1,
                "name": a["name"],
                "price": a["price"],
                "sku": a.get("sku"),
            }
            products.append(item)
            return result(item)
        if name == "list_orders":
            if WOO_URL and WOO_KEY and WOO_SECRET:
                params = {k: a[k] for k in ("status", "after", "before", "page", "per_page") if a.get(k) is not None}
                params.setdefault("per_page", 100)
                if a.get("today"):
                    from datetime import datetime, time, timedelta, timezone
                    from zoneinfo import ZoneInfo
                    zone = ZoneInfo(os.getenv("STORE_TIMEZONE", "Asia/Kolkata"))
                    day = datetime.now(zone).date()
                    start = datetime.combine(day, time.min, zone).astimezone(timezone.utc)
                    end = datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
                    params.update(after=start.isoformat(), before=(end - timedelta(seconds=1)).isoformat())
                rows = await woo("GET", "orders", params=params)
                return result([compact_order(o) for o in rows])
            return result([o for o in orders if not a.get("status") or o["status"] == a["status"]])
        if name == "get_order":
            if WOO_URL and WOO_KEY and WOO_SECRET:
                return result(compact_order(await woo("GET", f"orders/{a['order_id']}")))
            o = next((o for o in orders if o["id"] == a["order_id"]), None)
            return result(o) if o else result({"error": "Order not found"})
        if name == "update_order_status":
            if WOO_URL:
                return result(await woo("PUT", f"orders/{a['order_id']}", {"status": a["status"]}))
            o = next((o for o in orders if o["id"] == a["order_id"]), None)
            if not o:
                return result({"error": "Order not found"})
            o["status"] = a["status"]
            return result(o)
    if SERVICE == "inventory":
        if name == "list_inventory":
            return result(stock)
        if name == "check_stock":
            return result({"sku": a["sku"], "available": stock.get(a["sku"], 0)})
        if name == "reserve_stock":
            have = stock.get(a["sku"], 0)
            qty = a["quantity"]
            if qty > have:
                return result({"reserved": False, "available": have})
            stock[a["sku"]] = have - qty
            return result(
                {"reserved": True, "sku": a["sku"], "quantity": qty, "remaining": stock[a["sku"]]}
            )
    if SERVICE == "shipping":
        if name == "track_shipment":
            return result(shipments.get(a["order_id"], {"status": "not_found"}))
        if name == "estimate_shipping":
            return result(
                {
                    "postal_code": a["postal_code"],
                    "cost": round(49 + 20 * a["weight_kg"], 2),
                    "currency": "INR",
                    "eta_days": 4,
                }
            )
        if name == "create_shipment":
            shipments[a["order_id"]] = {
                "status": "label_created",
                "carrier": "DemoShip",
                "tracking_id": f"TRK-{a['order_id']}",
            }
            return result(shipments[a["order_id"]])
    return result({"error": f"Unknown tool {name}"})


@app.get("/health/live")
def live():
    return {"status": "alive", "service": SERVICE}


@app.post("/mcp")
async def mcp(payload: dict[str, Any], request: Request):
    import hmac
    token = os.getenv("MCP_AUTH_TOKEN")
    if token and not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + token):
        raise HTTPException(401, "Invalid upstream credential")
    method = payload.get("method")
    rid = payload.get("id")
    params = payload.get("params") or {}
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {
                "protocolVersion": params.get("protocolVersion", "2025-03-26"),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": f"{SERVICE}-mcp", "version": "1.0.0"},
            },
        }
    if method == "notifications/initialized":
        return Response(status_code=202)
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": tools()}}
    if method == "tools/call":
        name = params.get("name", "")
        if name not in {t["name"] for t in tools()}:
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "error": {"code": -32602, "message": "Unknown tool"},
            }
        try:
            schema = next(t["inputSchema"] for t in tools() if t["name"] == name)
            validate(params.get("arguments", {}), schema)
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "result": await call(name, params.get("arguments", {})),
            }
        except ValidationError:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "Invalid tool arguments; check the tool schema"}}
        except (httpx.HTTPError, KeyError, TypeError, ValueError, RuntimeError):
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "error": {"code": -32000, "message": "Tool failed; check upstream configuration"},
            }
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Method not found"}}
