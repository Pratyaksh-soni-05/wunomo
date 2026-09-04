const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Real DB connectivity check (unauthenticated, no tenant context) for the
// topbar's "AXIOM Online"/"AXIOM Offline" indicator - previously pure
// decoration that never checked anything real.
export async function checkDbHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/health/db`);
    return res.ok;
  } catch {
    return false;
  }
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : "Request failed");
    this.status = status;
    this.detail = detail;
  }
}

// A 401 on a request that carried a bearer token means the token is
// expired/invalid, not "wrong password" (those calls — login/register/
// email-code/Google — never send an Authorization header, so they're
// naturally excluded from this path). Central place to react to that,
// since every authed call in this file funnels through `request()`.
function handleSessionExpired() {
  clearSession();
  if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
    window.location.href = "/login?expired=1";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && new Headers(init?.headers).get("Authorization")) {
      handleSessionExpired();
    }
    throw new ApiError(res.status, body?.detail ?? body);
  }
  return body as T;
}

function authedRequest<T>(path: string, token: string): Promise<T> {
  return request(path, { headers: { Authorization: `Bearer ${token}` } });
}

// ---------- Shared response shapes ----------

export interface WorkspaceOption {
  tenant_id: string;
  tenant_name: string;
}

export interface AuthSuccess {
  access_token: string;
  token_type: string;
  user_id: string;
  tenant_id: string;
}

export interface ChooseWorkspace {
  status: "choose_workspace";
  options: WorkspaceOption[];
  // Present for email-code/Google (their proof is single-use and already
  // consumed by the time "choose" is returned) — absent for password login,
  // which finalizes by resubmitting the real password instead.
  resolution_token?: string;
}

export interface NoAccount {
  status: "no_account";
  detail: string;
}

export type IdentityResult = AuthSuccess | ChooseWorkspace | NoAccount;

function isChoose(r: IdentityResult): r is ChooseWorkspace {
  return (r as ChooseWorkspace).status === "choose_workspace";
}
function isNoAccount(r: IdentityResult): r is NoAccount {
  return (r as NoAccount).status === "no_account";
}
export { isChoose, isNoAccount };

// ---------- Password ----------

export async function register(params: {
  email: string;
  password: string;
  full_name: string;
  tenant_name: string;
}): Promise<AuthSuccess & { existing_workspaces: WorkspaceOption[] }> {
  return request("/api/v1/auth/register", { method: "POST", body: JSON.stringify(params) });
}

export async function login(
  username: string,
  password: string,
  tenant_id?: string
): Promise<AuthSuccess | ChooseWorkspace> {
  const form = new URLSearchParams();
  form.set("username", username);
  form.set("password", password);
  if (tenant_id) form.set("tenant_id", tenant_id);
  const res = await fetch(`${API_URL}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form.toString(),
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, body?.detail ?? body);
  return body;
}

// ---------- Email code ----------

export async function requestEmailCode(email: string, intended_tenant_id?: string): Promise<{ status: string }> {
  return request("/api/v1/auth/email-code/request", {
    method: "POST",
    body: JSON.stringify({ email, intended_tenant_id }),
  });
}

export async function verifyEmailCode(params: {
  email: string;
  code: string;
  tenant_id?: string;
  new_tenant_name?: string;
}): Promise<IdentityResult> {
  return request("/api/v1/auth/email-code/verify", { method: "POST", body: JSON.stringify(params) });
}

// ---------- Google ----------

export async function googleLoginUrl(): Promise<{ url: string; state: string }> {
  return request("/api/v1/auth/google/login-url");
}

export async function googleCallback(params: {
  code: string;
  state: string;
  intended_tenant_id?: string;
  new_tenant_name?: string;
}): Promise<IdentityResult> {
  return request("/api/v1/auth/google/callback", { method: "POST", body: JSON.stringify(params) });
}

export async function resolveWorkspace(resolution_token: string, tenant_id: string): Promise<AuthSuccess> {
  return request("/api/v1/auth/resolve-workspace", {
    method: "POST",
    body: JSON.stringify({ resolution_token, tenant_id }),
  });
}

// ---------- Workspace switcher (item 1) ----------

export function getMyWorkspaces(token: string): Promise<{ options: WorkspaceOption[] }> {
  return authedRequest("/api/v1/auth/my-workspaces", token);
}

export function switchWorkspace(token: string, tenant_id: string): Promise<AuthSuccess> {
  return request("/api/v1/auth/switch-workspace", {
    method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ tenant_id }),
  });
}

// ---------- Onboarding ----------

