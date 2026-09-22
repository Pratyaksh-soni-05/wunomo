"use client";

import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Card, Badge, Button, Modal, Input, Select, Tabs, Skeleton, useToast, RowActionsMenu,
  Table, Thead, Tbody, Tr, Th, Td,
} from "@/components/ui";
import {
  getToken, decodeUserFromToken, getSettings, updateSettings, getAiModels,
  createApiKey, listApiKeys, revokeApiKey, getOnboardingProfile, testSlackWebhook,
  getMe, requestEmailVerifyCode, verifyEmailVerifyCode, saveSession, isChoose, isNoAccount, isMfaRequired,
  getMfaStatus, mfaSetup, mfaEnable, mfaDisable, mfaRegenerateBackupCodes, getToken as readToken, ApiError,
  getSsoConfig, updateSsoConfig, type SsoConfig,
  getAuditTrail, type NotifyOn, type ApiKeyItem, type AuditEntry,
} from "@/lib/api";
import { applyTheme, getStoredTheme, resolveEffectiveTheme, type ThemePreference } from "@/lib/theme";
import { QRCodeSVG } from "qrcode.react";
import { formatApiDate, formatApiDateOnly } from "@/lib/dates";
import { applyTimezone, detectBrowserTimezone, timezoneOptionsWithDetected } from "@/lib/timezone";

// NOTE: no MODEL_OPTIONS constant here -- his branch independently found
// and fixed the same hand-maintained-list drift bug master's
// services/llm_service.py.supported_model_overrides() fixes (see GOTCHAS),
// but via a corrected hardcoded list rather than a real backend-derived
// one. Master's fix is used instead: this file already calls
// getAiModels(token) (below) and renders from that live result, so a
// second, still-hardcodeable list would just be dead weight re-introducing
// the exact drift risk both sides independently flagged.

const NOTIFY_ON_LABELS: Record<keyof NotifyOn, string> = {
  incident_created: "Incident created",
  pipeline_failed: "Pipeline failed",
  deployment_failed: "Deployment failed",
  approval_required: "Approval required",
};

// "audit-log" added in slice 12 (2026-09-15) -- moved out of the retired
// /governance page (findings item 94): tenant-wide by nature, so
// Settings is its real home, not a per-project Workbench surface the
// way Contracts (the OTHER governance tab) became.
const TABS = [
  { id: "workspace", label: "Workspace" },
  { id: "profile", label: "Profile" },
  { id: "security", label: "Security" },
  { id: "notifications", label: "Notifications" },
  { id: "ai-model", label: "AI Model" },
  { id: "theme", label: "Theme" },
  { id: "api-keys", label: "API Keys" },
  { id: "audit-log", label: "Audit Log" },
];
const TAB_IDS = new Set(TABS.map((t) => t.id));

export default function SettingsPage() {
  const token = getToken() as string;
  const user = decodeUserFromToken(token);
  const canManage = user?.role === "owner" || user?.role === "admin";
  const toast = useToast();
  const qc = useQueryClient();
  const [tab, setTab] = useState("workspace");

  // Reads window.location.search directly rather than next/navigation's
  // useSearchParams() -- same reason /chat's own ?session= consumer does
  // (see that file): useSearchParams() needs a <Suspense> boundary this
  // shell doesn't set up, and this only ever runs client-side anyway.
  // Left in the URL (not stripped) so /settings?tab=audit-log stays a
  // real, shareable deep link, unlike /chat's one-shot ?session= marker.
  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("tab");
    if (requested && TAB_IDS.has(requested)) setTab(requested);
  }, []);

  const settings = useQuery({ queryKey: ["settings"], queryFn: () => getSettings(token) });
  const s = settings.data?.settings;

  const saveMut = useMutation({
    mutationFn: (updates: Parameters<typeof updateSettings>[1]) => updateSettings(token, updates),
    onSuccess: () => {
      toast.push("Settings saved.", "success");
      qc.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: () => toast.push("Failed to save settings.", "danger"),
  });

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Settings</h1>
      </div>

      <div style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 20 }}>
        <Tabs items={TABS} activeId={tab} onChange={setTab} />

        {settings.isLoading ? (
          <Skeleton style={{ height: 200, borderRadius: 12 }} />
        ) : (
          <>
            {tab === "workspace" && (
              <WorkspaceTab settings={s} canManage={canManage} onSave={(u) => saveMut.mutate(u)} saving={saveMut.isPending} />
            )}
            {tab === "profile" && <ProfileTab token={token} />}
            {tab === "notifications" && (
              <NotificationsTab token={token} prefs={s?.notification_prefs} canManage={canManage} onSave={(u) => saveMut.mutate(u)} saving={saveMut.isPending} />
            )}
            {tab === "ai-model" && (
              <AiModelTab token={token} current={s?.ai_model_override ?? null} canManage={canManage} onSave={(u) => saveMut.mutate(u)} saving={saveMut.isPending} />
            )}
            {tab === "security" && (
              <>
                <SecurityTab token={token} />
                <div style={{ height: 16 }} />
                <SsoSection token={token} role={user?.role ?? ""} />
              </>
            )}
            {tab === "theme" && <ThemeTab token={token} />}
            {tab === "api-keys" && <ApiKeysTab token={token} canManage={canManage} />}
            {tab === "audit-log" && <AuditLogTab token={token} />}
          </>
        )}
      </div>
    </div>
  );
}

