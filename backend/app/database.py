"""
database.py
───────────
Purpose:
    Manages the SQLAlchemy asynchronous engine and session factory 
    for the primary PostgreSQL warehouse database.

Use Cases:
    - Provides a reusable database engine (`engine`) and session local (`AsyncSessionLocal`) 
      to interact with the database asynchronously.
    - Yields database sessions via `get_db()` dependency injection in FastAPI routers.
"""

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.core.config import settings

engine = create_async_engine(settings.WAREHOUSE_DB_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

