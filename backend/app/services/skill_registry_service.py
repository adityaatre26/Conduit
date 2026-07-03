"""
skill_registry_service.py
─────────────────────────
Purpose:
    Manages the registry of reusable transformation skills.
"""
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from app.extension_models import Skill, SkillScript, SkillExample, SkillIssueReference


async def register_skill(
    db: AsyncSession,
    skill_name: str,
    version: str,
    category: str,
    description: str,
    use_cases: Optional[str] = None,
    constraints: Optional[str] = None,
    owner: Optional[str] = None,
    examples: Optional[List[dict]] = None,
    issue_references: Optional[List[dict]] = None,
) -> Skill:
    """
    Create a new skill record and optional child records.
    Returns the persisted Skill ORM object.
    """
    skill = Skill(
        skill_name=skill_name,
        version=version,
        category=category,
        description=description,
        use_cases=use_cases,
        constraints=constraints,
        owner=owner,
    )
    db.add(skill)
    await db.flush()  # get skill.id without full commit

    if examples:
        for ex in examples:
            db.add(SkillExample(
                skill_id=skill.id,
                input_example=ex.get("input"),
                output_example=ex.get("output"),
            ))

    if issue_references:
        for ref in issue_references:
            db.add(SkillIssueReference(
                skill_id=skill.id,
                issue_reference=ref.get("reference"),
                resolution_notes=ref.get("notes"),
            ))

    await db.commit()
    await db.refresh(skill)

    # Automatically generate, save, and attach the Python script for the skill
    try:
        from app.services import ai_service
        import os
        import hashlib

        # Generate the script code
        code = await ai_service.generate_skill_script(
            skill_name=skill_name,
            description=description,
            category=category
        )

        # Build paths
        current_dir = os.path.dirname(os.path.abspath(__file__))
        scripts_dir = os.path.join(current_dir, "scripts")
        os.makedirs(scripts_dir, exist_ok=True)

        script_filename = f"{skill_name}.py"
        script_filepath = os.path.join(scripts_dir, script_filename)

        # Write to filesystem
        with open(script_filepath, "w", encoding="utf-8") as f:
            f.write(code)

        # Compute SHA-256 hash of the generated code
        script_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()

        # Database path reference
        db_path = f"app/services/scripts/{script_filename}"

        # Register script reference in database
        from app.extension_models import SkillScript
        db.add(SkillScript(
            skill_id=skill.id,
            script_path=db_path,
            script_hash=script_hash,
            is_validated=True
        ))
        await db.commit()
    except Exception as e:
        # Prevent auto-generation issues from breaking the main transaction, log error
        print(f"Failed to auto-generate and save skill script: {e}")

    # Mirror skill into Neo4j knowledge graph for AI context retrieval
    try:
        from app.services import graph_knowledge_service
        await graph_knowledge_service.upsert_skill(
            skill_name=skill_name,
            category=category,
            description=description,
            use_cases=use_cases,
            status="ACTIVE",
        )
    except Exception:
        pass

    return skill



async def get_skill(db: AsyncSession, skill_id: int) -> Optional[Skill]:
    """Fetch a single skill by primary key."""
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    return result.scalars().first()


async def get_skill_with_children(db: AsyncSession, skill_id: int) -> dict:
    """
    Return a skill along with its scripts, examples, and issue references.
    """
    skill = await get_skill(db, skill_id)
    if not skill:
        return {}

    scripts_res = await db.execute(
        select(SkillScript).where(SkillScript.skill_id == skill_id)
    )
    examples_res = await db.execute(
        select(SkillExample).where(SkillExample.skill_id == skill_id)
    )
    issues_res = await db.execute(
        select(SkillIssueReference).where(SkillIssueReference.skill_id == skill_id)
    )

    return {
        "skill": skill,
        "scripts": scripts_res.scalars().all(),
        "examples": examples_res.scalars().all(),
        "issue_references": issues_res.scalars().all(),
    }


async def list_skills(
    db: AsyncSession,
    category: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Skill]:
    """List all skills with optional filters."""
    stmt = select(Skill)
    if category:
        stmt = stmt.where(Skill.category == category)
    if status:
        stmt = stmt.where(Skill.status == status)
    stmt = stmt.order_by(Skill.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


async def find_matching_skills(
    db: AsyncSession,
    keywords: List[str],
    limit: int = 10,
) -> List[Skill]:
    """
    Keyword search across skill_name, description, and use_cases.
    Used by the context retrieval layer to surface relevant skills
    for an incoming dataset.  Keywords are OR-combined so any match
    surfaces the skill.
    """
    if not keywords:
        return []

    filters = []
    for kw in keywords:
        kw_like = f"%{kw}%"
        filters.append(Skill.skill_name.ilike(kw_like))
        filters.append(Skill.description.ilike(kw_like))
        filters.append(Skill.use_cases.ilike(kw_like))
        filters.append(Skill.category.ilike(kw_like))

    stmt = (
        select(Skill)
        .where(or_(*filters))
        .where(Skill.status == "ACTIVE")
        .order_by(Skill.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


async def update_skill(
    db: AsyncSession,
    skill_id: int,
    status: Optional[str] = None,
    owner: Optional[str] = None,
    description: Optional[str] = None,
    use_cases: Optional[str] = None,
    constraints: Optional[str] = None,
) -> Optional[Skill]:
    """
    Partially update a skill record.  Only supplied (non-None) fields
    are written.  Returns the updated Skill, or None if not found.
    """
    skill = await get_skill(db, skill_id)
    if not skill:
        return None

    if status is not None:
        valid_statuses = {"ACTIVE", "DEPRECATED", "DRAFT"}
        if status not in valid_statuses:
            raise ValueError(f"status must be one of {valid_statuses}")
        skill.status = status

    if owner is not None:
        skill.owner = owner
    if description is not None:
        skill.description = description
    if use_cases is not None:
        skill.use_cases = use_cases
    if constraints is not None:
        skill.constraints = constraints

    await db.commit()
    await db.refresh(skill)
    return skill


async def add_skill_script(
    db: AsyncSession,
    skill_id: int,
    script_path: str,
    script_hash: Optional[str] = None,
    is_validated: bool = True,
) -> Optional[SkillScript]:
    """
    Attach a script reference to an existing skill.
    Returns the new SkillScript record, or None if skill not found.
    """
    skill = await get_skill(db, skill_id)
    if not skill:
        return None
    script = SkillScript(
        skill_id=skill_id,
        script_path=script_path,
        script_hash=script_hash,
        is_validated=is_validated,
    )
    db.add(script)
    await db.commit()
    await db.refresh(script)
    return script


async def add_skill_issue(
    db: AsyncSession,
    skill_id: int,
    issue_reference: str,
    resolution_notes: Optional[str] = None,
) -> Optional[SkillIssueReference]:
    """
    Link a historical incident to a skill so the AI can learn from it.
    """
    skill = await get_skill(db, skill_id)
    if not skill:
        return None
    ref = SkillIssueReference(
        skill_id=skill_id,
        issue_reference=issue_reference,
        resolution_notes=resolution_notes,
    )
    db.add(ref)
    await db.commit()
    await db.refresh(ref)
    return ref
