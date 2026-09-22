"use client";

// Item #14: WorkOS sends the browser back here with ?code=&state= after the
// customer's IdP has authenticated the user. Mirrors the Google callback
// page: no picker is needed (the tenant was fixed before the IdP was
// contacted), and an MFA challenge is parked for /login the same way.

import { useEffect, useState, useRef, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Skeleton } from "@/components/ui";
import { ssoCallback, saveSession, getOnboarding, isMfaRequired, ApiError } from "@/lib/api";

async function completeAuth(token: string, tenantId: string, userId: string, router: ReturnType<typeof useRouter>) {
  saveSession(token, tenantId, userId);
  const profile = await getOnboarding(token).catch(() => ({ completed: false }));
  router.push(profile.completed ? "/dashboard" : "/onboarding");
}

export default function SsoCallbackPage() {
  return (
    <Suspense fallback={null}>
      <SsoCallbackInner />
    </Suspense>
  );
}

function SsoCallbackInner() {
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    const code = params.get("code");
    const state = params.get("state");
    if (!code || !state) {
      setError(params.get("error_description") || "Missing authorization code from the identity provider.");
      return;
    }
    ssoCallback({ code, state })
      .then(async (result) => {
        if (isMfaRequired(result)) {
          try { sessionStorage.setItem("wunomo_mfa_token", result.mfa_token); } catch { /* storage unavailable */ }
          router.replace("/login");
          return;
        }
        await completeAuth(result.access_token, result.tenant_id, result.user_id, router);
      })
      .catch((err) => {
        setError(err instanceof ApiError ? String(err.detail ?? "Single sign-on failed.") : "Single sign-on failed.");
      });
  }, [params, router]);

  if (error) {
    return (
      <div style={{ maxWidth: 480, margin: "80px auto", padding: 24 }}>
        <h2>Single sign-on failed</h2>
        <p className="text-danger text-sm">{error}</p>
        <p className="text-sm"><a href="/login" className="auth-link-btn">Back to login</a></p>
      </div>
    );
  }
  return <div style={{ maxWidth: 480, margin: "80px auto", padding: 24 }}><Skeleton style={{ height: 120 }} /></div>;
}
