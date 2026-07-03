import type {
  AuditEntry,
  ApproveRequest,
  CreateGraphEdgeRequest,
  CreateGraphNodeRequest,
  CreateSkillRequest,
  ExecutionResult,
  GraphEdgeResponse,
  GraphNodeResponse,
  ImpactAnalysisResponse,
  LineageEventResponse,
  LineageGraphResponse,
  NeighborsResponse,
  ProposalContextResponse,
  ProposalResponse,
  QuarantineEntry,
  RejectRequest,
  SkillDetailResponse,
  SkillResponse,
  SuggestTargetResponse,
  InsightItem,
  ConnectorProvider,
  ConnectorConnection,
  RegisterConnectorRequest,
} from "./types";

/* ─── Helpers ──────────────────────────────────────────────── */

const NEXT_PUBLIC_API_URL =
  (typeof window !== "undefined" ? (window as any).NEXT_PUBLIC_API_URL : null) ||
  process.env.NEXT_PUBLIC_API_URL ||
  "";

async function apiRequest<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${NEXT_PUBLIC_API_URL}${path}`;
  const res = await fetch(url, options);
  if (!res.ok) {
    let errText = "";
    try {
      const data = await res.json();
      const detail = data.detail;
      if (typeof detail === "string") {
        errText = detail;
      } else if (detail && typeof detail === "object") {
        errText = (detail as any).detail ?? JSON.stringify(detail);
      } else {
        errText = JSON.stringify(data);
      }
    } catch {
      try { errText = await res.text(); } catch {}
    }
    throw new Error(errText || `API request failed (status ${res.status})`);
  }
  return res.json() as Promise<T>;
}

/* ─── Ingest / Proposals / Execution ──────────────────────── */

export async function ingestFile(file: File, targetTable: string, descriptionMd?: string): Promise<ProposalResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("target_table", targetTable);
  if (descriptionMd) formData.append("description_md", descriptionMd);
  return apiRequest<ProposalResponse>("/api/ingest", { method: "POST", body: formData });
}

export async function suggestTargetTable(file: File): Promise<SuggestTargetResponse> {
  const formData = new FormData();
  formData.append("file", file);
  return apiRequest<SuggestTargetResponse>("/api/suggest-target", { method: "POST", body: formData });
}

export async function listProposals(params?: { limit?: number; offset?: number; status?: string }): Promise<ProposalResponse[]> {
  const q = new URLSearchParams();
  if (params?.limit !== undefined) q.append("limit", String(params.limit));
  if (params?.offset !== undefined) q.append("offset", String(params.offset));
  if (params?.status && params.status !== "ALL") q.append("status", params.status);
  const qs = q.toString();
  return apiRequest<ProposalResponse[]>(`/api/proposals${qs ? "?" + qs : ""}`);
}

export async function getProposal(id: string): Promise<ProposalResponse> {
  return apiRequest<ProposalResponse>(`/api/proposals/${id}`);
}

export async function getProposalContext(id: string): Promise<ProposalContextResponse> {
  return apiRequest<ProposalContextResponse>(`/api/proposals/${id}/context`);
}

export async function approveProposal(id: string, body: ApproveRequest): Promise<ExecutionResult> {
  return apiRequest<ExecutionResult>(`/api/proposals/${id}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function rejectProposal(id: string, body: RejectRequest): Promise<{ status: string }> {
  return apiRequest<{ status: string }>(`/api/proposals/${id}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/* ─── Audit / Quarantine ────────────────────────────────────── */

export async function listAudit(limit = 50, offset = 0): Promise<AuditEntry[]> {
  return apiRequest<AuditEntry[]>(`/api/audit?limit=${limit}&offset=${offset}`);
}

export async function listAuditForProposal(proposalId: string): Promise<AuditEntry[]> {
  return apiRequest<AuditEntry[]>(`/api/audit?proposal_id=${proposalId}`);
}

export async function getAuditEntry(id: number): Promise<AuditEntry> {
  return apiRequest<AuditEntry>(`/api/audit/${id}`);
}

export async function listQuarantine(): Promise<QuarantineEntry[]> {
  return apiRequest<QuarantineEntry[]>("/api/quarantine");
}

export async function getQuarantineForProposal(proposalId: string): Promise<QuarantineEntry[]> {
  return apiRequest<QuarantineEntry[]>(`/api/quarantine/${proposalId}`);
}

/* ─── Connectors ────────────────────────────────────────────── */

export async function listProviders(): Promise<ConnectorProvider[]> {
  const data = await apiRequest<{ providers: ConnectorProvider[] }>("/api/connectors/providers");
  return data.providers;
}

export async function listConnections(): Promise<ConnectorConnection[]> {
  return apiRequest<ConnectorConnection[]>("/api/connectors");
}

export async function registerConnector(body: RegisterConnectorRequest): Promise<{ status: string; conn_id: string; latency_ms: number }> {
  return apiRequest("/api/connectors/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function disconnectConnector(connId: string): Promise<{ status: string }> {
  return apiRequest(`/api/connectors/${connId}`, { method: "DELETE" });
}

export async function syncConnectorGraph(connId: string, tableNames?: string): Promise<{ status: string }> {
  const qs = tableNames ? `?table_names=${encodeURIComponent(tableNames)}` : "";
  return apiRequest(`/api/connectors/${connId}/sync-graph${qs}`, { method: "POST" });
}

/* ─── Skills ───────────────────────────────────────────────── */

export async function listSkills(params?: { category?: string; status?: string; limit?: number; offset?: number }): Promise<SkillResponse[]> {
  const q = new URLSearchParams();
  if (params?.limit !== undefined) q.append("limit", String(params.limit));
  if (params?.offset !== undefined) q.append("offset", String(params.offset));
  if (params?.category && params.category !== "ALL") q.append("category", params.category);
  if (params?.status && params.status !== "ALL") q.append("status", params.status);
  const qs = q.toString();
  return apiRequest<SkillResponse[]>(`/api/skills${qs ? "?" + qs : ""}`);
}

export async function searchSkills(q: string): Promise<SkillResponse[]> {
  return apiRequest<SkillResponse[]>(`/api/skills/search?q=${encodeURIComponent(q)}`);
}

export async function getSkill(id: number): Promise<SkillDetailResponse> {
  return apiRequest<SkillDetailResponse>(`/api/skills/${id}`);
}

export async function createSkill(body: CreateSkillRequest): Promise<SkillResponse> {
  return apiRequest<SkillResponse>("/api/skills", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/* ─── Graph ────────────────────────────────────────────────── */

export async function listGraphNodes(params?: { node_type?: string; limit?: number; offset?: number }): Promise<GraphNodeResponse[]> {
  const q = new URLSearchParams();
  if (params?.limit !== undefined) q.append("limit", String(params.limit));
  if (params?.offset !== undefined) q.append("offset", String(params.offset));
  if (params?.node_type) q.append("node_type", params.node_type);
  const qs = q.toString();
  return apiRequest<GraphNodeResponse[]>(`/api/graph/nodes${qs ? "?" + qs : ""}`);
}

export async function listGraphEdges(params?: { relation_type?: string; limit?: number; offset?: number }): Promise<GraphEdgeResponse[]> {
  const q = new URLSearchParams();
  if (params?.limit !== undefined) q.append("limit", String(params.limit));
  if (params?.offset !== undefined) q.append("offset", String(params.offset));
  if (params?.relation_type) q.append("relation_type", params.relation_type);
  const qs = q.toString();
  return apiRequest<GraphEdgeResponse[]>(`/api/graph/edges${qs ? "?" + qs : ""}`);
}

export async function getGraphLineage(entity: string, maxDepth = 4): Promise<LineageGraphResponse> {
  return apiRequest<LineageGraphResponse>(`/api/graph/lineage/${encodeURIComponent(entity)}?max_depth=${maxDepth}`);
}

export async function getGraphImpact(entity: string, maxDepth = 4): Promise<ImpactAnalysisResponse> {
  return apiRequest<ImpactAnalysisResponse>(`/api/graph/impact/${encodeURIComponent(entity)}?max_depth=${maxDepth}`);
}

export async function getGraphNeighbors(nodeId: number): Promise<NeighborsResponse> {
  return apiRequest<NeighborsResponse>(`/api/graph/neighbors/${nodeId}`);
}

export async function createGraphNode(body: CreateGraphNodeRequest): Promise<GraphNodeResponse> {
  return apiRequest<GraphNodeResponse>("/api/graph/nodes", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
}

export async function createGraphEdge(body: CreateGraphEdgeRequest): Promise<GraphEdgeResponse> {
  return apiRequest<GraphEdgeResponse>("/api/graph/edges", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
}

/* ─── Lineage ──────────────────────────────────────────────── */

export async function listLineage(params?: { limit?: number; offset?: number }): Promise<LineageEventResponse[]> {
  const q = new URLSearchParams();
  if (params?.limit !== undefined) q.append("limit", String(params.limit));
  if (params?.offset !== undefined) q.append("offset", String(params.offset));
  const qs = q.toString();
  return apiRequest<LineageEventResponse[]>(`/api/lineage${qs ? "?" + qs : ""}`);
}

export async function getLineageForProposal(proposalId: string): Promise<LineageEventResponse[]> {
  return apiRequest<LineageEventResponse[]>(`/api/lineage/${proposalId}`);
}

/* ─── Insights ─────────────────────────────────────────────── */

export async function listInsights(params?: { category?: string; severity?: string; limit?: number; offset?: number }): Promise<InsightItem[]> {
  const q = new URLSearchParams();
  if (params?.limit !== undefined) q.append("limit", String(params.limit));
  if (params?.offset !== undefined) q.append("offset", String(params.offset));
  if (params?.category) q.append("category", params.category);
  if (params?.severity) q.append("severity", params.severity);
  const qs = q.toString();
  return apiRequest<InsightItem[]>(`/api/insights${qs ? "?" + qs : ""}`);
}

export async function getInsightsForProposal(proposalId: string): Promise<InsightItem[]> {
  return apiRequest<InsightItem[]>(`/api/insights/${proposalId}`);
}

export async function getInsightsSummary(): Promise<{
  total: number; by_category: Record<string, number>; by_severity: Record<string, number>; recent_critical: InsightItem[];
}> {
  return apiRequest("/api/insights/summary");
}
