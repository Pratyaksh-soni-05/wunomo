"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Skeleton, useToast } from "@/components/ui";
import { ProjectHeader } from "@/components/chat";
import { ProjectChatContext, type ProjectChatContextValue } from "@/components/chat/ProjectChatContext";
import { computeProjectStatusBadge } from "@/lib/projectStatusBadge";
import {
  getToken, decodeUserFromToken, listProjects, getProjectAgents, listChannels, getChannel,
  getTeamMembers, getTasks, getActiveTasks, createChannel, addChannelAgent, removeChannelAgent,
  addChannelUser, removeChannelUser, ApiError,
} from "@/lib/api";

const TABS = [
  { slug: "chat", label: "Chat" },
  { slug: "workbench", label: "Workbench" },
  { slug: "tasks", label: "Tasks" },
  { slug: "agents", label: "Agents" },
];

/**
 * The project container shell. Header-merge pass (item 1, blueprint chrome
 * follow-up): this used to render a plain "← All Projects / {name} / [Hire
 * agent]" row, and the chat page rendered a SECOND, full §7.2 header below
 * it -- two headers, ~180px of chrome before any message, the single
 * biggest divergence from the blueprint's one-header layout. This file now
 * owns everything ProjectHeader needs (roster, channels, task counts,
 * personality/operation mode) and renders it as the container's only
 * header row, on all four tabs -- not just Chat, since project name, task
 * progress, and roster are project-level facts true regardless of which
 * tab is open. The chat page consumes this same state via
 * ProjectChatContext instead of owning its own copy.
 *
 * No GET /api/v1/projects/{id} endpoint exists -- same reasoning as before:
 * listProjects() is already a single cheap tenant-scoped query, so finding
 * this project's own name client-side avoids a second backend endpoint for
 * one field.
 */