function ReadOnlyNotice() {
  return (
    <p className="text-muted text-sm" style={{ marginBottom: 4 }}>
      Only owners and admins can change this — you have read-only access.
    </p>
  );
}

// ---------- Workspace ----------

function WorkspaceTab({
  settings, canManage, onSave, saving,
}: {
  settings: { name: string; timezone?: string; description?: string } | undefined;
  canManage: boolean;
  onSave: (u: { name: string; timezone: string; description: string }) => void;
  saving: boolean;
}) {
  const [name, setName] = useState("");
  const [timezone, setTimezone] = useState("");
  const [description, setDescription] = useState("");
  const tzOptions = timezoneOptionsWithDetected();

  useEffect(() => {
    if (!settings) return;
    setName(settings.name ?? "");
    // Item 22: an unconfigured workspace defaults the dropdown to the
    // browser's own detected zone ("correct according to the machine's
    // timezone") rather than a blank/arbitrary value - the user can still
    // override it, but the first thing they see is already right.
    setTimezone(settings.timezone || detectBrowserTimezone());
    setDescription(settings.description ?? "");
  }, [settings]);

  return (
    <Card>
      <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 480 }}>
        {!canManage && <ReadOnlyNotice />}
        <Input label="Workspace name" value={name} disabled={!canManage} onChange={(e) => setName(e.target.value)} />
        <Select label="Timezone" value={timezone} disabled={!canManage} onChange={(e) => setTimezone(e.target.value)}>
          {tzOptions.map((tz) => <option key={tz} value={tz}>{tz}</option>)}
        </Select>
        <p className="text-muted text-sm" style={{ marginTop: -8 }}>
          Applies to every timestamp shown across the app for everyone in this workspace.
        </p>
        <Input label="Description" placeholder="Optional" value={description} disabled={!canManage} onChange={(e) => setDescription(e.target.value)} />
        {canManage && (
          <div>
            <Button
              size="sm"
              disabled={saving || !name.trim()}
              onClick={() => {
                // Applies to this browser immediately rather than waiting
                // for the next full-shell mount to reconcile from the
                // server - same reasoning as ThemeTab's applyTheme() call.
                applyTimezone(timezone);
                onSave({ name, timezone, description });
              }}
            >
              {saving ? "Saving…" : "Save"}
            </Button>
          </div>
        )}
      </div>
    </Card>
  );
}

// ---------- Profile (item 23: surface onboarding answers, read-only) ----------

function ProfileField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="input-label" style={{ marginBottom: 4 }}>{label}</div>
      <div className="text-sm">{value}</div>
    </div>
  );
}