export interface OnboardingProfile {
  completed: boolean;
  role?: string;
  industry?: string;
  company_size?: string;
  use_cases?: string[];
  data_stack?: string[];
}

export async function getOnboarding(token: string): Promise<OnboardingProfile> {
  return request("/api/v1/onboarding/", { headers: { Authorization: `Bearer ${token}` } });
}

export async function submitOnboarding(
  token: string,
  params: {
    role: string;
    industry: string;
    company_size: string;
    use_cases: string[];
    data_stack: string[];
  }
): Promise<OnboardingProfile> {
  return request("/api/v1/onboarding/", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(params),
  });
}

// ---------- Dashboard (Phase 9) ----------

export interface AnalyticsOverview {
  tenant_id: string;
  evaluated_at: string;
  window_days: number;
  pipelines: { total: number; active: number; paused: number; draft: number; archived: number };
  runs: { total: number; success: number; failed: number; success_rate_pct: number };
  quality: { avg_score: number | null };
  incidents: { open: number };
  sources: { total_active: number; stale: number };
}

export interface QualityTrendPoint {
  date: string;
  run_count: number;
  pass_count: number;
  fail_count: number;
  avg_quality_score: number | null;
}

export interface RecentRun {
  run_id: string;
  pipeline_id: string;
  pipeline_name: string;
  status: string;
  rows_processed: number | null;
  duration_seconds: number | null;
  created_at: string | null;
}

export interface Approval {
  approval_id: string;
  user_id: string;
  action_name: string;
  action_args: Record<string, unknown>;
  risk_level: string;
  reason: string;
  status: string;
  created_at: string;
}

export interface Incident {
  id: string;
  title: string;
  description: string;
  severity: string;
  status: string;
  pipeline_id: string | null;
  detected_at: string;
}

export function getAnalyticsOverview(token: string): Promise<AnalyticsOverview> {
  return authedRequest("/api/v1/analytics", token);
}

export function getQualityTrends(token: string, windowDays = 7): Promise<{ trends: QualityTrendPoint[] }> {
  return authedRequest(`/api/v1/analytics/quality?window_days=${windowDays}`, token);
}

export function getRecentRuns(token: string, limit = 5): Promise<{ runs: RecentRun[] }> {
  return authedRequest(`/api/v1/analytics/recent-runs?limit=${limit}`, token);
}

export function getApprovals(token: string): Promise<{ approvals: Approval[]; count: number }> {
  return authedRequest("/api/v1/approvals", token);
}

export function approveRequest(token: string, approvalId: string): Promise<unknown> {
  return request(`/api/v1/approvals/${approvalId}/approve`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({}),
  });
}

export function rejectRequest(token: string, approvalId: string): Promise<unknown> {
  return request(`/api/v1/approvals/${approvalId}/reject`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({}),
  });
}

// getOpenIncidents used to call this same route with no status param at
// all - despite its name, it returned every incident regardless of status,
// which is why a resolved incident could sit in "open incidents" data and
// keep showing on the Dashboard's health banner indefinitely (finding 21).
// getIncidents() is the real general-purpose fetch (used by the Incidents
// screen, which genuinely needs the full history - it renders a Resolve
// button conditionally per row); getOpenIncidents() is now a thin wrapper
// that actually passes status=open, matching what its name has always
// implied and what the health banner actually needs.
export function getIncidents(token: string, status?: string): Promise<{ incidents: Incident[]; count: number }> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  return authedRequest(`/api/v1/incidents/${qs}`, token);
}

export function getOpenIncidents(token: string): Promise<{ incidents: Incident[]; count: number }> {
  return getIncidents(token, "open");
}

export interface ChatSessionSummary {
  session_id: string;
  title: string;
  started_at: string;
  last_activity: string;
  message_count: number;
}

export function getChatSessions(token: string): Promise<{ sessions: ChatSessionSummary[] }> {
  return authedRequest("/api/v1/chat/sessions", token);
}

export interface ChatToolCall {
  tool: string;
  args: Record<string, unknown>;
  result: unknown;
  // approval_approved/rejected/executed/failed are resolved from the real
  // ApprovalRequest at session-history read time (GET /chat/sessions/{id}/
  // history) -- a blocked call no longer stays frozen on
  // "blocked_pending_approval" forever once it's actually been resolved on
  // the Approvals screen. denied_insufficient_role comes from the
  // role-permission gate, separate from the risk-based approval gate.
  status:
    | "completed"
    | "blocked_pending_approval"
    | "approval_approved"
    | "approval_rejected"
    | "approval_executed"
    | "approval_failed"
    | "denied_insufficient_role";
  approval_id?: string;
}

