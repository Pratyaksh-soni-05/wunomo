const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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

export function getOpenIncidents(token: string): Promise<{ incidents: Incident[]; count: number }> {
  return authedRequest("/api/v1/incidents/", token);
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

// ---------- Pipelines (Phase 12) ----------

export interface PipelineItem {
  id: string;
  name: string;
  status: string;
  source_id: string | null;
  schedule_cron: string | null;
  description?: string | null;
  created_at?: string;
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
  email: string;
  role: string;
  tenant_id: string;
}

export function decodeUserFromToken(token: string): DecodedUser | null {
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    return { email: payload.email, role: payload.role, tenant_id: payload.tenant_id };
  } catch {
    return null;
  }
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(TENANT_KEY);
  localStorage.removeItem(USER_KEY);
}