// Item 25 (second half): "invalid email task should be there when the
// email not verified." Reuses the existing email-code login endpoints as
// a proof-of-ownership check on the account's CURRENT email - it's the
// same infrastructure, not a new verification mechanism, since re-proving
// you can receive mail at your own address is functionally identical to
// logging in via a code. Building a flow to CHANGE to a genuinely new
// email is a separate, larger, more security-sensitive piece (JWT
// reissue semantics, cross-tenant uniqueness, whether the old address
// gets notified) - deliberately not built here; see the session notes.
function EmailVerificationCard({ token }: { token: string }) {
  const toast = useToast();
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: () => getMe(token) });
  const [sent, setSent] = useState(false);
  const [code, setCode] = useState("");
  const [sending, setSending] = useState(false);
  const [verifying, setVerifying] = useState(false);

  if (me.isLoading) return <Skeleton style={{ height: 60, borderRadius: 12 }} />;
  if (!me.data || me.data.email_verified) return null;

  const email = me.data.email;

  const sendCode = async () => {
    setSending(true);
    try {
      const result = await requestEmailVerifyCode(email);
      // The endpoint returns 200 with {status: "rate_limited"} rather than
      // an error status (same enumeration-safety reasoning as the login
      // flow this is shared with) - found live while verifying this: after
      // enough requests in the last hour, this branch fires and no code is
      // actually sent. Must not fall through to the success toast/code-entry
      // view, or the user is left staring at a code box that can never
      // succeed with no indication why.
      if (result.status === "rate_limited") {
        toast.push("Too many code requests recently — wait a bit and try again.", "warning");
        return;
      }
      setSent(true);
      toast.push(`Verification code sent to ${email}.`, "default");
    } catch {
      toast.push("Couldn't send a verification code. Try again.", "danger");
    } finally {
      setSending(false);
    }
  };

  const verify = async () => {
    if (!code.trim()) return;
    setVerifying(true);
    try {
      const result = await verifyEmailVerifyCode(email, code.trim());
      if (isChoose(result) || isNoAccount(result)) {
        toast.push("Couldn't verify — try requesting a new code.", "danger");
        return;
      }
      // Item #13: the email is marked verified server-side before the session
      // decision is made, so an MFA challenge here just means "keep the
      // session you already have" -- the caller is logged in already.
      if (!isMfaRequired(result)) saveSession(result.access_token, result.tenant_id, result.user_id);
      qc.invalidateQueries({ queryKey: ["me"] });
      toast.push("Email verified.", "success");
      setSent(false);
      setCode("");
    } catch {
      toast.push("Invalid or expired code.", "danger");
    } finally {
      setVerifying(false);
    }
  };

  return (
    <Card>
      <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <Badge variant="warning">Email not verified</Badge>
        <p className="text-sm">
          <strong>{email}</strong> hasn&apos;t been verified. Some account-security features
          (like password reset) depend on being able to reach you at this address.
        </p>
        {!sent ? (
          <div>
            <Button size="sm" disabled={sending} onClick={sendCode}>
              {sending ? "Sending…" : "Send verification code"}
            </Button>
          </div>
        ) : (
          <div className="flex gap-2" style={{ maxWidth: 320 }}>
            <Input placeholder="6-digit code" value={code} onChange={(e) => setCode(e.target.value)} />
            <Button size="sm" disabled={verifying || !code.trim()} onClick={verify}>
              {verifying ? "Verifying…" : "Verify"}
            </Button>
          </div>
        )}
      </div>
    </Card>
  );
}

function ProfileTab({ token }: { token: string }) {
  const profile = useQuery({ queryKey: ["onboarding-profile"], queryFn: () => getOnboardingProfile(token) });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <EmailVerificationCard token={token} />

      {profile.isLoading ? (
        <Skeleton style={{ height: 160, borderRadius: 12 }} />
      ) : !profile.data?.completed ? (
        <Card>
          <div className="card-body">
            <p className="text-muted text-sm">
              No onboarding answers on file yet — this workspace either signed up before onboarding
              existed, or skipped it.
            </p>
          </div>
        </Card>
      ) : (
        <Card>
          <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 480 }}>
            <p className="text-muted text-sm">
              What you told us during setup. These aren&apos;t editable here yet — reach out if
              anything needs correcting.
            </p>
            <ProfileField label="Role" value={profile.data.role || "—"} />
            <ProfileField label="Industry" value={profile.data.industry || "—"} />
            <ProfileField label="Company size" value={profile.data.company_size || "—"} />
            <ProfileField label="How AXIOM helps you" value={profile.data.use_cases?.length ? profile.data.use_cases.join(", ") : "—"} />
            <ProfileField label="Data stack" value={profile.data.data_stack?.length ? profile.data.data_stack.join(", ") : "—"} />
            <ProfileField label="Completed" value={formatApiDateOnly(profile.data.completed_at)} />
          </div>
        </Card>
      )}
    </div>
  );
}

// ---------- Notifications ----------

