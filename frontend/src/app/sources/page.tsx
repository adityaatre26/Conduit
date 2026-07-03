"use client";

import { useEffect, useState, useCallback } from "react";
import clsx from "clsx";
import { registerConnector, listProviders, listConnections, disconnectConnector, syncConnectorGraph } from "@/lib/api";
import type { ConnectorProvider, ConnectorConnection } from "@/lib/types";
import { PageHeader } from "@/components/page-header";
import { StatusDot } from "@/components/badges";

// ── Provider config ─────────────────────────────────────────────────────────

const PROVIDER_ICONS: Record<string, string> = {
  postgresql: "🐘", mysql: "🐬", mongodb: "🍃", neo4j: "🔵",
  supabase: "⚡", databricks: "🧱", snowflake: "❄️", redis: "🔴",
  pinecone: "🌲", bigquery: "📊", sqlite: "📁", clickhouse: "🖱️",
};

// Per-provider set of fields that are truly Optional[...] = None in the Pydantic model.
// These are SKIPPED when the user leaves them blank (empty string → omit → Pydantic uses None default).
// Fields NOT in this set are sent even if blank so the backend can return a proper validation error.
const PROVIDER_OPTIONAL_FIELDS: Record<string, Set<string>> = {
  postgresql:  new Set(["sslmode", "sslrootcert", "hostaddr"]),
  mysql:       new Set(["ssl_ca", "ssl_cert", "ssl_key"]),
  mongodb:     new Set(["connection_string", "host", "port", "username", "password",
                        "authentication_mechanism", "replica_set"]),
  neo4j:       new Set(["uri", "host"]),
  supabase:    new Set(["database_host", "database_password"]),
  databricks:  new Set(["catalog", "schema_name"]),
  snowflake:   new Set(["warehouse", "database", "schema_name", "role"]),
  redis:       new Set(["url", "host", "password", "username"]),
  pinecone:    new Set(["index_name", "environment", "project_id", "namespace"]),
  bigquery:    new Set(["dataset"]),
  clickhouse:  new Set(["password"]),
  sqlite:      new Set(),
};

const FIELD_INPUT_TYPE: Record<string, "password" | "number" | "textarea" | "text"> = {
  password: "password",
  database_password: "password",
  service_account_json: "textarea",
  access_token: "password",
  supabase_service_role_key: "password",
  api_key: "password",
  port: "number",
  database_port: "number",
  db: "number",
};

const FIELD_PLACEHOLDERS: Record<string, string> = {
  host: "e.g. db.example.com",
  port: "5432",
  database: "mydb",
  user: "admin",
  login: "neo4j",
  password: "••••••••",
  uri: "bolt://localhost:7687",
  connection_string: "mongodb://user:pass@host:27017",
  supabase_url: "https://xxxx.supabase.co",
  supabase_service_role_key: "eyJ...",
  database_host: "db.xxxx.supabase.co",
  http_path: "/sql/1.0/warehouses/abc123",
  access_token: "dapi...",
  account: "myorg.us-east-1",
  file_path: "/data/mydb.sqlite",
  api_key: "pk-...",
  index_name: "my-index",
  environment: "us-east-1-gcp (legacy serverless)",
  project_id: "my-gcp-project",
  namespace: "default",
  url: "redis://:password@host:6379/0",
  dataset: "my_dataset",
  warehouse: "COMPUTE_WH",
  schema_name: "PUBLIC",
  role: "SYSADMIN",
  catalog: "main",
  replica_set: "rs0",
  sslmode: "prefer",
  username: "default",
};

// ── Connection Row ──────────────────────────────────────────────────────────

