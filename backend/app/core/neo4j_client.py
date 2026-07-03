"""
neo4j_client.py
───────────────
Purpose:
    Provides an asynchronous client wrapper for the Neo4j Graph Database.

Use Cases:
    - Verifies Neo4j database connectivity at startup.
    - Manages graph connection sessions and executes Cypher queries.
"""

import asyncio
import logging
from typing import Any
from neo4j import AsyncGraphDatabase
from app.core.config import settings

logger = logging.getLogger("conduit.neo4j")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False


class Neo4jClient:
    def __init__(self) -> None:
        self.driver = None
        self._database: str | None = None

    async def connect(self) -> None:
        if self.driver is not None:
            return

        uri = settings.NEO4J_URI
        user = settings.NEO4J_USER
        password = settings.NEO4J_PASSWORD
        self._database = settings.NEO4J_DATABASE or None

        logger.info(f"Connecting to Neo4j at {uri} (database={self._database or 'default'})...")
        try:
            self.driver = AsyncGraphDatabase.driver(
                uri,
                auth=(user, password),
                max_connection_lifetime=1800.0,
                liveness_check_timeout=30.0,
            )
            await self.driver.verify_connectivity()
            logger.info("Connected to Neo4j successfully!")
            await self.init_schema()
        except Exception as exc:
            logger.error(f"Failed to connect to Neo4j: {exc}")
            self.driver = None

    async def init_schema(self) -> None:
        if self.driver is None:
            return
        try:
            async with self.driver.session(database=self._database) as session:
                await asyncio.wait_for(
                    session.run(
                        "CREATE CONSTRAINT uq_graph_node_entity_id IF NOT EXISTS "
                        "FOR (n:GraphNode) REQUIRE n.entity_id IS UNIQUE"
                    ),
                    timeout=30.0,
                )
        except Exception as exc:
            logger.warning(f"Neo4j schema init skipped: {exc}")

    async def close(self) -> None:
        if self.driver is not None:
            logger.info("Closing Neo4j connection...")
            await self.driver.close()
            self.driver = None
            logger.info("Neo4j connection closed.")

    def get_driver(self) -> Any:
        if self.driver is None:
            raise RuntimeError("Neo4j driver is not initialized. Call connect() first.")
        return self.driver

    async def execute_query(self, query: str, parameters: dict = None) -> list:
        if self.driver is None:
            raise RuntimeError("Neo4j driver is not initialized.")
        async with self.driver.session(database=self._database) as session:
            result = await session.run(query, parameters or {})
            records = await result.data()
            return records


neo4j_client = Neo4jClient()