function NotificationsTab({
  token, prefs, canManage, onSave, saving,
}: {
  token: string;
  prefs: { slack_webhook_url: string | null; alert_email: string | null; notify_on: NotifyOn } | undefined;
  canManage: boolean;
  onSave: (u: { notification_prefs: { slack_webhook_url?: string; alert_email?: string; notify_on: NotifyOn } }) => void;
  saving: boolean;
}) {
  const toast = useToast();
  const [webhook, setWebhook] = useState("");
  const [email, setEmail] = useState("");
  const [notifyOn, setNotifyOn] = useState<NotifyOn>({
    incident_created: true, pipeline_failed: true, deployment_failed: true, approval_required: true,
  });
  // Item 25 "double verification": a changed Slack URL must pass a real
  // test send before Save is allowed to persist it - lastVerified tracks
  // exactly which string value passed, so editing the field after a
  // successful test re-locks Save (it's re-verifying THIS value, not a
  // one-time unlock). Unchanged from what's already saved never needs
  // re-testing at all.
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; error?: string } | null>(null);
  const [lastVerified, setLastVerified] = useState<string | null>(null);

  useEffect(() => {
    if (!prefs) return;
    setWebhook(prefs.slack_webhook_url ?? "");
    setEmail(prefs.alert_email ?? "");
    setNotifyOn(prefs.notify_on);
    setLastVerified(prefs.slack_webhook_url ?? null);
    setTestResult(null);
  }, [prefs]);

  const webhookChanged = webhook.trim() !== (prefs?.slack_webhook_url ?? "").trim();
  const webhookNeedsTest = webhook.trim() !== "" && webhookChanged && webhook.trim() !== lastVerified;

  const runTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await testSlackWebhook(token, webhook.trim());
      setTestResult(result);
      if (result.ok) {
        setLastVerified(webhook.trim());
        toast.push("Test message sent — check your Slack channel.", "success");
      }
    } catch {
      setTestResult({ ok: false, error: "Couldn't reach the server to run the test." });
    } finally {
      setTesting(false);
    }
  };

  return (
    <Card>
      <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 480 }}>
        {!canManage && <ReadOnlyNotice />}
        <div>
          <div className="flex gap-2" style={{ alignItems: "flex-end" }}>
            <div style={{ flex: 1 }}>
              <Input
                label="Slack webhook URL" placeholder="https://hooks.slack.com/..." value={webhook}
                disabled={!canManage}
                onChange={(e) => { setWebhook(e.target.value); setTestResult(null); }}
              />
            </div>
            {canManage && (
              <Button
                size="sm" variant="secondary"
                disabled={testing || !webhook.trim()}
                onClick={runTest}
              >
                {testing ? "Testing…" : "Test"}
              </Button>
            )}
          </div>
          {testResult && (
            <p className={`text-sm ${testResult.ok ? "" : "text-danger"}`} style={{ marginTop: 4 }}>
              {testResult.ok ? "✓ Verified — test message sent." : `✗ ${testResult.error}`}
            </p>
          )}
          {!testResult && webhookNeedsTest && (
            <p className="text-muted text-sm" style={{ marginTop: 4 }}>
              Test this webhook before saving — a new or changed URL must send successfully at least once.
            </p>
          )}
        </div>
        <Input label="Alert email" placeholder="alerts@yourcompany.com" value={email} disabled={!canManage} onChange={(e) => setEmail(e.target.value)} />

        <div>
          <label className="input-label" style={{ marginBottom: 8, display: "block" }}>Notify on</label>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {(Object.keys(NOTIFY_ON_LABELS) as (keyof NotifyOn)[]).map((key) => (
              <label key={key} className="flex items-center justify-between text-sm" style={{ cursor: canManage ? "pointer" : "default" }}>
                <span>{NOTIFY_ON_LABELS[key]}</span>
                <input
                  type="checkbox"
                  checked={notifyOn[key]}
                  disabled={!canManage}
                  onChange={(e) => setNotifyOn((prev) => ({ ...prev, [key]: e.target.checked }))}
                />
              </label>
            ))}
          </div>
        </div>

        {canManage && (
          <div>
            <Button
              size="sm"
              disabled={saving || webhookNeedsTest}
              title={webhookNeedsTest ? "Test the Slack webhook before saving" : undefined}
              onClick={() => onSave({ notification_prefs: { slack_webhook_url: webhook, alert_email: email, notify_on: notifyOn } })}
            >
              {saving ? "Saving…" : "Save"}
            </Button>
          </div>
        )}
      </div>
    </Card>
  );
}

// ---------- AI Model ----------

