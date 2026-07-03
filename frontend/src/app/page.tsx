"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import clsx from "clsx";
import {
  listAudit,
  listProposals,
  listQuarantine,
  listSkills,
  listConnections,
  listGraphNodes,
  listInsights,
} from "@/lib/api";
import type {
  AuditEntry,
  GatewayStatus,
  ProposalResponse,
  QuarantineEntry,
  ConnectorConnection,
  InsightItem,
} from "@/lib/types";
import { GatewayBadge, StatusDot, ExecutionBadge } from "@/components/badges";
import { PageHeader } from "@/components/page-header";
import { formatRelative } from "@/lib/format";

const GATEWAY_ORDER: GatewayStatus[] = ["AUTO_LINK", "SCHEMA_EVOLUTION", "CONFLICT"];

const GATEWAY_LABELS: Record<GatewayStatus, string> = {
  AUTO_LINK: "Auto Link",
  SCHEMA_EVOLUTION: "Schema Evolution",
  CONFLICT: "Conflict",
};

const GATEWAY_BAR: Record<GatewayStatus, string> = {
  AUTO_LINK: "bg-success",
  SCHEMA_EVOLUTION: "bg-warning",
  CONFLICT: "bg-danger",
};

function StatCard({ label, value, hint, accent }: {
  label: string; value: string | number; hint?: string; accent?: "success" | "warning" | "danger";
}) {
  return (
    <div className="card p-4">
      <div className="text-2xs font-medium uppercase tracking-wider text-fg-muted">{label}</div>
      <div className={clsx(
        "mt-2 text-2xl font-semibold tracking-tight tabular-nums",
        accent === "success" && "text-success",
        accent === "warning" && "text-warning",
        accent === "danger" && "text-danger",
      )}>{value}</div>
      {hint ? <div className="mt-1 text-2xs text-fg-muted">{hint}</div> : null}
    </div>
  );
}