export interface ChatMessageItem {
  role: "user" | "assistant";
  content: string;
  tool_calls: ChatToolCall[];
  timestamp: string;
}

export interface ChatContext {
  source_id: string;
  source_name: string;
}

export interface PendingApproval {
  name: string;
  args: Record<string, unknown>;
  risk_level: string;
  reason: string;
}

export interface ChatSendResponse {
  session_id: string;
  response: string;
  provider: string | null;
  pending_approvals: PendingApproval[];
  tool_calls: ChatToolCall[];
  timestamp: string;
}

export function sendChatMessage(
  token: string,
  params: {
    message: string;
    session_id?: string;
    personality_mode?: string;
    operation_mode?: string;
    context?: ChatContext;
  }
): Promise<ChatSendResponse> {
  return request("/api/v1/chat/", {
    method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(params),
  });
}

export function getChatHistory(token: string, sessionId: string): Promise<{ session_id: string; messages: ChatMessageItem[] }> {
  return authedRequest(`/api/v1/chat/sessions/${sessionId}/history`, token);
}

// Item 4: 409 (ApiError.status) means a pending approval still traces back
// to this session -- see chat.py's delete_session for why that's refused
// while a resolved one isn't.
export function deleteChatSession(token: string, sessionId: string): Promise<{ deleted: boolean; session_id: string }> {
  return request(`/api/v1/chat/sessions/${sessionId}`, {
    method: "DELETE", headers: { Authorization: `Bearer ${token}` },
  });
}

// ---------- Sources (Phase 12) ----------

export interface DataSourceItem {
  id: string;
  name: string;
  source_type: string;
  is_active: boolean;
  last_profiled_at: string | null;
  tags: string[];
  owner: string | null;
  created_at: string;
}

export function getSources(token: string): Promise<{ sources: DataSourceItem[]; count: number }> {
  return authedRequest("/api/v1/sources/", token);
}

export function createSource(
  token: string,
  params: { name: string; source_type: string; connection_config: Record<string, unknown> }
): Promise<{ id: string; name: string; source_type: string; status: string }> {
  return request("/api/v1/sources/", {
    method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(params),
  });
}

export function deleteSource(token: string, id: string): Promise<unknown> {
  return request(`/api/v1/sources/${id}`, { method: "DELETE", headers: { Authorization: `Bearer ${token}` } });
}

export function syncSource(token: string, id: string, mode = "incremental"): Promise<unknown> {
  return request(`/api/v1/sources/${id}/sync?mode=${mode}`, {
    method: "POST", headers: { Authorization: `Bearer ${token}` },
  });
}

export function profileSource(token: string, id: string): Promise<unknown> {
  return request(`/api/v1/sources/${id}/profile`, {
    method: "POST", headers: { Authorization: `Bearer ${token}` },
  });
}

// Multipart upload can't go through request() — it hardcodes
// "Content-Type: application/json", which would strip the multipart
// boundary fetch sets automatically for a FormData body.
export async function uploadAndRegisterSource(
  token: string,
  file: File,
  name?: string
): Promise<{ filename: string; source_id: string; ingest: unknown }> {
  const form = new FormData();
  form.append("file", file);
  if (name) form.append("name", name);
  const res = await fetch(`${API_URL}/api/v1/uploads/register`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401) handleSessionExpired();
    throw new ApiError(res.status, body?.detail ?? body);
  }
  return body;
}

// ---------- Pipelines (Phase 12) ----------

export interface PipelineItem {
  id: string;
  name: string;
  status: string;
  source_id: string | null;
  schedule_cron: string | null;
  description?: string | null;
  created_at?: string;
  last_run: {
    id: string;
    status: string;
    triggered_by: string;
    created_at: string;
    completed_at: string | null;
  } | null;
  next_run_at: string | null;
}

export interface PipelineRunItem {
  id: string;
  status: string;
  rows_processed: number | null;
  duration_seconds: number | null;
  created_at: string | null;
  error_message?: string | null;
}

export function getPipelines(token: string): Promise<{ pipelines: PipelineItem[]; count: number }> {
  return authedRequest("/api/v1/pipelines/", token);
}

export function createPipeline(
  token: string,
  params: { name: string; source_id?: string; description?: string; schedule_cron?: string }
): Promise<PipelineItem> {
  return request("/api/v1/pipelines/", {
    method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(params),
  });
}