function AiModelTab({
  token, current, canManage, onSave, saving,
}: {
  token: string;
  current: string | null;
  canManage: boolean;
  onSave: (u: { ai_model_override: string | null }) => void;
  saving: boolean;
}) {
  const [value, setValue] = useState("");
  // Options come from the backend allowlist (one source of truth); the
  // previous hard-coded copy offered a model the account did not serve.
  const models = useQuery({ queryKey: ["ai-models"], queryFn: () => getAiModels(token) });

  useEffect(() => { setValue(current ?? ""); }, [current]);

  const options = models.data?.models ?? [];
  // A stored override the backend no longer offers reads back as null from
  // the API, so `current` can never point at a missing option -- but guard
  // the select anyway so it never renders a value with no matching option.
  const currentIsOffered = value === "" || options.some((m) => m.value === value);

  return (
    <Card>
      <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 480 }}>
        {!canManage && <ReadOnlyNotice />}
        <p className="text-muted text-sm">
          Overrides which LLM AXIOM uses for this workspace. Leave on plan default unless you have a specific reason to pin one.
        </p>
        {models.isError && (
          <p className="text-sm text-danger">
            Could not load the available models. The plan default is still in effect.
          </p>
        )}
        <Select label="Model" value={currentIsOffered ? value : ""} disabled={!canManage || models.isLoading || models.isError} onChange={(e) => setValue(e.target.value)}>
          <option value="">{`Use plan default${models.data?.default ? ` (${models.data.default})` : ""}`}</option>
          {options.map((m) => (
            <option key={m.value} value={m.value}>{m.label}</option>
          ))}
        </Select>
        {canManage && (
          <div>
            <Button size="sm" disabled={saving} onClick={() => onSave({ ai_model_override: value || null })}>
              {saving ? "Saving…" : "Save"}
            </Button>
          </div>
        )}
      </div>
    </Card>
  );
}


// ---------- Security (Item #13: MFA) ----------

function SecurityTab({ token }: { token: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const status = useQuery({ queryKey: ["mfa-status"], queryFn: () => getMfaStatus(readToken() ?? token) });
  const [setup, setSetup] = useState<{ secret: string; provisioning_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);

  // Enable / disable / regenerate each bump the token epoch server-side and
  // hand back a fresh token; store it or the very next request is a 401.
  function adoptToken(access_token: string) {
    saveSession(access_token, localStorage.getItem("axiom_tenant_id") ?? "", localStorage.getItem("axiom_user_id") ?? "");
  }
  function fail(e: unknown, fallback: string) {
    const d = e instanceof ApiError ? e.detail : null;
    toast.push(typeof d === "string" ? d : fallback, "danger");
  }

  async function startSetup() {
    setBusy(true);
    try { setSetup(await mfaSetup(readToken() ?? token)); setCode(""); }
    catch (e) { fail(e, "Could not start setup."); }
    finally { setBusy(false); }
  }

  async function confirmEnable() {
    setBusy(true);
    try {
      const r = await mfaEnable(readToken() ?? token, code);
      adoptToken(r.access_token);
      setBackupCodes(r.backup_codes);
      setSetup(null); setCode("");
      qc.invalidateQueries({ queryKey: ["mfa-status"] });
      qc.invalidateQueries({ queryKey: ["me"] });
      toast.push("Two-factor authentication is on. Other sessions have been signed out.", "success");
    } catch (e) { fail(e, "That code was not accepted."); }
    finally { setBusy(false); }
  }

  async function disable() {
    setBusy(true);
    try {
      const r = await mfaDisable(readToken() ?? token, code);
      adoptToken(r.access_token); setCode("");
      qc.invalidateQueries({ queryKey: ["mfa-status"] });
      qc.invalidateQueries({ queryKey: ["me"] });
      toast.push("Two-factor authentication is off.", "default");
    } catch (e) { fail(e, "Could not disable."); }
    finally { setBusy(false); }
  }

  async function regenerate() {
    setBusy(true);
    try {
      const r = await mfaRegenerateBackupCodes(readToken() ?? token, code);
      adoptToken(r.access_token); setCode("");
      setBackupCodes(r.backup_codes);
      qc.invalidateQueries({ queryKey: ["mfa-status"] });
      toast.push("New backup codes issued. The old ones no longer work.", "success");
    } catch (e) { fail(e, "Could not regenerate."); }
    finally { setBusy(false); }
  }

  const s = status.data;
  return (
    <Card>
      <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 560 }}>
        <div className="flex items-center justify-between">
          <div>
            <div className="font-medium">Two-factor authentication (TOTP)</div>
            <p className="text-muted text-sm">
              A 6-digit code from an authenticator app (Google Authenticator, 1Password, Authy…) is required at every login.
            </p>
          </div>
          {s && <Badge variant={s.enabled ? "success" : s.overdue ? "danger" : s.required ? "warning" : "gray"}>
            {s.enabled ? "On" : s.overdue ? "Required — overdue" : s.required ? "Required" : "Off"}
          </Badge>}
        </div>

        {s && s.required && !s.enabled && (
          <p className={`text-sm${s.overdue ? " text-danger" : ""}`}>
            {s.overdue
              ? "Your role requires two-factor authentication and the grace period has ended: everything except this page is blocked until you enable it."
              : `Your role (owner/admin) requires two-factor authentication${s.enrollment_deadline ? ` by ${formatApiDateOnly(s.enrollment_deadline)}` : ""}.`}
          </p>
        )}

        {backupCodes && (
          <Card style={{ background: "var(--surface-hover)" }}>
            <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div className="font-medium text-sm">Backup codes — save these now, they are not shown again</div>
              <p className="text-muted text-xs">Each works once, in place of an authenticator code, if you lose your device.</p>
              <pre className="code-block" style={{ fontSize: 13 }}>{backupCodes.join("\n")}</pre>
              <div><Button size="sm" variant="secondary" onClick={() => setBackupCodes(null)}>I have saved them</Button></div>
            </div>
          </Card>
        )}

        {s && !s.enabled && !setup && (
          <div><Button size="sm" disabled={busy} onClick={startSetup}>Set up two-factor authentication</Button></div>
        )}

        {setup && (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <p className="text-sm">1. Scan this with your authenticator app:</p>
            <div style={{ background: "#fff", padding: 12, borderRadius: 8, width: "fit-content" }}>
              <QRCodeSVG value={setup.provisioning_uri} size={176} />
            </div>
            <p className="text-muted text-xs">Can&apos;t scan? Enter this key manually: <code className="mono">{setup.secret}</code></p>
            <p className="text-sm">2. Enter the 6-digit code the app shows, to confirm it works:</p>
            <div className="flex gap-2 items-end">
              <Input label="Code" value={code} onChange={(e) => setCode(e.target.value)} maxLength={6} placeholder="123456" />
              <Button size="sm" disabled={busy || code.trim().length !== 6} onClick={confirmEnable}>Verify &amp; enable</Button>
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => { setSetup(null); setCode(""); }}>Cancel</Button>
            </div>
            <p className="text-muted text-xs">Nothing is enabled until a code from your app is accepted, so you can&apos;t lock yourself out with a key that never worked.</p>
          </div>
        )}

        {s && s.enabled && (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <p className="text-sm text-muted">Backup codes remaining: <strong>{s.backup_codes_remaining}</strong></p>
            <div className="flex gap-2 items-end">
              <Input label="Current code (authenticator or backup)" value={code} onChange={(e) => setCode(e.target.value)} placeholder="123456 or XXXXX-XXXXX" />
              <Button size="sm" variant="secondary" disabled={busy || !code.trim()} onClick={regenerate}>New backup codes</Button>
              {!s.required && (
                <Button size="sm" variant="ghost" disabled={busy || !code.trim()} onClick={disable}>Turn off</Button>
              )}
            </div>
            {s.required && <p className="text-muted text-xs">Two-factor authentication cannot be turned off for owners and admins.</p>}
          </div>
        )}
      </div>
    </Card>
  );
}


