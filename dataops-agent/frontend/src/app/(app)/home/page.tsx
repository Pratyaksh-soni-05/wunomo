"use client";

// Command Center (blueprint §05, build 2026-09-30). Replaces the old plain
// "Welcome back" + project grid at /home -- /dashboard (pipeline/quality-
// centric, unrailed, reachable via ⌘K) is untouched and stays where it is.
//
// Governing rule taken directly from the build brief: "if nothing has
// happened to it in the last 24 hours, it is not on this page." Shipped as
// six parallel useQuery calls, no aggregating endpoint -- confirmed neither
// the blueprint nor DESIGN_SPEC.md actually specs a GET /workspace/live
// anywhere (grepped both directly; zero matches).
//
// Three fixed decisions applied, not re-litigated:
//   - No "Hours given back" card -- no real benchmark-minutes data exists
//     anywhere in this product to compute it honestly.
//   - "Working now" names the current step only (liveWorkStepLine) --
//     never a bare percentage or spinner. ActiveTaskRailItem has no
//     units_total/units_done to drive a real progress bar.
//   - No "Last 24 hours ▾" range dropdown from the mock: there is no second
//     honest range to switch to without new backend support, and a
//     dropdown with exactly one working option is the same kind of fake
//     control this codebase's own "never fabricate" rule forbids.
import { useMemo } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Button, Skeleton } from "@/components/ui";
import { NeedsYouStrip } from "@/components/dashboard/NeedsYouStrip";
import { WorkingNowList } from "@/components/dashboard/WorkingNowList";
import { SpendCycleCard } from "@/components/dashboard/SpendCycleCard";
import { JustFinishedCard } from "@/components/dashboard/JustFinishedCard";
import { ProjectStatusStrip } from "@/components/dashboard/ProjectStatusStrip";
import { RUNNING_STATUSES } from "@/lib/activeTaskDisplay";
import {
  getToken, decodeUserFromToken,
  getActiveTasks, getTasks, listAgents, listProjects, getUsage, getCurrentPlan,
} from "@/lib/api";

const DAY_MS = 24 * 60 * 60 * 1000;

function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

export default function HomePage() {
  const router = useRouter();
  const token = getToken() as string;
  const user = decodeUserFromToken(token);
  const displayName = user?.email ? user.email.split("@")[0] : "there";

  const activeTasksQuery = useQuery({ queryKey: ["active-tasks"], queryFn: () => getActiveTasks(token) });
  const tasksQuery = useQuery({ queryKey: ["tasks"], queryFn: () => getTasks(token) });
  const agentsQuery = useQuery({ queryKey: ["agents"], queryFn: () => listAgents(token) });
  const projectsQuery = useQuery({ queryKey: ["projects"], queryFn: () => listProjects(token) });
  const usageQuery = useQuery({ queryKey: ["billing-usage"], queryFn: () => getUsage(token) });
  const planQuery = useQuery({ queryKey: ["billing-plan"], queryFn: () => getCurrentPlan(token) });

  const activeTasks = useMemo(() => activeTasksQuery.data ?? [], [activeTasksQuery.data]);
  const needsYouTasks = useMemo(
    () => activeTasks.filter((t) => t.status === "paused_needs_approval"),
    [activeTasks]
  );
  const workingTasks = useMemo(
    () => activeTasks.filter((t) => RUNNING_STATUSES.has(t.status)),
    [activeTasks]
  );

  const agentsById = useMemo(
    () => new Map((agentsQuery.data?.agents ?? []).map((a) => [a.id, a])),
    [agentsQuery.data]
  );

  const justFinished = useMemo(() => {
    const cutoff = Date.now() - DAY_MS;
    return (tasksQuery.data ?? [])
      .filter((t) => t.status === "completed" && t.completed_at)
      .filter((t) => new Date(t.completed_at as string).getTime() >= cutoff)
      .sort((a, b) => new Date(b.completed_at as string).getTime() - new Date(a.completed_at as string).getTime())
      .slice(0, 6);
  }, [tasksQuery.data]);

  const isLoading = activeTasksQuery.isLoading || tasksQuery.isLoading || projectsQuery.isLoading;

  const workingAgentCount = new Set(workingTasks.map((t) => t.agent_id).filter(Boolean)).size;
  const activeProjectCount = new Set(activeTasks.map((t) => t.project_id).filter(Boolean)).size;
  const projects = projectsQuery.data?.projects ?? [];

  const nothingActive = activeTasks.length === 0 && justFinished.length === 0;

  let statusLine: string;
  if (needsYouTasks.length > 0) {
    statusLine = `${needsYouTasks.length} need${needsYouTasks.length === 1 ? "s" : ""} you.`;
  } else if (workingTasks.length > 0) {
    statusLine = "Everything's moving.";
  } else {
    statusLine = "Nothing needs you right now.";
  }

  return (
    <div style={{ padding: "44px 24px 56px", maxWidth: 1360, margin: "0 auto", width: "100%" }}>
      <div className="flex items-center justify-between" style={{ marginBottom: 24 }}>
        <div>
          <h1 className="font-display text-3xl">{greeting()}, {displayName}</h1>
          <p className="text-muted text-sm" style={{ margin: "6px 0 0" }}>
            {isLoading
              ? "Loading your workspace…"
              : `${workingAgentCount} employee${workingAgentCount === 1 ? "" : "s"} working across ${activeProjectCount} project${activeProjectCount === 1 ? "" : "s"}. ${statusLine}`}
          </p>
        </div>
        <Button onClick={() => router.push("/projects?new=1")}>New project</Button>
      </div>

      {isLoading ? (
        <Skeleton style={{ height: 300, borderRadius: 12 }} />
      ) : nothingActive ? (
        <div className="command-center-grid">
          <div className="command-center-empty card">
            {projects.length === 0 ? (
              <>
                <div className="command-center-empty-title">Nothing&apos;s running yet</div>
                <div className="command-center-empty-body">
                  Start a project and hire the employees it needs — their work will show up here the moment they start.
                </div>
                <Button onClick={() => router.push("/projects?new=1")}>Start a project</Button>
              </>
            ) : (
              <>
                <div className="command-center-empty-title">Your team is idle</div>
                <div className="command-center-empty-body">
                  Nothing&apos;s active and nothing finished in the last 24 hours. Open a project and give an employee a goal.
                </div>
                <Button onClick={() => router.push("/projects")}>Go to a project</Button>
              </>
            )}
          </div>
        </div>
      ) : (
        <div className="command-center-grid">
          <NeedsYouStrip tasks={needsYouTasks} />
          <WorkingNowList tasks={workingTasks} />
          <div className="command-center-side">
            <SpendCycleCard
              credits={usageQuery.data?.usage.ai_credits ?? null}
              planName={planQuery.data?.plan ?? null}
            />
            <JustFinishedCard tasks={justFinished} agentsById={agentsById} />
          </div>
          <ProjectStatusStrip activeTasks={activeTasks} />
        </div>
      )}
    </div>
  );
}
