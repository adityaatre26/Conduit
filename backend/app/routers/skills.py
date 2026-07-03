"""
skills.py
─────────
Purpose:
    FastAPI router defining endpoints for the transformation Skill Registry.

Use Cases:
    - POST /api/skills: Register new reusable transformation skills.
    - GET /api/skills: Query skill specifications, incidents, and example mappings.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from app.database import get_db
from app.extension_schemas import (
    CreateSkillRequest,
    UpdateSkillRequest,
    AddSkillScriptRequest,
    AddSkillIssueRequest,
    SkillResponse,
    SkillDetailResponse,
)
from app.services import skill_registry_service

router = APIRouter()


# ── List ─────────────────────────────────────────────────────────────────────

@router.get("/skills", response_model=List[SkillResponse])
async def list_skills(
    category: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """List all registered skills with optional filters."""
    skills = await skill_registry_service.list_skills(
        db, category=category, status=status, limit=limit, offset=offset
    )
    return [SkillResponse.model_validate(s) for s in skills]


# ── Keyword search — must be declared BEFORE /{skill_id} to avoid shadowing ──

@router.get("/skills/search", response_model=List[SkillResponse])
async def search_skills(
    q: str = Query(..., min_length=1, description="Keywords to match against name, description, use_cases, and category"),
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
):
    """
    Keyword search across skill_name, description, use_cases, and category.
    Multiple space-separated terms are OR-combined.

    Example:
        GET /api/skills/search?q=pii+email
    """
    keywords = [kw.strip() for kw in q.split() if kw.strip()]
    skills = await skill_registry_service.find_matching_skills(db, keywords=keywords, limit=limit)
    return [SkillResponse.model_validate(s) for s in skills]


# ── Single skill detail ───────────────────────────────────────────────────────

def read_script_code(script_path: str) -> Optional[str]:
    """Helper to locate and read the script file content from disk."""
    import os
    if not script_path:
        return None
    # Current file is backend/app/routers/skills.py.
    # We want backend/ as root, and script_path is e.g. 'app/services/scripts/name.py'
    current_dir = os.path.dirname(os.path.abspath(__file__))
    backend_root = os.path.dirname(os.path.dirname(current_dir))
    full_path = os.path.join(backend_root, script_path)
    if os.path.exists(full_path):
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            pass
    return None


@router.get("/skills/{skill_id}", response_model=SkillDetailResponse)
async def get_skill(skill_id: int, db: AsyncSession = Depends(get_db)):
    """Get a skill with all its scripts, examples, and issue references."""
    data = await skill_registry_service.get_skill_with_children(db, skill_id)
    if not data:
        raise HTTPException(status_code=404, detail="Skill not found")

    skill = data["skill"]
    return SkillDetailResponse(
        id=skill.id,
        skill_name=skill.skill_name,
        version=skill.version,
        category=skill.category,
        description=skill.description,
        use_cases=skill.use_cases,
        constraints=skill.constraints,
        owner=skill.owner,
        status=skill.status,
        created_at=skill.created_at,
        scripts=[
            {
                "id": s.id,
                "script_path": s.script_path,
                "script_hash": s.script_hash,
                "is_validated": s.is_validated,
                "code": read_script_code(s.script_path),
            }
            for s in data["scripts"]
        ],

        examples=[
            {
                "id": e.id,
                "input_example": e.input_example,
                "output_example": e.output_example,
            }
            for e in data["examples"]
        ],
        issue_references=[
            {
                "id": r.id,
                "issue_reference": r.issue_reference,
                "resolution_notes": r.resolution_notes,
            }
            for r in data["issue_references"]
        ],
    )


# ── Create ────────────────────────────────────────────────────────────────────

@router.post("/skills", response_model=SkillResponse, status_code=201)
async def create_skill(req: CreateSkillRequest, db: AsyncSession = Depends(get_db)):
    """Register a new skill in the registry."""
    try:
        skill = await skill_registry_service.register_skill(
            db=db,
            skill_name=req.skill_name,
            version=req.version,
            category=req.category,
            description=req.description,
            use_cases=req.use_cases,
            constraints=req.constraints,
            owner=req.owner,
            examples=[
                {"input": e.input, "output": e.output} for e in (req.examples or [])
            ],
            issue_references=[
                {"reference": r.reference, "notes": r.notes}
                for r in (req.issue_references or [])
            ],
        )
        return SkillResponse.model_validate(skill)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Partial update ────────────────────────────────────────────────────────────

@router.patch("/skills/{skill_id}", response_model=SkillResponse)
async def update_skill(
    skill_id: int,
    req: UpdateSkillRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Partially update a skill.  Only fields present in the request body are
    written — omitted fields keep their current value.

    Allowed fields: status, owner, description, use_cases, constraints.
    Valid status values: ACTIVE | DEPRECATED | DRAFT.
    """
    try:
        skill = await skill_registry_service.update_skill(
            db=db,
            skill_id=skill_id,
            status=req.status,
            owner=req.owner,
            description=req.description,
            use_cases=req.use_cases,
            constraints=req.constraints,
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return SkillResponse.model_validate(skill)


# ── Sub-resource: scripts ─────────────────────────────────────────────────────

@router.post("/skills/{skill_id}/scripts", status_code=201)
async def add_script(
    skill_id: int,
    req: AddSkillScriptRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Attach a validated script reference to an existing skill.
    This records that a particular script file implements this skill so the
    execution engine can locate and invoke it.
    """
    script = await skill_registry_service.add_skill_script(
        db=db,
        skill_id=skill_id,
        script_path=req.script_path,
        script_hash=req.script_hash,
        is_validated=req.is_validated,
    )
    if script is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {
        "id": script.id,
        "skill_id": script.skill_id,
        "script_path": script.script_path,
        "script_hash": script.script_hash,
        "is_validated": script.is_validated,
    }


# ── Sub-resource: historical issues ──────────────────────────────────────────

@router.post("/skills/{skill_id}/issues", status_code=201)
async def add_issue(
    skill_id: int,
    req: AddSkillIssueRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Link a historical incident to a skill so the AI can learn from past failures.
    Issue references are surfaced in the context bundle alongside the skill.
    """
    ref = await skill_registry_service.add_skill_issue(
        db=db,
        skill_id=skill_id,
        issue_reference=req.issue_reference,
        resolution_notes=req.resolution_notes,
    )
    if ref is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {
        "id": ref.id,
        "skill_id": ref.skill_id,
        "issue_reference": ref.issue_reference,
        "resolution_notes": ref.resolution_notes,
    }
