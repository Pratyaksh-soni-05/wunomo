"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Badge, Button, Card, CardHeader, CardBody, Modal, Progress, Skeleton, useToast,
} from "@/components/ui";
import {
  getToken, listAgents, getSources, getAgentSources, grantAgentSource, revokeAgentSource,
  getAgentQuota, offboardAgent, ApiError,
} from "@/lib/api";

const EMPLOYEE_TYPE_LABEL: Record<string, string> = {
  dataops: "DataOps Engineer",
};

function progressVariant(status: string): "default" | "success" | "warning" | "danger" {
  if (status === "exceeded") return "danger";
  if (status === "warning") return "warning";
  return "success";
}

export default function AgentDetailPage() {
  const token = getToken() as string;
  const params = useParams();
  const agentId = params.id as string;
  const router = useRouter();
  const toast = useToast();
  const qc = useQueryClient();
  const [offboardModalOpen, setOffboardModalOpen] = useState(false);
  // Wunomo Projects Phase 2 frontend, slice 9: completes the "pre-scoped"
  // half of the denial-UI grant links (chat's ToolCallBlock, the task
  // detail page) -- reads window.location.search directly rather than
  // useSearchParams(), matching chat/page.tsx's own established reason:
  // useSearchParams() needs a <Suspense> boundary this app's shell doesn't
  // set up, or the production build fails; this only ever runs client-side
  // anyway ("use client" at the top of this file).
  const [highlightSourceId, setHighlightSourceId] = useState<string | null>(null);
  useEffect(() => {
    setHighlightSourceId(new URLSearchParams(window.location.search).get("highlight_source"));
  }, []);

  // No GET /api/v1/agents/{id} endpoint exists -- same reasoning as the
  // Projects detail page: list_agents() is already a single cheap
  // tenant-scoped query, so finding this agent's own name/type/status/
  // budget client-side avoids a second backend endpoint for a few fields.
  const agents = useQuery({ queryKey: ["agents"], queryFn: () => listAgents(token) });
  const sources = useQuery({ queryKey: ["sources"], queryFn: () => getSources(token) });
  const agentSources = useQuery({
    queryKey: ["agent-sources", agentId],
    queryFn: () => getAgentSources(token, agentId),
  });
  const quota = useQuery({ queryKey: ["agent-quota", agentId], queryFn: () => getAgentQuota(token, agentId) });

  const agent = agents.data?.agents.find((a) => a.id === agentId);
  const sourceList = sources.data?.sources ?? [];
  const grantedIds = new Set((agentSources.data?.sources ?? []).map((s) => s.id));

  const grantMut = useMutation({
    mutationFn: (sourceId: string) => grantAgentSource(token, agentId, sourceId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agent-sources", agentId] }),
    onError: () => toast.push("Failed to grant source access.", "danger"),
  });
  const revokeMut = useMutation({
    mutationFn: (sourceId: string) => revokeAgentSource(token, agentId, sourceId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agent-sources", agentId] }),
    onError: () => toast.push("Failed to revoke source access.", "danger"),
  });

  const offboardMut = useMutation({
    mutationFn: () => offboardAgent(token, agentId),
    onSuccess: () => {
      setOffboardModalOpen(false);
      toast.push(`"${agent?.name ?? "Agent"}" has been offboarded.`, "default");
      qc.invalidateQueries({ queryKey: ["agents"] });
      router.push("/agents");
    },
    onError: (err) => {
      setOffboardModalOpen(false);
      if (err instanceof ApiError && err.status === 409 && err.detail && typeof err.detail === "object") {
        const detail = err.detail as { message?: string; task_id?: string };
        toast.push(detail.message ?? "Cannot offboard this agent right now.", "warning", {
          label: "View task",
          onClick: () => router.push(`/tasks/${detail.task_id}`),
        });
      } else {
        toast.push("Failed to offboard agent.", "danger");
      }
    },
  });

  if (agents.isError || sources.isError || agentSources.isError || quota.isError) {
    return (
      <div>
        <div className="page-header"><h1 className="page-title">Agent</h1></div>
        <div style={{ padding: "20px 24px" }}>
          <div className="empty-state">
            <h2 className="font-display text-xl">Can&apos;t open this agent</h2>
            <p className="text-muted text-sm" style={{ maxWidth: 360 }}>
              It may not exist, or it may belong to a different tenant.
            </p>
            <Button size="sm" onClick={() => router.push("/agents")}>← Back to Agents</Button>
          </div>
        </div>
      </div>
    );
  }

  if (agents.isLoading || sources.isLoading || agentSources.isLoading || quota.isLoading || !agent) {
    return (
      <div>
        <div className="page-header"><h1 className="page-title">Agent</h1></div>
        <div style={{ padding: "20px 24px" }}><Skeleton style={{ height: 240, borderRadius: 12 }} /></div>
      </div>
    );
  }

  const isOffboarded = agent.status === "offboarded";
  const q = quota.data!;

  return (
    <div>
      <div className="page-header">
        <button className="auth-link-btn text-sm" onClick={() => router.push("/agents")}>← All Agents</button>
        <div className="flex items-center gap-2" style={{ marginTop: 4 }}>
          <h1 className="page-title">{agent.name}</h1>
          <Badge variant="midnight">{EMPLOYEE_TYPE_LABEL[agent.employee_type] ?? agent.employee_type}</Badge>
          <Badge variant={isOffboarded ? "gray" : "success"}>{isOffboarded ? "Offboarded" : "Active"}</Badge>
        </div>
      </div>

      <div style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 16 }}>
        {isOffboarded && (
          <Card>
            <CardBody>
              <p className="text-muted text-sm">
                This agent has been offboarded — it can no longer be reached from chat, channels,
                or new tasks. Its history and source scope are preserved.
              </p>
            </CardBody>
          </Card>
        )}

        <Card>
          <CardHeader><span className="font-medium text-sm">Data source scope</span></CardHeader>
          <CardBody>
            {sourceList.length === 0 ? (
              <p className="text-muted text-sm">
                No sources connected yet. <Link href="/sources" className="auth-link-btn">Connect one</Link> to
                scope this agent&apos;s access.
              </p>
            ) : (
              <div className="flex flex-col gap-2">
                {sourceList.map((s) => (
                  <label
                    key={s.id}
                    className="flex items-center gap-2 text-sm"
                    style={s.id === highlightSourceId ? {
                      background: "var(--accent-subtle-bg)", border: "1px solid var(--accent-subtle-border)",
                      borderRadius: "var(--radius-sm)", padding: "6px 8px", margin: "-6px -8px",
                    } : undefined}
                  >
                    <input
                      type="checkbox"
                      checked={grantedIds.has(s.id)}
                      disabled={isOffboarded || grantMut.isPending || revokeMut.isPending}
                      onChange={() => {
                        if (grantedIds.has(s.id)) revokeMut.mutate(s.id);
                        else grantMut.mutate(s.id);
                      }}
                    />
                    {s.name}
                    {s.id === highlightSourceId && <span className="text-xs text-muted">← needs access</span>}
                  </label>
                ))}
              </div>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader><span className="font-medium text-sm">Token budget</span></CardHeader>
          <CardBody>
            {q.limit === null ? (
              <p className="text-muted text-sm">
                No agent-level limit — this agent draws against the tenant&apos;s own plan quota only.
              </p>
            ) : (
              <div>
                <div className="flex items-center justify-between text-sm" style={{ marginBottom: 6 }}>
                  <span>Monthly tokens</span>
                  <span className="text-muted">
                    {q.used.toLocaleString()} / {q.limit.toLocaleString()}
                  </span>
                </div>
                <Progress value={q.percent} variant={progressVariant(q.status)} />
              </div>
            )}
          </CardBody>
        </Card>

        {!isOffboarded && (
          <Card>
            <CardHeader><span className="font-medium text-sm">Danger zone</span></CardHeader>
            <CardBody className="flex items-center justify-between">
              <p className="text-muted text-sm" style={{ maxWidth: 480 }}>
                Offboarding removes this agent from every channel it&apos;s in and stops it from
                answering chat, channel, or task work. Its history and source scope are kept.
                This can&apos;t be undone from this screen.
              </p>
              <Button variant="danger" size="sm" onClick={() => setOffboardModalOpen(true)}>
                Offboard agent
              </Button>
            </CardBody>
          </Card>
        )}
      </div>

      <Modal
        open={offboardModalOpen}
        onClose={() => setOffboardModalOpen(false)}
        title="Offboard this agent?"
        footer={
          <>
            <Button variant="secondary" onClick={() => setOffboardModalOpen(false)}>Cancel</Button>
            <Button variant="danger" disabled={offboardMut.isPending} onClick={() => offboardMut.mutate()}>
              {offboardMut.isPending ? "Offboarding…" : "Offboard"}
            </Button>
          </>
        }
      >
        <p className="text-sm">
          <strong>{agent.name}</strong> will stop being reachable from chat, channels, and new
          tasks. This can&apos;t be undone from this screen. If {agent.name} has a task still in
          progress, offboarding will be blocked until it&apos;s resolved.
        </p>
      </Modal>
    </div>
  );
}
