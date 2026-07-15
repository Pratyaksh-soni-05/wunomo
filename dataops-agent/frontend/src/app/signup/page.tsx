"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Button, Input, useToast } from "@/components/ui";
import { AuthShell } from "@/components/auth/AuthShell";
import { WorkspacePicker } from "@/components/auth/WorkspacePicker";
import {
  register, requestEmailCode, verifyEmailCode, googleLoginUrl, resolveWorkspace,
  saveSession, getOnboarding, isChoose, isNoAccount,
  ApiError, type WorkspaceOption,
} from "@/lib/api";

type Mode = "form" | "code-request" | "code-verify";

async function completeAuth(token: string, tenantId: string, userId: string, router: ReturnType<typeof useRouter>) {
  saveSession(token, tenantId, userId);
  const profile = await getOnboarding(token).catch(() => ({ completed: false }));
  router.push(profile.completed ? "/dashboard" : "/onboarding");
}

export default function SignupPage() {
  const router = useRouter();
  const toast = useToast();
  const [mode, setMode] = useState<Mode>("form");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [tenantName, setTenantName] = useState("");
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const [nudge, setNudge] = useState<WorkspaceOption[]>([]);
  const [pendingAuth, setPendingAuth] = useState<{ token: string; tenantId: string; userId: string } | null>(null);
  const [workspaceOptions, setWorkspaceOptions] = useState<WorkspaceOption[] | null>(null);
  const pendingResubmit = useRef<((tenantId: string) => Promise<void>) | null>(null);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setInterval(() => setCooldown((c) => Math.max(0, c - 1)), 1000);
    return () => clearInterval(t);
  }, [cooldown]);

  async function handleRegister(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      const result = await register({ email, password, full_name: fullName, tenant_name: tenantName });
      if (result.existing_workspaces?.length) {
        // Non-blocking nudge (Phase 3 design): pause here so the banner is
        // actually visible instead of redirecting straight past it — the
        // user confirms via "Continue" below rather than auto-navigating.
        setNudge(result.existing_workspaces);
        setPendingAuth({ token: result.access_token, tenantId: result.tenant_id, userId: result.user_id });
        return;
      }
      await completeAuth(result.access_token, result.tenant_id, result.user_id, router);
    } catch (err) {
      toast.push(err instanceof ApiError ? String(err.detail ?? "Registration failed") : "Registration failed", "danger");
    } finally {
      setLoading(false);
    }
  }

  async function handleRequestCode(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await requestEmailCode(email);
      if (res.status === "rate_limited") {
        toast.push("Too many requests — try again later.", "warning");
        return;
      }
      toast.push("Code sent — check your email.", "success");
      setMode("code-verify");
      setCooldown(60);
    } catch {
      toast.push("Couldn't send code. Try again.", "danger");
    } finally {
      setLoading(false);
    }
  }

  async function handleVerifyCode(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      const result = await verifyEmailCode({ email, code, new_tenant_name: tenantName });
      if (isChoose(result)) {
        setWorkspaceOptions(result.options);
        const resolutionToken = result.resolution_token;
        pendingResubmit.current = async (tenantId: string) => {
          const r = await resolveWorkspace(resolutionToken!, tenantId);
          await completeAuth(r.access_token, r.tenant_id, r.user_id, router);
        };
        return;
      }
      if (isNoAccount(result)) {
        toast.push("Something went wrong creating your workspace. Try again.", "danger");
        return;
      }
      await completeAuth(result.access_token, result.tenant_id, result.user_id, router);
    } catch {
      toast.push("Invalid or expired code.", "danger");
    } finally {
      setLoading(false);
    }
  }

  async function handleGoogle() {
    if (tenantName) sessionStorage.setItem("axiom_pending_tenant_name", tenantName);
    const { url } = await googleLoginUrl();
    window.location.href = url;
  }

  return (
    <AuthShell
      headline="Set up your workspace on Wunomo AI"
      tagline="AXIOM, one of your AI employees, watches your pipelines, catches quality issues before they spread, and handles the busywork of DataOps autonomously."
    >
      <h2>Create your account</h2>
      <p className="auth-subtitle">Start your free workspace</p>

      {pendingAuth ? (
        <div className="flex flex-col gap-3">
          <div className="auth-nudge">
            <span>
              Heads up — this email already has {nudge.length === 1 ? "a workspace" : `${nudge.length} workspaces`}
              {" "}({nudge.map((w) => w.tenant_name).join(", ")}). Your new workspace was still created.
            </span>
          </div>
          <Button
            className="w-full"
            onClick={() => completeAuth(pendingAuth.token, pendingAuth.tenantId, pendingAuth.userId, router)}
          >
            Continue to your new workspace
          </Button>
          <Link href="/login" className="auth-link-btn" style={{ textAlign: "center" }}>
            Log in to an existing workspace instead
          </Link>
        </div>
      ) : mode === "form" && (
        <form onSubmit={handleRegister} className="flex flex-col gap-3">
          <Input id="signup-full-name" label="Full name" required value={fullName} onChange={(e) => setFullName(e.target.value)} />
          <Input id="signup-email" label="Email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          <Input id="signup-tenant-name" label="Workspace name" required value={tenantName} onChange={(e) => setTenantName(e.target.value)} />
          <Input id="signup-password" label="Password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          <Button type="submit" disabled={loading} className="w-full mt-2">Create account</Button>
          <button
            type="button"
            className="auth-link-btn"
            onClick={() => (tenantName && email ? setMode("code-request") : toast.push("Fill in your email and workspace name first.", "warning"))}
          >
            Verify by code instead of a password
          </button>
        </form>
      )}

      {mode === "code-request" && (
        <form onSubmit={handleRequestCode} className="flex flex-col gap-3">
          <p className="text-sm text-muted">We&apos;ll email a code to {email} to verify it&apos;s yours.</p>
          <Button type="submit" disabled={loading} className="w-full mt-2">Send code</Button>
          <button type="button" className="auth-link-btn" onClick={() => setMode("form")}>Back</button>
        </form>
      )}

      {mode === "code-verify" && (
        <form onSubmit={handleVerifyCode} className="flex flex-col gap-3">
          <p className="text-sm text-muted">Enter the 6-digit code sent to {email}</p>
          <Input id="signup-code" label="Code" required value={code} onChange={(e) => setCode(e.target.value)} maxLength={6} />
          <Button type="submit" disabled={loading} className="w-full mt-2">Verify &amp; create workspace</Button>
          <div className="flex justify-between items-center">
            <button type="button" className="auth-link-btn" onClick={() => setMode("form")}>Back</button>
            <button
              type="button"
              className="auth-link-btn"
              disabled={cooldown > 0}
              onClick={() => handleRequestCode(new Event("submit") as unknown as React.FormEvent)}
            >
              {cooldown > 0 ? `Resend in ${cooldown}s` : "Resend code"}
            </button>
          </div>
        </form>
      )}

      {!pendingAuth && (
        <>
          <div className="auth-divider">or</div>
          <Button variant="secondary" className="w-full" onClick={handleGoogle}>Continue with Google</Button>

          <p className="auth-footer">
            Already have a workspace? <Link href="/login" className="auth-link-btn">Log in</Link>
          </p>
        </>
      )}

      <WorkspacePicker
        open={!!workspaceOptions}
        options={workspaceOptions || []}
        onClose={() => setWorkspaceOptions(null)}
        onPick={async (tenantId) => {
          if (pendingResubmit.current) await pendingResubmit.current(tenantId);
          setWorkspaceOptions(null);
        }}
      />
    </AuthShell>
  );
}
