"""
schemas.py
──────────
Purpose:
    Defines the core Pydantic models for request validation and response serialization 
    for the primary API routes (Ingestion, Proposals, Audit, Quarantine, Sources).

Usage:
    - Facilitates standard type-checking and structural verification for HTTP data exchange.
"""

from pydantic import BaseModel

from typing import List, Optional, Any, Dict
from datetime import datetime

class DriftItem(BaseModel):
    column: str
    issue_type: str
    source_value: str
    target_expectation: str
    suggested_action: str
    severity: str

class InsightItem(BaseModel):
    id: int
    proposal_id: str
    category: str
    severity: str
    title: str
    description: str
    evidence: Optional[dict] = None
    created_at: Optional[datetime] = None

class InsightSummary(BaseModel):
    proposal_id: str
    target_table: str
    rows_analyzed: int
    insights: List[InsightItem]
    generated_at: Optional[datetime] = None

class ProposalResponse(BaseModel):
    proposal_id: str
    gateway_status: str
    target_table: Optional[str] = None
    drift_detected: List[DriftItem]
    proposed_steps: List[str]
    generated_code: str
    confidence_score: float
    pii_columns_found: List[str]
    estimated_rows: int
    llm_model_used: str
    # Phase 1 additions — AI reasoning in plain English
    reasoning: Optional[str] = None
    reasoning_note: Optional[str] = None
    description_md: Optional[str] = None
    suggested_skills_to_add: Optional[List[dict]] = None
    enrichment_applied: Optional[List[str]] = None
    extra_params: Optional[dict] = None


class ApproveRequest(BaseModel):
    human_approver_id: str

class RejectRequest(BaseModel):
    reason: str

class ExecutionResult(BaseModel):
    proposal_id: str
    rows_written: int
    rows_quarantined: int
    execution_status: str
    duration_ms: int
    insights: Optional[List[InsightItem]] = None

class AuditEntry(BaseModel):
    id: int
    proposal_id: str
    filename: str
    skill_name: str
    execution_status: str
    human_approver_id: str
    executed_at: datetime
    llm_prompt_sent: str
    llm_raw_response: str
    transformation_script_ref: str

class QuarantineEntry(BaseModel):
    id: int
    proposal_id: str
    raw_row: dict
    failure_reason: str
    quarantined_at: datetime

class WarehouseUnitResponse(BaseModel):
    id: int
    name: str
    unit_type: str
    status: str

