"use client";

import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Card, Badge, Button, Modal, Input, Select, Tabs, Skeleton, useToast,
} from "@/components/ui";
import {
  getToken, decodeUserFromToken, getSettings, updateSettings,
  createApiKey, listApiKeys, revokeApiKey,
  type NotifyOn, type ApiKeyItem,
} from "@/lib/api";
import { applyTheme, getStoredTheme, resolveEffectiveTheme, type ThemePreference } from "@/lib/theme";

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
            {tab === "notifications" && (
              <NotificationsTab prefs={s?.notification_prefs} canManage={canManage} onSave={(u) => saveMut.mutate(u)} saving={saveMut.isPending} />
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

  useEffect(() => {
    if (!settings) return;
    setName(settings.name ?? "");
    setTimezone(settings.timezone ?? "");
    setDescription(settings.description ?? "");
  }, [settings]);

  return (
    <Card>
      <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 480 }}>
        {!canManage && <ReadOnlyNotice />}
        <Input label="Workspace name" value={name} disabled={!canManage} onChange={(e) => setName(e.target.value)} />
        <Input label="Timezone" placeholder="e.g. America/New_York" value={timezone} disabled={!canManage} onChange={(e) => setTimezone(e.target.value)} />
        <Input label="Description" placeholder="Optional" value={description} disabled={!canManage} onChange={(e) => setDescription(e.target.value)} />
        {canManage && (
          <div>
            <Button size="sm" disabled={saving || !name.trim()} onClick={() => onSave({ name, timezone, description })}>
              {saving ? "Saving…" : "Save"}
            </Button>
          </div>
        )}
      </div>
    </Card>
  );
}

// ---------- Notifications ----------

function NotificationsTab({
  prefs, canManage, onSave, saving,
}: {
  prefs: { slack_webhook_url: string | null; alert_email: string | null; notify_on: NotifyOn } | undefined;
  canManage: boolean;
  onSave: (u: { notification_prefs: { slack_webhook_url?: string; alert_email?: string; notify_on: NotifyOn } }) => void;
  saving: boolean;
}) {
  const [webhook, setWebhook] = useState("");
  const [email, setEmail] = useState("");
  const [notifyOn, setNotifyOn] = useState<NotifyOn>({
    incident_created: true, pipeline_failed: true, deployment_failed: true, approval_required: true,
  });

  useEffect(() => {
    if (!prefs) return;
    setWebhook(prefs.slack_webhook_url ?? "");
    setEmail(prefs.alert_email ?? "");
    setNotifyOn(prefs.notify_on);
  }, [prefs]);

  return (
    <Card>
      <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 480 }}>
        {!canManage && <ReadOnlyNotice />}
        <Input label="Slack webhook URL" placeholder="https://hooks.slack.com/..." value={webhook} disabled={!canManage} onChange={(e) => setWebhook(e.target.value)} />
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
              disabled={saving}
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
                      <code>{k.key_prefix}…</code> · created {new Date(k.created_at).toLocaleDateString()}
                      {k.last_used_at ? ` · last used ${new Date(k.last_used_at).toLocaleDateString()}` : " · never used"}
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
