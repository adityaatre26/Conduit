"""
main.py
───────
Purpose:
    FastAPI Application entry point and configuration.
    Initializes middleware, routers, database schemas, and Neo4j seeding at startup.

Use Cases:
    - Bootstraps the web application framework.
    - Handles CORS configurations.
    - Triggers migrations and seeds the Neo4j demo database.
"""

import logging
import time
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.database import engine
from app.models import Base
from app.extension_models import ExtBase


from app.routers import ingest, proposals, audit, quarantine, sources
from app.routers import skills, graph, lineage
from app.routers import insights, connectors, health

from app.core.config import settings

logger = logging.getLogger("conduit.api")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False

app = FastAPI(title="Conduit API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    ms = (time.time() - start) * 1000
    logger.info(f"{request.method} {request.url.path} → {response.status_code} ({ms:.0f}ms)")
    return response

app.include_router(health.router,     prefix="/api")
app.include_router(ingest.router,     prefix="/api")
app.include_router(proposals.router,  prefix="/api")
app.include_router(audit.router,      prefix="/api")
app.include_router(quarantine.router, prefix="/api")
app.include_router(lineage.router,    prefix="/api")
app.include_router(insights.router,   prefix="/api")
app.include_router(connectors.router, prefix="/api")
app.include_router(sources.router,    prefix="/api")
app.include_router(skills.router,     prefix="/api")
app.include_router(graph.router,      prefix="/api")


async def _run_migrations(conn):
    from sqlalchemy import text
    migrations = [
        "CREATE SCHEMA IF NOT EXISTS conduit",
        "ALTER TABLE conduit.proposals ADD COLUMN IF NOT EXISTS description_md TEXT",
        "ALTER TABLE conduit.proposals ADD COLUMN IF NOT EXISTS suggested_skills_to_add JSONB",
        "ALTER TABLE conduit.proposals ADD COLUMN IF NOT EXISTS enrichment_applied JSONB",
        "ALTER TABLE conduit.proposals ADD COLUMN IF NOT EXISTS extra_params JSONB",
        "ALTER TABLE conduit.pipeline_skills_ledger ADD COLUMN IF NOT EXISTS graph_node_id VARCHAR(255)",
        "CREATE SCHEMA IF NOT EXISTS conduit_skills",
        "CREATE SCHEMA IF NOT EXISTS conduit_lineage",
    ]
    warehouse_migrations = [
        "ALTER TABLE public.orders_clean ADD COLUMN IF NOT EXISTS amount_tier VARCHAR(20)",
        "ALTER TABLE public.orders_clean ADD COLUMN IF NOT EXISTS amount_outlier BOOLEAN",
        "ALTER TABLE public.orders_clean ADD COLUMN IF NOT EXISTS is_potential_duplicate BOOLEAN",
    ]
    for sql in migrations:
        try:
            await conn.execute(text(sql))
        except Exception as exc:
            logger.warning(f"Migration skipped: {exc}")
    try:
        exists = await conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='orders_clean'"
        ))
        if exists.scalar():
            for sql in warehouse_migrations:
                try:
                    await conn.execute(text(sql))
                except Exception as exc:
                    logger.warning(f"Warehouse migration skipped: {exc}")
    except Exception as exc:
        logger.warning(f"Could not check orders_clean: {exc}")


@app.on_event("startup")
async def on_startup():
    # ── 1. PostgreSQL migrations ───────────────────────────────────────────────
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS conduit"))
        await conn.run_sync(Base.metadata.create_all)
        await _run_migrations(conn)
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS conduit_skills"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS conduit_lineage"))
        await conn.run_sync(ExtBase.metadata.create_all)

    logger.info("PostgreSQL ready")

    # ── 2. Neo4j ───────────────────────────────────────────────────────────────
    from app.core.neo4j_client import neo4j_client
    await neo4j_client.connect()

    if neo4j_client.driver is not None:
        from app.services import connector_introspection_service, graph_knowledge_service
        try:
            reg = await connector_introspection_service.register_default_warehouse_connector(
                settings.WAREHOUSE_DB_URL
            )
            if reg.get("status") == "success":
                logger.info("Default warehouse connector registered (conn_id=warehouse)")
                await graph_knowledge_service.seed_demo_knowledge()
                try:
                    await connector_introspection_service.sync_connection_to_graph("warehouse")
                except Exception as exc:
                    logger.warning(f"Schema sync failed: {exc}")
            else:
                await graph_knowledge_service.seed_demo_knowledge()
        except Exception as exc:
            logger.warning(f"Connector registration failed: {exc}")
            try:
                await graph_knowledge_service.seed_demo_knowledge()
            except Exception as seed_exc:
                logger.error(f"Demo seed also failed: {seed_exc}")


@app.on_event("shutdown")
async def on_shutdown():
    from app.core.neo4j_client import neo4j_client
    await neo4j_client.close()
