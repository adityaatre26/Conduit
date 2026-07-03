"""
connector_introspection_service.py
──────────────────────────────────
Purpose:
    Orchestrates target schema introspection from database connections.

Use Cases:
    - Queries information_schema columns for registered database nodes.
    - Syncs live database table metadata directly into the Neo4j knowledge graph.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional
from urllib.parse import urlparse

from app.connectors.db_factory import factory
from app.services import graph_knowledge_service

logger = logging.getLogger("conduit.connector_introspection")

# Tables the org wants Conduit to know about (extend via API later)
DEFAULT_INTROSPECT_TABLES = ["orders_clean"]


def parse_warehouse_url(db_url: str) -> dict:
    """Parse SQLAlchemy async URL into PostgreSQL connector credentials."""
    # postgresql+asyncpg://user:pass@host:5432/dbname
    raw = db_url.replace("postgresql+asyncpg://", "postgresql://")
    parsed = urlparse(raw)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "database": (parsed.path or "/warehousedb").lstrip("/"),
        "user": parsed.username or "user",
        "password": parsed.password or "password",
        "sslmode": "prefer",
    }


async def register_default_warehouse_connector(db_url: str) -> dict:
    """Register the internal warehouse Postgres as conn_id='warehouse'."""
    creds = parse_warehouse_url(db_url)
    return await factory.register_connection(
        conn_id="warehouse",
        db_type="postgresql",
        credentials=creds,
        read_only=True,
        display_name="Organization Warehouse (PostgreSQL)",
    )


async def introspect_postgres_tables(
    conn_id: str,
    table_names: Optional[List[str]] = None,
) -> List[dict]:
    """Read column metadata from information_schema via the connector factory."""
    tables = table_names or DEFAULT_INTROSPECT_TABLES
    schemas: List[dict] = []

    for table in tables:
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table):
            continue
        q = """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = :table
            ORDER BY ordinal_position
        """
        result = await factory.execute_query(
            conn_id=conn_id,
            query=q,
            params={"table": table},
            limit=500,
        )
        columns = []
        for row in result.get("rows", []):
            col_name = row.get("column_name") or row.get("COLUMN_NAME")
            dtype = row.get("data_type") or row.get("DATA_TYPE") or "VARCHAR"
            nullable = (row.get("is_nullable") or row.get("IS_NULLABLE") or "YES") == "YES"
            if not col_name:
                continue
            columns.append({
                "column_name": col_name,
                "data_type": dtype.upper(),
                "semantic_description": "",
                "is_required": not nullable,
                "is_pii": col_name.lower() in ("email", "customer_email", "ssn", "phone"),
                "sample_values": [],
            })
        if columns:
            schemas.append({
                "table_name": table,
                "semantic_description": f"Live schema introspected from connection '{conn_id}'.",
                "columns": columns,
            })
    return schemas


async def sync_connection_to_graph(
    conn_id: str,
    table_names: Optional[List[str]] = None,
) -> dict:
    """
    Introspect tables from a registered connector and upsert into Neo4j.
    This is the org-facing path: connect DB → sync knowledge graph.
    """
    info = factory.connections.get(conn_id)
    if not info:
        raise KeyError(f"Connection '{conn_id}' is not registered")

    db_type = info["type"]
    if db_type not in ("postgresql", "postgres"):
        raise ValueError(
            f"Graph sync currently supports PostgreSQL connections only (got '{db_type}')."
        )

    schemas = await introspect_postgres_tables(conn_id, table_names)
    synced = []
    for schema in schemas:
        await graph_knowledge_service.upsert_table_schema(
            table_name=schema["table_name"],
            semantic_description=schema["semantic_description"],
            columns=schema["columns"],
            conn_id=conn_id,
        )
        synced.append(schema["table_name"])

    logger.info(f"Synced {len(synced)} table(s) from '{conn_id}' to knowledge graph")
    return {"conn_id": conn_id, "tables_synced": synced, "count": len(synced)}