// ---------- Enterprise SSO (Item #14) ----------

function SsoSection({ token, role }: { token: string; role: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const canManage = role === "owner" || role === "admin";
  const isOwner = role === "owner";
  const cfg = useQuery({ queryKey: ["sso-config"], queryFn: () => getSsoConfig(readToken() ?? token), enabled: canManage });
  const [form, setForm] = useState<SsoConfig | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (cfg.data && !form) setForm(cfg.data); }, [cfg.data, form]);

  if (!canManage) return null;

  async function save() {
    if (!form) return;
    setBusy(true);
    try {
      const saved = await updateSsoConfig(readToken() ?? token, {
        connection_id: form.connection_id, email_domain: form.email_domain,
        enabled: form.enabled, satisfies_mfa: form.satisfies_mfa,
      });
      setForm({ ...form, ...saved });
      qc.invalidateQueries({ queryKey: ["sso-config"] });
      toast.push("Single sign-on settings saved.", "success");
    } catch (e) {
      const d = e instanceof ApiError ? e.detail : null;
      toast.push(typeof d === "string" ? d : "Could not save SSO settings.", "danger");
    } finally { setBusy(false); }
  }

  const d = cfg.data;
  return (
    <Card>
      <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 14, maxWidth: 560 }}>
        <div className="flex items-center justify-between">
          <div>
            <div className="font-medium">Enterprise single sign-on (SAML / OIDC via WorkOS)</div>
            <p className="text-muted text-sm">
              Let everyone at your organisation&apos;s email domain sign in through your identity provider (Okta, Azure AD, Google Workspace…).
            </p>
          </div>
          {d && <Badge variant={d.enabled ? "success" : "gray"}>{d.enabled ? "On" : "Off"}</Badge>}
        </div>

        {d && d.configured_on_deployment === false && (
          <p className="text-sm text-danger">SSO is not configured on this deployment (no WorkOS credentials), so it cannot be enabled here.</p>
        )}

        {form && (
          <>
            <Input label="WorkOS connection ID" value={form.connection_id} placeholder="conn_…"
                   onChange={(e) => setForm({ ...form, connection_id: e.target.value })} />
            <Input label="Email domain" value={form.email_domain} placeholder="acme.com"
                   onChange={(e) => setForm({ ...form, email_domain: e.target.value })} />
            <p className="text-muted text-xs">
              Only sign-ins your identity provider asserts for exactly this domain are accepted. A first-time sign-in from this domain creates a Viewer account automatically.
            </p>
            {d?.redirect_uri && <p className="text-muted text-xs">Redirect URI to register in WorkOS: <code className="mono">{d.redirect_uri}</code></p>}
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />
              Enable single sign-on for this workspace
            </label>
            <label className="flex items-center gap-2 text-sm" title={isOwner ? "" : "Only an owner can change this"}>
              <input type="checkbox" checked={form.satisfies_mfa} disabled={!isOwner}
                     onChange={(e) => setForm({ ...form, satisfies_mfa: e.target.checked })} />
              Trust the identity provider&apos;s MFA (skip Wunomo&apos;s authenticator step for SSO sign-ins)
            </label>
            <p className={`text-xs${form.satisfies_mfa ? " text-danger" : " text-muted"}`}>
              {form.satisfies_mfa
                ? "Weaker by design: SSO sessions will not be asked for a Wunomo authenticator code, and this counts as MFA for owners and admins on those sessions. Wunomo cannot verify that your identity provider actually enforced MFA. This choice is recorded in the audit log."
                : "Default: SSO is a first factor. Accounts with two-factor authentication on still enter their authenticator code after signing in through the identity provider."}
            </p>
            <div><Button size="sm" disabled={busy} onClick={save}>Save SSO settings</Button></div>
          </>
        )}
      </div>
    </Card>
  );
}