export function deletePipeline(token: string, id: string): Promise<unknown> {
  return request(`/api/v1/pipelines/${id}`, { method: "DELETE", headers: { Authorization: `Bearer ${token}` } });
}

export function triggerPipelineRun(token: string, id: string): Promise<unknown> {
  return request(`/api/v1/pipelines/${id}/trigger`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
}

export function pausePipeline(token: string, id: string): Promise<unknown> {
  return request(`/api/v1/pipelines/${id}/pause`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
}

export function activatePipeline(token: string, id: string): Promise<unknown> {
  return request(`/api/v1/pipelines/${id}/activate`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
}

export function getPipelineRuns(
  token: string, id: string, limit = 20
): Promise<{ pipeline_id: string; pipeline_name: string; runs: PipelineRunItem[] }> {
  return authedRequest(`/api/v1/pipelines/${id}/runs?limit=${limit}`, token);
}

// ---------- Quality (Phase 12) ----------

export interface QualityRuleItem {
  id: string;
  pipeline_id: string;
  name: string;
  rule_type: string;
  column_name: string | null;
  severity: string;
  is_blocking: boolean;
  is_active?: boolean;
  pass_count?: number;
  fail_count?: number;
}

export function getQualityRules(token: string, pipelineId?: string): Promise<{ rules: QualityRuleItem[]; count: number }> {
  return authedRequest(`/api/v1/quality/${pipelineId ? `?pipeline_id=${pipelineId}` : ""}`, token);
}

export function createQualityRule(
  token: string,
  params: { pipeline_id: string; name: string; rule_type: string; column_name?: string; severity?: string; is_blocking?: boolean }
): Promise<unknown> {
  return request("/api/v1/quality/", {
    method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(params),
  });
}

export function runQualityChecks(token: string, pipelineId: string): Promise<unknown> {
  return request(`/api/v1/quality/${pipelineId}/run`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
}

export function deleteQualityRule(token: string, ruleId: string): Promise<unknown> {
  return request(`/api/v1/quality/${ruleId}`, { method: "DELETE", headers: { Authorization: `Bearer ${token}` } });
}

// ---------- Incidents (Phase 12) ----------

export function resolveIncident(token: string, id: string, resolution_notes: string): Promise<unknown> {
  return request(`/api/v1/incidents/${id}/resolve`, {
    method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ resolution_notes }),
  });
}

export function createIncident(
  token: string,
  params: { title: string; description?: string; severity?: string; pipeline_id?: string }
): Promise<unknown> {
  return request("/api/v1/incidents/", {
    method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(params),
  });
}

// ---------- CI/CD (Phase 12) ----------

export interface CommitItem {
  id: string;
  pipeline_id: string | null;
  commit_sha: string;
  branch: string;
  author: string | null;
  ci_status: string;
  gate_decision: string | null;
  risk_score: number;
  trigger_time: string;
  completed_at: string | null;
  error_message: string | null;
}

export interface DeploymentItem {
  id: string;
  pipeline_id: string;
  commit_sha: string;
  status: string;
  monitoring_active: boolean;
  post_deploy_run_count: number;
  post_deploy_failure_count: number;
  deployed_at: string | null;
  created_at: string;
}

export function getCommits(token: string, limit = 20): Promise<CommitItem[]> {
  return authedRequest(`/api/v1/cicd/commits?limit=${limit}`, token);
}

export function getDeployments(token: string, limit = 20): Promise<DeploymentItem[]> {
  return authedRequest(`/api/v1/cicd/deployments?limit=${limit}`, token);
}

export function getCicdStatusSummary(token: string): Promise<Record<string, unknown>> {
  return authedRequest("/api/v1/cicd/status/summary", token);
}

export function approveCommit(token: string, commitId: string): Promise<unknown> {
  return request(`/api/v1/cicd/commits/${commitId}/approve`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
}

export function rejectCommit(token: string, commitId: string): Promise<unknown> {
  return request(`/api/v1/cicd/commits/${commitId}/reject`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
}

// ---------- Approvals — merged (Phase 12) ----------

export interface MergedApproval {
  id: string;
  source: "policy_engine" | "cicd_deployment";
  title: string;
  description: string;
  risk_level: string;
  created_at: string;
  raw: Record<string, unknown>;
}

export function getMergedApprovals(token: string): Promise<{ approvals: MergedApproval[]; count: number }> {
  return authedRequest("/api/v1/approvals/merged", token);
}

// ---------- Governance (Phase 12) ----------

export interface LineageNode {
  id: string;
  name: string;
  node_type: string;
  metadata: Record<string, unknown>;
  created_at: string | null;
}

export interface LineageEdge {
  edge_id: string;
  upstream_id: string;
  downstream_id: string;
  relationship_type: string;
}

export interface DataContract {
  contract_id: string;
  name: string;
  producer_source_id: string | null;
  consumer_description: string;
  is_active: boolean;
  validation_status: string;
  last_validated_at: string | null;
  created_at: string | null;
}

export interface AuditEntry {
  actor: string;
  action: string;
  resource_type: string;
  resource_id: string;
  payload: Record<string, unknown>;
  timestamp?: string;
  created_at?: string;
}

export function getLineageGraph(token: string): Promise<{ nodes: LineageNode[]; edges: LineageEdge[]; node_count: number; edge_count: number }> {
  return authedRequest("/api/v1/governance/graph", token);
}

export function getContracts(token: string): Promise<{ contracts: DataContract[]; count: number }> {
  return authedRequest("/api/v1/governance/contracts", token);
}

export function createContract(
  token: string,
  params: { name: string; producer_source_id: string; consumer_description?: string }
): Promise<DataContract> {
  return request("/api/v1/governance/contracts", {
    method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(params),
  });
}

export function validateContract(token: string, contractId: string): Promise<unknown> {
  return request(`/api/v1/governance/contracts/${contractId}/validate`, {
    method: "POST", headers: { Authorization: `Bearer ${token}` },
  });
}

export function getAuditTrail(token: string, limit = 50): Promise<{ entries: AuditEntry[]; count: number }> {
  return authedRequest(`/api/v1/governance/audit?limit=${limit}`, token);
}

// ---------- Transforms (Phase 14) ----------

export interface GenerateResult {
  type: "sql" | "pandas";
  code: string;
  source_id: string | null;
  schema_used: boolean;
  generated_at: string;
  warnings: string[];
}

export interface RunResult {
  rows: Record<string, unknown>[];
  columns: string[];
  row_count: number;
  truncated: boolean;
  duration_ms: number;
  source_id?: string;
  executed_sql?: string;
  warnings?: string[];
  preview?: boolean;
}

export interface DryRunResult {
  plan: Record<string, unknown>[];
  columns: string[];
  source_id: string;
}

export interface ExplainResult {
  explanation: string;
  language: string;
}

export interface TransformRunItem {
  id: string;
  source_id: string;
  transform_type: string;
  origin: string;
  code: string;
  status: string;
  row_count: number | null;
  duration_ms: number | null;
  error_message: string | null;
  created_at: string;
}

function postTransform<T>(token: string, path: string, body: unknown): Promise<T> {
  return request(`/api/v1/transformations${path}`, {
    method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(body),
  });
}

export function generateSqlTransform(
  token: string,
  params: { request: string; source_id?: string; pipeline_id?: string; extra_context?: string }
): Promise<GenerateResult> {
  return postTransform(token, "/generate/sql", params);
}

export function generatePandasTransform(
  token: string,
  params: { request: string; source_id?: string; pipeline_id?: string; extra_context?: string }
): Promise<GenerateResult> {
  return postTransform(token, "/generate/pandas", params);
}

export function runSqlTransform(
  token: string,
  params: { source_id: string; sql: string; params?: Record<string, unknown>; row_limit?: number }
): Promise<RunResult> {
  return postTransform(token, "/run/sql", params);
}

export function dryRunSqlTransform(
  token: string,
  params: { source_id: string; sql: string }
): Promise<DryRunResult> {
  return postTransform(token, "/run/sql/dry-run", params);
}

export function runPandasTransform(
  token: string,
  params: { source_id: string; code: string; row_limit?: number }
): Promise<RunResult> {
  return postTransform(token, "/run/pandas", params);
}

export function previewPandasTransform(
  token: string,
  params: { source_id: string; code: string }
): Promise<RunResult> {
  return postTransform(token, "/preview/pandas", params);
}

export function explainCode(
  token: string,
  params: { code: string; language?: string }
): Promise<ExplainResult> {
  return postTransform(token, "/explain", params);
}

export function getTransformRuns(
  token: string,
  opts?: { limit?: number; offset?: number; source_id?: string }
): Promise<{ runs: TransformRunItem[]; count: number }> {
  const qs = new URLSearchParams();
  if (opts?.limit) qs.set("limit", String(opts.limit));
  if (opts?.offset) qs.set("offset", String(opts.offset));
  if (opts?.source_id) qs.set("source_id", opts.source_id);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return authedRequest(`/api/v1/transformations/runs${suffix}`, token);
}

// ---------- Data Catalog (Phase 13/14) ----------

export interface CatalogColumn {
  name: string | null;
  type: string | null;
  nullable: boolean;
}

export interface CatalogEntry {
  source_id: string;
  source_name: string;
  source_type: string;
  table_name: string | null;
  row_count: number | null;
  column_count: number;
  columns: CatalogColumn[];
  profiled: boolean;
  last_profiled_at: string | null;
  tags: string[];
  owner: string | null;
}

export function getCatalog(token: string, sourceId?: string): Promise<{ entries: CatalogEntry[]; count: number }> {
  const suffix = sourceId ? `?source_id=${encodeURIComponent(sourceId)}` : "";
  return authedRequest(`/api/v1/catalog/${suffix}`, token);
}

// ---------- Settings (Phase 17) ----------

export interface NotifyOn {
  incident_created: boolean;
  pipeline_failed: boolean;
  deployment_failed: boolean;
  approval_required: boolean;
}

export interface NotificationPrefs {
  slack_webhook_url: string | null;
  alert_email: string | null;
  notify_on: NotifyOn;
}

export interface TenantSettings {
  name: string;
  timezone?: string;
  description?: string;
  ai_model_override?: string | null;
  notification_prefs?: NotificationPrefs;
}

export function getSettings(token: string): Promise<{ settings: TenantSettings }> {
  return authedRequest("/api/v1/settings/", token);
}

// Item 25: server-side test send, gating the Notifications tab's Save
// button in the frontend until a changed Slack URL has passed this.
export function testSlackWebhook(token: string, webhook_url: string): Promise<{ ok: boolean; error?: string }> {
  return request("/api/v1/settings/test-slack-webhook", {
    method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ webhook_url }),
  });
}

export function updateSettings(
  token: string,
  updates: Partial<{
    name: string;
    timezone: string;
    description: string;
    ai_model_override: string | null;
    notification_prefs: Partial<NotificationPrefs>;
  }>
): Promise<{ settings: TenantSettings }> {
  return request("/api/v1/settings/", {
    method: "PATCH", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(updates),
  });
}

// ---------- Onboarding (item 23: surfaced read-only in Settings) ----------

export interface OnboardingProfileData {
  completed: boolean;
  role?: string | null;
  industry?: string | null;
  company_size?: string | null;
  use_cases?: string[];
  data_stack?: string[];
  completed_at?: string | null;
}

export function getOnboardingProfile(token: string): Promise<OnboardingProfileData> {
  return authedRequest("/api/v1/onboarding/", token);
}

// ---------- Auth /me — theme (Phase 17) ----------

export interface MeInfo {
  sub: string;
  tenant_id: string;
  email: string;
  role: string;
  theme: string | null;
  email_verified: boolean;
}

export function getMe(token: string): Promise<MeInfo> {
  return authedRequest("/api/v1/auth/me", token);
}

// ---------- Email verification (item 25) ----------
// Reuses the same request/verify endpoints the email-code login flow
// already uses (services/auth_service.py) - "verify your current email"
// and "log in via a code sent to your email" are the same proof of
// ownership, so this deliberately doesn't duplicate that infrastructure.
// verify's success response includes a fresh access_token (same shape as
// login) since resolve_identity() always issues one on a match; the caller
// should saveSession() it so the token backing future requests reflects
// the (unchanged, but now re-proven) identity.

export function requestEmailVerifyCode(email: string): Promise<{ status: string }> {
  return request("/api/v1/auth/email-code/request", {
    method: "POST", body: JSON.stringify({ email }),
  });
}

// Typed as the full IdentityResult union (not just AuthSuccess) because the
// endpoint is shared with login - a "choose_workspace"/"no_account" result
// should never actually happen when re-verifying the email already backing
// the caller's current session, but the type can't promise that, so callers
// must narrow with isChoose()/isNoAccount() before trusting the token.
export function verifyEmailVerifyCode(email: string, code: string): Promise<IdentityResult> {
  return request("/api/v1/auth/email-code/verify", {
    method: "POST", body: JSON.stringify({ email, code }),
  });
}

export function updateMe(token: string, updates: { theme: string | null }): Promise<{ theme: string | null }> {
  return request("/api/v1/auth/me", {
    method: "PATCH", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(updates),
  });
}

// ---------- API keys (Phase 17) ----------
// NOTE: these are CRUD-only today - nothing in the backend accepts one as a
// request credential yet (see CLAUDE.md's Not-yet-built entry). Settings UI
// copy must not imply otherwise.

export interface ApiKeyItem {
  id: string;
  name: string;
  key_prefix: string;
  created_by_user_id: string;
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

export interface ApiKeyCreated extends ApiKeyItem {
  raw_key: string;
  is_revoked: boolean;
}

export function createApiKey(token: string, name: string): Promise<ApiKeyCreated> {
  return request("/api/v1/api-keys/", {
    method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ name }),
  });
}

export function listApiKeys(token: string): Promise<{ api_keys: ApiKeyItem[] }> {
  return authedRequest("/api/v1/api-keys/", token);
}

export function revokeApiKey(token: string, id: string): Promise<unknown> {
  return request(`/api/v1/api-keys/${id}`, { method: "DELETE", headers: { Authorization: `Bearer ${token}` } });
}

// ---------- Team (Phase 17) ----------

export interface TeamMember {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  created_at: string;
}

export interface TeamInviteItem {
  id: string;
  email: string;
  role: string;
  status: string;
  expires_at: string;
  created_at: string;
  accepted_at: string | null;
}

export function getTeamMembers(token: string): Promise<{ members: TeamMember[] }> {
  return authedRequest("/api/v1/team/members", token);
}

export function changeMemberRole(token: string, userId: string, role: string): Promise<unknown> {
  return request(`/api/v1/team/members/${userId}/role`, {
    method: "PATCH", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ role }),
  });
}

