"""
context_retrieval_service.py
────────────────────────────
Purpose:
    Builds the context bundle required by the LLM during proposal generation.

Use Cases:
    - Traces entity dependencies and matches relevant transformation skills.
"""
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import graph_service, graph_knowledge_service


async def build_context_bundle(
    db: AsyncSession,
    target_table: str,
    incoming_columns: Optional[List[str]] = None,
) -> dict:
    lineage_data = await graph_service.get_lineage(
        db, entity_name=target_table, max_depth=2
    )
    graph_nodes: List[dict] = lineage_data.get("nodes", [])

    related_entities = [
        {"id": n["id"], "name": n["entity_name"], "type": n["node_type"]}
        for n in graph_nodes
        if n.get("entity_name") and n["entity_name"].lower() != target_table.lower()
    ]

    dependencies: List[dict] = []
    pii_columns: List[str] = []
    eid = graph_knowledge_service.table_entity_id(target_table)
    table_nodes = [
        n for n in graph_nodes
        if n.get("entity_id") == eid
        or (n.get("entity_name") and n["entity_name"].lower() == target_table.lower())
    ]
    if table_nodes:
        target_node_id = table_nodes[0]["id"]
        deps = await graph_service.get_neighbors(db, node_id=target_node_id, direction="in")
        for item in deps.get("inbound", []):
            dependencies.append({
                "id": item["node"]["id"],
                "name": item["node"]["entity_name"],
                "type": item["node"]["node_type"],
            })

        for node in graph_nodes:
            if (
                node.get("node_type") == "COLUMN"
                and node.get("node_metadata")
                and node["node_metadata"].get("is_pii")
            ):
                pii_columns.append(node.get("entity_name") or "")

    keywords = [target_table] + (incoming_columns or [])
    matching_skills = await graph_knowledge_service.find_matching_skills(
        keywords=keywords, limit=10
    )
    related_skills = [
        {
            "id": s["skill_name"],
            "name": s["skill_name"],
            "category": s["category"],
            "description": s["description"],
        }
        for s in matching_skills
    ]

    business_context: List[str] = []
    for node in graph_nodes:
        if node.get("node_metadata"):
            kpi = node["node_metadata"].get("business_kpi_impact")
            if kpi:
                business_context.append(kpi)

    return {
        "target_table": target_table,
        "related_entities": related_entities,
        "related_skills": related_skills,
        "dependencies": dependencies,
        "business_context": business_context,
        "pii_columns": list(set(pii_columns)),
    }


async def store_proposal_context(
    db: AsyncSession,
    proposal_id: str,
    target_table: str,
    bundle: dict,
) -> None:
    try:
        await graph_knowledge_service.store_proposal_context(
            proposal_id=proposal_id,
            target_table=target_table,
            bundle=bundle,
        )
    except RuntimeError:
        pass


async def get_proposal_context(
    db: AsyncSession,
    proposal_id: str,
) -> Optional[dict]:
    try:
        return await graph_knowledge_service.get_proposal_context(proposal_id)
    except RuntimeError:
        return None