// ---------- Theme ----------

function ThemeTab({ token }: { token: string }) {
  const toast = useToast();
  const [pref, setPref] = useState<ThemePreference>("system");

  useEffect(() => { setPref(getStoredTheme()); }, []);

  const mut = useMutation({
    mutationFn: async (next: ThemePreference) => {
      applyTheme(next);
      const { updateMe } = await import("@/lib/api");
      return updateMe(token, { theme: next });
    },
    onSuccess: (_data, next) => { setPref(next); toast.push("Theme updated.", "success"); },
    onError: () => toast.push("Failed to save theme preference.", "danger"),
  });

  const options: { value: ThemePreference; label: string }[] = [
    { value: "light", label: "Light" },
    { value: "dark", label: "Dark" },
    { value: "system", label: "System" },
  ];

  return (
    <Card>
      <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 480 }}>
        <p className="text-muted text-sm">Applies to this account across every device you log in on.</p>
        <div className="flex gap-2">
          {options.map((o) => (
            <Button
              key={o.value}
              size="sm"
              variant={pref === o.value ? "primary" : "secondary"}
              disabled={mut.isPending}
              onClick={() => mut.mutate(o.value)}
            >
              {o.label}
            </Button>
          ))}
        </div>
        <p className="text-muted text-sm">
          Currently rendering: <strong>{resolveEffectiveTheme(pref) === "dark" ? "Dark" : "Light"}</strong>
        </p>
      </div>
    </Card>
  );
}

// ---------- API Keys ----------

