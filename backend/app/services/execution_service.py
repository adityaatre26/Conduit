"""
execution_service.py
────────────────────
Purpose:
    Executes generated data transformation Python scripts.

Use Cases:
    - Runs python code in a restricted/sandboxed namespace.
    - Inserts valid rows into PostgreSQL and isolates failures in quarantine tables.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import pandas as pd
from datetime import datetime
from fastapi import HTTPException
from app.models import Proposal, PipelineSkillsLedger, QuarantineRecord
from app.schemas import ExecutionResult, InsightItem

# NEW — lineage hook (additive, never raises)
from app.services import lineage_service
# NEW — graph auto-linking hook (additive, never raises)
from app.services import graph_service


async def execute_proposal(
    proposal: Proposal,
    approver_id: str,
    db: AsyncSession
) -> ExecutionResult:
    if proposal.status != "PENDING":
        raise ValueError(f"Proposal is {proposal.status}, not PENDING")

    # Capture all scalar values before database commits to avoid lazy loading issues
    proposal_id = proposal.id
    filename = proposal.filename or "unknown_source"
    gateway_status = proposal.gateway_status or "TRANSFORM"
    generated_code = proposal.generated_code
    llm_model_used = proposal.llm_model_used or "llama-3.3-70b-versatile"
    target_table = proposal.target_table or "orders_clean"
    file_path = proposal.file_path

    proposal.status = "APPROVED"
    proposal.human_approver_id = approver_id
    proposal.approved_at = datetime.utcnow()
    await db.commit()

    filepath = file_path
    try:
        import os as _os
        _ext = _os.path.splitext(filepath or "")[-1].lower()
        df = pd.read_json(filepath) if _ext == ".json" else pd.read_csv(filepath)
    except Exception as e:
        proposal.status = "FAILED"
        await db.commit()
        # After a failure, reset the proposal so it can be retried
        proposal.status = "PENDING"
        await db.commit()
        raise e

    import hashlib
    import numpy as np
    namespace = {"pd": pd, "df": df, "hashlib": hashlib, "np": np}
    try:
        exec(generated_code, namespace)
        transform_fn = namespace["transform"]
        transformed_df = transform_fn(df)
    except TypeError as e:
        proposal.status = "FAILED"
        ledger_entry = PipelineSkillsLedger(
            table_id=None,
            proposal_id=proposal_id,
            skill_name=f"transform_{filename}",
            applied_by_llm_version=llm_model_used,
            transformation_script_ref=generated_code,
            human_approver_id=approver_id,
            execution_status="FAILED",
            graph_node_id=f"tbl-{target_table}"
        )
        db.add(ledger_entry)
        await db.commit()
        proposal.status = "PENDING"
        await db.commit()
        raise HTTPException(
            status_code=422,
            detail=(
                f"The AI-generated transformation code failed with a type error "
                f"during execution: {e}. "
                "This usually means the generated code applied a numeric or "
                "statistical operation (e.g. quantile, mean, std) to a column "
                "that contains string data. "
                "Reject this proposal and re-ingest the file — the system will "
                "generate a new transformation script."
            )
        )
    except KeyError as e:
        proposal.status = "FAILED"
        ledger_entry = PipelineSkillsLedger(
            table_id=None,
            proposal_id=proposal_id,
            skill_name=f"transform_{filename}",
            applied_by_llm_version=llm_model_used,
            transformation_script_ref=generated_code,
            human_approver_id=approver_id,
            execution_status="FAILED",
            graph_node_id=f"tbl-{target_table}"
        )
        db.add(ledger_entry)
        await db.commit()
        proposal.status = "PENDING"
        await db.commit()
        raise HTTPException(
            status_code=422,
            detail=(
                f"The AI-generated transformation code referenced a column that "
                f"does not exist in the uploaded file: {e}. "
                "Reject this proposal and re-ingest."
            )
        )
    except Exception as e:
        proposal.status = "FAILED"
        ledger_entry = PipelineSkillsLedger(
            table_id=None,
            proposal_id=proposal_id,
            skill_name=f"transform_{filename}",
            applied_by_llm_version=llm_model_used,
            transformation_script_ref=generated_code,
            human_approver_id=approver_id,
            execution_status="FAILED",
            graph_node_id=f"tbl-{target_table}"
        )
        db.add(ledger_entry)
        await db.commit()
        proposal.status = "PENDING"
        await db.commit()
        raise HTTPException(
            status_code=422,
            detail=(
                f"The AI-generated transformation code failed during execution: "
                f"{type(e).__name__}: {e}. "
                "Reject this proposal and re-ingest the file."
            )
        )

    # Insert into warehouse database (live data — separate from audit PG role)
    rows_written = 0
    rows_quarantined = 0
    start_time = datetime.now()

    cols = transformed_df.columns.tolist()
    placeholders = ", ".join([f":{c}" for c in cols])
    insert_sql = text(f"INSERT INTO {target_table} ({', '.join(cols)}) VALUES ({placeholders})")

    for row in transformed_df.to_dict('records'):
        clean_row = {}
        for k, v in row.items():
            if pd.isna(v):
                clean_row[k] = None
            elif isinstance(v, pd.Timestamp):
                clean_row[k] = v.to_pydatetime()
            else:
                clean_row[k] = v
        try:
            async with db.begin_nested():
                await db.execute(insert_sql, clean_row)
                rows_written += 1
        except Exception as e:
            qr_row = {k: (v.isoformat() if hasattr(v, 'isoformat') else v) for k, v in clean_row.items()}
            qr = QuarantineRecord(
                proposal_id=proposal_id,
                raw_row=qr_row,
                failure_reason=str(e)
            )
            db.add(qr)
            rows_quarantined += 1

    try:
        ledger_status = "SUCCESS" if rows_written > 0 else "FAILED"
        ledger_entry = PipelineSkillsLedger(
            table_id=None,
            proposal_id=proposal_id,
            skill_name=f"transform_{filename}",
            applied_by_llm_version=llm_model_used,
            transformation_script_ref=generated_code,
            human_approver_id=approver_id,
            execution_status=ledger_status,
            graph_node_id=f"tbl-{target_table}"
        )
        db.add(ledger_entry)
        proposal.status = "EXECUTED"
        await db.commit()
    except Exception as e:
        await db.rollback()
        proposal.status = "FAILED"
        db.add(PipelineSkillsLedger(
            table_id=None,
            proposal_id=proposal_id,
            skill_name=f"transform_{filename}",
            applied_by_llm_version=llm_model_used,
            transformation_script_ref=generated_code,
            human_approver_id=approver_id,
            execution_status="ROLLEDBACK",
            graph_node_id=f"tbl-{target_table}"
        ))
        await db.commit()
        # After a failure, reset the proposal so it can be retried
        proposal.status = "PENDING"
        await db.commit()
        raise e

    duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

    # NEW: record lineage event + auto-populate graph (both additive, never raise)
    if rows_written > 0:
        skill_applied = f"transform_{filename}"
        op_type = (
            "SCHEMA_EVOLUTION"
            if gateway_status == "SCHEMA_EVOLUTION"
            else gateway_status
        )
        await lineage_service.record_event(
            db=db,
            proposal_id=proposal_id,
            source_entity=filename,
            target_entity=target_table,
            operation_type=op_type,
            skill_used=skill_applied,
        )
        # Auto-populate relationship graph so nodes/edges appear without manual API calls
        await graph_service.auto_link_execution(
            db=db,
            proposal_id=proposal_id,
            source_filename=filename,
            target_table=target_table,
            skill_name=skill_applied,
        )

    # NEW: Post-load insight generation (additive, never raises)
    insight_items = []
    if rows_written > 0:
        try:
            from app.services import insight_service
            raw_insights = await insight_service.generate_insights(
                proposal_id=proposal_id,
                target_table=target_table,
                rows_written=rows_written,
                transformed_df=transformed_df,
                db=db,
                filename=filename,
            )
            insight_items = [
                InsightItem(
                    id=ins.get("id", 0),
                    proposal_id=ins.get("proposal_id", proposal_id),
                    category=ins.get("category", "DATA_QUALITY"),
                    severity=ins.get("severity", "INFO"),
                    title=ins.get("title", ""),
                    description=ins.get("description", ""),
                    evidence=ins.get("evidence"),
                    created_at=ins.get("created_at"),
                )
                for ins in raw_insights
            ]
        except Exception:
            pass  # insight failure must never block execution

    return ExecutionResult(
        proposal_id=proposal_id,
        rows_written=rows_written,
        rows_quarantined=rows_quarantined,
        execution_status="SUCCESS" if rows_written > 0 else "FAILED",
        duration_ms=duration_ms,
        insights=insight_items if insight_items else None,
    )
