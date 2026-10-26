import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.openapi.docs import get_swagger_ui_html
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal, init_database
from app.gateway import router as gateway_router
from app.models import UpstreamServer
from app.routes import router
from app.stores import router as stores_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Create the current schema for the reference deployment; production evolution should use migrations.
    init_database()
    raw = os.getenv("UPSTREAMS_JSON", "[]")
    try:
        upstreams = json.loads(raw)
    except json.JSONDecodeError:
        upstreams = []
    with SessionLocal() as db:
        for item in upstreams:
            if not db.query(UpstreamServer).filter_by(slug=item["slug"]).first():
                db.add(
                    UpstreamServer(
                        name=item["name"],
                        slug=item["slug"],
                        url=item["url"],
                        is_enabled=True,
                        status="unknown",
                    )
                )
        db.commit()
    yield


app = FastAPI(
    title="Urumi Team MCP Gateway",
    version="0.1.0",
    description="Team dashboard API and MCP gateway.",
    lifespan=lifespan,
    docs_url=None,
    servers=[{"url": "."}],
)
app.include_router(router)
app.include_router(stores_router)
app.include_router(gateway_router)
app.include_router(gateway_router, prefix="/api")


@app.get("/health/live", tags=["health"])
async def liveness() -> dict[str, str]:
    """Kubernetes liveness probe: the process is responding."""
    return {"status": "alive"}


@app.get("/health/ready", tags=["health"])
async def readiness() -> dict[str, str]:
    """Kubernetes readiness probe: the service can reach its database."""
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.exception("Database readiness check failed")
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "ready", "database": "connected"}


@app.get("/docs", include_in_schema=False)
async def api_docs():
    return get_swagger_ui_html(
        openapi_url="./openapi.json",
        title="Urumi Gateway API",
    )