export function removeTeamMember(token: string, userId: string): Promise<unknown> {
  return request(`/api/v1/team/members/${userId}`, { method: "DELETE", headers: { Authorization: `Bearer ${token}` } });
}

export function getTeamInvites(token: string): Promise<{ invites: TeamInviteItem[] }> {
  return authedRequest("/api/v1/team/invites", token);
}

export function createTeamInvite(
  token: string,
  params: { email: string; role: string }
): Promise<TeamInviteItem & { invite_link_token: string }> {
  return request("/api/v1/team/invites", {
    method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(params),
  });
}

export function revokeTeamInvite(token: string, id: string): Promise<unknown> {
  return request(`/api/v1/team/invites/${id}`, { method: "DELETE", headers: { Authorization: `Bearer ${token}` } });
}

// Public - no auth (the invitee isn't logged in yet).

// Matches the real get_invite_by_token() shape exactly (services/
// team_service.py) - no inviter_email field exists there, don't invent one.
export interface InviteVerifyResult {
  email: string;
  role: string;
  tenant_name: string | null;
}

export function verifyInvite(token: string): Promise<InviteVerifyResult> {
  return request(`/api/v1/team/invites/verify?token=${encodeURIComponent(token)}`);
}

export function acceptInvite(params: { token: string; password: string; full_name: string }): Promise<AuthSuccess> {
  return request("/api/v1/team/invites/accept", { method: "POST", body: JSON.stringify(params) });
}

