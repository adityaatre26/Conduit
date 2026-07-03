"""
ingest.py
─────────
Purpose:
    FastAPI router defining the primary data ingestion pipeline entry point.

Use Cases:
    - POST /api/ingest: Receives file uploads, performs validation, runs AI schema comparison, and returns execution proposals.
"""

from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
import uuid
import aiofiles
import pandas as pd
import json

from app.database import get_db
from app.services import validation_service, mcp_service, ai_service, gateway_service, suggest_service
from app.services import context_retrieval_service  # Phase 1 & 2 — build & store context bundle
from app.models import Proposal
from app.schemas import ProposalResponse, DriftItem
from typing import Optional

router = APIRouter()

@router.post("/suggest-target")
async def suggest_target_table(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    file_bytes = await file.read()
    
    # Validate magic bytes
    ext = ""
    if file.filename:
        ext = "." + file.filename.split(".")[-1]
    is_valid, reason = validation_service.validate_magic_bytes(file_bytes, ext)
    if not is_valid:
        raise HTTPException(status_code=400, detail=reason)
        
    # Save file temporarily
    file_id = str(uuid.uuid4())
    import os
    try:
        os.makedirs("/tmp", exist_ok=True)
    except Exception:
        pass
    tmp_path = f"/tmp/{file_id}_{file.filename}"
    try:
        async with aiofiles.open(tmp_path, 'wb') as f:
            await f.write(file_bytes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {str(e)}")
        
    try:
        if ext.lower() == ".json":
            df = pd.read_json(tmp_path)
        else:
            df = pd.read_csv(tmp_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid file format: {str(e)}")
    finally:
        # Clean up temp file
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
            
    try:
        suggestions = await suggest_service.suggest_target_table(df, db)
        return suggestions
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate table suggestions: {str(e)}")

@router.post("/ingest", response_model=ProposalResponse)
async def ingest_file(
    file: UploadFile = File(...),
    target_table: str = Form(...),
    description_md: Optional[str] = Form(None),
    extra_params: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db)
):
    # Parse extra_params JSON string into dict
    extra_params_dict = None
    if extra_params:
        try:
            extra_params_dict = json.loads(extra_params)
        except (json.JSONDecodeError, TypeError):
            raise HTTPException(status_code=400, detail="extra_params must be a valid JSON object")
    file_bytes = await file.read()
    
    # 2. Validate magic bytes
    ext = ""
    if file.filename:
        ext = "." + file.filename.split(".")[-1]
    is_valid, reason = validation_service.validate_magic_bytes(file_bytes, ext)
    if not is_valid:
        raise HTTPException(status_code=400, detail=reason)
        
    # 3. Save file
    file_id = str(uuid.uuid4())
    import os
    try:
        os.makedirs("/tmp", exist_ok=True)
    except Exception:
        pass  # ignore if directory creation fails or not applicable
    tmp_path = f"/tmp/{file_id}_{file.filename}"
    try:
        async with aiofiles.open(tmp_path, 'wb') as f:
            await f.write(file_bytes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {str(e)}")
        
    # 4. Load sample rows
    try:
        if ext.lower() == ".json":
            df = pd.read_json(tmp_path)
        else:
            df = pd.read_csv(tmp_path)
    except pd.errors.EmptyDataError as e:
        raise HTTPException(status_code=400, detail=f"Invalid file format: EmptyDataError - {str(e)}")
    except pd.errors.ParserError as e:
        raise HTTPException(status_code=400, detail=f"Invalid file format: ParserError - {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid file format: {str(e)}")
        
    sample_rows = df.head(5).to_dict(orient="records")
    
    # 5. Detect incoming schema
    incoming_schema = {col: str(dtype) for col, dtype in df.dtypes.items()}
    incoming_cols = set(incoming_schema.keys())
    
    # 6. Target schema
    try:
        target_schema = await mcp_service.get_target_schema(target_table, db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch target schema: {str(e)}")
        
    target_cols = {col["column_name"] for col in target_schema.get("columns", [])}
    
    if len(incoming_cols.intersection(target_cols)) == 0:
        drift_detected = [
            {
                "column": "ALL_COLUMNS",
                "issue_type": "SCHEMA_MISMATCH",
                "source_value": ", ".join(sorted(incoming_cols)),
                "target_expectation": ", ".join(sorted(target_cols)),
                "suggested_action": "Reject upload. No matching columns found.",
                "severity": "CRITICAL"
            }
        ]
        proposed_steps = ["Reject dataset. Zero columns in common with target schema."]
        generated_code = "def transform(df):\n    # Zero columns in common. No transformation possible.\n    return df"
        
        # STAGE 2: include target_table in the proposal
        proposal = Proposal(
            id=file_id,
            filename=file.filename,
            gateway_status="CONFLICT",
            drift_detected=drift_detected,
            proposed_steps=proposed_steps,
            generated_code=generated_code,
            confidence_score=0.0,
            llm_raw_response="Skipped LLM call: Zero columns in common.",
            llm_prompt_sent="Skipped LLM call: Zero columns in common.",
            status="PENDING",
            file_path=tmp_path,
            target_table=target_table,
            estimated_rows=len(df),
            pii_columns_found=[],
            llm_model_used="none",
            description_md=description_md,
            suggested_skills_to_add=[],
            extra_params=extra_params_dict
        )
        db.add(proposal)
        await db.commit()

        # Store an empty context bundle so GET /proposals/{id}/context returns successfully
        try:
            empty_bundle = {
                "target_table": target_table,
                "related_entities": [],
                "related_skills": [],
                "dependencies": [],
                "business_context": [],
                "pii_columns": []
            }
            await context_retrieval_service.store_proposal_context(
                db=db,
                proposal_id=file_id,
                target_table=target_table,
                bundle=empty_bundle
            )
        except Exception:
            pass
        
        drift_items = [DriftItem(**item) for item in drift_detected]
        
        # STAGE 4: No context bundle for zero-overlap fast path (no point)
        return ProposalResponse(
            proposal_id=file_id,
            gateway_status="CONFLICT",
            target_table=target_table,
            drift_detected=drift_items,
            proposed_steps=proposed_steps,
            generated_code=generated_code,
            confidence_score=0.0,
            pii_columns_found=[],
            estimated_rows=len(df),
            llm_model_used="none",
            description_md=description_md,
            suggested_skills_to_add=[],
            extra_params=extra_params_dict
        )
    
    # Table semantic context for AI (from knowledge graph, not PG)
    table_metadata = {"semantic_description": target_schema.get("semantic_description", "")}

    # ── STAGE 4: Build context bundle BEFORE AI call (Phase 2 reorder) ────────
    context_bundle = None
    try:
        context_bundle = await context_retrieval_service.build_context_bundle(
            db=db,
            target_table=target_table,
            incoming_columns=list(incoming_schema.keys()),
        )
    except Exception:
        pass  # context bundle failure must never block ingest
    # ──────────────────────────────────────────────────────────────────────────
    
    # 7. AI proposal & 8. Validate code
    is_retry = False
    try:
        # STAGE 3/4: Pass context_bundle to AI service
        ai_resp = await ai_service.generate_pipeline_proposal(
            incoming_schema, target_schema, sample_rows, table_metadata,
            context_bundle=context_bundle,
            description_md=description_md,
        )
        parsed = ai_resp["parsed"]
        generated_code = parsed["generated_code"]
        
        is_valid_code, code_reason = validation_service.validate_generated_code(generated_code)
        if not is_valid_code:
            # Retry once
            is_retry = True
            ai_resp = await ai_service.generate_pipeline_proposal(
                incoming_schema, target_schema, sample_rows, table_metadata,
                context_bundle=context_bundle,
                retry_msg=f"Code validation failed: {code_reason}. Provide fixed code.",
                description_md=description_md,
            )
            parsed = ai_resp["parsed"]
            generated_code = parsed["generated_code"]
            is_valid_code, code_reason = validation_service.validate_generated_code(generated_code)
            if not is_valid_code:
                raise HTTPException(status_code=422, detail={"error": "code validation failed", "detail": code_reason})
    except Exception as e:
        from sqlalchemy import select
        stmt = select(Proposal).where(Proposal.status == "EXECUTED").order_by(Proposal.created_at.desc()).limit(1)
        res = await db.execute(stmt)
        cached_proposal = res.scalars().first()
        
        if cached_proposal:
            reasoning_note = "Fallback cache was used due to API timeout/failure."
            
            raw_resp = json.dumps({
                "drift_detected": cached_proposal.drift_detected,
                "proposed_steps": cached_proposal.proposed_steps,
                "generated_code": cached_proposal.generated_code,
                "confidence_score": cached_proposal.confidence_score,
                "pii_columns_found": cached_proposal.pii_columns_found,
                "reasoning": reasoning_note,
                "gateway_recommendation": cached_proposal.gateway_status
            })
            
            # STAGE 2: include target_table in the fallback proposal
            proposal = Proposal(
                id=file_id,
                filename=file.filename,
                gateway_status=cached_proposal.gateway_status,
                drift_detected=cached_proposal.drift_detected,
                proposed_steps=cached_proposal.proposed_steps,
                generated_code=cached_proposal.generated_code,
                confidence_score=cached_proposal.confidence_score,
                llm_raw_response=raw_resp,
                llm_prompt_sent=f"Fallback cache used. Original exception: {str(e)}",
                status="PENDING",
                file_path=tmp_path,
                target_table=target_table,
                estimated_rows=len(df),
                pii_columns_found=cached_proposal.pii_columns_found,
                llm_model_used="cached-fallback",
                description_md=description_md,
                suggested_skills_to_add=[],
                extra_params=extra_params_dict
            )
            proposal.reasoning = reasoning_note
            proposal.reasoning_note = reasoning_note
            
            db.add(proposal)
            await db.commit()
            
            drift_items = [DriftItem(**item) for item in cached_proposal.drift_detected]
            
            return ProposalResponse(
                proposal_id=file_id,
                gateway_status=cached_proposal.gateway_status,
                target_table=target_table,
                drift_detected=drift_items,
                proposed_steps=cached_proposal.proposed_steps,
                generated_code=cached_proposal.generated_code,
                confidence_score=cached_proposal.confidence_score,
                pii_columns_found=cached_proposal.pii_columns_found,
                estimated_rows=len(df),
                llm_model_used="cached-fallback",
                reasoning=reasoning_note,
                reasoning_note=reasoning_note,
                description_md=description_md,
                suggested_skills_to_add=[],
                extra_params=extra_params_dict
            )
        else:
            if isinstance(e, HTTPException):
                raise e
            detail_msg = f"AI Retry Service failed: {str(e)}" if is_retry else f"AI Generation Service failed: {str(e)}"
            raise HTTPException(status_code=502, detail=detail_msg)
            
    # 9. Gateway classification
    gateway_status = gateway_service.classify_gateway_state(
        parsed["gateway_recommendation"],
        parsed["drift_detected"],
        parsed["confidence_score"]
    )
    
    suggested_skills = parsed.get("suggested_skills_to_add", [])
    enrichment_applied = parsed.get("enrichment_applied", [])

    # 10. Save proposal (STAGE 2: includes target_table)
    proposal = Proposal(
        id=file_id,
        filename=file.filename,
        gateway_status=gateway_status,
        drift_detected=parsed["drift_detected"],
        proposed_steps=parsed["proposed_steps"],
        generated_code=generated_code,
        confidence_score=parsed["confidence_score"],
        llm_raw_response=ai_resp["raw_response"],
        llm_prompt_sent=ai_resp["prompt_sent"],
        status="PENDING",
        file_path=tmp_path,
        target_table=target_table,
        estimated_rows=len(df),
        pii_columns_found=parsed["pii_columns_found"],
        llm_model_used=ai_resp["model_used"],
        description_md=description_md,
        suggested_skills_to_add=suggested_skills,
        enrichment_applied=enrichment_applied,
        extra_params=extra_params_dict
    )
    db.add(proposal)
    await db.commit()
    
    drift_items = [DriftItem(**item) for item in parsed["drift_detected"]]
    
    # ── STAGE 4: Store context bundle AFTER proposal save ──────────────────
    # (for GET /proposals/{id}/context endpoint)
    try:
        if context_bundle:
            await context_retrieval_service.store_proposal_context(
                db=db,
                proposal_id=file_id,
                target_table=target_table,
                bundle=context_bundle,
            )
    except Exception:
        pass  # context bundle storage failure must never block ingest
    # ───────────────────────────────────────────────────────────────────────
    
    # 11. Return (STAGE 7: includes target_table)
    return ProposalResponse(
        proposal_id=file_id,
        gateway_status=gateway_status,
        target_table=target_table,
        drift_detected=drift_items,
        proposed_steps=parsed["proposed_steps"],
        generated_code=generated_code,
        confidence_score=parsed["confidence_score"],
        pii_columns_found=parsed["pii_columns_found"],
        estimated_rows=len(df),
        llm_model_used=ai_resp["model_used"],
        description_md=description_md,
        suggested_skills_to_add=suggested_skills,
        enrichment_applied=enrichment_applied,
        extra_params=extra_params_dict
    )
