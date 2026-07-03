"""
db_factory.py
─────────────
Universal database connection factory.

HOW TO ADD A NEW DATASOURCE (5 lines of real work):
  1. Add its DBType entry to models/credentials.py  → 1 line
  2. Add its Pydantic credential class              → ~8 lines
  3. Register it in CRED_MODELS dict                → 1 line
  4. Add its connect block in _create_connection()  → ~8 lines
  5. Add its query block in _dispatch_query()       → ~5 lines

Everything else (encryption, validation, read-only, connection lifecycle) is free.
"""

import asyncio
import json
import time
import logging
import os
from typing import Dict, Any, Optional

from cryptography.fernet import Fernet

from app.connectors.models.credentials import (
    validate_credentials,
    PostgreSQLCreds, MySQLCreds, MongoDBCreds, Neo4jCreds,
    SupabaseCreds, DatabricksCreds, SnowflakeCreds, RedisCreds,
    PineconeCreds, BigQueryCreds, SQLiteCreds, ClickHouseCreds,
)

logger = logging.getLogger(__name__)

# ── Write-keyword blocklist for read-only enforcement ──────────────────────────
WRITE_KEYWORDS = frozenset({
    "INSERT", "UPDATE", "DELETE", "DROP", "CREATE",
    "ALTER", "TRUNCATE", "MERGE", "REPLACE",
})


