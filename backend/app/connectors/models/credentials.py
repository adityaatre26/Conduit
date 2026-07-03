"""
models/credentials.py
─────────────────────
Pydantic credential schemas — one model per provider,
parameter names match the official documentation exactly.

Adding a new provider = add its class here + register in CRED_MODELS.
"""

from __future__ import annotations
from pydantic import BaseModel, Field, model_validator
from typing import Optional, Literal, get_args, get_origin, Union
from enum import Enum
import types


# ── Supported DB Types ─────────────────────────────────────────────────────────

class DBType(str, Enum):
    POSTGRESQL = "postgresql"
    MYSQL      = "mysql"
    MONGODB    = "mongodb"
    NEO4J      = "neo4j"
    SUPABASE   = "supabase"
    DATABRICKS = "databricks"
    SNOWFLAKE  = "snowflake"
    REDIS      = "redis"
    PINECONE   = "pinecone"
    BIGQUERY   = "bigquery"
    SQLITE     = "sqlite"
    CLICKHOUSE = "clickhouse"


# ── Shared validator mixin ─────────────────────────────────────────────────────

def _is_optional(annotation) -> bool:
    """Return True if the field type is Optional[X] (i.e. Union[X, None])."""
    origin = get_origin(annotation)
    # Python 3.10+ union: X | None  →  types.UnionType
    if origin is Union or (hasattr(types, "UnionType") and isinstance(annotation, types.UnionType)):
        return type(None) in get_args(annotation)
    return False


class StripEmptyOptionalsMixin(BaseModel):
    """
    Before Pydantic validates fields, replace empty-string values with None
    for every field that is declared Optional[...].

    This makes the frontend safe: it can send '' for an un-filled optional
    input instead of omitting the key entirely, without breaking validation.
    """

    @model_validator(mode="before")
    @classmethod
    def strip_empty_strings_on_optional_fields(cls, values: dict) -> dict:
        if not isinstance(values, dict):
            return values
        for field_name, field_info in cls.model_fields.items():
            if field_name in values and values[field_name] == "":
                if _is_optional(field_info.annotation):
                    values[field_name] = None
        return values


# ── Per-Provider Credential Models ─────────────────────────────────────────────

class PostgreSQLCreds(StripEmptyOptionalsMixin):
    """
    Official params: PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD, PGSSLMODE
    Ref: https://www.postgresql.org/docs/current/libpq-envars.html
    """
    host:        str
    port:        int = 5432
    database:    str
    user:        str
    password:    str
    sslmode:     Optional[Literal["disable", "allow", "prefer",
                                   "require", "verify-ca", "verify-full"]] = "prefer"
    sslrootcert: Optional[str] = None
    hostaddr:    Optional[str] = None


class MySQLCreds(StripEmptyOptionalsMixin):
    """
    Official params: Host, Port, Database, Username, Password, SSL
    Ref: https://dev.mysql.com/doc/refman/8.0/en/connecting.html
    """
    host:     str
    port:     int = 3306
    database: str
    user:     str
    password: str
    ssl:      bool = False
    ssl_ca:   Optional[str] = None
    ssl_cert: Optional[str] = None
    ssl_key:  Optional[str] = None


class MongoDBCreds(StripEmptyOptionalsMixin):
    """
    Official params: connection string URI or individual host/port + auth options
    Ref: https://www.mongodb.com/docs/manual/reference/connection-string/
    """
    connection_string:        Optional[str] = None        # mongodb:// URI (takes priority)
    host:                     Optional[str] = None
    port:                     Optional[int] = 27017
    username:                 Optional[str] = None
    password:                 Optional[str] = None
    authentication_source:    str           = "admin"
    authentication_mechanism: Optional[str] = None
    replica_set:              Optional[str] = None
    tls:                      bool          = False

    def resolved_uri(self) -> str:
        if self.connection_string:
            return self.connection_string
        auth = ""
        if self.username:
            auth = f"{self.username}:{self.password}@"
        tls_param = "?tls=true" if self.tls else ""
        return f"mongodb://{auth}{self.host}:{self.port}{tls_param}"


class Neo4jCreds(StripEmptyOptionalsMixin):
    """
    Official params: host/uri, login, password, database, encryption
    Ref: https://neo4j.com/docs/driver-manual/current/client-applications/
    Note: Neo4j calls the username field 'login', not 'user'.
    """
    uri:        Optional[str] = None          # bolt:// or neo4j:// (takes priority)
    host:       Optional[str] = None
    port:       int           = 7687
    login:      str
    password:   str
    database:   str           = "neo4j"
    encryption: bool          = False

    def resolved_uri(self) -> str:
        return self.uri or f"bolt://{self.host}:{self.port}"


