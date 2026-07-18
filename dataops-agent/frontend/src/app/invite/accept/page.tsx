"use client";

import { useEffect, useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Button, Input, Skeleton, useToast } from "@/components/ui";
import { AuthShell } from "@/components/auth/AuthShell";
import { verifyInvite, acceptInvite, saveSession, ApiError, type InviteVerifyResult } from "@/lib/api";

// Public route (no auth guard) - the invitee isn't logged in yet. Not part
// of the (app) route group for exactly that reason.
export default function InviteAcceptPage() {
  return (
    <Suspense fallback={null}>
      <InviteAcceptInner />
    </Suspense>
  );
}

function InviteAcceptInner() {
  const router = useRouter();
  const toast = useToast();
  const params = useSearchParams();
  const token = params.get("token") || "";

  const [loading, setLoading] = useState(true);
  const [invite, setInvite] = useState<InviteVerifyResult | null>(null);
  const [invalidReason, setInvalidReason] = useState<string | null>(null);
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!token) {
      setInvalidReason("This invite link is missing its token.");
      setLoading(false);
      return;
    }
    verifyInvite(token)
      .then((result) => setInvite(result))
      .catch(() => setInvalidReason("This invite is invalid, expired, or has already been used."))
      .finally(() => setLoading(false));
  }, [token]);

  async function handleAccept(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      const result = await acceptInvite({ token, password, full_name: fullName });
      saveSession(result.access_token, result.tenant_id, result.user_id);
      router.push("/dashboard");
    } catch (err) {
      toast.push(err instanceof ApiError ? String(err.detail ?? "Failed to accept invite") : "Failed to accept invite", "danger");
      setSubmitting(false);
    }
  }

  return (
    <AuthShell headline="Join your team on Wunomo AI" tagline="Accept your invite to get started with AXIOM.">
      {loading ? (
        <div className="flex flex-col gap-3">
          <Skeleton style={{ height: 12, width: "70%" }} />
          <Skeleton style={{ height: 12, width: "50%" }} />
        </div>
      ) : invalidReason ? (
        <div className="flex flex-col gap-3">
          <p className="text-danger font-medium">{invalidReason}</p>
          <a href="/login" className="auth-link-btn">Back to login</a>
        </div>
      ) : (
        <form onSubmit={handleAccept} className="flex flex-col gap-4">
          <p className="text-sm">
            You&apos;ve been invited to join <strong>{invite?.tenant_name ?? "this workspace"}</strong> as{" "}
            <strong>{invite?.role}</strong>.
          </p>
          <Input label="Email" value={invite?.email ?? ""} disabled />
          <Input label="Full name" value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Optional" />
          <Input label="Password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          <Button type="submit" disabled={submitting || !password}>
            {submitting ? "Joining…" : "Accept invite & join"}
          </Button>
        </form>
      )}
    </AuthShell>
  );
}