export default function OverviewPage() {
  const [proposals, setProposals] = useState<ProposalResponse[] | null>(null);
  const [audit, setAudit] = useState<AuditEntry[] | null>(null);
  const [quarantine, setQuarantine] = useState<QuarantineEntry[] | null>(null);
  const [sources, setSources] = useState<ConnectorConnection[] | null>(null);
  const [skillCount, setSkillCount] = useState<number | null>(null);
  const [graphNodeCount, setGraphNodeCount] = useState<number | null>(null);
  const [insights, setInsights] = useState<InsightItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      listProposals({ limit: 200 }),
      listAudit(50),
      listQuarantine(),
      listConnections(),
      listSkills({ limit: 9999 }),
      listGraphNodes({ limit: 9999 }),
      listInsights({ limit: 4 }),
    ])
      .then(([p, a, q, s, sk, gn, ins]) => {
        if (cancelled) return;
        setProposals(p); setAudit(a); setQuarantine(q); setSources(s);
        setSkillCount(sk.length); setGraphNodeCount(gn.length); setInsights(ins);
      })
      .catch((e) => !cancelled && setError(String(e.message ?? e)));
    return () => { cancelled = true; };
  }, []);

  const loading = proposals === null || audit === null || quarantine === null || sources === null || insights === null;

  const proposalCount = proposals?.length ?? 0;
  const autoLinked = proposals?.filter((p) => p.gateway_status === "AUTO_LINK").length ?? 0;
  const schemaEvolved = proposals?.filter((p) => p.gateway_status === "SCHEMA_EVOLUTION").length ?? 0;
  const conflicts = proposals?.filter((p) => p.gateway_status === "CONFLICT").length ?? 0;
  const autoLinkedPct = proposalCount === 0 ? 0 : Math.round((autoLinked / proposalCount) * 100);
  const successCount = audit?.filter((a) => a.execution_status === "SUCCESS").length ?? 0;
  const failedCount = audit?.filter((a) => a.execution_status === "FAILED" || a.execution_status === "ROLLEDBACK").length ?? 0;
  const auditedCount = audit?.length ?? 0;
  const successPct = auditedCount === 0 ? 0 : Math.round((successCount / auditedCount) * 100);
  const connectedSources = sources?.filter((s) => s.status === "connected").length ?? 0;
  const totalSources = sources?.length ?? 0;
  const breakdown = GATEWAY_ORDER.map((g) => ({
    status: g,
    count: proposals?.filter((p) => p.gateway_status === g).length ?? 0,
  }));

  return (
    <div className="space-y-8 anim-fade">
      <PageHeader
        title="Overview"
        description="Operational status of the data engineering pipeline."
        actions={<Link href="/ingest" className="btn-primary">New Ingest</Link>}
      />

      {error && (
        <div className="card border-danger-border bg-danger-bg p-4 text-sm text-danger">
          Failed to load overview: {error}
        </div>
      )}

      <div className="grid grid-cols-4 gap-4">
        <StatCard label="Auto-resolved rate" value={loading ? "—" : `${autoLinkedPct}%`}
          hint={loading ? undefined : `${autoLinked} of ${proposalCount} proposals auto-linked`}
          accent={autoLinkedPct >= 75 ? "success" : autoLinkedPct >= 50 ? "warning" : "danger"} />
        <StatCard label="Proposals" value={loading ? "—" : proposalCount}
          hint={loading ? undefined : `${schemaEvolved} evolve · ${conflicts} conflict`} />
        <StatCard label="Execution success" value={loading ? "—" : `${successPct}%`}
          hint={loading ? undefined : `${successCount} ok · ${failedCount} failed of ${auditedCount}`}
          accent={successPct >= 90 ? "success" : successPct >= 70 ? "warning" : "danger"} />
        <StatCard label="Quarantined rows" value={loading ? "—" : quarantine!.length} hint="Awaiting review" />
      </div>

      <div className="grid grid-cols-12 gap-6">
        <div className="col-span-7 space-y-6">

          {/* Gateway breakdown */}
          <div className="panel">
            <div className="panel-header">
              <div>
                <h3 className="text-sm font-semibold">Gateway classification</h3>
                <p className="text-2xs text-fg-muted mt-0.5">Last {proposalCount} proposal{proposalCount === 1 ? "" : "s"}</p>
              </div>
              <Link href="/proposals" className="btn-ghost h-7 px-2 text-2xs">View proposals →</Link>
            </div>
            <div className="panel-body space-y-3">
              {loading ? (
                [...Array(3)].map((_, i) => <div key={i} className="h-8 rounded bg-bg-subtle anim-fade" />)
              ) : proposalCount === 0 ? (
                <div className="text-sm text-fg-muted">No proposals yet. <Link href="/ingest" className="text-fg underline">Ingest a file</Link> to get started.</div>
              ) : (
                breakdown.map((b) => {
                  const pct = proposalCount === 0 ? 0 : (b.count / proposalCount) * 100;
                  return (
                    <div key={b.status} className="space-y-1.5">
                      <div className="flex items-center justify-between text-2xs">
                        <div className="flex items-center gap-2">
                          <span className={clsx("w-2 h-2 rounded-full",
                            b.status === "AUTO_LINK" && "bg-success",
                            b.status === "SCHEMA_EVOLUTION" && "bg-warning",
                            b.status === "CONFLICT" && "bg-danger")} />
                          <span className="font-medium text-fg">{GATEWAY_LABELS[b.status]}</span>
                        </div>
                        <div className="font-mono tabular-nums text-fg-muted">{b.count} · {Math.round(pct)}%</div>
                      </div>
                      <div className="h-1.5 rounded-full bg-bg-subtle overflow-hidden">
                        <div className={clsx("h-full", GATEWAY_BAR[b.status])} style={{ width: `${pct}%` }} />
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* Recent proposals */}
          <div className="panel">
            <div className="panel-header">
              <h3 className="text-sm font-semibold">Recent proposals</h3>
            </div>
            {loading || !proposals ? (
              <div className="panel-body space-y-2">{[...Array(5)].map((_, i) => <div key={i} className="h-8 rounded bg-bg-subtle anim-fade" />)}</div>
            ) : proposals.length === 0 ? (
              <div className="panel-body text-sm text-fg-muted">No proposals yet.</div>
            ) : (
              <table className="table-base">
                <thead><tr><th>Proposal</th><th>Target</th><th>Gateway</th><th className="text-right">Drift</th></tr></thead>
                <tbody>
                  {proposals.slice(0, 8).map((p) => (
                    <tr key={p.proposal_id}>
                      <td><Link href={`/proposals/${p.proposal_id}`} className="font-mono text-2xs text-fg hover:underline">{p.proposal_id.slice(0, 8)}…</Link></td>
                      <td className="font-mono text-xs">{p.target_table ?? <span className="text-fg-subtle">—</span>}</td>
                      <td><GatewayBadge status={p.gateway_status} /></td>
                      <td className="text-right font-mono text-sm tabular-nums">{p.drift_detected.length}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        <div className="col-span-5 space-y-6">

          {/* Recent executions */}
          <div className="panel">
            <div className="panel-header">
              <div>
                <h3 className="text-sm font-semibold">Recent executions</h3>
                <p className="text-2xs text-fg-muted mt-0.5">Pipeline ledger activity</p>
              </div>
              <Link href="/audit" className="btn-ghost h-7 px-2 text-2xs">View all →</Link>
            </div>
            {loading || !audit ? (
              <div className="panel-body space-y-2">{[...Array(4)].map((_, i) => <div key={i} className="h-10 rounded bg-bg-subtle anim-fade" />)}</div>
            ) : audit.length === 0 ? (
              <div className="panel-body text-sm text-fg-muted">No executions yet.</div>
            ) : (
              <ul className="divide-y divide-border-subtle">
                {audit.slice(0, 6).map((a) => (
                  <li key={a.id} className="px-5 py-3 flex items-center justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="font-mono text-xs truncate">{a.filename}</div>
                      <div className="text-2xs text-fg-muted mt-0.5 flex items-center gap-1.5">
                        <span className="font-mono">{a.skill_name}</span>
                        <span>·</span>
                        <span>{formatRelative(a.executed_at)}</span>
                      </div>
                    </div>
                    <ExecutionBadge status={a.execution_status} />
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Recent insights */}
          <div className="panel">
            <div className="panel-header">
              <div>
                <h3 className="text-sm font-semibold">Recent insights</h3>
                <p className="text-2xs text-fg-muted mt-0.5">Discovered patterns and anomalies</p>
              </div>
              <Link href="/insights" className="btn-ghost h-7 px-2 text-2xs">View all →</Link>
            </div>
            {loading || !insights ? (
              <div className="panel-body space-y-2">{[...Array(3)].map((_, i) => <div key={i} className="h-10 rounded bg-bg-subtle anim-fade" />)}</div>
            ) : insights.length === 0 ? (
              <div className="panel-body text-sm text-fg-muted">No insights generated yet.</div>
            ) : (
              <ul className="divide-y divide-border-subtle">
                {insights.slice(0, 4).map((item) => (
                  <li key={item.id} className="px-5 py-3.5 space-y-1.5 hover:bg-bg-inset transition-colors">
                    <div className="flex items-center justify-between gap-2">
                      <span className={clsx("badge text-[10px] font-mono tracking-wider uppercase px-1.5 py-0.5",
                        item.severity === "CRITICAL" && "text-danger bg-danger-bg border-danger-border",
                        item.severity === "WARNING" && "text-warning bg-warning-bg border-warning-border",
                        item.severity === "INFO" && "text-info bg-info-bg border-info-border")}>
                        {item.severity}
                      </span>
                      <span className="text-2xs text-fg-subtle font-mono">{item.category}</span>
                    </div>
                    <div className="text-xs font-semibold text-fg leading-tight">{item.title}</div>
                    <div className="text-2xs text-fg-muted line-clamp-2">{item.description}</div>
                    <Link href={`/proposals/${item.proposal_id}`} className="text-[10px] font-mono text-fg-subtle hover:underline hover:text-fg">
                      Proposal: {item.proposal_id.slice(0, 8)}…
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Sources */}
          <div className="panel">
            <div className="panel-header">
              <div>
                <h3 className="text-sm font-semibold">Sources</h3>
                <p className="text-2xs text-fg-muted mt-0.5">{connectedSources} of {totalSources} connected</p>
              </div>
              <Link href="/sources" className="btn-ghost h-7 px-2 text-2xs">Manage →</Link>
            </div>
            {loading || !sources ? (
              <div className="panel-body space-y-2">{[...Array(3)].map((_, i) => <div key={i} className="h-10 rounded bg-bg-subtle anim-fade" />)}</div>
            ) : sources.length === 0 ? (
              <div className="panel-body text-sm text-fg-muted">No sources registered.</div>
            ) : (
              <ul className="divide-y divide-border-subtle">
                {sources.map((s) => (
                  <li key={s.id} className="px-5 py-3 flex items-center justify-between">
                    <div className="min-w-0">
                      <div className="text-sm font-medium truncate">{s.display_name}</div>
                      <div className="text-2xs text-fg-muted font-mono">{s.type.toUpperCase()}</div>
                    </div>
                    <div className="flex items-center gap-1.5 text-xs text-fg-muted">
                      <StatusDot status={s.status === "connected" ? "CONNECTED" : "UNREACHABLE"} />
                      {s.status}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Counts */}
          <div className="grid grid-cols-2 gap-3">
            <div className="card p-3">
              <div className="text-2xs font-medium uppercase tracking-wider text-fg-muted">Skills</div>
              <div className="mt-2 text-xl font-semibold tabular-nums">{skillCount === null ? "—" : skillCount}</div>
              <Link href="/skills" className="text-2xs text-fg-muted hover:text-fg">Registry →</Link>
            </div>
            <div className="card p-3">
              <div className="text-2xs font-medium uppercase tracking-wider text-fg-muted">Graph nodes</div>
              <div className="mt-2 text-xl font-semibold tabular-nums">{graphNodeCount === null ? "—" : graphNodeCount}</div>
              <Link href="/graph" className="text-2xs text-fg-muted hover:text-fg">Explore →</Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
