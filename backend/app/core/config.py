"""
config.py
─────────
Purpose:
    Loads and validates system environment variables using Pydantic BaseSettings.

Use Cases:
    - Provides global configuration variables (GROQ_API_KEY, WAREHOUSE_DB_URL, NEO4J credentials, etc.).
"""

from pydantic_settings import BaseSettings
from pydantic import model_validator
from typing import Optional

class Settings(BaseSettings):
    GROQ_API_KEY: str
    WAREHOUSE_DB_URL: str
    SOURCE_DB_URL: str
    ENVIRONMENT: str = "development"
    MOCK_AI: bool = False
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_USERNAME: Optional[str] = None
    NEO4J_PASSWORD: str = "conduit_graph_2026"
    # Neo4j Aura: database name (same as instance ID on Aura)
    NEO4J_DATABASE: Optional[str] = None

    @model_validator(mode="after")
    def resolve_neo4j_user(self):
        if self.NEO4J_USERNAME and (self.NEO4J_USER == "neo4j" or not self.NEO4J_USER):
            self.NEO4J_USER = self.NEO4J_USERNAME
        return self

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