class SupabaseCreds(StripEmptyOptionalsMixin):
    """
    Official params: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
    For direct Postgres access: database_host, database_password
    Ref: https://supabase.com/docs/guides/api/api-keys
    SECURITY: service_role_key must NEVER be exposed to the browser.
    """
    supabase_url:              str
    supabase_service_role_key: str
    database_host:             Optional[str] = None
    database_password:         Optional[str] = None
    database_port:             int           = 5432
    database_name:             str           = "postgres"


class DatabricksCreds(StripEmptyOptionalsMixin):
    """
    Official params: server_hostname, http_path, access_token, catalog, schema
    Ref: https://docs.databricks.com/integrations/jdbc-odbc-bi.html
    """
    host:         str
    http_path:    str
    access_token: str
    catalog:      Optional[str] = None
    schema_name:  Optional[str] = None


class SnowflakeCreds(StripEmptyOptionalsMixin):
    """
    Official params: account, user, password, warehouse, database, schema, role
    Ref: https://docs.snowflake.com/en/developer-guide/python-connector/python-connector-connect
    """
    account:     str
    user:        str
    password:    str
    warehouse:   Optional[str] = None
    database:    Optional[str] = None
    schema_name: Optional[str] = None
    role:        Optional[str] = None


class RedisCreds(StripEmptyOptionalsMixin):
    """
    Official params: redis:// URI, or host/port/password/username/db
    Ref: https://redis.io/docs/connect/clients/python/
    """
    url:      Optional[str] = None
    host:     Optional[str] = None
    port:     int           = 6379
    password: Optional[str] = None
    username: Optional[str] = None
    db:       int           = 0

    def resolved_url(self) -> str:
        if self.url:
            return self.url
        auth = ""
        if self.username and self.password:
            auth = f"{self.username}:{self.password}@"
        elif self.password:
            auth = f":{self.password}@"
        return f"redis://{auth}{self.host or 'localhost'}:{self.port}/{self.db}"


class PineconeCreds(StripEmptyOptionalsMixin):
    """
    Official params: api_key, index_name, environment (legacy), namespace
    Ref: https://docs.pinecone.io/docs/quickstart
    """
    api_key:     str
    index_name:  Optional[str] = None
    environment: Optional[str] = None
    project_id:  Optional[str] = None
    namespace:   Optional[str] = None


class BigQueryCreds(StripEmptyOptionalsMixin):
    """
    Official params: project_id, service account JSON, dataset, location
    Ref: https://cloud.google.com/bigquery/docs/authentication/service-account-file
    """
    project_id:           str
    service_account_json: str
    dataset:              Optional[str] = None
    location:             str           = "US"


class SQLiteCreds(StripEmptyOptionalsMixin):
    """SQLite is file-based — only needs a file path."""
    file_path: str


class ClickHouseCreds(StripEmptyOptionalsMixin):
    """
    Official params: host, port, database, username, password, TLS
    Ref: https://clickhouse.com/docs/en/integrations/python
    """
    host:     str
    port:     int          = 8123
    database: str          = "default"
    username: str          = "default"
    password: Optional[str] = None
    tls:      bool         = False


# ── Request / Response DTOs ────────────────────────────────────────────────────

class ConnectionRequest(BaseModel):
    conn_id:      str  = Field(..., min_length=1, max_length=64,
                               pattern=r"^[a-zA-Z0-9_-]+$",
                               description="Unique ID — letters, numbers, hyphens, underscores")
    db_type:      DBType
    credentials:  dict
    read_only:    bool          = True
    display_name: Optional[str] = None


class QueryRequest(BaseModel):
    conn_id: str
    query:   str
    params:  Optional[dict] = None
    limit:   int             = Field(1000, ge=1, le=10_000)


# ── Credential Validator Registry ──────────────────────────────────────────────

CRED_MODELS: dict = {
    "postgresql": PostgreSQLCreds,
    "postgres":   PostgreSQLCreds,
    "mysql":      MySQLCreds,
    "mongodb":    MongoDBCreds,
    "neo4j":      Neo4jCreds,
    "supabase":   SupabaseCreds,
    "databricks": DatabricksCreds,
    "snowflake":  SnowflakeCreds,
    "redis":      RedisCreds,
    "pinecone":   PineconeCreds,
    "bigquery":   BigQueryCreds,
    "sqlite":     SQLiteCreds,
    "clickhouse": ClickHouseCreds,
}


def validate_credentials(db_type: str, raw: dict) -> BaseModel:
    """Validate a raw credentials dict against the provider's Pydantic model.
    Empty strings on Optional fields are automatically coerced to None by
    StripEmptyOptionalsMixin before field validation runs."""
    model = CRED_MODELS.get(db_type.lower())
    if not model:
        raise ValueError(
            f"Unknown provider '{db_type}'. "
            f"Supported: {list(CRED_MODELS.keys())}"
        )
    return model(**raw)
