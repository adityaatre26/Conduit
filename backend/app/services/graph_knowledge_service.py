"""
Graph Knowledge Service — Neo4j store for AI-facing data knowledge.

Responsibilities (NOT in PostgreSQL):
  - Target table/column schemas (semantic metadata, PII flags)
  - Skill catalog for context retrieval
  - Proposal context bundles built at ingest time
  - Entity relationships used by the AI pipeline

PostgreSQL retains audit/history only (proposals, ledger, quarantine, lineage).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.neo4j_client import neo4j_client

logger = logging.getLogger("conduit.graph_knowledge")


def table_entity_id(table_name: str) -> str:
    """Canonical Neo4j entity_id for a target table."""
    return f"tbl-{table_name}"


def _require_graph():
    if neo4j_client.driver is None:
        raise RuntimeError("Neo4j is not available. Knowledge graph operations are disabled.")


# ── Schema reads (replaces PG tables_metadata / attributes_metadata for AI) ──

async def get_target_schema(table_name: str) -> dict:
    """Return column metadata for a registered table from the knowledge graph."""
    _require_graph()
    eid = table_entity_id(table_name)
    return await _read_schema_from_graph(table_name, eid)


async def _read_schema_from_graph(table_name: str, eid: str) -> dict:
    """Schema fetch without APOC (works on Neo4j Community)."""
    table_recs = await neo4j_client.execute_query(
        """
        MATCH (t:GraphNode {entity_id: $eid})
        RETURN t.entity_name AS table_name, t.metadata_json AS table_meta
        """,
        {"eid": eid},
    )
    if not table_recs:
        return {"table_name": table_name, "semantic_description": "", "columns": []}

    table_meta = json.loads(table_recs[0].get("table_meta") or "{}")
    col_recs = await neo4j_client.execute_query(
        """
        MATCH (c:GraphNode)-[:BELONGS_TO]->(t:GraphNode {entity_id: $eid})
        WHERE c.node_type = 'COLUMN'
        RETURN c.entity_name AS column_name, c.metadata_json AS meta
        ORDER BY c.entity_name
        """,
        {"eid": eid},
    )
    columns = []
    for cr in col_recs:
        meta = json.loads(cr.get("meta") or "{}")
        columns.append({
            "column_name": cr["column_name"],
            "data_type": meta.get("data_type", "VARCHAR"),
            "semantic_description": meta.get("semantic_description", ""),
            "is_required": bool(meta.get("is_required", False)),
            "is_pii": bool(meta.get("is_pii", False)),
            "anomaly_threshold": float(meta.get("anomaly_threshold", 0.05)),
            "sample_values": meta.get("sample_values") or [],
        })

    return {
        "table_name": table_recs[0].get("table_name") or table_name,
        "semantic_description": table_meta.get("semantic_description", ""),
        "columns": columns,
    }


async def get_all_table_schemas() -> List[dict]:
    _require_graph()
    tables = await neo4j_client.execute_query(
        """
        MATCH (t:GraphNode)
        WHERE t.node_type IN ['STORAGE_UNIT', 'TABLE']
        RETURN t.entity_name AS table_name
        ORDER BY t.entity_name
        """,
        {},
    )
    out = []
    for t in tables:
        name = t.get("table_name")
        if name:
            out.append(await get_target_schema(name))
    return out


async def list_registered_tables() -> List[dict]:
    _require_graph()
    records = await neo4j_client.execute_query(
        """
        MATCH (t:GraphNode)
        WHERE t.node_type IN ['STORAGE_UNIT', 'TABLE']
        OPTIONAL MATCH (svc:GraphNode)-[:HAS_STORAGE_UNIT|HAS_PROJECT*1..4]->(t)
        RETURN t.entity_id AS entity_id,
               t.entity_name AS table_name,
               coalesce(svc.entity_name, 'default') AS connection_name
        ORDER BY t.entity_name
        """,
        {},
    )
    return [
        {
            "table_id": r.get("entity_id"),
            "table_name": r.get("table_name"),
            "warehouse_name": r.get("connection_name"),
            "sub_project_name": "",
            "data_role": "PERSISTENT",
        }
        for r in records
    ]


# ── Schema writes (from connector introspection or demo seed) ────────────────

async def upsert_table_schema(
    table_name: str,
    semantic_description: str,
    columns: List[dict],
    conn_id: Optional[str] = None,
    extra_metadata: Optional[dict] = None,
) -> None:
    """Register or update a table + columns in the knowledge graph."""
    _require_graph()
    from app.services import graph_service

    eid = table_entity_id(table_name)
    meta = {
        "semantic_description": semantic_description,
        "conn_id": conn_id,
        **(extra_metadata or {}),
    }
    table_node = await graph_service.get_or_create_node(
        None,
        node_type="STORAGE_UNIT",
        entity_id=eid,
        entity_name=table_name,
        metadata=meta,
    )

    if conn_id:
        conn_node = await graph_service.get_or_create_node(
            None,
            node_type="CONNECTION",
            entity_id=f"conn-{conn_id}",
            entity_name=conn_id,
            metadata={"conn_id": conn_id},
        )
        await graph_service.get_or_create_edge(
            None,
            conn_node["id"],
            table_node["id"],
            "HAS_TABLE",
            1.0,
        )

    for col in columns:
        col_eid = f"col-{table_name}-{col['column_name']}"
        col_meta = {
            "data_type": col.get("data_type", "VARCHAR"),
            "semantic_description": col.get("semantic_description", ""),
            "is_required": bool(col.get("is_required", False)),
            "is_pii": bool(col.get("is_pii", False)),
            "anomaly_threshold": float(col.get("anomaly_threshold", 0.05)),
            "sample_values": col.get("sample_values") or [],
            "parent_table": table_name,
        }
        col_node = await graph_service.get_or_create_node(
            None,
            node_type="COLUMN",
            entity_id=col_eid,
            entity_name=col["column_name"],
            metadata=col_meta,
        )
        await graph_service.get_or_create_edge(
            None,
            col_node["id"],
            table_node["id"],
            "BELONGS_TO",
            1.0,
        )


# ── Skills (AI context) ──────────────────────────────────────────────────────

async def upsert_skill(
    skill_name: str,
    category: str,
    description: str,
    use_cases: Optional[str] = None,
    status: str = "ACTIVE",
) -> None:
    _require_graph()
    from app.services import graph_service

    await graph_service.get_or_create_node(
        None,
        node_type="SKILL",
        entity_id=f"skill-{skill_name}",
        entity_name=skill_name,
        metadata={
            "category": category,
            "description": description,
            "use_cases": use_cases or "",
            "status": status,
        },
    )


async def find_matching_skills(keywords: List[str], limit: int = 10) -> List[dict]:
    _require_graph()
    if not keywords:
        return []
    return await _search_skills_in_graph(keywords, limit)


async def _search_skills_in_graph(keywords: List[str], limit: int) -> List[dict]:
    records = await neo4j_client.execute_query(
        """
        MATCH (s:GraphNode)
        WHERE s.node_type = 'SKILL'
        RETURN s.entity_name AS skill_name, s.metadata_json AS meta
        """,
        {},
    )
    kw_lower = []
    for k in keywords:
        k_low = k.lower()
        kw_lower.append(k_low)
        if "_" in k_low:
            kw_lower.append(k_low.replace("_", " "))
            kw_lower.extend([t for t in k_low.split("_") if len(t) > 2])
    kw_lower = list(set(kw_lower))

    matches = []
    for r in records:
        meta = json.loads(r.get("meta") or "{}")
        if meta.get("status", "ACTIVE") != "ACTIVE":
            continue
        hay = " ".join([
            r.get("skill_name", ""),
            meta.get("description", ""),
            meta.get("use_cases", ""),
        ]).lower()
        if any(k in hay for k in kw_lower):
            matches.append({
                "id": r["skill_name"],
                "skill_name": r["skill_name"],
                "category": meta.get("category", ""),
                "description": meta.get("description", ""),
            })
    return matches[:limit]


# ── Proposal context bundles (AI ingest context) ─────────────────────────────

async def store_proposal_context(
    proposal_id: str,
    target_table: str,
    bundle: dict,
) -> None:
    _require_graph()
    from app.services import graph_service

    await graph_service.get_or_create_node(
        None,
        node_type="PROPOSAL_CONTEXT",
        entity_id=f"ctx-{proposal_id}",
        entity_name=proposal_id,
        metadata={
            "target_table": target_table,
            "context_bundle": bundle,
            "generated_at": datetime.utcnow().isoformat(),
        },
    )


async def get_proposal_context(proposal_id: str) -> Optional[dict]:
    _require_graph()
    records = await neo4j_client.execute_query(
        """
        MATCH (n:GraphNode {entity_id: $eid})
        RETURN n.metadata_json AS meta
        """,
        {"eid": f"ctx-{proposal_id}"},
    )
    if not records:
        return None
    meta = json.loads(records[0].get("meta") or "{}")
    return {
        "proposal_id": proposal_id,
        "target_table": meta.get("target_table"),
        "context_bundle": meta.get("context_bundle"),
        "generated_at": meta.get("generated_at"),
    }


# ── Demo seed (replaces PG metadata + seed_extensions graph section) ─────────

async def seed_demo_knowledge() -> None:
    """Bootstrap demo table schema, skills, and KPI relationships in Neo4j."""
    if neo4j_client.driver is None:
        logger.warning("Neo4j unavailable — skipping demo knowledge seed")
        return

    await upsert_table_schema(
        table_name="orders_clean",
        semantic_description=(
            "Cleaned and validated order records from all sales channels. "
            "Primary source for revenue reporting."
        ),
        columns=[
            {"column_name": "order_id", "data_type": "INT", "semantic_description": "Unique order identifier", "is_required": True, "is_pii": False, "sample_values": ["1001", "1002"]},
            {"column_name": "customer_id", "data_type": "INT", "semantic_description": "Reference to customer record", "is_required": True, "is_pii": False, "sample_values": ["501"]},
            {"column_name": "amount_usd", "data_type": "DECIMAL", "semantic_description": "Order total in USD", "is_required": True, "is_pii": False, "sample_values": ["49.99"]},
            {"column_name": "order_status", "data_type": "VARCHAR", "semantic_description": "Fulfillment status", "is_required": True, "is_pii": False, "sample_values": ["completed"]},
            {"column_name": "customer_email", "data_type": "VARCHAR", "semantic_description": "Customer contact email", "is_required": True, "is_pii": True, "sample_values": ["user@example.com"]},
            {"column_name": "created_at", "data_type": "TIMESTAMP", "semantic_description": "Order creation timestamp", "is_required": True, "is_pii": False, "sample_values": []},
            {"column_name": "processed_at", "data_type": "TIMESTAMP", "semantic_description": "Pipeline processing timestamp", "is_required": False, "is_pii": False, "sample_values": []},
        ],
        conn_id="warehouse",
    )

    demo_skills = [
        ("pii_masking", "SECURITY", "Hashes PII columns using SHA-256.", "Customer contact fields."),
        ("rename_column", "SCHEMA_EVOLUTION", "Renames columns to match target schema.", "Supplier feeds with non-standard names."),
        ("fill_nulls", "DATA_CLEANING", "Fills null values with defaults.", "Order status fields."),
        ("type_conversion", "SCHEMA_EVOLUTION", "Converts column data types.", "CSV uploads arriving as strings."),
        ("deduplicate_records", "DATA_CLEANING", "Removes duplicate rows.", "CRM imports."),
        ("drop_extra_columns", "SCHEMA_EVOLUTION", "Drops columns not in target schema.", "Extra supplier columns."),
    ]
    for name, cat, desc, use in demo_skills:
        await upsert_skill(name, cat, desc, use)

    from app.services import graph_service

    kpi = await graph_service.get_or_create_node(
        None, "KPI", "kpi-revenue", "monthly_revenue",
        {"description": "Aggregate revenue for executive dashboards."},
    )
    dash = await graph_service.get_or_create_node(
        None, "DASHBOARD", "dash-exec", "Executive Revenue Dashboard",
        {"description": "Real-time revenue dashboard.", "refresh_frequency": "hourly"},
    )
    tbl = await graph_service.get_or_create_node(
        None, "STORAGE_UNIT", table_entity_id("orders_clean"), "orders_clean",
        {"semantic_description": "Clean orders table."},
    )
    await graph_service.get_or_create_edge(None, tbl["id"], kpi["id"], "AFFECTS_KPI", 0.9)
    await graph_service.get_or_create_edge(None, dash["id"], kpi["id"], "DEPENDS_ON", 0.9)

    logger.info("Demo knowledge graph seeded in Neo4j")
