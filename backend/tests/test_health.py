from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.database import engine
from app.main import app


def test_health_endpoints_and_database_readiness() -> None:
    with TestClient(app) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")

    assert live.status_code == 200
    assert live.json() == {"status": "alive"}
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready", "database": "connected"}
    assert {"users", "api_keys", "upstream_servers", "audit_logs"}.issubset(
        set(inspect(engine).get_table_names())
    )