// ---------- Billing (Phase 17) ----------

export interface QuotaStatus {
  resource: string;
  used: number;
  limit: number | null;
  percent: number;
  status: "ok" | "warning" | "exceeded";
}

export interface UsageSummary {
  ai_credits: QuotaStatus;
  pipeline_runs: QuotaStatus;
  data_sources: QuotaStatus;
  team_members: QuotaStatus;
}

export interface PlanLimits {
  ai_credits_per_month: number;
  pipeline_runs_per_month: number;
  max_data_sources: number | null;
  max_team_members: number | null;
}

export interface CurrentPlan {
  plan: string;
  limits: PlanLimits;
}

export function getUsage(token: string): Promise<{ usage: UsageSummary }> {
  return authedRequest("/api/v1/billing/usage", token);
}

export function getCurrentPlan(token: string): Promise<CurrentPlan> {
  return authedRequest("/api/v1/billing/plan", token);
}

// getPlans()/changePlan() removed (public-launch risk cluster, item b):
// self-serve plan changes are disabled server-side (POST /change-plan now
// always 501s) until Stripe billing is real, so nothing in the frontend
// calls either anymore. GET /billing/plans still exists on the backend if
// a future read-only plan-comparison view needs it.

// ---------- Tasks (item 6, stage 7) ----------