function ConnectionRow({
  conn, onDisconnect, onSyncGraph, syncingId,
}: {
  conn: ConnectorConnection;
  onDisconnect: (id: string) => void;
  onSyncGraph: (id: string) => void;
  syncingId: string | null;
}) {
  const [confirming, setConfirming] = useState(false);
  return (
    <tr>
      <td>
        <div className="flex items-center gap-2">
          <span className="text-base">{PROVIDER_ICONS[conn.type] ?? "🔌"}</span>
          <div>
            <div className="font-medium text-sm">{conn.display_name}</div>
            <div className="font-mono text-2xs text-fg-muted">{conn.id}</div>
          </div>
        </div>
      </td>
      <td className="font-mono text-xs text-fg-muted uppercase">{conn.type}</td>
      <td>
        <span className="inline-flex items-center gap-1.5 text-sm">
          <StatusDot status={conn.status === "connected" ? "CONNECTED" : "UNREACHABLE"} />
          {conn.status === "connected" ? "Connected" : "Disconnected"}
        </span>
      </td>
      <td className="text-2xs">
        {conn.read_only
          ? <span className="badge bg-bg-subtle border-border text-fg-muted">read-only</span>
          : <span className="badge bg-warning-bg border-warning-border text-warning">read-write</span>}
      </td>
      <td>
        <div className="flex items-center gap-2 justify-end">
          <button
            onClick={() => onSyncGraph(conn.id)}
            disabled={syncingId === conn.id}
            className="btn-ghost h-7 px-2 text-2xs"
          >
            {syncingId === conn.id ? "Syncing…" : "Sync Graph"}
          </button>
          {confirming ? (
            <div className="flex items-center gap-1.5">
              <span className="text-2xs text-danger">Disconnect?</span>
              <button onClick={() => { onDisconnect(conn.id); setConfirming(false); }} className="btn-ghost h-7 px-2 text-2xs text-danger">Yes</button>
              <button onClick={() => setConfirming(false)} className="btn-ghost h-7 px-2 text-2xs">No</button>
            </div>
          ) : (
            <button onClick={() => setConfirming(true)} className="btn-ghost h-7 px-2 text-2xs text-danger">Disconnect</button>
          )}
        </div>
      </td>
    </tr>
  );
}

// ── Connect Modal ───────────────────────────────────────────────────────────

