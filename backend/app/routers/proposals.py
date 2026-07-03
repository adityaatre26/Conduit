"""
proposals.py
────────────
Purpose:
    FastAPI router defining endpoints for managing generated data transformation proposals.

Use Cases:
    - GET /api/proposals: Query pending/executed proposals.
    - POST /api/proposals/{id}/approve: Execute approved proposal code against the warehouse.
    - POST /api/proposals/{id}/reject: Mark proposal as rejected with reason.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from app.database import get_db
from app.models import Proposal, PipelineSkillsLedger
from app.schemas import ProposalResponse, ApproveRequest, RejectRequest, ExecutionResult, DriftItem
from app.services.execution_service import execute_proposal
# NEW — context bundle retrieval (additive, read-only)
from app.services import context_retrieval_service
from app.extension_schemas import ProposalContextResponse

router = APIRouter()

@router.get("/proposals", response_model=List[ProposalResponse])
async def list_proposals(
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Proposal)
    if status is not None:
        stmt = stmt.where(Proposal.status == status)
    stmt = stmt.order_by(Proposal.created_at.desc()).offset(offset).limit(limit)
    res = await db.execute(stmt)
    proposals = res.scalars().all()
    
    results = []
    for p in proposals:
        drift_items = [DriftItem(**item) for item in p.drift_detected] if p.drift_detected else []
        results.append(
            ProposalResponse(
                proposal_id=p.id,
                gateway_status=p.gateway_status,
                target_table=p.target_table,
                drift_detected=drift_items,
                proposed_steps=p.proposed_steps or [],
                generated_code=p.generated_code or "",
                confidence_score=p.confidence_score or 0.0,
                pii_columns_found=p.pii_columns_found or [],
                estimated_rows=p.estimated_rows or 0,
                llm_model_used=p.llm_model_used or "llama-3.3-70b-versatile",
                description_md=p.description_md,
                suggested_skills_to_add=p.suggested_skills_to_add,
                enrichment_applied=p.enrichment_applied,
                extra_params=p.extra_params
            )
        )
    return results

@router.get("/proposals/{proposal_id}", response_model=ProposalResponse)
async def get_proposal(proposal_id: str, db: AsyncSession = Depends(get_db)):
    stmt = select(Proposal).where(Proposal.id == proposal_id)
    res = await db.execute(stmt)
    proposal = res.scalars().first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
        
    drift_items = [DriftItem(**item) for item in proposal.drift_detected]
    
    return ProposalResponse(
        proposal_id=proposal.id,
        gateway_status=proposal.gateway_status,
        target_table=proposal.target_table,
        drift_detected=drift_items,
        proposed_steps=proposal.proposed_steps,
        generated_code=proposal.generated_code,
        confidence_score=proposal.confidence_score,
        pii_columns_found=proposal.pii_columns_found or [],
        estimated_rows=proposal.estimated_rows or 0,
        llm_model_used=proposal.llm_model_used or "llama-3.3-70b-versatile",
        description_md=proposal.description_md,
        suggested_skills_to_add=proposal.suggested_skills_to_add,
        enrichment_applied=proposal.enrichment_applied,
        extra_params=proposal.extra_params
    )


@router.post("/proposals/{proposal_id}/approve", response_model=ExecutionResult)
async def approve_proposal(proposal_id: str, req: ApproveRequest, db: AsyncSession = Depends(get_db)):
    stmt = select(Proposal).where(Proposal.id == proposal_id)
    res = await db.execute(stmt)
    proposal = res.scalars().first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
        
    return await execute_proposal(proposal, req.human_approver_id, db)

@router.post("/proposals/{proposal_id}/reject")
async def reject_proposal(proposal_id: str, req: RejectRequest, db: AsyncSession = Depends(get_db)):
    stmt = select(Proposal).where(Proposal.id == proposal_id)
    res = await db.execute(stmt)
    proposal = res.scalars().first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
        
    proposal.status = "REJECTED"
    
    ledger_entry = PipelineSkillsLedger(
        table_id=None,
        proposal_id=proposal.id,
        skill_name="rejected_by_engineer",
        applied_by_llm_version=None,
        transformation_script_ref=req.reason,
        human_approver_id="system",
        execution_status="FAILED"
    )
    db.add(ledger_entry)
    await db.commit()
    
    return {"status": "rejected"}


@router.get("/proposals/{proposal_id}/context", response_model=ProposalContextResponse)
async def get_proposal_context(
    proposal_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Return the rich context bundle that was built at ingest time for this proposal.

    Phase 1: the bundle is stored but not injected into the LLM prompt.
    Phase 2+: the bundle will be used to enrich AI reasoning.

    Returns 404 if the proposal does not exist.
    Returns 204 (empty body with 200 here for simplicity) if context was never built
    (e.g. proposals created before Phase 1 was deployed).
    """
    # Verify the proposal exists first
    stmt = select(Proposal).where(Proposal.id == proposal_id)
    res = await db.execute(stmt)
    proposal = res.scalars().first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    ctx = await context_retrieval_service.get_proposal_context(db, proposal_id=proposal_id)
    if ctx is None:
        raise HTTPException(
            status_code=404,
            detail="No context bundle found for this proposal. "
                   "Context is built at ingest time; this proposal may pre-date Phase 1.",
        )

    return ProposalContextResponse(
        proposal_id=ctx["proposal_id"],
        target_table=ctx["target_table"],
        context_bundle=ctx["context_bundle"],
        generated_at=ctx["generated_at"],
    )