export type TaskShapeValue = "diagnose_pipeline_failure" | "investigate_incident" | "sync_profile_quality";

export const TASK_SHAPES: { value: TaskShapeValue; label: string }[] = [
  { value: "diagnose_pipeline_failure", label: "Diagnose pipeline failure" },
  { value: "investigate_incident", label: "Investigate incident" },
  { value: "sync_profile_quality", label: "Sync, profile & quality-check a source" },
];

export type TaskStepProvenance = "llm_planned" | "human_edited" | "system_inserted";

export interface TaskStepItem {
  id: string;
  step_index: number;
  description: string;
  source: TaskStepProvenance;
  tool_name: string;
  tool_args: Record<string, unknown>;
  depends_on_step_index: number | null;
  status: "pending" | "running" | "verifying" | "succeeded" | "failed" | "skipped" | "blocked_approval";
  attempt_count: number;
  error_message: string | null;
  outcome_summary: string | null;
  approval_request_id: string | null;
}

export interface TaskCost {
  llm_calls: number;
  input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  total_tokens: number;
  credits: number;
}

export interface TaskItem {
  id: string;
  tenant_id: string;
  user_id: string;
  goal: string;
  task_shape: TaskShapeValue;
  status: string;
  pause_reason: string | null;
  completion_note: string | null;
  approval_pending_reason: string | null;
  expiry_reason: string | null;
  quota_paused_reason: string | null;
  source_locked_reason: string | null;
  termination_reason: string | null;
  paused_at: string | null;
  plan_approved_by: string | null;
  plan_approved_at: string | null;
  plan_edited: boolean;
  step_budget_max: number;
  step_budget_used: number;
  created_at: string | null;
  started_at: string | null;
  steps: TaskStepItem[];
  cost: TaskCost;
}

