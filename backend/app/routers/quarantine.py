"""
quarantine.py
─────────────
Purpose:
    FastAPI router defining endpoints for inspecting quarantined rows.

Use Cases:
    - GET /api/quarantine: Retrieves rows that failed validation constraints during execution.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import QuarantineRecord
from app.schemas import QuarantineEntry
from typing import List

router = APIRouter()

@router.get("/quarantine", response_model=List[QuarantineEntry])
async def get_quarantine(
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(QuarantineRecord)
        .order_by(QuarantineRecord.quarantined_at.desc())
        .limit(limit)
        .offset(offset)
    )
    res = await db.execute(stmt)
    records = res.scalars().all()
    return [QuarantineEntry(
        id=r.id,
        proposal_id=r.proposal_id,
        raw_row=r.raw_row,
        failure_reason=r.failure_reason,
        quarantined_at=r.quarantined_at
    ) for r in records]

@router.get("/quarantine/{proposal_id}", response_model=List[QuarantineEntry])
async def get_quarantine_by_proposal(
    proposal_id: str,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(QuarantineRecord)
        .where(QuarantineRecord.proposal_id == proposal_id)
        .order_by(QuarantineRecord.quarantined_at.desc())
        .limit(limit)
        .offset(offset)
    )
    res = await db.execute(stmt)
    records = res.scalars().all()
    return [QuarantineEntry(
        id=r.id,
        proposal_id=r.proposal_id,
        raw_row=r.raw_row,
        failure_reason=r.failure_reason,
        quarantined_at=r.quarantined_at
    ) for r in records]
