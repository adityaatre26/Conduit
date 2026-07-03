export type GatewayStatus = "AUTO_LINK" | "SCHEMA_EVOLUTION" | "CONFLICT";
export type IssueType =
  | "RENAME"
  | "EXTRA_COLUMN"
  | "TYPE_MISMATCH"
  | "NULL_VIOLATION"
  | "MISSING_REQUIRED";
export type Severity = "LOW" | "MEDIUM" | "HIGH";
export type ProposalStatus =
  | "PENDING"
  | "APPROVED"
  | "REJECTED"
  | "EXECUTED"
  | "FAILED";

export interface DriftItem {
  column: string;
  issue_type: IssueType;
  source_value: string;
  target_expectation: string;
  suggested_action: string;
  severity: Severity;
}

export interface ProposalResponse {
  proposal_id: string;
  gateway_status: GatewayStatus;
  target_table?: string | null;
  drift_detected: DriftItem[];
  proposed_steps: string[];
  generated_code: string;
  confidence_score: number;
  pii_columns_found: string[];
  estimated_rows: number;
  llm_model_used: string;
  reasoning?: string | null;
  reasoning_note?: string | null;
  description_md?: string | null;
  suggested_skills_to_add?: Array<{
    skill_name: string;
    description: string;
    category: string;
  }> | null;
  enrichment_applied?: string[] | null;
}

export interface ExecutionResult {
  proposal_id: string;
  rows_written: number;
  rows_quarantined: number;
  execution_status: string;
  duration_ms: number;
  insights?: InsightItem[] | null;
}

export type InsightCategory = "CONCENTRATION" | "ANOMALY" | "DATA_QUALITY" | "TREND" | "PATTERN";
export type InsightSeverity = "INFO" | "WARNING" | "CRITICAL";

export interface InsightItem {
  id: number;
  proposal_id: string;
  category: InsightCategory;
  severity: InsightSeverity;
  title: string;
  description: string;
  evidence?: Record<string, unknown> | null;
  created_at?: string | null;
}

export interface InsightSummary {
  proposal_id: string;
  target_table: string;
  rows_analyzed: number;
  insights: InsightItem[];
  generated_at?: string | null;
}

export interface AuditEntry {
  id: number;
  proposal_id: string;
  filename: string;
  skill_name: string;
  execution_status: string;
  human_approver_id: string;
  executed_at: string;
  llm_prompt_sent: string;
  llm_raw_response: string;
  transformation_script_ref: string;
}

export interface QuarantineEntry {
  id: number;
  proposal_id: string;
  raw_row: Record<string, unknown>;
  failure_reason: string;
  quarantined_at: string;
}

export interface WarehouseUnitResponse {
  id: number;
  name: string;
  unit_type: string;
  status: "CONNECTED" | "UNREACHABLE";
}

export interface ApproveRequest {
  human_approver_id: string;
}

export interface RejectRequest {
  reason: string;
}

/* ─── Connector types ──────────────────────────────────────── */

export interface ConnectorProvider {
  type: string;
  credential_fields: string[];
}

export interface ConnectorConnection {
  id: string;
  type: string;
  display_name: string;
  status: "connected" | "disconnected";
  read_only: boolean;
  connected_at?: number | null;
}

export interface RegisterConnectorRequest {
  conn_id: string;
  db_type: string;
  credentials: Record<string, unknown>;
  read_only?: boolean;
  display_name?: string;
}

/* ─── Extension types ──────────────────────────────────────── */

export type SkillStatus = "ACTIVE" | "DRAFT" | "DEPRECATED";

export interface SkillResponse {
  id: number;
  skill_name: string;
  version: string;
  category: string;
  description: string;
  use_cases?: string | null;
  constraints?: string | null;
  owner?: string | null;
  status: SkillStatus;
  created_at?: string | null;
}

export interface SkillExample {
  input?: unknown;
  output?: unknown;
}

export interface SkillIssueRef {
  reference?: string | null;
  notes?: string | null;
}

export interface SkillDetailResponse extends SkillResponse {
  scripts?: Array<Record<string, unknown>>;
  examples?: SkillExample[];
  issue_references?: SkillIssueRef[];
}

export interface CreateSkillRequest {
  skill_name: string;
  version?: string;
  category: string;
  description: string;
  use_cases?: string | null;
  constraints?: string | null;
  owner?: string | null;
  status?: SkillStatus;
}

export interface GraphNodeResponse {
  id: number;
  node_type?: string | null;
  entity_id?: string | null;
  entity_name?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface GraphEdgeResponse {
  id: number;
  source_node_id: number;
  target_node_id: number;
  relation_type?: string | null;
  confidence_score?: number;
  created_at?: string | null;
}

export interface CreateGraphNodeRequest {
  node_type: string;
  entity_id: string;
  entity_name?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface CreateGraphEdgeRequest {
  source_node_id: number;
  target_node_id: number;
  relation_type: string;
  confidence_score?: number;
}

export interface LineageEventResponse {
  id: number;
  proposal_id?: string | null;
  source_entity?: string | null;
  target_entity?: string | null;
  operation_type?: string | null;
  skill_used?: string | null;
  executed_at?: string | null;
}

export interface LineageGraphResponse {
  nodes: GraphNodeResponse[];
  edges: GraphEdgeResponse[];
}

export interface ImpactedNode {
  node: GraphNodeResponse;
  depth: number;
  relation_type: string;
  path: string[];
}

export interface ImpactAnalysisResponse {
  entity: string;
  start_nodes: GraphNodeResponse[];
  impacted_nodes: ImpactedNode[];
  total_impacted: number;
}

export interface NeighborDetail {
  direction: string;
  relation_type?: string | null;
  confidence_score: number;
  node: GraphNodeResponse;
}

export interface NeighborsResponse {
  node_id: number;
  neighbors: NeighborDetail[];
  total: number;
}

export interface ProposalContextResponse {
  proposal_id: string;
  target_table?: string | null;
  context_bundle?: Record<string, unknown> | null;
  generated_at: string;
}

export interface TableSuggestion {
  table_name: string;
  final_score: number;
  column_match_score: number;
  data_profile_score: number;
  llm_confidence: number;
  llm_reasoning: string;
  matched_columns: string[];
  missing_columns: string[];
  extra_columns: string[];
}

export interface SuggestTargetResponse {
  data_understanding: string;
  incoming_columns: string[];
  suggestions: TableSuggestion[];
}
