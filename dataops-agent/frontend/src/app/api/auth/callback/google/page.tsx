"use client";

import { useEffect, useState, useRef, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Skeleton } from "@/components/ui";
import { WorkspacePicker } from "@/components/auth/WorkspacePicker";
import {
  googleCallback, resolveWorkspace, saveSession, getOnboarding,
  isChoose, ApiError, type WorkspaceOption,
} from "@/lib/api";

async function completeAuth(token: string, tenantId: string, userId: string, router: ReturnType<typeof useRouter>) {
  saveSession(token, tenantId, userId);
  const profile = await getOnboarding(token).catch(() => ({ completed: false }));
  router.push(profile.completed ? "/dashboard" : "/onboarding");
}

export default function GoogleCallbackPage() {
  return (
    <Suspense fallback={null}>
      <GoogleCallbackInner />
    </Suspense>
  );
}

function GoogleCallbackInner() {
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const [workspaceOptions, setWorkspaceOptions] = useState<WorkspaceOption[] | null>(null);
  const pendingResubmit = useRef<((tenantId: string) => Promise<void>) | null>(null);
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;

    const code = params.get("code");
    const state = params.get("state");
    if (!code || !state) {
      setError("Missing authorization code from Google.");
      return;
    }

    const new_tenant_name = sessionStorage.getItem("axiom_pending_tenant_name") || undefined;
    sessionStorage.removeItem("axiom_pending_tenant_name");

    googleCallback({ code, state, new_tenant_name })
      .then(async (result) => {
        if (isChoose(result)) {
          setWorkspaceOptions(result.options);
          const resolutionToken = result.resolution_token;
          pendingResubmit.current = async (tenantId: string) => {
            const r = await resolveWorkspace(resolutionToken!, tenantId);
            await completeAuth(r.access_token, r.tenant_id, r.user_id, router);
          };
          return;
        }
        if ("status" in result && result.status === "no_account") {
          setError("No workspace found for this Google account. Sign up first, then link Google from there.");
          return;
        }
        await completeAuth(result.access_token, result.tenant_id, result.user_id, router);
      })
      .catch((err) => {
        setError(
          err instanceof ApiError && err.status === 403
            ? String(err.detail)
            : "Google sign-in failed. Please try again."
        );
      });
  }, [params, router]);

  return (
    <div className="onboarding-shell">
      <div className="onboarding-card card p-6">
        {error ? (
          <div className="flex flex-col gap-3">
            <p className="text-danger font-medium">{error}</p>
            <a href="/login" className="auth-link-btn">Back to login</a>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <p className="text-secondary">Finishing Google sign-in…</p>
            <Skeleton style={{ height: 12, width: "60%" }} />
            <Skeleton style={{ height: 12, width: "40%" }} />
          </div>
        )}
      </div>
      <WorkspacePicker
        open={!!workspaceOptions}
        options={workspaceOptions || []}
        onClose={() => setWorkspaceOptions(null)}
        onPick={async (tenantId) => {
          if (pendingResubmit.current) await pendingResubmit.current(tenantId);
          setWorkspaceOptions(null);
        }}
      />
    </div>
  );
}
