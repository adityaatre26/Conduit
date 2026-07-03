"""
models.py
─────────
Purpose:
    Defines the core SQLAlchemy ORM models representing tables 
    in the `conduit` schema of the PostgreSQL database.

Models:
    - `PipelineSkillsLedger`: Logs executions of transformation scripts.
    - `QuarantineRecord`: Stores raw CSV rows that failed validation and execution rules.
    - `Proposal`: Stores ingestion proposals, generated code, gateway state, and audit logs.
    - `InsightRecord`: Stores AI-generated business/data insights for proposals.
"""

from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, JSON
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()


# NOTE: WarehouseUnit, SubProject, TableMetadata, AttributeMetadata removed.
# Connections are now managed by DBConnectionFactory (app/connectors/db_factory.py).
# Schema metadata lives in the Neo4j knowledge graph (graph_knowledge_service.py).

class PipelineSkillsLedger(Base):
    __tablename__ = "pipeline_skills_ledger"
    __table_args__ = {"schema": "conduit"}
    id = Column(Integer, primary_key=True, autoincrement=True)
    table_id = Column(Integer, nullable=True)  # Legacy: was FK to tables_metadata (model removed)
    proposal_id = Column(String, ForeignKey("conduit.proposals.id", ondelete="CASCADE"), nullable=True)
    skill_name = Column(String)
    applied_by_llm_version = Column(String, nullable=True)
    transformation_script_ref = Column(String)
    human_approver_id = Column(String)
    execution_status = Column(String)
    executed_at = Column(DateTime, default=datetime.utcnow)
    graph_node_id = Column(String, nullable=True)


class QuarantineRecord(Base):
    __tablename__ = "quarantine_records"
    __table_args__ = {"schema": "conduit"}
    id = Column(Integer, primary_key=True, autoincrement=True)
    proposal_id = Column(String)
    raw_row = Column(JSON)
    failure_reason = Column(String)
    quarantined_at = Column(DateTime, default=datetime.utcnow)

class Proposal(Base):
    __tablename__ = "proposals"
    __table_args__ = {"schema": "conduit"}
    id = Column(String, primary_key=True)
    filename = Column(String)
    gateway_status = Column(String)
    drift_detected = Column(JSON)
    proposed_steps = Column(JSON)
    generated_code = Column(String)
    confidence_score = Column(Float)
    llm_raw_response = Column(String)
    llm_prompt_sent = Column(String)
    status = Column(String)
    human_approver_id = Column(String, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    file_path = Column(String)
    target_table = Column(String, nullable=True)
    estimated_rows = Column(Integer, nullable=True)
    pii_columns_found = Column(JSON, nullable=True)
    llm_model_used = Column(String, nullable=True)
    description_md = Column(String, nullable=True)
    suggested_skills_to_add = Column(JSON, nullable=True)
    enrichment_applied = Column(JSON, nullable=True)
    # Extra user-supplied key-value parameters (source_system, batch_id, env, etc.)
    extra_params = Column(JSON, nullable=True)


class InsightRecord(Base):
    __tablename__ = "insight_records"
    __table_args__ = {"schema": "conduit"}
    id = Column(Integer, primary_key=True, autoincrement=True)
    proposal_id = Column(String, ForeignKey("conduit.proposals.id", ondelete="CASCADE"))
    category = Column(String)       # CONCENTRATION | ANOMALY | DATA_QUALITY | TREND | PATTERN
    severity = Column(String)       # INFO | WARNING | CRITICAL
    title = Column(String)
    description = Column(String)
    evidence = Column(JSON)         # Raw statistics backing the insight
    created_at = Column(DateTime, default=datetime.utcnow)
