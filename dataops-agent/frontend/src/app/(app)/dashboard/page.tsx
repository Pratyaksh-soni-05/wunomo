"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Card, CardBody } from "@/components/ui";
import { getToken, clearSession, type OnboardingProfile, getOnboarding } from "@/lib/api";

export default function DashboardPage() {
  const router = useRouter();
  const [profile, setProfile] = useState<OnboardingProfile | null>(null);

  useEffect(() => {
    const token = getToken();
    if (token) getOnboarding(token).then(setProfile).catch(() => {});
  }, []);

  return (
    <div style={{ padding: 24, display: "flex", justifyContent: "center" }}>
      <Card style={{ maxWidth: 560, width: "100%" }}>
        <CardBody>
          <h2 className="font-display text-2xl mb-2">Welcome to Wunomo AI</h2>
          <p className="text-muted mb-4">
            You&apos;re signed in. AXIOM — your autonomous DataOps AI employee — is one of the personalities on the
            platform. The real dashboard (pipelines, quality, incidents) is wired up in Phase 9 — this page and the
            rest of the app shell around it (Phase 7) are what make that possible.
          </p>
          {profile && (
            <p className="text-sm text-secondary mb-4">
              Role: {profile.role} · Industry: {profile.industry} · Size: {profile.company_size}
            </p>
          )}
          <Button
            variant="secondary"
            onClick={() => {
              clearSession();
              router.push("/login");
            }}
          >
            Log out
          </Button>
        </CardBody>
      </Card>
    </div>
  );
}