function ApiKeysTab({ token, canManage }: { token: string; canManage: boolean }) {
  const toast = useToast();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  // Deliberately plain component state, never written into the React Query
  // cache and never logged - the raw secret must only exist for as long as
  // this modal is open, discarded (state reset to null) the moment it closes.
  const [revealedKey, setRevealedKey] = useState<string | null>(null);

  const keys = useQuery({
    queryKey: ["api-keys"],
    queryFn: () => listApiKeys(token),
    enabled: canManage, // GET /api-keys/ is Owner/Admin-only server-side
  });

  const createMut = useMutation({
    mutationFn: () => createApiKey(token, name),
    onSuccess: (result) => {
      setRevealedKey(result.raw_key);
      setName("");
      qc.invalidateQueries({ queryKey: ["api-keys"] });
    },
    onError: () => toast.push("Failed to create API key.", "danger"),
  });

  const revokeMut = useMutation({
    mutationFn: (id: string) => revokeApiKey(token, id),
    onSuccess: () => { toast.push("Key revoked.", "default"); qc.invalidateQueries({ queryKey: ["api-keys"] }); },
    onError: () => toast.push("Failed to revoke key.", "danger"),
  });

  if (!canManage) {
    return (
      <Card>
        <div className="card-body">
          <p className="text-muted text-sm">Only owners and admins can view or manage API keys.</p>
        </div>
      </Card>
    );
  }

  const list = keys.data?.api_keys ?? [];

  return (
    <>
      <Card>
        <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <p className="text-muted text-sm">
            API keys are for reference and audit today — nothing in AXIOM currently accepts one as a
            request credential. Authenticating requests with a key is planned but not yet built.
          </p>

          <div className="flex gap-2" style={{ maxWidth: 420 }}>
            <Input placeholder="Key name (e.g. CI pipeline)" value={name} onChange={(e) => setName(e.target.value)} />
            <Button size="sm" disabled={createMut.isPending || !name.trim()} onClick={() => createMut.mutate()}>
              {createMut.isPending ? "Creating…" : "Create"}
            </Button>
          </div>

          {keys.isLoading ? (
            <Skeleton style={{ height: 120, borderRadius: 12 }} />
          ) : list.length === 0 ? (
            <p className="text-muted text-sm">No API keys yet.</p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {list.map((k: ApiKeyItem) => (
                <div key={k.id} className="flex items-center justify-between" style={{ padding: "10px 0", borderTop: "1px solid var(--border)" }}>
                  <div>
                    <div className="text-sm" style={{ fontWeight: 600 }}>{k.name}</div>
                    <div className="text-muted text-sm">
                      <code>{k.key_prefix}…</code> · created {formatApiDateOnly(k.created_at)}
                      {k.last_used_at ? ` · last used ${formatApiDateOnly(k.last_used_at)}` : " · never used"}
                    </div>
                  </div>
                  {k.revoked_at ? (
                    <Badge variant="gray">Revoked</Badge>
                  ) : (
                    <div className="row-actions">
                      <RowActionsMenu
                        actions={[
                          { label: "Revoke", disabled: revokeMut.isPending, onClick: () => revokeMut.mutate(k.id) },
                        ]}
                      />
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </Card>

      <Modal open={!!revealedKey} onClose={() => setRevealedKey(null)} title="API key created" size="sm">
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <p className="text-sm">
            Copy this now — for your security, it won&apos;t be shown again.
          </p>
          <code className="code-block" style={{ display: "block", wordBreak: "break-all" }}>
            {revealedKey}
          </code>
          <div className="flex gap-2">
            <Button
              size="sm"
              onClick={async () => {
                if (revealedKey) await navigator.clipboard.writeText(revealedKey);
                toast.push("Copied to clipboard.", "success");
              }}
            >
              Copy
            </Button>
            <Button size="sm" variant="secondary" onClick={() => setRevealedKey(null)}>Done</Button>
          </div>
        </div>
      </Modal>
    </>
  );
}

// ---------- Audit Log (moved from the retired /governance page, slice 12) ----------

function AuditLogTab({ token }: { token: string }) {
  const audit = useQuery({ queryKey: ["audit-trail"], queryFn: () => getAuditTrail(token) });
  const list = audit.data?.entries ?? [];

  return (
    <Card>
      {audit.isLoading ? (
        <div className="card-body"><Skeleton style={{ height: 200, borderRadius: 12 }} /></div>
      ) : list.length === 0 ? (
        <div className="card-body">
          <div className="empty-state" style={{ minHeight: "auto", padding: "40px 20px" }}>
            <h2 className="font-display text-xl">No audit events yet</h2>
            <p className="text-muted text-sm" style={{ maxWidth: 380 }}>
              Every governance and approval action taken in this workspace is logged here.
            </p>
          </div>
        </div>
      ) : (
        <Table>
          <Thead>
            <Tr><Th>Actor</Th><Th>Action</Th><Th>Resource</Th><Th>When</Th></Tr>
          </Thead>
          <Tbody>
            {list.map((e: AuditEntry, i: number) => (
              <Tr key={i}>
                <Td>{e.actor}</Td>
                <Td><code>{e.action}</code></Td>
                <Td>{e.resource_type}{e.resource_id ? ` · ${e.resource_id.slice(0, 8)}` : ""}</Td>
                <Td>{formatApiDate(e.created_at)}</Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      )}
    </Card>
  );
}
