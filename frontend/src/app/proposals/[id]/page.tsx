"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import clsx from "clsx";
import {
  approveProposal,
  createSkill,
  getProposal,
  getProposalContext,
  listAuditForProposal,
  rejectProposal,
  getInsightsForProposal,
} from "@/lib/api";
import type {
  AuditEntry,
  ExecutionResult,
  ProposalContextResponse,
  ProposalResponse,
  InsightItem,
} from "@/lib/types";
import { PageHeader, SectionHeader } from "@/components/page-header";
import { GatewayBadge, SeverityBadge } from "@/components/badges";
import { CodeBlock } from "@/components/code-block";
import { CopyButton } from "@/components/copy-button";
import { formatRelative } from "@/lib/format";

type Tab = "drift" | "code" | "prompt" | "context";

export default function ProposalDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const id = params.id;

  const [proposal, setProposal] = useState<ProposalResponse | null>(null);
  const [audit, setAudit] = useState<AuditEntry | null>(null);
  const [context, setContext] = useState<ProposalContextResponse | null>(null);
  const [contextLoading, setContextLoading] = useState(false);
  const [contextError, setContextError] = useState<string | null>(null);
  const [contextErrorStatus, setContextErrorStatus] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("drift");

  const [approver, setApprover] = useState("demo_engineer_01");
  const [actionLoading, setActionLoading] = useState<"approve" | "reject" | null>(
    null,
  );
  const [actionResult, setActionResult] = useState<ExecutionResult | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [showRejectModal, setShowRejectModal] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [proposalInsights, setProposalInsights] = useState<InsightItem[] | null>(null);

  // Fetch insights if the proposal is already executed (has audit record) or after we just executed it (actionResult)
  useEffect(() => {
    if (!id) return;
    if (audit || actionResult) {
      getInsightsForProposal(id)
        .then(setProposalInsights)
        .catch(console.error);
    } else {
      setProposalInsights(null);
    }
  }, [id, audit, actionResult]);

  useEffect(() => {
    if (!id) return;
    getProposal(id)
      .then(setProposal)
      .catch((e) => setError(String(e.message ?? e)));
  }, [id]);

  useEffect(() => {
    if (tab !== "context" || !id || context) return;
    setContextLoading(true);
    setContextError(null);
    setContextErrorStatus(null);
    getProposalContext(id)
      .then(setContext)
      .catch((e) => {
        const err = e as Error & { status?: number };
        setContextError(String(err.message ?? err));
        setContextErrorStatus(err.status ?? null);
      })
      .finally(() => setContextLoading(false));
  }, [tab, id, context]);

  // Look up the audit ledger entry for this proposal (only exists after execution)
  useEffect(() => {
    if (!id) return;
    setAudit(null);
    listAuditForProposal(id)
      .then((rows) => {
        if (rows.length > 0) setAudit(rows[0]);
      })
      .catch(() => {
        // no audit entry yet — this is expected for unexecuted proposals
      });
  }, [id]);

  async function handleApprove() {
    if (!id) return;
    setActionLoading("approve");
    setActionError(null);
    try {
      const res = await approveProposal(id, { human_approver_id: approver });
      setActionResult(res);
      // Re-fetch audit entry to update state
      if (res.proposal_id) {
        try {
          const rows = await listAuditForProposal(res.proposal_id);
          if (rows.length > 0) setAudit(rows[0]);
        } catch {}
      }
    } catch (e) {
      setActionError(String((e as Error).message ?? e));
    } finally {
      setActionLoading(null);
    }
  }

  async function handleReject() {
    if (!id) return;
    setActionLoading("reject");
    setActionError(null);
    try {
      await rejectProposal(id, { reason: rejectReason || "Rejected by engineer" });
      router.push("/proposals");
    } catch (e) {
      setActionError(String((e as Error).message ?? e));
      setActionLoading(null);
    }
  }

  if (error) {
    return (
      <div className="space-y-6">
        <PageHeader title="Proposal" />
        <div className="card border-danger-border bg-danger-bg p-4 text-sm text-danger">
          {error}
        </div>
      </div>
    );
  }

  if (!proposal) {
    return (
      <div className="space-y-4">
        <PageHeader title="Loading proposal…" />
        <div className="h-32 rounded-lg bg-bg-subtle anim-fade" />
      </div>
    );
  }

  const confidencePct = Math.round(proposal.confidence_score * 100);

  return (
    <div className="space-y-6 anim-fade">
      <div className="space-y-3">
        <Link
          href="/proposals"
          className="text-2xs text-fg-muted hover:text-fg inline-flex items-center gap-1"
        >
          ← Proposals
        </Link>
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-semibold tracking-tight">
                Proposal
              </h1>
              <GatewayBadge status={proposal.gateway_status} />
            </div>
            <p className="mt-1 text-2xs text-fg-muted font-mono">
              {proposal.proposal_id}
            </p>
          </div>
        </div>
      </div>

      {proposal.description_md ? (
        <div className="card p-4 bg-bg-subtle border-border space-y-2 anim-in">
          <div className="text-2xs font-semibold uppercase tracking-wider text-fg-muted">
            Dataset Description
          </div>
          <div className="text-xs text-fg leading-relaxed whitespace-pre-line font-mono bg-white p-3 border border-border-subtle rounded max-h-48 overflow-y-auto">
            {proposal.description_md}
          </div>
        </div>
      ) : null}

      <div className="grid grid-cols-12 gap-6">
        <div className="col-span-8 space-y-6">
          <div className="panel">
            <div className="border-b border-border-subtle px-1 py-1 flex items-center gap-0.5">
              {(
                [
                  { key: "drift", label: "Drift" },
                  { key: "code", label: "Generated code" },
                  { key: "prompt", label: "AI prompt" },
                  { key: "context", label: "AI context bundle" },
                ] as { key: Tab; label: string }[]
              ).map((t) => (
                <button
                  key={t.key}
                  onClick={() => setTab(t.key)}
                  className={clsx(
                    "px-3 h-8 text-sm rounded-md transition-colors",
                    tab === t.key
                      ? "bg-bg-subtle text-fg font-medium"
                      : "text-fg-muted hover:text-fg",
                  )}
                >
                  {t.label}
                </button>
              ))}
            </div>

            {tab === "drift" && (
              <div>
                {proposal.drift_detected.length > 0 ? (
                  <table className="table-base">
                    <thead>
                      <tr>
                        <th>Column</th>
                        <th>Issue</th>
                        <th>Source</th>
                        <th>Target</th>
                        <th>Action</th>
                        <th>Severity</th>
                      </tr>
                    </thead>
                    <tbody>
                      {proposal.drift_detected.map((d, i) => (
                        <tr key={i}>
                          <td className="font-mono text-xs">{d.column}</td>
                          <td>
                            <span className="badge text-2xs font-mono uppercase tracking-wider bg-bg-subtle border-border text-fg-muted">
                              {d.issue_type}
                            </span>
                          </td>
                          <td className="text-fg-muted text-2xs font-mono max-w-xs truncate">
                            {d.source_value || "—"}
                          </td>
                          <td className="text-fg-muted text-2xs font-mono max-w-xs truncate">
                            {d.target_expectation || "—"}
                          </td>
                          <td className="text-sm max-w-md">
                            {d.suggested_action}
                          </td>
                          <td>
                            <SeverityBadge severity={d.severity} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <div className="panel-body text-sm text-fg-muted">
                    No drift detected. The incoming schema matches the target.
                  </div>
                )}
              </div>
            )}

            {tab === "code" && (
              <div className="p-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="text-2xs text-fg-muted">
                    AST-validated · executes in a restricted namespace
                  </div>
                  <CopyButton value={proposal.generated_code} />
                </div>
                <CodeBlock
                  code={proposal.generated_code}
                  language="python"
                  maxHeight="max-h-[60vh]"
                />
              </div>
            )}

            {tab === "prompt" && (
              <div className="p-4 space-y-3">
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="text-xs font-medium">User message</div>
                    <CopyButton
                      value={
                        audit?.llm_prompt_sent ??
                        "(no execution record — approve the proposal to capture the prompt)"
                      }
                    />
                  </div>
                  <CodeBlock
                    code={
                      audit?.llm_prompt_sent ??
                      "(no execution record yet — approve the proposal to capture the prompt)"
                    }
                    language="text"
                    maxHeight="max-h-[60vh]"
                  />
                </div>
                {audit?.llm_raw_response ? (
                  <div>
                    <div className="flex items-center justify-between mb-1.5">
                      <div className="text-xs font-medium">Raw LLM response</div>
                      <CopyButton value={audit.llm_raw_response} />
                    </div>
                    <CodeBlock
                      code={audit.llm_raw_response}
                      language="json"
                      maxHeight="max-h-[40vh]"
                    />
                  </div>
                ) : null}
              </div>
            )}

            {tab === "context" && (
              <ContextBundleTab
                context={context}
                loading={contextLoading}
                error={contextError}
                errorStatus={contextErrorStatus}
              />
            )}
          </div>

          {actionResult ? (
            <div className="panel">
              <div className="panel-header">
                <h3 className="text-sm font-semibold">Execution result</h3>
                <span className="text-2xs text-fg-muted font-mono">
                  {actionResult.execution_status}
                </span>
              </div>
              <div className="panel-body grid grid-cols-3 gap-6">
                <div>
                  <div className="text-2xs font-medium uppercase tracking-wider text-fg-muted">
                    Rows written
                  </div>
                  <div className="mt-1 text-2xl font-semibold tabular-nums">
                    {actionResult.rows_written.toLocaleString()}
                  </div>
                </div>
                <div>
                  <div className="text-2xs font-medium uppercase tracking-wider text-fg-muted">
                    Rows quarantined
                  </div>
                  <div className="mt-1 text-2xl font-semibold tabular-nums">
                    {actionResult.rows_quarantined.toLocaleString()}
                  </div>
                </div>
                <div>
                  <div className="text-2xs font-medium uppercase tracking-wider text-fg-muted">
                    Duration
                  </div>
                  <div className="mt-1 text-2xl font-semibold tabular-nums">
                    {actionResult.duration_ms}ms
                  </div>
                </div>
              </div>
            </div>
          ) : null}

          {proposalInsights && proposalInsights.length > 0 ? (
            <div className="panel mt-6">
              <div className="panel-header">
                <div>
                  <h3 className="text-sm font-semibold">Insights Discovered</h3>
                  <p className="text-2xs text-fg-muted mt-0.5 font-sans">
                    Surfaced patterns and data quality issues from this executed dataset
                  </p>
                </div>
                <Link href="/insights" className="btn-ghost h-7 px-2 text-2xs">
                  View all insights →
                </Link>
              </div>
              <div className="panel-body space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {proposalInsights.map((item) => (
                    <div key={item.id} className="card p-4 space-y-2 hover:border-fg-subtle transition-colors">
                      <div className="flex items-center justify-between gap-2">
                        <span className={clsx(
                          "badge text-[10px] font-mono tracking-wider uppercase px-1.5 py-0.5",
                          item.severity === "CRITICAL" && "text-danger bg-danger-bg border-danger-border",
                          item.severity === "WARNING" && "text-warning bg-warning-bg border-warning-border",
                          item.severity === "INFO" && "text-info bg-info-bg border-info-border",
                        )}>
                          {item.severity}
                        </span>
                        <span className="text-2xs text-fg-subtle font-mono">{item.category}</span>
                      </div>
                      <h4 className="text-sm font-semibold text-fg leading-snug">{item.title}</h4>
                      <p className="text-xs text-fg-muted leading-relaxed">{item.description}</p>
                      
                      {item.evidence && Object.keys(item.evidence).length > 0 && (
                        <details className="text-2xs font-mono pt-1 text-fg-subtle cursor-pointer select-none">
                          <summary className="hover:text-fg font-sans font-medium mb-1">View Evidence Statistics</summary>
                          <pre className="p-2 bg-bg-subtle border border-border-subtle rounded text-[10px] overflow-x-auto whitespace-pre-wrap">
                            {JSON.stringify(item.evidence, null, 2)}
                          </pre>
                        </details>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : (audit || actionResult) ? (
            <div className="panel mt-6">
              <div className="panel-header">
                <h3 className="text-sm font-semibold">Insights Discovered</h3>
              </div>
              <div className="panel-body text-xs text-fg-muted">
                No insights were surfaced for this dataset.
              </div>
            </div>
          ) : null}
        </div>

        <div className="col-span-4 space-y-4">
          <div className="card p-4 space-y-3">
            <div>
              <div className="text-2xs font-medium uppercase tracking-wider text-fg-muted">
                Confidence
              </div>
              <div className="mt-1 flex items-baseline gap-1.5">
                <span
                  className={clsx(
                    "text-2xl font-semibold tabular-nums",
                    proposal.confidence_score > 0.9
                      ? "text-success"
                      : proposal.confidence_score > 0.75
                      ? "text-warning"
                      : "text-danger",
                  )}
                >
                  {confidencePct}%
                </span>
                <span className="text-2xs text-fg-muted">
                  {proposal.llm_model_used}
                </span>
              </div>
              <div className="mt-2 h-1 rounded-full bg-bg-subtle overflow-hidden">
                <div
                  className={clsx(
                    "h-full",
                    proposal.confidence_score > 0.9
                      ? "bg-success"
                      : proposal.confidence_score > 0.75
                      ? "bg-warning"
                      : "bg-danger",
                  )}
                  style={{ width: `${confidencePct}%` }}
                />
              </div>
            </div>

            <div className="divider" />

            <dl className="space-y-2.5 text-sm">
              <div className="flex items-center justify-between">
                <dt className="text-fg-muted">Estimated rows</dt>
                <dd className="font-mono tabular-nums">
                  {proposal.estimated_rows.toLocaleString()}
                </dd>
              </div>
              <div className="flex items-center justify-between">
                <dt className="text-fg-muted">Drift items</dt>
                <dd className="font-mono tabular-nums">
                  {proposal.drift_detected.length}
                </dd>
              </div>
              <div className="flex items-center justify-between">
                <dt className="text-fg-muted">PII columns</dt>
                <dd className="font-mono text-2xs">
                  {proposal.pii_columns_found.length === 0
                    ? "—"
                    : proposal.pii_columns_found.join(", ")}
                </dd>
              </div>
            </dl>
            {proposal.enrichment_applied && proposal.enrichment_applied.length > 0 && (
              <div className="pt-2.5 border-t border-border-subtle mt-2.5">
                <div className="text-2xs font-medium uppercase tracking-wider text-fg-muted mb-1.5">Enrichment Applied</div>
                <div className="flex flex-wrap gap-1">
                  {proposal.enrichment_applied.map((rule, idx) => (
                    <span key={idx} className="badge text-[10px] bg-bg-subtle border-border text-fg-muted px-1.5 py-0.5">
                      {rule.replace(/_/g, " ")}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {proposal.extra_params && Object.keys(proposal.extra_params).length > 0 && (
              <div className="pt-2.5 border-t border-border-subtle mt-2.5">
                <div className="text-2xs font-medium uppercase tracking-wider text-fg-muted mb-1.5">Extra Parameters</div>
                <div className="space-y-1">
                  {Object.entries(proposal.extra_params).map(([key, val]) => (
                    <div key={key} className="flex justify-between items-center text-xs">
                      <span className="font-mono text-fg-muted">{key}</span>
                      <span className="font-mono bg-bg-subtle px-1.5 py-0.5 rounded text-fg-strong border border-border-subtle">{String(val)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {proposal.suggested_skills_to_add && proposal.suggested_skills_to_add.length > 0 ? (
            <SuggestedSkillsCard skills={proposal.suggested_skills_to_add} />
          ) : null}

          <div className="card p-4 space-y-3">
            <div>
              <div className="text-sm font-semibold">Proposed steps</div>
              <div className="text-2xs text-fg-muted mt-0.5">
                Plain-English action plan from the AI
              </div>
            </div>
            {proposal.proposed_steps.length > 0 ? (
              <ol className="space-y-1.5 text-sm list-decimal list-inside text-fg">
                {proposal.proposed_steps.map((step, i) => (
                  <li key={i} className="leading-relaxed">
                    {step}
                  </li>
                ))}
              </ol>
            ) : (
              <div className="text-sm text-fg-muted">No steps proposed.</div>
            )}
          </div>

          {proposal.gateway_status === "CONFLICT" ? (
            <div className="card p-4 border-danger-border bg-danger-bg space-y-2">
              <div className="text-sm font-semibold text-danger">
                Conflict — manual review required
              </div>
              <p className="text-2xs text-fg-muted leading-relaxed">
                The agent detected drift that cannot be auto-resolved.
                Approve only if you have manually verified the generated
                transformation.
              </p>
            </div>
          ) : null}

          {audit ? (
            <div className="card p-4 space-y-2">
              <div className="text-sm font-semibold">Execution</div>
              <dl className="space-y-2 text-sm">
                <div>
                  <dt className="text-2xs text-fg-muted">Status</dt>
                  <dd className="font-mono text-xs mt-0.5">
                    {audit.execution_status}
                  </dd>
                </div>
                <div>
                  <dt className="text-2xs text-fg-muted">Approver</dt>
                  <dd className="font-mono text-xs mt-0.5">
                    {audit.human_approver_id}
                  </dd>
                </div>
                <div>
                  <dt className="text-2xs text-fg-muted">Executed</dt>
                  <dd className="text-xs mt-0.5">
                    {formatRelative(audit.executed_at)}
                  </dd>
                </div>
              </dl>
            </div>
          ) : (
            <div className="card p-4 space-y-3">
              <div>
                <div className="text-sm font-semibold">Approve & execute</div>
                <div className="text-2xs text-fg-muted mt-0.5">
                  Trigger the transformation against the warehouse
                </div>
              </div>
              <div>
                <label className="label">Approver ID</label>
                <input
                  type="text"
                  className="input font-mono"
                  value={approver}
                  onChange={(e) => setApprover(e.target.value)}
                  placeholder="e.g. demo_engineer_01"
                />
              </div>
              {actionError ? (
                <div className="text-2xs text-danger border border-danger-border bg-danger-bg rounded p-2">
                  {actionError}
                </div>
              ) : null}
              <div className="flex flex-col gap-2">
                <button
                  onClick={handleApprove}
                  disabled={actionLoading !== null}
                  className="btn-primary w-full"
                >
                  {actionLoading === "approve" ? "Executing…" : "Approve & execute"}
                </button>
                <button
                  onClick={() => setShowRejectModal(true)}
                  disabled={actionLoading !== null}
                  className="btn-secondary w-full"
                >
                  Reject
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {showRejectModal ? (
        <div
          className="fixed inset-0 bg-black/30 flex items-center justify-center z-50 anim-fade"
          onClick={() => setShowRejectModal(false)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="card p-5 w-full max-w-md space-y-3"
          >
            <div>
              <h3 className="text-sm font-semibold">Reject proposal</h3>
              <p className="text-2xs text-fg-muted mt-0.5">
                The reason will be stored in the audit ledger.
              </p>
            </div>
            <textarea
              className="input min-h-24 py-2 h-auto"
              placeholder="Why are you rejecting this proposal?"
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
            />
            <div className="flex items-center justify-end gap-2">
              <button
                onClick={() => setShowRejectModal(false)}
                className="btn-ghost"
              >
                Cancel
              </button>
              <button
                onClick={handleReject}
                disabled={actionLoading !== null}
                className="btn-danger"
              >
                {actionLoading === "reject" ? "Rejecting…" : "Confirm reject"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ContextBundleTab({
  context,
  loading,
  error,
  errorStatus,
}: {
  context: ProposalContextResponse | null;
  loading: boolean;
  error: string | null;
  errorStatus: number | null;
}) {
  if (loading) {
    return (
      <div className="p-4 space-y-3 anim-fade">
        <div className="h-20 rounded bg-bg-subtle" />
        <div className="h-32 rounded bg-bg-subtle" />
        <div className="h-20 rounded bg-bg-subtle" />
      </div>
    );
  }

  if (error) {
    const is404 = errorStatus === 404;
    return (
      <div className="p-4">
        {is404 ? (
          <div className="text-sm text-fg-muted">
            No context bundle was stored for this proposal (e.g., it skipped the AI generation path because of zero matching columns or pre-dates the extensions layer).
          </div>
        ) : (
          <div className="rounded-md border border-danger-border bg-danger-bg p-3 text-sm text-danger">
            {error}
          </div>
        )}
      </div>
    );
  }

  if (!context || !context.context_bundle) {
    return (
      <div className="p-4 text-sm text-fg-muted">
        No context bundle was stored for this proposal. The bundle is built
        and persisted during ingest (Phase 1) — proposals created before
        Phase 1 will not have one.
      </div>
    );
  }

  const bundle = context.context_bundle;
  const relatedSkills = Array.isArray(bundle.related_skills)
    ? (bundle.related_skills as Array<Record<string, unknown>>)
    : [];
  const relatedEntities = Array.isArray(bundle.related_entities)
    ? (bundle.related_entities as Array<Record<string, unknown>>)
    : [];
  const dependencies = Array.isArray(bundle.dependencies)
    ? (bundle.dependencies as Array<Record<string, unknown>>)
    : [];
  const businessContext = Array.isArray(bundle.business_context)
    ? (bundle.business_context as Array<string>)
    : [];
  const piiColumns = Array.isArray(bundle.pii_columns)
    ? (bundle.pii_columns as Array<string>)
    : [];

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between text-2xs text-fg-muted">
        <div>
          Built during ingest · target{" "}
          <span className="font-mono text-fg">
            {(bundle.target_table as string | undefined) ?? context.target_table ?? "—"}
          </span>
        </div>
        <div className="font-mono">{formatRelative(context.generated_at)}</div>
      </div>

      {piiColumns.length > 0 ? (
        <div className="card p-3 border-danger-border bg-danger-bg">
          <div className="text-2xs font-medium uppercase tracking-wider text-danger">
            PII columns
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {piiColumns.map((c, i) => (
              <span
                key={i}
                className="badge font-mono text-danger bg-white border-danger-border"
              >
                {c}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-4">
        <div className="card p-3">
          <div className="text-2xs font-medium uppercase tracking-wider text-fg-muted">
            Related skills
          </div>
          {relatedSkills.length === 0 ? (
            <div className="mt-2 text-2xs text-fg-subtle">
              No matching skills found.
            </div>
          ) : (
            <ul className="mt-2 space-y-1.5">
              {relatedSkills.map((s, i) => (
                <li
                  key={i}
                  className="text-sm flex items-center justify-between gap-2"
                >
                  <div className="min-w-0">
                    <div className="font-mono text-xs truncate">
                      {String(s.name ?? "—")}
                    </div>
                    <div className="text-2xs text-fg-muted truncate">
                      {String(s.description ?? "")}
                    </div>
                  </div>
                  <span className="badge font-mono uppercase tracking-wider text-fg-muted bg-bg-subtle border-border whitespace-nowrap">
                    {String(s.category ?? "—").replace(/_/g, " ")}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="card p-3">
          <div className="text-2xs font-medium uppercase tracking-wider text-fg-muted">
            Related entities
          </div>
          {relatedEntities.length === 0 ? (
            <div className="mt-2 text-2xs text-fg-subtle">
              No related entities within 2 hops.
            </div>
          ) : (
            <ul className="mt-2 space-y-1.5">
              {relatedEntities.map((e, i) => (
                <li
                  key={i}
                  className="text-sm flex items-center justify-between gap-2"
                >
                  <span className="font-mono text-xs truncate">
                    {String(e.name ?? "—")}
                  </span>
                  <span className="badge font-mono uppercase tracking-wider text-fg-muted bg-bg-subtle border-border whitespace-nowrap">
                    {String(e.type ?? "—").replace(/_/g, " ")}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="card p-3">
        <div className="text-2xs font-medium uppercase tracking-wider text-fg-muted">
          Direct dependencies
        </div>
        {dependencies.length === 0 ? (
          <div className="mt-2 text-2xs text-fg-subtle">
            No direct dependencies recorded.
          </div>
        ) : (
          <ul className="mt-2 space-y-1.5">
            {dependencies.map((d, i) => (
              <li
                key={i}
                className="text-sm flex items-center justify-between gap-2"
              >
                <span className="font-mono text-xs truncate">
                  {String(d.name ?? "—")}
                </span>
                <span className="badge font-mono uppercase tracking-wider text-fg-muted bg-bg-subtle border-border whitespace-nowrap">
                  {String(d.type ?? "—").replace(/_/g, " ")}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {businessContext.length > 0 ? (
        <div className="card p-3">
          <div className="text-2xs font-medium uppercase tracking-wider text-fg-muted">
            Business context
          </div>
          <ul className="mt-2 space-y-1.5 text-sm text-fg leading-relaxed">
            {businessContext.map((b, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-fg-subtle">·</span>
                <span>{b}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <details className="card p-3">
        <summary className="text-2xs font-medium uppercase tracking-wider text-fg-muted cursor-pointer">
          Raw JSON
        </summary>
        <div className="mt-3">
          <CodeBlock
            code={JSON.stringify(bundle, null, 2)}
            language="json"
            maxHeight="max-h-96"
          />
        </div>
      </details>
    </div>
  );
}

function SuggestedSkillsCard({
  skills,
}: {
  skills: Array<{ skill_name: string; description: string; category: string }>;
}) {
  const [registered, setRegistered] = useState<Record<string, "pending" | "success" | "error">>({});

  async function handleAddSkill(name: string, desc: string, cat: string) {
    setRegistered((prev) => ({ ...prev, [name]: "pending" }));
    try {
      await createSkill({
        skill_name: name,
        description: desc,
        category: cat,
        version: "1.0.0",
        owner: "system",
        status: "ACTIVE",
      });
      setRegistered((prev) => ({ ...prev, [name]: "success" }));
    } catch (e) {
      console.error("Failed to add skill:", e);
      setRegistered((prev) => ({ ...prev, [name]: "error" }));
    }
  }

  return (
    <div className="card p-4 space-y-3 border-warning-border bg-warning-bg/10">
      <div>
        <div className="text-sm font-semibold text-warning flex items-center gap-1.5">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          Suggested Skills to Add
        </div>
        <p className="text-2xs text-fg-muted mt-0.5">
          The AI recommends registering these reusable transformation skills.
        </p>
      </div>
      <div className="space-y-3 pt-1">
        {skills.map((s, idx) => {
          const status = registered[s.skill_name];
          return (
            <div key={idx} className="p-3 bg-white rounded border border-warning-border/30 space-y-2">
              <div className="flex items-start justify-between gap-2">
                <span className="font-mono text-xs font-semibold break-all text-fg">{s.skill_name}</span>
                <span className="badge text-3xs font-mono uppercase tracking-wider text-fg-muted bg-bg-subtle border border-border whitespace-nowrap">
                  {s.category.replace(/_/g, " ")}
                </span>
              </div>
              <p className="text-2xs text-fg-muted leading-relaxed">{s.description}</p>
              <div>
                {status === "success" ? (
                  <span className="text-3xs text-success font-semibold flex items-center gap-1 font-mono">
                    ✓ Registered successfully!
                  </span>
                ) : (
                  <button
                    onClick={() => handleAddSkill(s.skill_name, s.description, s.category)}
                    disabled={status === "pending"}
                    className={clsx(
                      "text-3xs px-2 py-1 border rounded font-semibold transition-colors font-mono",
                      status === "pending"
                        ? "bg-bg-subtle border-border text-fg-muted cursor-not-allowed"
                        : "bg-white hover:bg-bg-subtle border-border hover:border-fg-subtle text-fg"
                    )}
                  >
                    {status === "pending" ? "Registering..." : "+ Add to registry"}
                  </button>
                )}
                {status === "error" && (
                  <span className="text-3xs text-danger block mt-1 font-mono">
                    Failed to register. Check console.
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

