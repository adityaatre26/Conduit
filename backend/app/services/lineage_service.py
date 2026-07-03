"""
lineage_service.py
──────────────────
Purpose:
    Provides services to log pipeline execution events in the lineage database.
"""
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.extension_models import LineageEvent


async def record_event(
    db: AsyncSession,
    proposal_id: str,
    source_entity: str,
    target_entity: str,
    operation_type: str,
    skill_used: Optional[str] = None,
) -> LineageEvent:
    """
    Append one lineage record.  Called after successful execution.
    Never raises — any failure is swallowed so it cannot break the
    existing execution flow.
    """
    try:
        event = LineageEvent(
            proposal_id=proposal_id,
            source_entity=source_entity,
            target_entity=target_entity,
            operation_type=operation_type,
            skill_used=skill_used,
        )
        db.add(event)
        await db.commit()
        await db.refresh(event)
        return event
    except Exception:
        # Lineage logging must never break the main execution flow
        await db.rollback()
        return None  # type: ignore


async def list_events(
    db: AsyncSession,
    limit: int = 100,
    offset: int = 0,
) -> List[LineageEvent]:
    """Return lineage events ordered by most recent first."""
    result = await db.execute(
        select(LineageEvent)
        .order_by(LineageEvent.executed_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return result.scalars().all()


async def get_events_for_proposal(
    db: AsyncSession,
    proposal_id: str,
) -> List[LineageEvent]:
    """Return all lineage events for a specific proposal."""
    result = await db.execute(
        select(LineageEvent)
        .where(LineageEvent.proposal_id == proposal_id)
        .order_by(LineageEvent.executed_at.asc())
    )
    return result.scalars().all()
