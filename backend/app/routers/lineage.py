"""
lineage.py
──────────
Purpose:
    FastAPI router defining endpoints for data lineage audit events.

Use Cases:
    - GET /api/lineage: List chronological system operational history (ingestion, schema change).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.database import get_db
from app.extension_schemas import LineageEventResponse
from app.services import lineage_service

router = APIRouter()


@router.get("/lineage", response_model=List[LineageEventResponse])
async def list_lineage_events(
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Return all lineage events, most recent first."""
    events = await lineage_service.list_events(db, limit=limit, offset=offset)
    return [LineageEventResponse.model_validate(e) for e in events]


@router.get("/lineage/{proposal_id}", response_model=List[LineageEventResponse])
async def get_lineage_for_proposal(
    proposal_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Return all lineage events for a specific proposal, in execution order."""
    events = await lineage_service.get_events_for_proposal(db, proposal_id=proposal_id)
    return [LineageEventResponse.model_validate(e) for e in events]
