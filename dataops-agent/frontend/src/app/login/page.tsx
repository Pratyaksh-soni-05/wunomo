"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Button, Input, useToast } from "@/components/ui";
import { AuthShell } from "@/components/auth/AuthShell";
import { WorkspacePicker } from "@/components/auth/WorkspacePicker";
import {
  login, requestEmailCode, verifyEmailCode, googleLoginUrl, resolveWorkspace,
  saveSession, getOnboarding, isChoose, isNoAccount,
  ApiError, type WorkspaceOption,
} from "@/lib/api";

type Mode = "password" | "code-request" | "code-verify";

async function completeLogin(token: string, tenantId: string, userId: string, router: ReturnType<typeof useRouter>) {
  saveSession(token, tenantId, userId);
  const profile = await getOnboarding(token).catch(() => ({ completed: false }));
  router.push(profile.completed ? "/dashboard" : "/onboarding");
}

export default function LoginPage() {
  const router = useRouter();
  const toast = useToast();
  const [mode, setMode] = useState<Mode>("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const [workspaceOptions, setWorkspaceOptions] = useState<WorkspaceOption[] | null>(null);
  const pendingResubmit = useRef<((tenantId: string) => Promise<void>) | null>(null);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setInterval(() => setCooldown((c) => Math.max(0, c - 1)), 1000);
    return () => clearInterval(t);
  }, [cooldown]);

  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("expired") === "1") {
      toast.push("Your session expired. Please log in again.", "warning");
      router.replace("/login");
    }
    // Runs once on mount to consume the ?expired=1 redirect marker.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handlePasswordSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      const result = await login(email, password);
      if (isChoose(result)) {
        setWorkspaceOptions(result.options);
        pendingResubmit.current = async (tenantId: string) => {
          const r = await login(email, password, tenantId);
          if (!isChoose(r)) await completeLogin(r.access_token, r.tenant_id, r.user_id, router);
        };
        return;
      }
      await completeLogin(result.access_token, result.tenant_id, result.user_id, router);
    } catch (err) {
      toast.push(err instanceof ApiError ? String(err.detail ?? "Invalid credentials") : "Login failed", "danger");
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
        toast.push("Too many requests right now. Try again in a bit.", "warning");
        return;
      }
      toast.push("Check your email for the code.", "success");
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
      const result = await verifyEmailCode({ email, code });
      if (isChoose(result)) {
        setWorkspaceOptions(result.options);
        const resolutionToken = result.resolution_token;
        pendingResubmit.current = async (tenantId: string) => {
          // The code is already single-use consumed at this point — finalize
          // against the resolution token, not by resubmitting the code.
          const r = await resolveWorkspace(resolutionToken!, tenantId);
          await completeLogin(r.access_token, r.tenant_id, r.user_id, router);
        };
        return;
      }
      if (isNoAccount(result)) {
        toast.push("No workspace found for this email. Sign up instead.", "warning");
        return;
      }
      await completeLogin(result.access_token, result.tenant_id, result.user_id, router);
    } catch {
      toast.push("Invalid or expired code.", "danger");
    } finally {
      setLoading(false);
    }
  }

  async function handleGoogle() {
    try {
      const { url } = await googleLoginUrl();
      window.location.href = url;
    } catch (err) {
      // A blocked CORS preflight (wrong origin/port) throws a raw fetch
      // TypeError here, not an ApiError — surface that case with an
      // actionable message instead of letting the click look dead. See
      // docs/context/WALKTHROUGH_FINDINGS_2026-08.md for the origin-
      // mismatch history this is guarding against.
      console.error("Google sign-in failed:", err);
      toast.push(
        err instanceof ApiError
          ? String(err.detail ?? "Google sign-in failed.")
          : "Couldn't reach the API. Check the backend is running and this page is open on the origin it expects (localhost:3000 in dev).",
        "danger"
      );
    }
  }

  return (
    <AuthShell
      headline="Welcome back to Wunomo AI"
      tagline="Meet AXIOM, your autonomous DataOps AI employee — pipelines, quality checks, and incident response, all in one place."
    >
      <h2>Log in</h2>
      <p className="auth-subtitle">Access your workspace</p>

      {mode === "password" && (
        <form onSubmit={handlePasswordSubmit} className="flex flex-col gap-3">
          <Input id="login-email" label="Email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          <Input id="login-password" label="Password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          <Button type="submit" disabled={loading} className="w-full mt-2">Log in</Button>
          <button type="button" className="auth-link-btn" onClick={() => setMode("code-request")}>
            Email me a code instead
          </button>
        </form>
      )}

      {mode === "code-request" && (
        <form onSubmit={handleRequestCode} className="flex flex-col gap-3">
          <Input id="login-code-email" label="Email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          <Button type="submit" disabled={loading} className="w-full mt-2">Send code</Button>
          <button type="button" className="auth-link-btn" onClick={() => setMode("password")}>
            Back to password
          </button>
        </form>
      )}

      {mode === "code-verify" && (
        <form onSubmit={handleVerifyCode} className="flex flex-col gap-3">
          <p className="text-sm text-muted">Enter the 6-digit code sent to {email}</p>
          <Input id="login-code" label="Code" required value={code} onChange={(e) => setCode(e.target.value)} maxLength={6} />
          <Button type="submit" disabled={loading} className="w-full mt-2">Verify &amp; log in</Button>
          <div className="flex justify-between items-center">
            <button type="button" className="auth-link-btn" onClick={() => setMode("password")}>
              Back to password
            </button>
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

      <div className="auth-divider">or</div>
      <Button variant="secondary" className="w-full" onClick={handleGoogle}>Continue with Google</Button>

      <p className="auth-footer">
        Don&apos;t have a workspace? <Link href="/signup" className="auth-link-btn">Sign up</Link>
      </p>

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
