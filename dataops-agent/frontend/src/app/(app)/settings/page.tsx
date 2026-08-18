"use client";

import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Card, Badge, Button, Modal, Input, Select, Tabs, Skeleton, useToast,
} from "@/components/ui";
import {
  getToken, decodeUserFromToken, getSettings, updateSettings,
  createApiKey, listApiKeys, revokeApiKey, getOnboardingProfile, testSlackWebhook,
  getMe, requestEmailVerifyCode, verifyEmailVerifyCode, saveSession, isChoose, isNoAccount,
  type NotifyOn, type ApiKeyItem,
} from "@/lib/api";
import { applyTheme, getStoredTheme, resolveEffectiveTheme, type ThemePreference } from "@/lib/theme";
import { formatApiDateOnly } from "@/lib/dates";
import { applyTimezone, detectBrowserTimezone, timezoneOptionsWithDetected } from "@/lib/timezone";

// Kept in sync manually with backend/services/llm_service.py's
// SUPPORTED_MODEL_OVERRIDES - there's no list endpoint to fetch this from
// (see CLAUDE.md's Known-broken/tech-debt entry: this list will silently
// drift out of sync with the backend allowlist if either changes without
// updating the other).
const MODEL_OPTIONS = [
  { value: "", label: "Use plan default" },
  { value: "gemini-3.5-flash", label: "Gemini 3.5 Flash" },
  { value: "llama-3.3-70b-versatile", label: "Llama 3.3 70B (Groq)" },
];

const NOTIFY_ON_LABELS: Record<keyof NotifyOn, string> = {
  incident_created: "Incident created",
  pipeline_failed: "Pipeline failed",
  deployment_failed: "Deployment failed",
  approval_required: "Approval required",
};

const TABS = [
  { id: "workspace", label: "Workspace" },
  { id: "profile", label: "Profile" },
  { id: "notifications", label: "Notifications" },
  { id: "ai-model", label: "AI Model" },
  { id: "theme", label: "Theme" },
  { id: "api-keys", label: "API Keys" },
];

export default function SettingsPage() {
  const token = getToken() as string;
  const user = decodeUserFromToken(token);
  const canManage = user?.role === "owner" || user?.role === "admin";
  const toast = useToast();
  const qc = useQueryClient();
  const [tab, setTab] = useState("workspace");

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
              <AiModelTab current={s?.ai_model_override ?? null} canManage={canManage} onSave={(u) => saveMut.mutate(u)} saving={saveMut.isPending} />
            )}
            {tab === "theme" && <ThemeTab token={token} />}
            {tab === "api-keys" && <ApiKeysTab token={token} canManage={canManage} />}
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
      saveSession(result.access_token, result.tenant_id, result.user_id);
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
  current, canManage, onSave, saving,
}: {
  current: string | null;
  canManage: boolean;
  onSave: (u: { ai_model_override: string | null }) => void;
  saving: boolean;
}) {
  const [value, setValue] = useState("");

  useEffect(() => { setValue(current ?? ""); }, [current]);

  return (
    <Card>
      <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 480 }}>
        {!canManage && <ReadOnlyNotice />}
        <p className="text-muted text-sm">
          Overrides which LLM AXIOM uses for this workspace. Leave on plan default unless you have a specific reason to pin one.
        </p>
        <Select label="Model" value={value} disabled={!canManage} onChange={(e) => setValue(e.target.value)}>
          {MODEL_OPTIONS.map((m) => (
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
                    <Button size="sm" variant="danger" disabled={revokeMut.isPending} onClick={() => revokeMut.mutate(k.id)}>Revoke</Button>
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
