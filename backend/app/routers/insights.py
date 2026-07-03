"""
insights.py
───────────
Purpose:
    FastAPI router defining endpoints for fetching data insights.

Use Cases:
    - GET /api/insights/{proposal_id}: Fetch structural anomalies, trends, and data quality insights.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.database import get_db
from app.services import insight_service

router = APIRouter()


@router.get("/insights")
async def list_insights(
    category: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """List all insights with optional filters."""
    items = await insight_service.list_all_insights(
        db, category=category, severity=severity, limit=limit, offset=offset
    )
    return items


@router.get("/insights/summary")
async def insights_summary(db: AsyncSession = Depends(get_db)):
    """Aggregate stats: totals by category, severity, and recent critical findings."""
    return await insight_service.get_insights_summary(db)


@router.get("/insights/{proposal_id}")
async def get_insights_for_proposal(
    proposal_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get all insights generated for a specific proposal."""
    items = await insight_service.get_insights(proposal_id, db)
    return items
