"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Button, Skeleton, useToast } from "@/components/ui";
import {
  getToken,
  getAnalyticsOverview,
  getQualityTrends,
  getRecentRuns,
  getApprovals,
  getOpenIncidents,
  getChatSessions,
} from "@/lib/api";
import { KpiCard } from "@/components/dashboard/KpiCard";
import { HealthBanner } from "@/components/dashboard/HealthBanner";
import { RunHistoryChart, QualityTrendChart } from "@/components/dashboard/TrendCharts";
import { RecentRunsCard } from "@/components/dashboard/RecentRunsCard";
import { ApprovalsCard } from "@/components/dashboard/ApprovalsCard";
import { AxiomActivityCard } from "@/components/dashboard/AxiomActivityCard";

export default function DashboardPage() {
  const router = useRouter();
  const toast = useToast();
  const token = getToken() as string;

  const overview = useQuery({ queryKey: ["analytics-overview"], queryFn: () => getAnalyticsOverview(token) });
  const quality = useQuery({ queryKey: ["quality-trends"], queryFn: () => getQualityTrends(token, 7) });
  const recentRuns = useQuery({ queryKey: ["recent-runs"], queryFn: () => getRecentRuns(token, 5) });
  const approvals = useQuery({ queryKey: ["approvals"], queryFn: () => getApprovals(token) });
  const incidents = useQuery({ queryKey: ["open-incidents"], queryFn: () => getOpenIncidents(token) });
  const sessions = useQuery({ queryKey: ["chat-sessions"], queryFn: () => getChatSessions(token) });

  const loading = overview.isLoading || quality.isLoading;
  const trends = quality.data?.trends ?? [];
  const runCounts = trends.map((t) => t.run_count);
  const qualityScores = trends.map((t) => t.avg_quality_score ?? 0);
  const healthTrend = trends.map((t) => (t.run_count > 0 ? Math.round((t.pass_count / t.run_count) * 100) : 0));

  const o = overview.data;
  const mostRecentIncident = incidents.data?.incidents?.[0];

  // Dismissing the health banner (finding 21) hides it for this specific
  // incident only, persisted so it survives a reload - it does not resolve
  // the incident (that's still a real, separate action via "Investigate").
  // Once the incident actually gets resolved, getOpenIncidents() (now
  // correctly filtered server-side) stops returning it at all, so the
  // banner disappears on its own regardless of this dismissed state - this
  // is purely for "I've seen this, stop showing it to me for now."
  const DISMISS_KEY = "axiom_dismissed_incident_id";
  const [dismissedId, setDismissedId] = useState<string | null>(null);
  useEffect(() => {
    setDismissedId(localStorage.getItem(DISMISS_KEY));
  }, []);
  const bannerIncident = mostRecentIncident && mostRecentIncident.id !== dismissedId ? mostRecentIncident : undefined;

  function refresh() {
    overview.refetch();
    quality.refetch();
    recentRuns.refetch();
    approvals.refetch();
    incidents.refetch();
    sessions.refetch();
    toast.push("Dashboard refreshed.", "default");
  }

  return (
    <div>
      <div className="page-header">
        <div className="flex items-center justify-between">
          <h1 className="page-title">Dashboard</h1>
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" onClick={refresh}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="23 4 23 10 17 10" />
                <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
              </svg>
              Refresh
            </Button>
            <Button size="sm" onClick={() => router.push("/chat")}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 2a8 8 0 0 1 8 8v12l-4-4H4a8 8 0 0 1 0-16" />
              </svg>
              Ask AXIOM
            </Button>
          </div>
        </div>
      </div>

      <div style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 20 }}>
        {loading ? (
          <div data-testid="dashboard-loading">
            <Skeleton style={{ height: 90, borderRadius: 12, marginBottom: 20 }} />
            <div className="stats-grid">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} style={{ height: 90, borderRadius: 12 }} />
              ))}
            </div>
          </div>
        ) : (
          <>
            {bannerIncident && (
              <HealthBanner
                incident={bannerIncident}
                onDismiss={() => {
                  localStorage.setItem(DISMISS_KEY, bannerIncident.id);
                  setDismissedId(bannerIncident.id);
                }}
              />
            )}

            <div className="stats-grid">
              <KpiCard
                label="System Health"
                value={`${o?.runs.success_rate_pct ?? 0}%`}
                subLabel="7-day success rate"
                color="var(--success)"
                sparklineData={healthTrend.length > 1 ? healthTrend : undefined}
              />
              <KpiCard
                label="Pipelines Active"
                value={String(o?.pipelines.active ?? 0)}
                subLabel={o?.pipelines.paused ? `${o.pipelines.paused} paused` : `${o?.pipelines.total ?? 0} total`}
                color="var(--text-primary)"
              />
              <KpiCard
                label="Quality Score"
                value={o?.quality.avg_score != null ? `${o.quality.avg_score}/100` : "—"}
                color="var(--accent-text)"
                chartColor="var(--chart-accent)"
                sparklineData={qualityScores.length > 1 ? qualityScores : undefined}
              />
              <KpiCard
                label="7-Day Runs"
                value={String(o?.runs.total ?? 0)}
                subLabel={`${o?.runs.success_rate_pct ?? 0}% success`}
                subLabelTone={(o?.runs.success_rate_pct ?? 0) >= 90 ? "up" : "neutral"}
                color="var(--text-primary)"
                sparklineData={runCounts.length > 1 ? runCounts : undefined}
              />
              <KpiCard
                label="Data Sources"
                value={String(o?.sources.total_active ?? 0)}
                subLabel={o?.sources.stale ? `${o.sources.stale} stale` : undefined}
                subLabelTone={o?.sources.stale ? "down" : "neutral"}
                color="var(--warning)"
              />
              <KpiCard
                label="Open Incidents"
                value={String(o?.incidents.open ?? 0)}
                color={o && o.incidents.open > 0 ? "var(--danger)" : "var(--success)"}
              />
              <KpiCard
                label="Pending Approvals"
                value={String(approvals.data?.count ?? 0)}
                color="var(--warning)"
              />
            </div>

            {trends.length > 0 && (
              <div className="grid grid-2" style={{ gap: 16 }}>
                <RunHistoryChart trends={trends} />
                <QualityTrendChart trends={trends} />
              </div>
            )}

            <div className="grid grid-3" style={{ gap: 16 }}>
              <RecentRunsCard runs={recentRuns.data?.runs ?? []} />
              <ApprovalsCard approvals={approvals.data?.approvals ?? []} token={token} />
              <AxiomActivityCard sessions={sessions.data?.sessions ?? []} />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
