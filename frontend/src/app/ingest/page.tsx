"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import Link from "next/link";
import clsx from "clsx";
import { ingestFile, suggestTargetTable } from "@/lib/api";
import type { ProposalResponse, TableSuggestion } from "@/lib/types";
import { PageHeader } from "@/components/page-header";
import { GatewayBadge } from "@/components/badges";
import { formatBytes } from "@/lib/format";

type Phase = "idle" | "reasoning" | "resolution" | "error";

type StepStatus = "pending" | "active" | "done" | "error";

interface Step {
  label: string;
  description: string;
}

const STEPS: Step[] = [
  {
    label: "Validating file magic bytes",
    description: "Sniffing the upload to confirm the file format and reject malformed input.",
  },
  {
    label: "Introspecting target schema",
    description: "Loading column definitions from the warehouse metadata store.",
  },
  {
    label: "Building context bundle",
    description: "Traversing the knowledge graph for related entities, dependencies, and PII columns.",
  },
  {
    label: "Generating transformation script",
    description: "Composing a Python script that normalizes the incoming data into the target shape.",
  },
  {
    label: "Validating AST",
    description: "Parsing the generated script and rejecting anything that violates the safety policy.",
  },
  {
    label: "Classifying gateway policy",
    description: "Deciding whether the proposal can auto-link, requires schema evolution, or is a conflict.",
  },
];

const STEP_DURATION_MS = 900;

