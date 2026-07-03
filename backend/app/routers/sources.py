"""
sources.py
──────────
Purpose:
    FastAPI router defining endpoints for listing registered warehouse connections.
"""
from fastapi import APIRouter
from typing import List
from app.schemas import WarehouseUnitResponse
from app.connectors.db_factory import factory

router = APIRouter()


@router.get("/sources", response_model=List[WarehouseUnitResponse])
async def get_sources():
    """
    Return org-registered database connections.
    These are the live connectors an org configures — not PG catalog rows.
    """
    connections = factory.list_connections()
    out = []
    for i, c in enumerate(connections, start=1):
        out.append(WarehouseUnitResponse(
            id=i,
            name=c.get("display_name") or c.get("id"),
            unit_type=c.get("type", "UNKNOWN").upper(),
            status="CONNECTED" if c.get("status") == "connected" else "UNREACHABLE",
        ))
    if not out:
        # Fallback label when no connectors registered yet
        out.append(WarehouseUnitResponse(
            id=0,
            name="No connections registered",
            unit_type="NONE",
            status="UNREACHABLE",
        ))
    return out
