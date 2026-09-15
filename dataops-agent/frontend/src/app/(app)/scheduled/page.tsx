"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, Badge, Button, Table, Thead, Tbody, Tr, Th, Td, Skeleton, useToast } from "@/components/ui";
import { taskStatusVariant, taskStatusLabel, shapeLabel } from "@/components/tasks/taskDisplay";
import { formatApiDate } from "@/lib/dates";
import {
  getToken, getSchedules, reactivateSchedule, deleteSchedule,
  ApiError, type ScheduleItem,
} from "@/lib/api";

/**
 * Scheduled (Wunomo UI-rebuild slice 10, 2026-09-15) -- replaces the
 * StubPage with the real, tenant-wide ScheduledAgentTask list. Pipeline
 * schedule_cron deliberately NOT shown here (explicit decision): it's an
 * unrelated mechanism with no deactivation-reason concept at all, already
 * has a correct home in each project's Workbench Pipelines tab (schedule
 * column, Pause/Activate), and bolting it into this table would mean an
 * "Agent" column empty for every pipeline row -- two things forced into
 * one shape rather than each keeping its own.
 *
 * No create button -- ScheduledAgentTask's own docstring calls the
 * creation UI "its own later slice," deliberately deferred when the
 * backend was built. Confirmed why: tool_name is constrained to a small
 * fixed set per task_shape (TASK_SHAPE_ALLOWED_TOOLS, ~14 tools total
 * across the 3 shapes), but tool_args' real shape differs per tool (some
 * need source_id, some pipeline_id, some nothing) with no single generic
 * schema to render a form from -- real work, logged as its own finding
 * rather than shipping a form that produces args the backend would
 * reject. Creation stays API-only; the empty state says so plainly.
 *
 * "On" is a static badge, not a toggle -- there is no manual pause
 * endpoint, only automatic deactivation. Reactivate and Delete are the
 * only two real actions on an inactive row; deactivation_reason is shown
 * verbatim (already real, written prose from validate_schedule_can_run,
 * not a code needing UI copy) rather than the preview's own "re-point it"
 * phrasing, which describes an edit action that doesn't exist --
 * tool_args are immutable once a schedule is created, so every real
 * message says "delete this schedule and create a new one," not "edit."
 */
export default function ScheduledPage() {
  const token = getToken() as string;
  const toast = useToast();
  const qc = useQueryClient();

  const schedulesQuery = useQuery({ queryKey: ["schedules"], queryFn: () => getSchedules(token) });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["schedules"] });

  const reactivateMut = useMutation({
    mutationFn: (s: ScheduleItem) => reactivateSchedule(token, s.agent_id, s.id),
    onSuccess: () => { toast.push("Reactivated.", "success"); invalidate(); },
    onError: (err: unknown) => {
      // The real, live re-validation the backend re-runs at this exact
      // click -- if the cause is still true, this is the same message
      // deactivation_reason already shows, not a generic failure.
      const message = err instanceof ApiError && typeof err.detail === "string"
        ? err.detail
        : "Failed to reactivate.";
      toast.push(message, "danger");
    },
  });

  const deleteMut = useMutation({
    mutationFn: (s: ScheduleItem) => deleteSchedule(token, s.agent_id, s.id),
    onSuccess: () => { toast.push("Schedule deleted.", "default"); invalidate(); },
    onError: () => toast.push("Failed to delete.", "danger"),
  });

  if (schedulesQuery.isError) {
    const err = schedulesQuery.error;
    const forbidden = err instanceof ApiError && err.status === 403;
    return (
      <div>
        <div className="page-header"><h1 className="page-title">Scheduled</h1></div>
        <div style={{ padding: "20px 24px" }}>
          <div className="empty-state">
            <h2 className="font-display text-xl">{forbidden ? "You don't have permission to view this" : "Couldn't load schedules"}</h2>
            <p className="text-muted text-sm" style={{ maxWidth: 380 }}>
              {forbidden
                ? "Scheduled work is visible to workspace Owners and Admins."
                : "Something went wrong loading schedules. Try again."}
            </p>
          </div>
        </div>
      </div>
    );
  }

  const list = schedulesQuery.data?.schedules ?? [];
  const inactiveList = list.filter((s) => !s.active);

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Scheduled</h1>
      </div>

      <div style={{ padding: "20px 24px" }}>
        {schedulesQuery.isLoading ? (
          <Skeleton style={{ height: 300, borderRadius: 12 }} />
        ) : list.length === 0 ? (
          <div className="empty-state">
            <h2 className="font-display text-xl">No schedules yet</h2>
            <p className="text-muted text-sm" style={{ maxWidth: 420 }}>
              A schedule runs one fixed action for an agent on a cron interval — a freshness check
              every morning, a weekly drift report — with no re-planning involved. There&apos;s no
              creation screen yet; schedules are created via the API today
              (<code>POST /api/v1/agents/&#123;agent_id&#125;/schedules</code>).
            </p>
          </div>
        ) : (
          <>
            <Card>
              <Table>
                <Thead>
                  <Tr>
                    <Th>What</Th>
                    <Th>Agent</Th>
                    <Th>Project</Th>
                    <Th>When</Th>
                    <Th>Last run</Th>
                    <Th></Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {list.map((s) => (
                    <Tr key={s.id}>
                      <Td>
                        <div className="font-medium">{s.description}</div>
                        <div className="text-muted text-xs">{shapeLabel(s.task_shape)}</div>
                      </Td>
                      <Td>{s.agent_name ?? "—"}</Td>
                      <Td>{s.project_name ?? "No project"}</Td>
                      <Td><code className="text-xs">{s.schedule_cron}</code></Td>
                      <Td>
                        {s.last_run ? (
                          <div className="flex items-center gap-2">
                            <Badge variant={taskStatusVariant(s.last_run.status)}>{taskStatusLabel(s.last_run.status)}</Badge>
                            <span className="text-muted text-xs">{formatApiDate(s.last_run.completed_at ?? s.last_run.created_at)}</span>
                          </div>
                        ) : (
                          <span className="text-muted text-sm">Never run</span>
                        )}
                      </Td>
                      <Td>
                        <Badge variant={s.active ? "success" : "danger"}>{s.active ? "on" : "off"}</Badge>
                      </Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            </Card>

            {inactiveList.length > 0 && (
              <div className="flex flex-col gap-3" style={{ marginTop: 16 }}>
                {inactiveList.map((s) => (
                  <Card key={s.id} style={{ padding: 16, borderColor: "var(--danger)" }}>
                    <div className="font-medium text-sm" style={{ marginBottom: 3 }}>
                      &quot;{s.description}&quot; was turned off automatically
                    </div>
                    <p className="text-muted text-sm" style={{ margin: "0 0 11px" }}>
                      {s.deactivation_reason}
                    </p>
                    <div className="flex gap-2">
                      <Button size="sm" disabled={reactivateMut.isPending} onClick={() => reactivateMut.mutate(s)}>
                        Reactivate
                      </Button>
                      <Button size="sm" variant="secondary" disabled={deleteMut.isPending} onClick={() => deleteMut.mutate(s)}>
                        Delete
                      </Button>
                    </div>
                  </Card>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