export default function IngestPage() {
  const [file, setFile] = useState<File | null>(null);
  const [targetTable, setTargetTable] = useState("orders_clean");
  const [descriptionMd, setDescriptionMd] = useState("");
  const [extraParams, setExtraParams] = useState<Array<{ key: string; value: string }>>([
    { key: "", value: "" },
  ]);
  const [dragging, setDragging] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [stepIndex, setStepIndex] = useState(0);
  const [stepStatus, setStepStatus] = useState<StepStatus[]>(
    () => STEPS.map(() => "pending"),
  );
  const [error, setError] = useState<string | null>(null);
  const [proposal, setProposal] = useState<ProposalResponse | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [suggestions, setSuggestions] = useState<TableSuggestion[] | null>(null);
  const [dataUnderstanding, setDataUnderstanding] = useState<string | null>(null);
  const [manualMode, setManualMode] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const stepTimers = useRef<ReturnType<typeof setTimeout>[]>([]);

  const clearTimers = useCallback(() => {
    stepTimers.current.forEach((t) => clearTimeout(t));
    stepTimers.current = [];
  }, []);

  const analyzeFile = useCallback(async (f: File) => {
    setIsAnalyzing(true);
    setSuggestions(null);
    setDataUnderstanding(null);
    setManualMode(false);
    setError(null);
    try {
      const res = await suggestTargetTable(f);
      setSuggestions(res.suggestions);
      setDataUnderstanding(res.data_understanding);
      if (res.suggestions.length > 0) {
        setTargetTable(res.suggestions[0].table_name);
      } else {
        setManualMode(true);
      }
    } catch (err) {
      console.error("Failed to suggest target table:", err);
      setManualMode(true);
    } finally {
      setIsAnalyzing(false);
    }
  }, []);

  useEffect(() => () => clearTimers(), [clearTimers]);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files?.[0];
    if (f) {
      setFile(f);
      setError(null);
      analyzeFile(f);
    }
  }, [analyzeFile]);

  const onSelect = useCallback((f: File | null) => {
    if (!f) return;
    setFile(f);
    setError(null);
    analyzeFile(f);
  }, [analyzeFile]);

  function reset() {
    clearTimers();
    setFile(null);
    setProposal(null);
    setError(null);
    setPhase("idle");
    setStepIndex(0);
    setStepStatus(STEPS.map(() => "pending"));
    setSuggestions(null);
    setDataUnderstanding(null);
    setManualMode(false);
    setIsAnalyzing(false);
    setDescriptionMd("");
    setExtraParams([{ key: "", value: "" }]);
    if (inputRef.current) inputRef.current.value = "";
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) {
      setError("Please choose a file to ingest.");
      return;
    }
    clearTimers();
    setPhase("reasoning");
    setStepIndex(0);
    setStepStatus(STEPS.map(() => "pending"));
    setError(null);

    // Schedule step progression
    for (let i = 0; i < STEPS.length; i++) {
      const idx = i;
      const t = setTimeout(() => {
        setStepStatus((prev) => {
          const next = [...prev];
          if (idx > 0) next[idx - 1] = "done";
          next[idx] = "active";
          return next;
        });
        setStepIndex(idx);
      }, idx * STEP_DURATION_MS);
      stepTimers.current.push(t);
    }

    try {
      const extraParamsObj: Record<string, string> = {};
      extraParams.forEach((param) => {
        if (param.key.trim()) {
          extraParamsObj[param.key.trim()] = param.value;
        }
      });
      const p = await ingestFile(file, targetTable, descriptionMd, extraParamsObj);
      clearTimers();
      setStepStatus((prev) => {
        const next = [...prev];
        for (let i = 0; i < STEPS.length; i++) next[i] = "done";
        return next;
      });
      setStepIndex(STEPS.length);
      setProposal(p);
      setPhase("resolution");
    } catch (err) {
      clearTimers();
      setStepStatus((prev) => {
        const next = [...prev];
        const failedAt = stepIndex;
        for (let i = 0; i < failedAt; i++) next[i] = "done";
        if (failedAt < STEPS.length) next[failedAt] = "error";
        return next;
      });
      setError(String((err as Error).message ?? err));
      setPhase("error");
    }
  }

  return (
    <div className="space-y-8 anim-fade">
      <PageHeader
        title="Ingest"
        description="Upload a data file. The agent will detect schema drift, build a context bundle from the knowledge graph, and submit a proposal for your review."
      />

      {phase === "idle" || phase === "error" ? (
        <form onSubmit={handleSubmit} className="grid grid-cols-3 gap-6">
          <div className="col-span-2 space-y-4">
            <div>
              <label className="label">Source file</label>
              <div
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={onDrop}
                onClick={() => inputRef.current?.click()}
                className={clsx(
                  "rounded-lg border-2 border-dashed cursor-pointer transition-colors",
                  dragging
                    ? "border-fg bg-bg-subtle"
                    : "border-border hover:border-fg-subtle hover:bg-bg-subtle",
                  "px-6 py-12 text-center",
                )}
              >
                <input
                  ref={inputRef}
                  type="file"
                  accept=".csv,.json"
                  className="hidden"
                  onChange={(e) => onSelect(e.target.files?.[0] ?? null)}
                />
                {file ? (
                  <div className="space-y-1.5">
                    <div className="text-sm font-medium">{file.name}</div>
                    <div className="text-2xs text-fg-muted font-mono">
                      {formatBytes(file.size)} ·{" "}
                      {file.type || "application/octet-stream"}
                    </div>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        reset();
                      }}
                      className="text-2xs text-fg-muted hover:text-fg underline mt-2"
                    >
                      Choose a different file
                    </button>
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    <div className="text-sm font-medium text-fg">
                      Drop your file here
                    </div>
                    <div className="text-2xs text-fg-muted">
                      or click to browse · CSV or JSON · up to 50MB
                    </div>
                  </div>
                )}
              </div>
            </div>

            {isAnalyzing && (
              <div className="rounded-lg border border-border bg-bg-subtle p-6 text-center space-y-3 anim-in">
                <div className="flex justify-center">
                  <svg className="animate-spin h-6 w-6 text-fg" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                </div>
                <div className="text-sm font-medium">Analyzing data schema & semantics...</div>
                <div className="text-2xs text-fg-muted">Profiling columns, value distributions, and querying AI relations</div>
              </div>
            )}

            {!isAnalyzing && file && (
              <div className="space-y-4 anim-in">
                <div>
                  <label className="label" htmlFor="description_md">
                    Dataset Description (Markdown)
                  </label>
                  <textarea
                    id="description_md"
                    className="input min-h-24 py-2 h-auto text-sm leading-relaxed"
                    placeholder="Enter a description of this data in markdown format (e.g., details about columns, expected formats, or business logic)..."
                    value={descriptionMd}
                    onChange={(e) => setDescriptionMd(e.target.value)}
                  />
                  <p className="text-2xs text-fg-muted">
                    This context helps the AI understand the business purpose of the dataset and perform better transformations.
                  </p>
                </div>

                <div>
                  <label className="label">Extra Parameters</label>
                  <p className="text-2xs text-fg-muted mb-2">
                    Add custom key-value pairs (e.g. source_system, batch_id, environment) to attach to the ingested dataset.
                  </p>
                  <div className="space-y-2">
                    {extraParams.map((param, index) => (
                      <div key={index} className="flex gap-2 items-center">
                        <input
                          type="text"
                          placeholder="Key (e.g., source_system)"
                          value={param.key}
                          onChange={(e) => {
                            const updated = [...extraParams];
                            updated[index].key = e.target.value;
                            setExtraParams(updated);
                          }}
                          className="input font-mono text-xs flex-1"
                        />
                        <input
                          type="text"
                          placeholder="Value (e.g., sap_erp)"
                          value={param.value}
                          onChange={(e) => {
                            const updated = [...extraParams];
                            updated[index].value = e.target.value;
                            setExtraParams(updated);
                          }}
                          className="input font-mono text-xs flex-1"
                        />
                        <button
                          type="button"
                          onClick={() => {
                            const updated = extraParams.filter((_, i) => i !== index);
                            setExtraParams(updated.length > 0 ? updated : [{ key: "", value: "" }]);
                          }}
                          className="btn-danger h-9 px-2.5 flex items-center justify-center flex-shrink-0"
                          title="Remove Parameter"
                        >
                          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                          </svg>
                        </button>
                      </div>
                    ))}
                    <button
                      type="button"
                      onClick={() => setExtraParams([...extraParams, { key: "", value: "" }])}
                      className="btn-secondary text-xs h-8 px-3.5 flex items-center gap-1 mt-1"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
                      </svg>
                      Add Parameter
                    </button>
                  </div>
                </div>

                {dataUnderstanding && (
                  <div className="rounded-md bg-bg-subtle border border-border p-3">
                    <div className="text-2xs font-semibold uppercase tracking-wider text-fg-muted mb-1 flex items-center gap-1.5">
                      <svg className="w-3.5 h-3.5 text-success" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 21l8.982-8.982M18 10a3 3 0 11-6 0 3 3 0 016 0z" />
                      </svg>
                      AI Data Understanding
                    </div>
                    <p className="text-xs text-fg leading-relaxed">{dataUnderstanding}</p>
                  </div>
                )}

                {manualMode ? (
                  <div className="space-y-2">
                    <div className="flex justify-between items-center">
                      <label className="label" htmlFor="target_table">
                        Target table
                      </label>
                      {suggestions && suggestions.length > 0 && (
                        <button
                          type="button"
                          onClick={() => setManualMode(false)}
                          className="text-2xs text-fg-muted hover:text-fg underline font-mono"
                        >
                          Use suggestions
                        </button>
                      )}
                    </div>
                    <input
                      id="target_table"
                      type="text"
                      className="input font-mono"
                      value={targetTable}
                      onChange={(e) => setTargetTable(e.target.value)}
                      placeholder="e.g. orders_clean"
                    />
                    <p className="text-2xs text-fg-muted">
                      Type the target table registered in the conduit metadata store
                    </p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    <div className="flex justify-between items-center">
                      <label className="label">Suggested Target Table</label>
                      <button
                        type="button"
                        onClick={() => setManualMode(true)}
                        className="text-2xs text-fg-muted hover:text-fg underline font-mono"
                      >
                        Enter manually
                      </button>
                    </div>

                    {suggestions && suggestions.length > 0 ? (
                      <div className="space-y-3">
                        {suggestions.map((sug) => {
                          const isSelected = targetTable === sug.table_name;
                          const scorePercent = Math.round(sug.final_score * 100);
                          const scoreColor =
                            sug.final_score > 0.8
                              ? "bg-success-bg text-success border-success-border"
                              : sug.final_score > 0.5
                              ? "bg-warning-bg text-warning border-warning-border"
                              : "bg-danger-bg text-danger border-danger-border";

                          return (
                            <div
                              key={sug.table_name}
                              onClick={() => setTargetTable(sug.table_name)}
                              className={clsx(
                                "p-4 rounded-lg border-2 transition-all cursor-pointer flex flex-col gap-2.5",
                                isSelected
                                  ? "border-fg bg-white"
                                  : "border-border hover:border-fg-subtle bg-bg-subtle",
                              )}
                            >
                              <div className="flex justify-between items-start">
                                <div className="space-y-0.5">
                                  <div className="flex items-center gap-2">
                                    <span className="font-mono text-sm font-semibold">{sug.table_name}</span>
                                    {sug === suggestions[0] && (
                                      <span className="badge bg-fg text-bg text-3xs font-semibold px-1 py-0.25 uppercase tracking-wider rounded">
                                        Best Match
                                      </span>
                                    )}
                                  </div>
                                </div>
                                <span className={clsx("badge border text-xs px-2 py-0.5 font-bold font-mono", scoreColor)}>
                                  {scorePercent}% match
                                </span>
                              </div>

                              <p className="text-xs text-fg-muted italic leading-relaxed">
                                &ldquo;{sug.llm_reasoning}&rdquo;
                              </p>

                              <div className="flex flex-wrap gap-2 text-3xs font-mono mt-1">
                                <span className="text-success bg-success-bg border border-success-border px-1.5 py-0.5 rounded">
                                  ✓ {sug.matched_columns.length} matched
                                </span>
                                {sug.missing_columns.length > 0 && (
                                  <span className="text-warning bg-warning-bg border border-warning-border px-1.5 py-0.5 rounded">
                                    ⚠️ {sug.missing_columns.length} missing in upload
                                  </span>
                                )}
                                {sug.extra_columns.length > 0 && (
                                  <span className="text-fg-muted bg-bg-subtle border border-border px-1.5 py-0.5 rounded">
                                    + {sug.extra_columns.length} extra columns
                                  </span>
                                )}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="rounded-lg border border-border p-4 text-center text-xs text-fg-muted bg-bg-subtle">
                        No matching tables found. Please click &quot;Enter manually&quot; above.
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {error ? (
              <div className="rounded-md border border-danger-border bg-danger-bg p-3 text-sm text-danger">
                {error}
              </div>
            ) : null}

            <div className="flex items-center gap-2">
              <button
                type="submit"
                className="btn-primary"
                disabled={!file || isAnalyzing}
              >
                Generate proposal
              </button>
              <button
                type="button"
                onClick={reset}
                className="btn-ghost"
              >
                Reset
              </button>
            </div>
          </div>

          <aside className="space-y-4">
            <div className="panel">
              <div className="panel-header">
                <h3 className="text-sm font-semibold">How it works</h3>
              </div>
              <ol className="panel-body text-sm text-fg-muted space-y-2 list-decimal list-inside">
                <li>Schema detection on the uploaded file</li>
                <li>Comparison against target metadata</li>
                <li>Context bundle built from the knowledge graph</li>
                <li>AI generates a transformation plan and a gateway classification</li>
                <li>Generated code is AST-validated for safety</li>
                <li>You review and approve the proposal</li>
              </ol>
            </div>

            <div className="panel">
              <div className="panel-header">
                <h3 className="text-sm font-semibold">Try the demo files</h3>
              </div>
              <ul className="panel-body text-2xs font-mono text-fg-muted space-y-1.5">
                <li>db/demo_csvs/clean_orders.csv</li>
                <li>db/demo_csvs/drifted_orders.csv</li>
                <li>db/demo_csvs/conflicted_orders.csv</li>
              </ul>
            </div>
          </aside>
        </form>
      ) : phase === "reasoning" ? (
        <ReasoningView
          stepIndex={stepIndex}
          stepStatus={stepStatus}
          file={file}
        />
      ) : phase === "resolution" && proposal ? (
        <ProposalReview proposal={proposal} onReset={reset} />
      ) : null}
    </div>
  );
}

function StepDot({ status }: { status: StepStatus }) {
  if (status === "done") {
    return (
      <span className="w-5 h-5 rounded-full bg-success flex items-center justify-center text-white">
        <svg
          width="10"
          height="10"
          viewBox="0 0 10 10"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
        >
          <path d="M2 5L4 7L8 3" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
    );
  }
  if (status === "active") {
    return (
      <span className="relative w-5 h-5 rounded-full bg-fg flex items-center justify-center">
        <span className="absolute inset-0 rounded-full bg-fg anim-fade" />
        <span className="relative w-1.5 h-1.5 rounded-full bg-white" />
      </span>
    );
  }
  if (status === "error") {
    return (
      <span className="w-5 h-5 rounded-full bg-danger flex items-center justify-center text-white">
        <svg
          width="10"
          height="10"
          viewBox="0 0 10 10"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
        >
          <path d="M2 2L8 8M8 2L2 8" strokeLinecap="round" />
        </svg>
      </span>
    );
  }
  return (
    <span className="w-5 h-5 rounded-full border border-border-strong bg-white" />
  );
}

function ReasoningView({
  stepIndex,
  stepStatus,
  file,
}: {
  stepIndex: number;
  stepStatus: StepStatus[];
  file: File | null;
}) {
  const done = stepStatus.filter((s) => s === "done").length;
  const pct = (done / STEPS.length) * 100;
  return (
    <div className="space-y-4 anim-in">
      <div className="panel">
        <div className="panel-header">
          <div>
            <h2 className="text-sm font-semibold">AI reasoning</h2>
            <p className="text-2xs text-fg-muted mt-0.5">
              {file
                ? `Processing ${file.name} · ${formatBytes(file.size)}`
                : "Processing…"}
            </p>
          </div>
          <span className="text-2xs text-fg-muted font-mono tabular-nums">
            {done}/{STEPS.length}
          </span>
        </div>
        <div className="h-1 bg-bg-subtle overflow-hidden">
          <div
            className="h-full bg-fg transition-all duration-300 ease-out"
            style={{ width: `${pct}%` }}
          />
        </div>
        <ul className="panel-body divide-y divide-border-subtle">
          {STEPS.map((s, i) => {
            const status = stepStatus[i] ?? "pending";
            return (
              <li
                key={i}
                className={clsx(
                  "py-3 first:pt-0 last:pb-0 flex items-start gap-3 transition-opacity duration-150",
                  status === "pending" ? "opacity-50" : "opacity-100",
                )}
              >
                <div className="pt-0.5">
                  <StepDot status={status} />
                </div>
                <div className="min-w-0 flex-1">
                  <div
                    className={clsx(
                      "text-sm font-medium font-mono transition-colors",
                      status === "active"
                        ? "text-fg"
                        : status === "pending"
                        ? "text-fg-muted"
                        : "text-fg",
                    )}
                  >
                    {s.label}
                  </div>
                  <div className="text-2xs text-fg-muted mt-0.5 leading-relaxed">
                    {s.description}
                  </div>
                </div>
                <div className="text-2xs font-mono text-fg-subtle pt-1">
                  0{i + 1}
                </div>
              </li>
            );
          })}
        </ul>
      </div>

      {stepIndex < STEPS.length ? (
        <div className="text-2xs text-fg-muted text-center font-mono">
          step {stepIndex + 1} of {STEPS.length}
        </div>
      ) : null}
    </div>
  );
}

function ProposalReview({
  proposal,
  onReset,
}: {
  proposal: ProposalResponse;
  onReset: () => void;
}) {
  const confidencePct = Math.round(proposal.confidence_score * 100);
  const confidenceColor =
    proposal.confidence_score > 0.9
      ? "text-success"
      : proposal.confidence_score > 0.75
      ? "text-warning"
      : "text-danger";

  return (
    <div className="space-y-6 anim-in">
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold tracking-tight">
              Proposal review
            </h2>
            <GatewayBadge status={proposal.gateway_status} />
          </div>
          <p className="text-2xs text-fg-muted font-mono">
            {proposal.proposal_id}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={onReset} className="btn-secondary">
            Start over
          </button>
          <Link
            href={`/proposals/${proposal.proposal_id}`}
            className="btn-primary"
          >
            Open detail view →
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-4">
        <div className="card p-4">
          <div className="text-2xs font-medium uppercase tracking-wider text-fg-muted">
            Confidence
          </div>
          <div
            className={clsx(
              "mt-2 text-2xl font-semibold tabular-nums",
              confidenceColor,
            )}
          >
            {confidencePct}%
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
        <div className="card p-4">
          <div className="text-2xs font-medium uppercase tracking-wider text-fg-muted">
            Drift items
          </div>
          <div className="mt-2 text-2xl font-semibold tabular-nums">
            {proposal.drift_detected.length}
          </div>
        </div>
        <div className="card p-4">
          <div className="text-2xs font-medium uppercase tracking-wider text-fg-muted">
            Estimated rows
          </div>
          <div className="mt-2 text-2xl font-semibold tabular-nums">
            {proposal.estimated_rows.toLocaleString()}
          </div>
        </div>
        <div className="card p-4">
          <div className="text-2xs font-medium uppercase tracking-wider text-fg-muted">
            PII columns
          </div>
          <div className="mt-2 text-sm font-medium truncate">
            {proposal.pii_columns_found.length === 0
              ? "None detected"
              : proposal.pii_columns_found.join(", ")}
          </div>
        </div>
      </div>

      {proposal.reasoning || proposal.reasoning_note ? (
        <div className="panel">
          <div className="panel-header">
            <div>
              <h3 className="text-sm font-semibold">AI reasoning</h3>
              <p className="text-2xs text-fg-muted mt-0.5">
                Why the agent made this decision
              </p>
            </div>
          </div>
          <div className="panel-body space-y-3 text-sm leading-relaxed">
            {proposal.reasoning ? (
              <p className="text-fg">{proposal.reasoning}</p>
            ) : null}
            {proposal.reasoning_note ? (
              <p className="text-2xs text-fg-muted">{proposal.reasoning_note}</p>
            ) : null}
          </div>
        </div>
      ) : null}

      <div className="panel">
        <div className="panel-header">
          <h3 className="text-sm font-semibold">Drift detected</h3>
          <span className="text-2xs text-fg-muted font-mono">
            {proposal.drift_detected.length} items
          </span>
        </div>
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
                  <td className="text-fg-muted text-2xs font-mono">
                    {d.source_value || "—"}
                  </td>
                  <td className="text-fg-muted text-2xs font-mono">
                    {d.target_expectation || "—"}
                  </td>
                  <td className="text-sm">{d.suggested_action}</td>
                  <td>
                    <span
                      className={clsx(
                        "badge uppercase tracking-wider",
                        d.severity === "HIGH" &&
                          "text-danger bg-danger-bg border-danger-border",
                        d.severity === "MEDIUM" &&
                          "text-warning bg-warning-bg border-warning-border",
                        d.severity === "LOW" &&
                          "text-fg-muted bg-bg-subtle border-border",
                      )}
                    >
                      {d.severity}
                    </span>
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
    </div>
  );
}
