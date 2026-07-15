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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, body?.detail ?? body);
  return body as T;
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

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(TENANT_KEY);
  localStorage.removeItem(USER_KEY);
}