export default function ProjectContainerLayout({ children }: { children: ReactNode }) {
  const token = getToken() as string;
  const decoded = decodeUserFromToken(token);
  const currentUserId = decoded?.sub ?? null;
  const params = useParams();
  const projectId = params.id as string;
  const pathname = usePathname();
  const router = useRouter();
  const qc = useQueryClient();
  const toast = useToast();

  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [personalityMode, setPersonalityMode] = useState("engineer");
  const [operationMode, setOperationMode] = useState("assisted");
  const [liveWorkOpen, setLiveWorkOpen] = useState(false);
  const autoSelectedRef = useRef(false);

  const projects = useQuery({ queryKey: ["projects"], queryFn: () => listProjects(token) });
  const project = projects.data?.projects.find((p) => p.id === projectId);

  const projectAgentsQuery = useQuery({ queryKey: ["project-agents", projectId], queryFn: () => getProjectAgents(token, projectId) });
  const agentRoster = projectAgentsQuery.data?.agents ?? [];
  const selectableAgents = agentRoster.map((a) => ({ id: a.id, name: a.name, sources: [] }));

  const channelsQuery = useQuery({ queryKey: ["channels"], queryFn: () => listChannels(token) });
  const projectChannels = (channelsQuery.data?.channels ?? []).filter((c) => c.project_id === projectId);
  const teamQuery = useQuery({ queryKey: ["team-members"], queryFn: () => getTeamMembers(token) });

  const agentIds = new Set(agentRoster.map((a) => a.id));
  const tasksQuery = useQuery({ queryKey: ["tasks"], queryFn: () => getTasks(token) });
  const projectTasks = (tasksQuery.data ?? []).filter((t) => t.agent_id && agentIds.has(t.agent_id));
  const tasksTotal = projectTasks.length;
  const tasksDone = projectTasks.filter((t) => t.status === "completed").length;

  const activeTasksQuery = useQuery({ queryKey: ["active-tasks"], queryFn: () => getActiveTasks(token), enabled: !!token });
  const sessionActiveTaskCount = activeSessionId
    ? (activeTasksQuery.data ?? []).filter((t) => t.originating_session_id === activeSessionId).length
    : 0;

  // §7.2 header status badge -- project-wide (every channel's tasks).
  // Precedence lives in lib/projectStatusBadge.ts, shared with Command
  // Center's project-cards strip (blueprint §05) so the two can't drift.
  const projectActiveTasks = (activeTasksQuery.data ?? []).filter((t) => t.project_id === projectId);
  const statusBadge = computeProjectStatusBadge(projectActiveTasks);

  const activeChannel = projectChannels.find((c) => c.id === activeSessionId) ?? null;
  const channelDetailQuery = useQuery({
    queryKey: ["channel-detail", activeSessionId],
    queryFn: () => getChannel(token, activeSessionId as string),
    enabled: !!activeChannel,
  });

  // Lands on the project's most recently active channel rather than a
  // blank composer with nothing selected. Lives here, not the chat page,
  // now that activeSessionId itself lives here -- and since this layout
  // persists across tab switches (the chat page fully unmounts/remounts),
  // the selection now survives navigating to Workbench and back, which it
  // didn't before.
  useEffect(() => {
    if (autoSelectedRef.current || activeSessionId) return;
    if (projectChannels.length > 0) {
      autoSelectedRef.current = true;
      setActiveSessionId(projectChannels[0].id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectChannels.length]);

  const createChannelWithAgents = async (name: string, agentIds2: string[]) => {
    try {
      const channel = await createChannel(token, { name, project_id: projectId });
      for (const agentId of agentIds2) {
        await addChannelAgent(token, channel.id, agentId);
      }
      qc.invalidateQueries({ queryKey: ["channels"] });
      autoSelectedRef.current = true;
      setActiveSessionId(channel.id);
      if (!pathname.endsWith("/chat")) router.push(`/projects/${projectId}/chat`);
      toast.push(`Channel "${channel.name}" created.`, "success");
    } catch {
      toast.push("Failed to create channel.", "danger");
    }
  };

  const addAgentToActiveChannel = async (agentId: string) => {
    if (!activeSessionId) return;
    try {
      const result = await addChannelAgent(token, activeSessionId, agentId);
      qc.invalidateQueries({ queryKey: ["channel-detail", activeSessionId] });
      qc.invalidateQueries({ queryKey: ["channels"] });
      toast.push(`${result.agent_name} added to the channel.`, "success");
    } catch {
      toast.push("Failed to add agent.", "danger");
    }
  };

  const removeAgentFromActiveChannel = async (agentId: string, agentName: string) => {
    if (!activeSessionId) return;
    try {
      await removeChannelAgent(token, activeSessionId, agentId);
      qc.invalidateQueries({ queryKey: ["channel-detail", activeSessionId] });
      qc.invalidateQueries({ queryKey: ["channels"] });
      toast.push(`${agentName} removed from the channel.`, "default");
    } catch {
      toast.push("Failed to remove agent.", "danger");
    }
  };

  const addPersonToActiveChannel = async (userId: string) => {
    if (!activeSessionId) return;
    try {
      await addChannelUser(token, activeSessionId, userId);
      qc.invalidateQueries({ queryKey: ["channel-detail", activeSessionId] });
      toast.push("Added to the channel.", "success");
    } catch {
      toast.push("Failed to add person.", "danger");
    }
  };

  const removePersonFromActiveChannel = async (userId: string) => {
    if (!activeSessionId) return;
    try {
      await removeChannelUser(token, activeSessionId, userId);
      if (userId === currentUserId) {
        setActiveSessionId(null);
        qc.invalidateQueries({ queryKey: ["channels"] });
        toast.push("You left the channel.", "default");
      } else {
        qc.invalidateQueries({ queryKey: ["channel-detail", activeSessionId] });
        toast.push("Removed from the channel.", "default");
      }
    } catch (err) {
      const message = err instanceof ApiError && typeof err.detail === "string" ? err.detail : "Failed to remove person.";
      toast.push(message, "danger");
    }
  };

  const activeTab = pathname.split("/")[3] ?? "";

  if (projects.isError) {
    return (
      <div>
        <div className="page-header"><h1 className="page-title">Project</h1></div>
        <div style={{ padding: "20px 24px" }}>
          <div className="empty-state">
            <h2 className="font-display text-xl">Can&apos;t open this project</h2>
            <p className="text-muted text-sm" style={{ maxWidth: 360 }}>
              It may not exist, or it may belong to a different tenant.
            </p>
            <Button size="sm" onClick={() => router.push("/projects")}>← Back to Projects</Button>
          </div>
        </div>
      </div>
    );
  }

  if (projects.isLoading) {
    return (
      <div>
        <div className="page-header"><h1 className="page-title">Project</h1></div>
        <div style={{ padding: "20px 24px" }}><Skeleton style={{ height: 200, borderRadius: 12 }} /></div>
      </div>
    );
  }

  if (!project) {
    return (
      <div>
        <div className="page-header"><h1 className="page-title">Project</h1></div>
        <div style={{ padding: "20px 24px" }}>
          <div className="empty-state">
            <h2 className="font-display text-xl">Can&apos;t open this project</h2>
            <p className="text-muted text-sm" style={{ maxWidth: 360 }}>
              It may not exist, or it may belong to a different tenant.
            </p>
            <Button size="sm" onClick={() => router.push("/projects")}>← Back to Projects</Button>
          </div>
        </div>
      </div>
    );
  }

  const contextValue: ProjectChatContextValue = {
    activeSessionId, setActiveSessionId,
    channels: projectChannels, channelsLoading: channelsQuery.isLoading,
    activeChannel,
    channelAgents: channelDetailQuery.data?.agents ?? [],
    channelUsers: channelDetailQuery.data?.users ?? [],
    agentRoster, agentRosterLoading: projectAgentsQuery.isLoading,
    selectableAgents,
    availablePeople: teamQuery.data?.members ?? [],
    currentUserId,
    createChannelWithAgents, addAgentToActiveChannel, removeAgentFromActiveChannel,
    addPersonToActiveChannel, removePersonFromActiveChannel,
    personalityMode, operationMode, setPersonalityMode, setOperationMode,
    liveWorkOpen, setLiveWorkOpen,
    sessionActiveTaskCount,
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <ProjectHeader
        token={token}
        projectId={projectId}
        projectName={project.name}
        projectDescription={project.description ?? null}
        tasksDone={tasksDone}
        tasksTotal={tasksTotal}
        statusBadge={statusBadge}
        agentRoster={agentRoster}
        availableAgents={selectableAgents}
        channels={projectChannels}
        activeChannel={activeChannel}
        onSelectChannel={setActiveSessionId}
        onCreateChannel={createChannelWithAgents}
        channelAgents={channelDetailQuery.data?.agents ?? []}
        channelUsers={channelDetailQuery.data?.users ?? []}
        availablePeople={teamQuery.data?.members ?? []}
        currentUserId={currentUserId}
        onAddAgent={addAgentToActiveChannel}
        onRemoveAgent={removeAgentFromActiveChannel}
        onAddPerson={addPersonToActiveChannel}
        onRemovePerson={removePersonFromActiveChannel}
        personalityMode={personalityMode}
        operationMode={operationMode}
        onPersonalityChange={setPersonalityMode}
        onOperationChange={setOperationMode}
        liveWorkToggle={
          activeTab === "chat"
            ? { count: sessionActiveTaskCount, open: liveWorkOpen, onToggle: () => setLiveWorkOpen((v) => !v) }
            : undefined
        }
      />

      <div className="tabs" role="tablist" style={{ padding: "0 24px" }}>
        {TABS.map((t) => (
          <Link
            key={t.slug}
            href={`/projects/${projectId}/${t.slug}`}
            role="tab"
            aria-selected={activeTab === t.slug}
            className={["tab", activeTab === t.slug ? "active" : ""].filter(Boolean).join(" ")}
          >
            {t.label}
          </Link>
        ))}
      </div>

      <div style={{ flex: 1, minHeight: 0 }}>
        <ProjectChatContext.Provider value={contextValue}>
          {children}
        </ProjectChatContext.Provider>
      </div>
    </div>
  );
}
