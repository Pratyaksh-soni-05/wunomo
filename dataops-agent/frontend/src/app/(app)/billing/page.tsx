"use client";

import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Card, Button, Select, Progress, Skeleton, useToast } from "@/components/ui";
import {
  getToken, decodeUserFromToken, getUsage, getCurrentPlan, getPlans, changePlan,
  type QuotaStatus, type PlanLimits,
} from "@/lib/api";

const RESOURCE_LABELS: Record<string, string> = {
  ai_credits: "AI Credits",
  pipeline_runs: "Pipeline Runs",
  data_sources: "Data Sources",
  team_members: "Team Members",
};

const LIMIT_KEY: Record<string, keyof PlanLimits> = {
  ai_credits: "ai_credits_per_month",
  pipeline_runs: "pipeline_runs_per_month",
  data_sources: "max_data_sources",
  team_members: "max_team_members",
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
  const user = decodeUserFromToken(token);
  const canManage = user?.role === "owner" || user?.role === "admin";
  const toast = useToast();
  const qc = useQueryClient();
  const [selectedPlan, setSelectedPlan] = useState("");

  const usage = useQuery({ queryKey: ["billing-usage"], queryFn: () => getUsage(token) });
  const plan = useQuery({ queryKey: ["billing-plan"], queryFn: () => getCurrentPlan(token) });
  const plans = useQuery({ queryKey: ["billing-plans"], queryFn: () => getPlans() });

  useEffect(() => {
    if (plan.data?.plan) setSelectedPlan(plan.data.plan);
  }, [plan.data?.plan]);

  const changeMut = useMutation({
    mutationFn: (target: string) => changePlan(token, target),
    onSuccess: (result) => {
      toast.push(`Plan changed to ${planLabel(result.plan)}.`, "success");
      qc.invalidateQueries({ queryKey: ["billing-plan"] });
      qc.invalidateQueries({ queryKey: ["billing-usage"] });
    },
    onError: (e: unknown) => toast.push(e instanceof Error ? e.message : "Failed to change plan.", "danger"),
  });

  const planEntries = Object.entries(plans.data?.plans ?? {}) as [string, PlanLimits][];
  const usageEntries = Object.entries(usage.data?.usage ?? {}) as [string, QuotaStatus][];

  // The backend allows any plan change unconditionally, even when current
  // usage already exceeds the target plan's limits (verified live - it does
  // NOT block, it grandfathers existing usage and only hard-blocks *new*
  // usage of the over-limit resource afterward via enforce_quota). This
  // computes an honest, non-blocking warning from data already on the page
  // rather than inventing a client-side block the backend doesn't have.
  const targetLimits = plans.data?.plans?.[selectedPlan];
  const wouldExceed = targetLimits
    ? usageEntries
        .filter(([key, q]) => {
          const limit = targetLimits[LIMIT_KEY[key]];
          return limit !== null && q.used > limit;
        })
        .map(([key]) => RESOURCE_LABELS[key] ?? key)
    : [];

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Billing</h1>
      </div>

      <div style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 20, maxWidth: 640 }}>
        {plan.isLoading ? (
          <Skeleton style={{ height: 140, borderRadius: 12 }} />
        ) : (
          <Card>
            <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <div>
                <div className="text-muted text-sm">Current plan</div>
                <div className="font-display text-xl">{plan.data ? planLabel(plan.data.plan) : "—"}</div>
              </div>
              {canManage && (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <div className="flex gap-2" style={{ alignItems: "flex-end" }}>
                    <Select label="Change plan" value={selectedPlan} onChange={(e) => setSelectedPlan(e.target.value)}>
                      {planEntries.map(([name]) => <option key={name} value={name}>{planLabel(name)}</option>)}
                    </Select>
                    <Button
                      size="sm"
                      disabled={changeMut.isPending || !selectedPlan || selectedPlan === plan.data?.plan}
                      onClick={() => changeMut.mutate(selectedPlan)}
                    >
                      {changeMut.isPending ? "Changing…" : "Confirm change"}
                    </Button>
                  </div>
                  {wouldExceed.length > 0 && (
                    <p className="text-sm text-danger">
                      Your current usage already exceeds {planLabel(selectedPlan)}&apos;s limits for:{" "}
                      {wouldExceed.join(", ")}. The change will still go through — existing usage is
                      grandfathered, but any new usage of these will be blocked until you&apos;re back under
                      the limit.
                    </p>
                  )}
                </div>
              )}
              <p className="text-muted text-sm">
                Plan changes take effect immediately — there&apos;s no payment step yet (dev mode). This will
                change before launch.
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
