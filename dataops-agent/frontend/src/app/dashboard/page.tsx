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
    if (!token) {
      router.push("/login");
      return;
    }
    getOnboarding(token).then(setProfile).catch(() => {});
  }, [router]);

  return (
    <div className="onboarding-shell">
      <Card className="onboarding-card">
        <CardBody>
          <h2 className="font-display text-2xl mb-2">Welcome to Wunomo AI</h2>
          <p className="text-muted mb-4">
            You&apos;re signed in. AXIOM — your autonomous DataOps AI employee — is one of the personalities on the
            platform. The real dashboard (pipelines, quality, incidents) lands in a later phase — this is just
            confirmation the auth flow completed.
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