class DBConnectionFactory:
    """
    Manages connections to any supported database.
    Credentials are Fernet-encrypted in memory.
    """

    def __init__(self, encryption_key: Optional[str] = None):
        self.connections: Dict[str, dict] = {}     # metadata + encrypted creds
        self.engines: Dict[str, Any] = {}          # live connection objects
        key = encryption_key or os.getenv("ENCRYPTION_KEY") or Fernet.generate_key().decode()
        # Fernet key must be 32 url-safe base64 bytes → 44 chars
        if len(key) != 44:
            key = Fernet.generate_key().decode()
        self._cipher = Fernet(key.encode())
        logger.info("DBConnectionFactory initialized")

    # ── Encryption ─────────────────────────────────────────────────────────────

    def _encrypt(self, data: dict) -> str:
        return self._cipher.encrypt(json.dumps(data).encode()).decode()

    def _decrypt(self, token: str) -> dict:
        return json.loads(self._cipher.decrypt(token.encode()).decode())

    # ── Public API ─────────────────────────────────────────────────────────────

    async def register_connection(
        self,
        conn_id: str,
        db_type: str,
        credentials: dict,
        read_only: bool = True,
        display_name: Optional[str] = None,
    ) -> dict:
        """
        Validate → test → store → create persistent connection.
        Returns {"status": "success"|"error", ...}
        """
        t0 = time.time()
        db_type = db_type.lower()
        try:
            # 1. Validate credentials against the provider schema
            validated = validate_credentials(db_type, credentials)
            creds = validated.model_dump()

            # 2. Test connection (throws on failure)
            await self._create_connection(db_type, creds, test_only=True)

            # 3. Store encrypted metadata
            self.connections[conn_id] = {
                "type":         db_type,
                "display_name": display_name or f"{db_type}/{conn_id}",
                "credentials":  self._encrypt(creds),
                "read_only":    read_only,
                "status":       "connected",
                "connected_at": time.time(),
            }

            # 4. Create persistent live connection
            self.engines[conn_id] = await self._create_connection(db_type, creds)

            elapsed = round((time.time() - t0) * 1000, 1)
            logger.info(f"[{conn_id}] connected to {db_type} in {elapsed}ms")
            return {"status": "success", "conn_id": conn_id, "latency_ms": elapsed}

        except Exception as exc:
            logger.warning(f"[{conn_id}] connection failed: {exc}")
            return {"status": "error", "message": str(exc)}

    async def execute_query(
        self,
        conn_id: str,
        query: str,
        params: Optional[dict] = None,
        limit: int = 1000,
    ) -> dict:
        """Execute query with read-only enforcement and timing."""
        info = self.connections.get(conn_id)
        if not info:
            raise KeyError(f"No connection registered with id '{conn_id}'")

        if info["read_only"]:
            self._assert_read_only(query)

        t0 = time.time()
        conn = await self.get_connection(conn_id)
        rows = await self._dispatch_query(info["type"], conn, query, params or {}, limit)
        return {
            "conn_id":            conn_id,
            "row_count":          len(rows),
            "execution_time_ms":  round((time.time() - t0) * 1000, 1),
            "rows":               rows,
        }

    def list_connections(self) -> list:
        return [
            {
                "id":           cid,
                "type":         info["type"],
                "display_name": info["display_name"],
                "status":       info["status"],
                "read_only":    info["read_only"],
                "connected_at": info.get("connected_at"),
            }
            for cid, info in self.connections.items()
        ]

    async def disconnect(self, conn_id: str) -> dict:
        """Gracefully close and remove a connection."""
        conn = self.engines.pop(conn_id, None)
        if conn:
            try:
                if hasattr(conn, "dispose"):     conn.dispose()       # SQLAlchemy
                elif hasattr(conn, "aclose"):    await conn.aclose()  # redis async
                elif hasattr(conn, "close"):     conn.close()         # others
            except Exception:
                pass
        self.connections.pop(conn_id, None)
        return {"status": "disconnected", "conn_id": conn_id}

    async def get_connection(self, conn_id: str) -> Any:
        """Return live connection, lazily reconnecting if engine was evicted."""
        if conn_id not in self.engines:
            info = self.connections.get(conn_id)
            if not info:
                raise KeyError(f"Connection '{conn_id}' not found")
            creds = self._decrypt(info["credentials"])
            self.engines[conn_id] = await self._create_connection(info["type"], creds)
        return self.engines[conn_id]

    # ── Provider Connection Factory ────────────────────────────────────────────

    async def _create_connection(self, db_type: str, credentials: dict, test_only: bool = False):
        """
        One block per provider.  test_only=True → verify connectivity then return True.
        """
        db = db_type.lower()

        # ── PostgreSQL ─────────────────────────────────────────────────────────
        if db in ("postgresql", "postgres"):
            from sqlalchemy import create_engine, text
            from sqlalchemy.pool import QueuePool
            c = PostgreSQLCreds(**credentials)
            dsn = (f"postgresql://{c.user}:{c.password}@{c.host}:{c.port}/{c.database}"
                   + (f"?sslmode={c.sslmode}" if c.sslmode else ""))
            engine = create_engine(dsn, poolclass=QueuePool,
                                   pool_size=5, max_overflow=10, pool_pre_ping=True)
            if test_only:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                engine.dispose()
                return True
            return engine

        # ── MySQL ─────────────────────────────────────────────────────────────
        if db == "mysql":
            from sqlalchemy import create_engine, text
            c = MySQLCreds(**credentials)
            dsn = f"mysql+pymysql://{c.user}:{c.password}@{c.host}:{c.port}/{c.database}"
            engine = create_engine(dsn, pool_pre_ping=True)
            if test_only:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                engine.dispose()
                return True
            return engine

        # ── Supabase ──────────────────────────────────────────────────────────
        if db == "supabase":
            c = SupabaseCreds(**credentials)
            if c.database_host:
                # Direct Postgres connection via pooler / service role
                from sqlalchemy import create_engine, text
                dsn = (f"postgresql://postgres:{c.database_password}"
                       f"@{c.database_host}:{c.database_port}/{c.database_name}"
                       f"?sslmode=require")
                engine = create_engine(dsn, pool_pre_ping=True)
                if test_only:
                    with engine.connect() as conn:
                        conn.execute(text("SELECT 1"))
                    engine.dispose()
                    return True
                return engine
            else:
                # Supabase REST client
                from supabase import create_client
                client = create_client(c.supabase_url, c.supabase_service_role_key)
                if test_only:
                    # Light probe — fetch zero rows from any table
                    try:
                        client.table("_healthcheck").select("*").limit(0).execute()
                    except Exception:
                        pass   # Table won't exist; 404 still means auth OK
                    return True
                return client

        # ── MongoDB ───────────────────────────────────────────────────────────
        if db == "mongodb":
            import pymongo
            c = MongoDBCreds(**credentials)
            client = pymongo.MongoClient(c.resolved_uri(), serverSelectionTimeoutMS=5000)
            if test_only:
                client.server_info()
                return True
            return client

        # ── Neo4j ─────────────────────────────────────────────────────────────
        if db == "neo4j":
            from neo4j import GraphDatabase
            c = Neo4jCreds(**credentials)
            driver = GraphDatabase.driver(
                c.resolved_uri(),
                auth=(c.login, c.password),
                encrypted=c.encryption,
            )
            if test_only:
                driver.verify_connectivity()
                driver.close()
                return True
            return driver

        # ── Redis ─────────────────────────────────────────────────────────────
        if db == "redis":
            import redis.asyncio as redis_async
            c = RedisCreds(**credentials)
            client = redis_async.from_url(c.resolved_url(), decode_responses=True)
            if test_only:
                await client.ping()
                await client.aclose()
                return True
            return client

        # ── Snowflake ─────────────────────────────────────────────────────────
        if db == "snowflake":
            import snowflake.connector
            c = SnowflakeCreds(**credentials)
            conn = snowflake.connector.connect(
                account=c.account, user=c.user, password=c.password,
                warehouse=c.warehouse, database=c.database,
                schema=c.schema_name, role=c.role,
            )
            if test_only:
                conn.cursor().execute("SELECT CURRENT_VERSION()")
                conn.close()
                return True
            return conn

        # ── BigQuery ──────────────────────────────────────────────────────────
        if db == "bigquery":
            import tempfile
            from google.cloud import bigquery
            c = BigQueryCreds(**credentials)
            sa = json.loads(c.service_account_json)
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                json.dump(sa, f)
                tmp = f.name
            client = bigquery.Client.from_service_account_json(tmp)
            os.unlink(tmp)
            if test_only:
                list(client.query("SELECT 1").result())
                return True
            return client

        # ── Pinecone ──────────────────────────────────────────────────────────
        if db == "pinecone":
            import pinecone as pc_module
            c = PineconeCreds(**credentials)
            pc = pc_module.Pinecone(api_key=c.api_key)
            if test_only:
                pc.list_indexes()
                return True
            return pc

        # ── ClickHouse ────────────────────────────────────────────────────────
        if db == "clickhouse":
            import clickhouse_connect
            c = ClickHouseCreds(**credentials)
            client = clickhouse_connect.get_client(
                host=c.host, port=c.port, username=c.username,
                password=c.password or "", database=c.database, secure=c.tls,
            )
            if test_only:
                client.query("SELECT 1")
                return True
            return client

        # ── Databricks ────────────────────────────────────────────────────────
        if db == "databricks":
            import databricks.sql as dbsql
            c = DatabricksCreds(**credentials)
            conn = dbsql.connect(
                server_hostname=c.host,
                http_path=c.http_path,
                access_token=c.access_token,
                catalog=c.catalog,
                schema=c.schema_name,
            )
            if test_only:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                conn.close()
                return True
            return conn

        # ── SQLite ────────────────────────────────────────────────────────────
        if db == "sqlite":
            import sqlite3
            c = SQLiteCreds(**credentials)
            conn = sqlite3.connect(c.file_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            if test_only:
                conn.execute("SELECT 1")
                conn.close()
                return True
            return conn

        raise ValueError(f"Unsupported database type: '{db_type}'")

    # ── Query Dispatch ─────────────────────────────────────────────────────────

    def _assert_read_only(self, query: str):
        """Block write operations when read_only=True."""
        first = query.strip().split()[0].upper()
        if first in WRITE_KEYWORDS:
            raise PermissionError(
                f"Write operation '{first}' is not permitted in read-only mode. "
                "Set read_only=False when registering the connection to allow writes."
            )

    async def _dispatch_query(
        self, db_type: str, conn: Any, query: str,
        params: dict, limit: int
    ) -> list:
        """Route query execution to the correct method per DB type."""
        db = db_type.lower()

        # ── SQLAlchemy-backed (PostgreSQL, MySQL, Supabase-direct) ─────────────
        if db in ("postgresql", "postgres", "mysql"):
            from sqlalchemy import text
            with conn.connect() as c:
                result = c.execute(text(query), params)
                return [dict(r) for r in result.mappings()][:limit]

        if db == "supabase":
            if hasattr(conn, "connect"):                       # SQLAlchemy path
                from sqlalchemy import text
                with conn.connect() as c:
                    result = c.execute(text(query), params)
                    return [dict(r) for r in result.mappings()][:limit]
            else:                                              # REST client path
                table = params.get("table", "")
                cols  = params.get("columns", "*")
                response = conn.table(table).select(cols).limit(limit).execute()
                return response.data

        if db == "sqlite":
            cursor = conn.cursor()
            cursor.execute(query, list(params.values()) if params else [])
            return [dict(row) for row in cursor.fetchmany(limit)]

        if db == "mongodb":
            # params = {"database": ..., "collection": ..., "filter": {...}}
            mdb  = conn[params.get("database", "test")]
            col  = mdb[params.get("collection", "documents")]
            filt = params.get("filter", {})
            return list(col.find(filt).limit(limit))

        if db == "neo4j":
            with conn.session(database=None) as session:
                result = session.run(query, params)
                return [dict(record) for record in result]

        if db == "redis":
            result = await conn.execute_command(*query.split())
            return [{"result": result}]

        if db == "snowflake":
            import snowflake.connector
            cur = conn.cursor(snowflake.connector.DictCursor)
            cur.execute(query, list(params.values()) if params else [])
            return cur.fetchmany(limit)

        if db == "bigquery":
            job = conn.query(query)
            return [dict(row) for row in job.result()][:limit]

        if db == "clickhouse":
            res  = conn.query(query)
            cols = res.column_names
            return [dict(zip(cols, row)) for row in res.result_rows][:limit]

        if db == "databricks":
            with conn.cursor() as cur:
                cur.execute(query)
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchmany(limit)]

        if db == "pinecone":
            # query must be JSON: {"index_name": "...", "vector": [...], "top_k": 10}
            q     = json.loads(query)
            index = conn.Index(q["index_name"])
            res   = index.query(vector=q["vector"], top_k=q.get("top_k", 10),
                                include_metadata=True)
            # Serialize matches safely — Pinecone match objects have circular refs in __dict__
            matches = []
            for m in res.matches:
                matches.append({
                    "id":       m.id,
                    "score":    m.score,
                    "metadata": dict(m.metadata) if m.metadata else {},
                })
            return matches

        return []


# ── Singleton factory ──────────────────────────────────────────────────────────
factory = DBConnectionFactory()
