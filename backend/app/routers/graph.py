"""
graph.py
────────
Purpose:
    FastAPI router defining endpoints for interacting with the Neo4j relationship graph.

Use Cases:
    - Traverses nodes/edges in the database network.
    - Runs impact analysis and lineage tracing queries using BFS traversal.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from app.database import get_db
from app.extension_schemas import (
    GraphNodeResponse,
    GraphEdgeResponse,
    LineageGraphResponse,
    CreateGraphNodeRequest,
    CreateGraphEdgeRequest,
    NeighborDetail,
    NeighborsResponse,
    ImpactedNode,
    ImpactAnalysisResponse,
)
from app.services import graph_service

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
#  Node endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/graph/nodes", response_model=List[GraphNodeResponse])
async def list_nodes(
    node_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Return all graph nodes, optionally filtered by type."""
    nodes = await graph_service.get_all_nodes(
        db, node_type=node_type, limit=limit, offset=offset
    )
    return [
        GraphNodeResponse(
            id=n["id"],
            node_type=n["node_type"],
            entity_id=n["entity_id"],
            entity_name=n["entity_name"],
            metadata=n["node_metadata"]
        )
        for n in nodes
    ]


@router.post("/graph/nodes", response_model=GraphNodeResponse, status_code=201)
async def create_node(
    req: CreateGraphNodeRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Create or retrieve a graph node idempotently.
    """
    try:
        node = await graph_service.get_or_create_node(
            db,
            node_type=req.node_type,
            entity_id=req.entity_id,
            entity_name=req.entity_name,
            metadata=req.metadata,
        )
        return GraphNodeResponse(
            id=node["id"],
            node_type=node["node_type"],
            entity_id=node["entity_id"],
            entity_name=node["entity_name"],
            metadata=node["node_metadata"]
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
#  Edge endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/graph/edges", response_model=List[GraphEdgeResponse])
async def list_edges(
    relation_type: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Return all graph edges, optionally filtered by relation type."""
    edges = await graph_service.get_all_edges(
        db, relation_type=relation_type, limit=limit, offset=offset
    )
    return [
        GraphEdgeResponse(
            id=e["id"],
            source_node_id=e["source_node_id"],
            target_node_id=e["target_node_id"],
            relation_type=e["relation_type"],
            confidence_score=e["confidence_score"],
            created_at=e["created_at"]
        )
        for e in edges
    ]


@router.post("/graph/edges", response_model=GraphEdgeResponse, status_code=201)
async def create_edge(
    req: CreateGraphEdgeRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a directed edge between two existing graph nodes.
    """
    try:
        edge = await graph_service.get_or_create_edge(
            db,
            source_node_id=req.source_node_id,
            target_node_id=req.target_node_id,
            relation_type=req.relation_type,
            confidence_score=req.confidence_score,
        )
        return GraphEdgeResponse(
            id=edge["id"],
            source_node_id=edge["source_node_id"],
            target_node_id=edge["target_node_id"],
            relation_type=edge["relation_type"],
            confidence_score=edge["confidence_score"],
            created_at=edge["created_at"]
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
#  Traversal endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/graph/neighbors/{node_id}", response_model=NeighborsResponse)
async def get_neighbors(
    node_id: int,
    direction: str = "both",
    db: AsyncSession = Depends(get_db),
):
    """
    Return every node one hop away from node_id.
    """
    if direction not in ("out", "in", "both"):
        raise HTTPException(
            status_code=400,
            detail="direction must be 'out', 'in', or 'both'",
        )

    result = await graph_service.get_neighbors(db, node_id=node_id, direction=direction)

    neighbors: List[NeighborDetail] = []
    for item in result.get("outbound", []):
        neighbors.append(
            NeighborDetail(
                direction="outbound",
                relation_type=item["edge"]["relation_type"],
                confidence_score=item["edge"]["confidence_score"],
                node=GraphNodeResponse(
                    id=item["node"]["id"],
                    node_type=item["node"]["node_type"],
                    entity_id=item["node"]["entity_id"],
                    entity_name=item["node"]["entity_name"],
                    metadata=item["node"]["node_metadata"]
                )
            )
        )
    for item in result.get("inbound", []):
        neighbors.append(
            NeighborDetail(
                direction="inbound",
                relation_type=item["edge"]["relation_type"],
                confidence_score=item["edge"]["confidence_score"],
                node=GraphNodeResponse(
                    id=item["node"]["id"],
                    node_type=item["node"]["node_type"],
                    entity_id=item["node"]["entity_id"],
                    entity_name=item["node"]["entity_name"],
                    metadata=item["node"]["node_metadata"]
                )
            )
        )

    return NeighborsResponse(node_id=node_id, neighbors=neighbors, total=len(neighbors))


@router.get("/graph/lineage/{entity}", response_model=LineageGraphResponse)
async def get_entity_lineage(
    entity: str,
    max_depth: int = 4,
    db: AsyncSession = Depends(get_db),
):
    """
    BFS traversal from any node matching the entity name or id.
    """
    result = await graph_service.get_lineage(
        db, entity_name=entity, max_depth=max_depth
    )
    return LineageGraphResponse(
        nodes=[
            GraphNodeResponse(
                id=n["id"],
                node_type=n["node_type"],
                entity_id=n["entity_id"],
                entity_name=n["entity_name"],
                metadata=n["node_metadata"]
            )
            for n in result["nodes"]
        ],
        edges=[
            GraphEdgeResponse(
                id=e["id"],
                source_node_id=e["source_node_id"],
                target_node_id=e["target_node_id"],
                relation_type=e["relation_type"],
                confidence_score=e["confidence_score"],
                created_at=e["created_at"]
            )
            for e in result["edges"]
        ],
    )


@router.get("/graph/impact/{entity}", response_model=ImpactAnalysisResponse)
async def get_impact_analysis(
    entity: str,
    max_depth: int = 4,
    db: AsyncSession = Depends(get_db),
):
    """
    Reverse BFS impact analysis in Neo4j.
    """
    result = await graph_service.get_impact_analysis(
        db, entity_name=entity, max_depth=max_depth
    )

    impacted = [
        ImpactedNode(
            node=GraphNodeResponse(
                id=item["node"]["id"],
                node_type=item["node"]["node_type"],
                entity_id=item["node"]["entity_id"],
                entity_name=item["node"]["entity_name"],
                metadata=item["node"]["node_metadata"]
            ),
            depth=item["depth"],
            relation_type=item["relation_type"],
            path=item["path"],
        )
        for item in result["impacted_nodes"]
    ]

    return ImpactAnalysisResponse(
        entity=entity,
        start_nodes=[
            GraphNodeResponse(
                id=n["id"],
                node_type=n["node_type"],
                entity_id=n["entity_id"],
                entity_name=n["entity_name"],
                metadata=n["node_metadata"]
            )
            for n in result["start_nodes"]
        ],
        impacted_nodes=impacted,
        total_impacted=result["total_impacted"],
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Catalog Synchronization & Auditing Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/graph/sync", status_code=200)
async def sync_metadata_catalog(db: AsyncSession = Depends(get_db)):
    """
    Sync knowledge graph from the default warehouse connector.
    Org path: register connector → POST /connectors/{id}/sync-graph.
    """
    try:
        from app.services import connector_introspection_service
        from app.connectors.db_factory import factory
        if "warehouse" in factory.connections:
            result = await connector_introspection_service.sync_connection_to_graph("warehouse")
            return {"status": "success", "message": "Knowledge graph synced from warehouse connector.", **result}
        from app.services import graph_knowledge_service
        await graph_knowledge_service.seed_demo_knowledge()
        return {"status": "success", "message": "Demo knowledge graph seeded (no connector registered)."}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Synchronization failed: {str(exc)}")


@router.get("/graph/audit/{entity_id}")
async def get_node_audit_history(
    entity_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve audit history from PostgreSQL for a given Neo4j node entity_id.
    """
    try:
        history = await graph_service.get_audit_history_for_node(entity_id, db)
        return history
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
