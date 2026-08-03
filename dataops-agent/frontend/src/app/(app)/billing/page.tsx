"use client";

import { useQuery } from "@tanstack/react-query";
import { Card, Progress, Skeleton } from "@/components/ui";
import { getToken, getUsage, getCurrentPlan, type QuotaStatus } from "@/lib/api";

const RESOURCE_LABELS: Record<string, string> = {
  ai_credits: "AI Credits",
  pipeline_runs: "Pipeline Runs",
  data_sources: "Data Sources",
  team_members: "Team Members",
};

function progressVariant(status: QuotaStatus["status"]): "default" | "success" | "warning" | "danger" {
  if (status === "exceeded") return "danger";
  if (status === "warning") return "warning";
  return "success";
}

function planLabel(name: string) {
  return name.charAt(0).toUpperCase() + name.slice(1);
}

export default function BillingPage() {
  const token = getToken() as string;

  const usage = useQuery({ queryKey: ["billing-usage"], queryFn: () => getUsage(token) });
  const plan = useQuery({ queryKey: ["billing-plan"], queryFn: () => getCurrentPlan(token) });

  const usageEntries = Object.entries(usage.data?.usage ?? {}) as [string, QuotaStatus][];

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Billing</h1>
      </div>

      <div style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 20, maxWidth: 640 }}>
        {plan.isLoading ? (
          <Skeleton style={{ height: 100, borderRadius: 12 }} />
        ) : (
          <Card>
            <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <div>
                <div className="text-muted text-sm">Current plan</div>
                <div className="font-display text-xl">{plan.data ? planLabel(plan.data.plan) : "—"}</div>
              </div>
              <p className="text-muted text-sm">
                Plan changes are handled manually by the AXIOM team for now — self-serve upgrades are
                disabled until Stripe billing is live. Contact us if you&apos;d like to change your plan.
              </p>
            </div>
          </Card>
        )}

        {usage.isLoading ? (
          <Skeleton style={{ height: 220, borderRadius: 12 }} />
        ) : (
          <Card>
            <div className="card-header text-sm text-muted">Usage this month</div>
            <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 18 }}>
              {usageEntries.map(([key, q]) => (
                <div key={key}>
                  <div className="flex items-center justify-between text-sm" style={{ marginBottom: 6 }}>
                    <span>{RESOURCE_LABELS[key] ?? key}</span>
                    <span className="text-muted">
                      {q.used.toLocaleString()} {q.limit === null ? "· Unlimited" : `/ ${q.limit.toLocaleString()}`}
                    </span>
                  </div>
                  <Progress value={q.limit === null ? 0 : q.percent} variant={progressVariant(q.status)} />
                </div>
              ))}
            </div>
          </Card>
        )}

        <Card>
          <div className="card-body">
            <div className="font-display" style={{ marginBottom: 4 }}>Checkout &amp; invoices</div>
            <p className="text-muted text-sm">Coming soon — Stripe billing isn&apos;t wired up yet.</p>
          </div>
        </Card>
      </div>
    </div>
  );
}