export interface TaskSummary {
  id: string;
  user_id: string;
  goal: string;
  task_shape: TaskShapeValue;
  status: string;
  plan_edited: boolean;
  created_at: string | null;
}

export function getTasks(token: string): Promise<TaskSummary[]> {
  return authedRequest("/api/v1/tasks/", token);
}

// Hard-gated tasks.manage_all -- 403s for anyone without it, unlike
// getTasks() above (a soft per-caller filter that never itself 403s).
export function getAllTenantTasks(token: string): Promise<TaskSummary[]> {
  return authedRequest("/api/v1/tasks/all", token);
}

export function getTaskCounts(token: string): Promise<{ active: number }> {
  return authedRequest("/api/v1/tasks/counts", token);
}

export function getTask(token: string, id: string): Promise<TaskItem> {
  return authedRequest(`/api/v1/tasks/${id}`, token);
}

export function createTask(
  token: string,
  params: { goal: string; task_shape: TaskShapeValue; originating_session_id?: string }
): Promise<TaskItem> {
  return request("/api/v1/tasks/", {
    method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(params),
  });
}

export interface TaskStepEditInput {
  description: string;
  tool_name: string;
  tool_args: Record<string, unknown>;
  depends_on_step_index: number | null;
}

export function editTaskSteps(token: string, id: string, steps: TaskStepEditInput[]): Promise<TaskItem> {
  return request(`/api/v1/tasks/${id}/steps`, {
    method: "PATCH", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ steps }),
  });
}

export function approveTaskPlan(token: string, id: string): Promise<TaskItem> {
  return request(`/api/v1/tasks/${id}/approve-plan`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
}

export function rejectTaskPlan(token: string, id: string): Promise<TaskItem & { message: string }> {
  return request(`/api/v1/tasks/${id}/reject-plan`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
}

export function advanceTask(token: string, id: string): Promise<TaskItem & { advance_outcome: Record<string, unknown> }> {
  return request(`/api/v1/tasks/${id}/advance`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
}

export function resumeTask(token: string, id: string, notes = ""): Promise<TaskItem> {
  return request(`/api/v1/tasks/${id}/resume`, {
    method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ notes }),
  });
}

export function rejectTaskStep(token: string, id: string, notes = ""): Promise<TaskItem> {
  return request(`/api/v1/tasks/${id}/reject-step`, {
    method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ notes }),
  });
}

export function cancelTask(token: string, id: string): Promise<TaskItem> {
  return request(`/api/v1/tasks/${id}/cancel`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
}

// ---------- Local session storage ----------

const TOKEN_KEY = "axiom_token";
const TENANT_KEY = "axiom_tenant_id";
const USER_KEY = "axiom_user_id";

export function saveSession(token: string, tenant_id: string, user_id: string) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(TENANT_KEY, tenant_id);
  localStorage.setItem(USER_KEY, user_id);
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export interface DecodedUser {
  sub: string;
  email: string;
  role: string;
  tenant_id: string;
}

export function decodeUserFromToken(token: string): DecodedUser | null {
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    return { sub: payload.sub, email: payload.email, role: payload.role, tenant_id: payload.tenant_id };
  } catch {
    return null;
  }
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(TENANT_KEY);
  localStorage.removeItem(USER_KEY);
}
