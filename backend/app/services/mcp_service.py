"""
mcp_service.py — Schema Service
Reads target-table knowledge from Neo4j (AI graph).

PostgreSQL is NOT used for schema/catalog metadata.
Live row statistics (get_data_distribution) are available for warehouse queries.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.services import graph_knowledge_service


async def get_target_schema(table_name: str, db: AsyncSession = None) -> dict:
    """Fetch target schema from the Neo4j knowledge graph."""
    try:
        return await graph_knowledge_service.get_target_schema(table_name)
    except RuntimeError:
        # Neo4j down — last-resort empty schema (ingest will CONFLICT)
        return {"table_name": table_name, "semantic_description": "", "columns": []}


async def list_registered_tables(db: AsyncSession = None) -> list[dict]:
    try:
        return await graph_knowledge_service.list_registered_tables()
    except RuntimeError:
        return []


async def get_all_table_schemas(db: AsyncSession = None) -> list[dict]:
    try:
        return await graph_knowledge_service.get_all_table_schemas()
    except RuntimeError:
        return []


async def get_data_distribution(table_name: str, db: AsyncSession) -> dict:
    """
    Read live row statistics directly from the warehouse DB.
    Only called by tooling/diagnostics — not part of the ingest path.
    """
    import re
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)?$", table_name):
        raise ValueError("Invalid table name")

    simple = table_name.split(".")[-1] if "." in table_name else table_name

    try:
        schema = await graph_knowledge_service.get_target_schema(simple)
        if not schema.get("columns"):
            return {}
    except RuntimeError:
        return {}

    try:
        count_q = text(f"SELECT COUNT(*) FROM {table_name}")
        row_count = (await db.execute(count_q)).scalar()

        cols = [c["column_name"] for c in schema["columns"]]
        columns = []
        for c in cols:
            if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", c):
                continue
            null_count = (await db.execute(text(f"SELECT COUNT(*) - COUNT({c}) FROM {table_name}"))).scalar()
            distinct   = (await db.execute(text(f"SELECT COUNT(DISTINCT {c}) FROM {table_name}"))).scalar()
            columns.append({
                "column_name": c,
                "null_count": null_count,
                "null_ratio": null_count / row_count if row_count else 0,
                "distinct_count": distinct,
            })

        return {"table_name": table_name, "row_count": row_count, "columns": columns}
    except Exception:
        return {}
