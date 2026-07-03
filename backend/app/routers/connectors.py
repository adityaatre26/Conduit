"""
connectors.py
─────────────
Purpose:
    FastAPI router defining endpoints for managing external database connectors.

Use Cases:
    - GET /api/connectors: List connections and register new database datasources.
"""

from fastapi import APIRouter, HTTPException
from typing import Optional
from pydantic import BaseModel, Field

from app.connectors.db_factory import factory
from app.connectors.models.credentials import (
    ConnectionRequest, QueryRequest, DBType, CRED_MODELS,
)

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
#  Registration
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/connectors/register")
async def register_connection(req: ConnectionRequest):
    """
    Validate credentials, test connectivity, and register a persistent
    connection to an external database.

    Supported providers: postgresql, mysql, mongodb, neo4j, supabase,
    databricks, snowflake, redis, pinecone, bigquery, sqlite, clickhouse
    """
    result = await factory.register_connection(
        conn_id=req.conn_id,
        db_type=req.db_type.value,
        credentials=req.credentials,
        read_only=req.read_only,
        display_name=req.display_name,
    )
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return result


# ─────────────────────────────────────────────────────────────────────────────
#  Listing
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/connectors")
async def list_connections():
    """Return metadata for every registered connection (credentials are never exposed)."""
    return factory.list_connections()


@router.get("/connectors/providers")
async def list_providers():
    """Return the list of supported database provider types."""
    return {
        "providers": [
            {
                "type": db_type,
                "credential_fields": list(model.model_fields.keys()),
            }
            for db_type, model in CRED_MODELS.items()
            if db_type != "postgres"  # skip alias, show 'postgresql' only
        ]
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Query execution
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/connectors/query")
async def execute_query(req: QueryRequest):
    """
    Execute a query against a registered connection.

    Read-only connections will block INSERT/UPDATE/DELETE/DROP/etc.
    Results are capped at `limit` rows (default 1000, max 10000).
    """
    try:
        result = await factory.execute_query(
            conn_id=req.conn_id,
            query=req.query,
            params=req.params,
            limit=req.limit,
        )
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Query execution failed: {str(exc)}")


# ─────────────────────────────────────────────────────────────────────────────
#  Disconnect
# ─────────────────────────────────────────────────────────────────────────────

@router.delete("/connectors/{conn_id}")
async def disconnect(conn_id: str):
    """Gracefully close and remove a registered connection."""
    if conn_id not in factory.connections:
        raise HTTPException(status_code=404, detail=f"Connection '{conn_id}' not found")
    return await factory.disconnect(conn_id)


@router.post("/connectors/{conn_id}/sync-graph")
async def sync_connection_graph(
    conn_id: str,
    table_names: Optional[str] = None,
):
    """
    Introspect tables from a registered connector and publish schema
    into the Neo4j knowledge graph for AI ingest/context.

    Optional query param `table_names`: comma-separated list (default: orders_clean).
    """
    from app.services import connector_introspection_service

    tables = [t.strip() for t in table_names.split(",")] if table_names else None
    try:
        result = await connector_introspection_service.sync_connection_to_graph(
            conn_id, tables
        )
        return {"status": "success", **result}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Graph sync failed: {exc}")