function ConnectModal({
  providers, onClose, onSuccess,
}: {
  providers: ConnectorProvider[];
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [selectedType, setSelectedType] = useState("");
  const [connId, setConnId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [readOnly, setReadOnly] = useState(true);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const selectedProvider = providers.find((p) => p.type === selectedType);
  const optionalForProvider = PROVIDER_OPTIONAL_FIELDS[selectedType] ?? new Set<string>();

  const handleTypeChange = (type: string) => {
    setSelectedType(type);
    setFields({});
    setError(null);
    if (!connId) setConnId(`${type}-1`);
    if (!displayName) setDisplayName(`${type} connection`);
  };

  const handleSubmit = async () => {
    if (!selectedType || !connId) { setError("Provider and Connection ID are required."); return; }
    setSubmitting(true);
    setError(null);
    try {
      const optFields = PROVIDER_OPTIONAL_FIELDS[selectedType] ?? new Set<string>();
      const creds: Record<string, unknown> = {};

      for (const [key, val] of Object.entries(fields)) {
        // Skip optional fields left blank — let Pydantic use the None default
        if (val === "" && optFields.has(key)) continue;

        const inputType = FIELD_INPUT_TYPE[key];
        if (inputType === "number") {
          // Only send if non-empty; optional numbers left blank are also skipped
          if (val !== "") creds[key] = Number(val);
          else if (!optFields.has(key)) creds[key] = val; // required number, let backend error
        } else {
          creds[key] = val;
        }
      }

      await registerConnector({
        conn_id: connId,
        db_type: selectedType,
        credentials: creds,
        read_only: readOnly,
        display_name: displayName || undefined,
      });
      setSuccess(true);
      setTimeout(() => { onSuccess(); onClose(); }, 1200);
    } catch (e: any) {
      setError(e.message ?? String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm anim-fade">
      <div className="bg-bg border border-border rounded-xl shadow-2xl w-full max-w-lg max-h-[90vh] flex flex-col overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border shrink-0">
          <div>
            <h2 className="text-sm font-semibold">Connect a database</h2>
            <p className="text-2xs text-fg-muted mt-0.5">Credentials encrypted in memory · never logged</p>
          </div>
          <button onClick={onClose} className="btn-ghost h-8 w-8 p-0 text-xl leading-none">×</button>
        </div>

        {/* Body */}
        <div className="overflow-y-auto flex-1 px-6 py-5 space-y-5">
          {success ? (
            <div className="flex flex-col items-center justify-center py-10 gap-3 text-success">
              <svg className="w-10 h-10" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <div className="text-sm font-semibold">Connection registered!</div>
            </div>
          ) : (
            <>
              {/* Provider grid */}
              <div>
                <label className="label">Database provider</label>
                <div className="grid grid-cols-4 gap-2 mt-1">
                  {providers.map((p) => (
                    <button
                      key={p.type}
                      type="button"
                      onClick={() => handleTypeChange(p.type)}
                      className={clsx(
                        "flex flex-col items-center gap-1 p-2.5 rounded-lg border-2 text-center transition-all",
                        selectedType === p.type ? "border-fg bg-bg-subtle" : "border-border hover:border-fg-subtle",
                      )}
                    >
                      <span className="text-lg">{PROVIDER_ICONS[p.type] ?? "🔌"}</span>
                      <span className="text-[10px] font-mono font-medium leading-tight">{p.type}</span>
                    </button>
                  ))}
                </div>
              </div>

              {selectedProvider && (
                <>
                  {/* Connection ID + display name */}
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="label">Connection ID</label>
                      <input
                        className="input font-mono"
                        value={connId}
                        onChange={(e) => setConnId(e.target.value.replace(/[^a-zA-Z0-9_-]/g, ""))}
                        placeholder={`e.g. ${selectedType}-prod`}
                      />
                      <p className="text-2xs text-fg-muted mt-1">Letters, numbers, - _ only</p>
                    </div>
                    <div>
                      <label className="label">Display name</label>
                      <input
                        className="input"
                        value={displayName}
                        onChange={(e) => setDisplayName(e.target.value)}
                        placeholder="e.g. Production DB"
                      />
                    </div>
                  </div>

                  {/* Credential fields */}
                  <div>
                    <label className="label mb-2">
                      Credentials
                      <span className="ml-1.5 text-2xs text-fg-muted font-normal normal-case">— {selectedProvider.type}</span>
                    </label>
                    <div className="space-y-3">
                      {selectedProvider.credential_fields.map((field) => {
                        const isOptional = optionalForProvider.has(field);
                        const inputType = FIELD_INPUT_TYPE[field] ?? "text";
                        return (
                          <div key={field}>
                            <label className="text-2xs font-medium text-fg-muted uppercase tracking-wider block mb-1">
                              {field.replace(/_/g, " ")}
                              {isOptional && (
                                <span className="ml-1.5 normal-case text-fg-subtle font-normal tracking-normal">optional</span>
                              )}
                            </label>
                            {inputType === "textarea" ? (
                              <textarea
                                className="input font-mono text-xs min-h-20 py-2 h-auto"
                                placeholder='{"type": "service_account", ...}'
                                value={fields[field] ?? ""}
                                onChange={(e) => setFields((p) => ({ ...p, [field]: e.target.value }))}
                              />
                            ) : (
                              <input
                                type={inputType === "password" ? "password" : inputType === "number" ? "number" : "text"}
                                className="input font-mono"
                                placeholder={FIELD_PLACEHOLDERS[field] ?? ""}
                                value={fields[field] ?? ""}
                                onChange={(e) => setFields((p) => ({ ...p, [field]: e.target.value }))}
                              />
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  {/* Read-only toggle */}
                  <div className="flex items-center gap-3 p-3 rounded-lg bg-bg-subtle border border-border">
                    <button
                      type="button"
                      onClick={() => setReadOnly((v) => !v)}
                      className={clsx(
                        "relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors",
                        readOnly ? "bg-fg" : "bg-border",
                      )}
                    >
                      <span className={clsx(
                        "inline-block h-4 w-4 rounded-full bg-white shadow transition-transform",
                        readOnly ? "translate-x-4" : "translate-x-0",
                      )} />
                    </button>
                    <div>
                      <div className="text-xs font-medium">Read-only mode</div>
                      <div className="text-2xs text-fg-muted">
                        {readOnly ? "INSERT / UPDATE / DELETE blocked" : "All queries permitted — use with caution"}
                      </div>
                    </div>
                  </div>

                  {error && (
                    <div className="rounded-md border border-danger-border bg-danger-bg p-3 text-sm text-danger break-words">
                      {error}
                    </div>
                  )}
                </>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        {!success && (
          <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-border shrink-0">
            <button onClick={onClose} className="btn-secondary">Cancel</button>
            <button
              onClick={handleSubmit}
              disabled={!selectedType || !connId || submitting}
              className="btn-primary"
            >
              {submitting ? "Testing connection…" : "Connect"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main Page ───────────────────────────────────────────────────────────────

export default function SourcesPage() {
  const [connections, setConnections] = useState<ConnectorConnection[] | null>(null);
  const [providers, setProviders] = useState<ConnectorProvider[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [conns, provs] = await Promise.all([listConnections(), listProviders()]);
      setConnections(conns);
      setProviders(provs);
    } catch (e: any) {
      setError(e.message ?? String(e));
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleDisconnect = async (id: string) => {
    try { await disconnectConnector(id); await load(); }
    catch (e: any) { setError(e.message ?? String(e)); }
  };

  const handleSyncGraph = async (id: string) => {
    setSyncingId(id); setSyncMsg(null);
    try {
      await syncConnectorGraph(id);
      setSyncMsg(`Schema synced from "${id}" → knowledge graph`);
      await load();
    } catch (e: any) {
      setError(e.message ?? String(e));
    } finally {
      setSyncingId(null);
      setTimeout(() => setSyncMsg(null), 4000);
    }
  };

  const connected = connections?.filter((c) => c.status === "connected").length ?? 0;
  const total = connections?.length ?? 0;

  return (
    <div className="space-y-6 anim-fade">
      <PageHeader
        title="Sources"
        description="Register external database connections. Credentials are encrypted in memory. Use Sync Graph to publish table schemas into the knowledge graph for AI-assisted ingest."
        actions={
          <button onClick={() => setShowModal(true)} className="btn-primary">+ Connect database</button>
        }
      />

      {error && (
        <div className="card border-danger-border bg-danger-bg p-4 text-sm text-danger flex items-center justify-between gap-4">
          <span className="break-words">{error}</span>
          <button onClick={() => setError(null)} className="shrink-0 text-danger hover:opacity-70 text-lg leading-none">×</button>
        </div>
      )}
      {syncMsg && (
        <div className="card border-success-border bg-success-bg p-3 text-sm text-success">✓ {syncMsg}</div>
      )}

      <div className="grid grid-cols-3 gap-4">
        <div className="card p-4">
          <div className="text-2xs font-medium uppercase tracking-wider text-fg-muted">Total</div>
          <div className="mt-2 text-2xl font-semibold tabular-nums">{connections === null ? "—" : total}</div>
        </div>
        <div className="card p-4">
          <div className="text-2xs font-medium uppercase tracking-wider text-fg-muted">Connected</div>
          <div className="mt-2 text-2xl font-semibold tabular-nums text-success">{connections === null ? "—" : connected}</div>
        </div>
        <div className="card p-4">
          <div className="text-2xs font-medium uppercase tracking-wider text-fg-muted">Disconnected</div>
          <div className="mt-2 text-2xl font-semibold tabular-nums text-danger">{connections === null ? "—" : total - connected}</div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-header">
          <h3 className="text-sm font-semibold">Registered connections</h3>
          <button onClick={() => setShowModal(true)} className="btn-ghost h-7 px-2 text-2xs">+ Add connection</button>
        </div>
        {connections === null ? (
          <div className="panel-body space-y-2">
            {[...Array(3)].map((_, i) => <div key={i} className="h-12 rounded bg-bg-subtle anim-fade" />)}
          </div>
        ) : connections.length === 0 ? (
          <div className="panel-body text-center py-12 space-y-3">
            <div className="text-4xl">🔌</div>
            <div className="text-sm font-medium text-fg">No connections yet</div>
            <p className="text-2xs text-fg-muted max-w-xs mx-auto">
              Connect your first database to start ingesting data and syncing schemas to the knowledge graph.
            </p>
            <button onClick={() => setShowModal(true)} className="btn-primary mt-2">Connect a database</button>
          </div>
        ) : (
          <table className="table-base">
            <thead>
              <tr>
                <th>Connection</th><th>Type</th><th>Status</th><th>Mode</th><th className="text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {connections.map((conn) => (
                <ConnectionRow key={conn.id} conn={conn} onDisconnect={handleDisconnect} onSyncGraph={handleSyncGraph} syncingId={syncingId} />
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="panel">
        <div className="panel-header">
          <h3 className="text-sm font-semibold">How connections work</h3>
        </div>
        <div className="panel-body grid grid-cols-3 gap-6">
          {[
            { emoji: "1️⃣", title: "Register", desc: "Enter credentials. Conduit tests the connection, encrypts them in memory, and stores a live engine." },
            { emoji: "2️⃣", title: "Sync Graph", desc: "Introspects the connected database and publishes table schemas into the Neo4j knowledge graph for AI-assisted ingest." },
            { emoji: "3️⃣", title: "Ingest", desc: "Upload a file. The AI will see your registered schemas and automatically suggest the right target table." },
          ].map((item) => (
            <div key={item.title} className="space-y-1.5">
              <div className="text-xs font-semibold text-fg flex items-center gap-1.5">
                <span className="text-base">{item.emoji}</span> {item.title}
              </div>
              <p className="text-2xs text-fg-muted leading-relaxed">{item.desc}</p>
            </div>
          ))}
        </div>
      </div>

      {showModal && (
        <ConnectModal providers={providers} onClose={() => setShowModal(false)} onSuccess={load} />
      )}
    </div>
  );
}
