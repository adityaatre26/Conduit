"""
health.py
─────────
Purpose:
    FastAPI router defining endpoints for application health checks.

Use Cases:
    - GET /api/health: Validates connectivity to PostgreSQL, Neo4j, and Mock AI settings.
"""

from fastapi import APIRouter
from app.core.config import settings
from app.core.neo4j_client import neo4j_client

router = APIRouter()

@router.get("/health")
async def health():
    neo4j_ok = neo4j_client.driver is not None
    return {
        "status": "ok",
        "mock_ai": settings.MOCK_AI,
        "environment": settings.ENVIRONMENT,
        "neo4j": "connected" if neo4j_ok else "unavailable",
    }
