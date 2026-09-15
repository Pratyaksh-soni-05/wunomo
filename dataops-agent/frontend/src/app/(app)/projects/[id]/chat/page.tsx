"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useToast } from "@/components/ui";
import { SessionList, MessageThread, ProjectContextPanel, type LocalChatMessage } from "@/components/chat";
import { TaskCreateModal } from "@/components/tasks/TaskCreateModal";
import { NoAgentsEmptyState } from "@/components/workbench/WorkbenchEmptyStates";
import {
  getToken, decodeUserFromToken, getChatHistory, sendChatMessage,
  listChannels, createChannel, getChannel, addChannelAgent, removeChannelAgent,
  addChannelUser, removeChannelUser, getProjectAgents, getTeamMembers, uploadToChannel,
  ApiError, type ChatContext, type TaskItem,
} from "@/lib/api";

/**
 * The project's real Chat tab (slice 7, 2026-09-15) -- replaces the
 * slice-5 signpost stub. Reuses /chat's own MessageThread unchanged (it
 * takes everything as props, doesn't care what scopes its channel list)
 * and a narrower SessionList (showDirect=false -- AXIOM Direct has no
 * project concept anywhere in the schema, see SessionList's own comment).
 * ProjectContextPanel replaces ContextPanel -- a separate component, not
 * that one made configurable, since /chat's own AXIOM Direct sessions and
 * non-project channels have nothing to show an Agents/Data roster for.
 *
 * Deliberately NOT a copy of /chat/page.tsx's full logic: no 1:1
 * sessions, no "+ New Chat", no session deletion, no ?session= deep-link
 * handling -- none of that applies to a project's channels-only view, so
 * it's a smaller page, not a parallel one carrying dead branches.
 */
export default function ProjectChatTab() {
  const token = getToken() as string;
  const decoded = decodeUserFromToken(token);
  const currentUserId = decoded?.sub ?? null;
  const currentUserRole = decoded?.role ?? null;
  const params = useParams();
  const projectId = params.id as string;
  const toast = useToast();
  const router = useRouter();
  const qc = useQueryClient();

  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<LocalChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [provider, setProvider] = useState<string | null>(null);
  const [personalityMode, setPersonalityMode] = useState("engineer");
  const [operationMode, setOperationMode] = useState("assisted");
  const [attachedContext, setAttachedContext] = useState<ChatContext | null>(null);
  const [taskModalOpen, setTaskModalOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const chatGenerationRef = useRef(0);
  const autoSelectedRef = useRef(false);

  const projectAgentsQuery = useQuery({ queryKey: ["project-agents", projectId], queryFn: () => getProjectAgents(token, projectId) });
  const projectAgents = projectAgentsQuery.data?.agents ?? [];

  // Free filter, same reasoning as every other "project's own slice of a
  // tenant-wide list" surface in this rebuild (Home's ProjectCardStats,
  // the Tasks tab, Workbench's Pipelines/Incidents/Transforms) --
  // ChannelItem.project_id already exists on the model, no new endpoint
  // needed.
  const channelsQuery = useQuery({ queryKey: ["channels"], queryFn: () => listChannels(token) });
  const projectChannels = (channelsQuery.data?.channels ?? []).filter((c) => c.project_id === projectId);
  const teamQuery = useQuery({ queryKey: ["team-members"], queryFn: () => getTeamMembers(token) });

  const activeChannel = projectChannels.find((c) => c.id === activeSessionId) ?? null;
  const channelDetailQuery = useQuery({
    queryKey: ["channel-detail", activeSessionId],
    queryFn: () => getChannel(token, activeSessionId as string),
    enabled: !!activeChannel,
  });

  const selectSession = async (id: string) => {
    chatGenerationRef.current += 1;
    setActiveSessionId(id);
    setSendError(null);
    setUploadError(null);
    setSending(false);
    try {
      const history = await getChatHistory(token, id);
      setMessages(history.messages);
    } catch {
      toast.push("Failed to load conversation history.", "danger");
    }
  };

  // Land on the project's most recently active channel rather than a
  // blank composer with nothing selected -- the channel model supports
  // several per project (Q2), so "one open" needs a real default, not a
  // forced single-channel constraint. Guarded by a ref, not a `messages`/
  // `activeSessionId` check, so switching away from the auto-selected
  // channel (or deleting its history) doesn't silently re-trigger it.
  useEffect(() => {
    if (autoSelectedRef.current || activeSessionId) return;
    if (projectChannels.length > 0) {
      autoSelectedRef.current = true;
      selectSession(projectChannels[0].id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectChannels.length]);

  const createChannelWithAgents = async (name: string, agentIds: string[]) => {
    try {
      const channel = await createChannel(token, { name, project_id: projectId });
      for (const agentId of agentIds) {
        await addChannelAgent(token, channel.id, agentId);
      }
      qc.invalidateQueries({ queryKey: ["channels"] });
      chatGenerationRef.current += 1;
      autoSelectedRef.current = true;
      setActiveSessionId(channel.id);
      setMessages([]);
      setSendError(null);
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
        chatGenerationRef.current += 1;
        setActiveSessionId(null);
        setMessages([]);
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

  const handleUploadFile = async (file: File) => {
    if (!activeSessionId || !activeChannel) return;
    setUploadError(null);
    setUploading(true);
    try {
      const result = await uploadToChannel(token, activeSessionId, file, draft);
      setAttachedContext({ source_id: result.source_id, source_name: result.source_name });
      toast.push(`${result.agent_name} is ready with "${result.source_name}" on your next message.`, "success");
      qc.invalidateQueries({ queryKey: ["sources"] });
    } catch (err) {
      const message = err instanceof ApiError && typeof err.detail === "string"
        ? err.detail
        : "Couldn't upload that file. Try again.";
      setUploadError(message);
    } finally {
      setUploading(false);
    }
  };

  const send = async () => {
    const text = draft.trim();
    if (!text || sending) return;

    const myGeneration = chatGenerationRef.current;
    const sessionAtSendTime = activeSessionId;

    const userMsg: LocalChatMessage = { role: "user", content: text, tool_calls: [], timestamp: new Date().toISOString() };
    setMessages((prev) => [...prev, userMsg]);
    setDraft("");
    setSendError(null);
    setSending(true);

    try {
      const res = await sendChatMessage(token, {
        message: text,
        session_id: sessionAtSendTime ?? undefined,
        personality_mode: personalityMode,
        operation_mode: operationMode,
        context: attachedContext ?? undefined,
      });
      if (chatGenerationRef.current !== myGeneration) return;
      const assistantMsg: LocalChatMessage = {
        role: "assistant", content: res.response, tool_calls: res.tool_calls,
        timestamp: res.timestamp, approvals: res.pending_approvals,
        isSystemNotice: res.provider === null,
      };
      setMessages((prev) => [...prev, assistantMsg]);
      setProvider(res.provider);
      if (!sessionAtSendTime) setActiveSessionId(res.session_id);
      qc.invalidateQueries({ queryKey: ["chat-sessions"] });
    } catch (err) {
      if (chatGenerationRef.current !== myGeneration) return;
      if (err instanceof ApiError && err.status === 402 && err.detail && typeof err.detail === "object") {
        const detail = err.detail as { error?: string; agent_id?: string; used?: number; limit?: number };
        if (detail.error === "quota_exceeded") {
          const message = "Your workspace's AI-credit quota is exhausted for this billing period.";
          setSendError(message);
          toast.push(message, "danger", { label: "Go to Billing", onClick: () => router.push("/team?tab=billing") });
        } else if (detail.error === "agent_budget_exceeded") {
          const usage = detail.used != null && detail.limit != null ? ` (${detail.used}/${detail.limit} tokens)` : "";
          const message = `This agent's own monthly token budget${usage} is exhausted.`;
          setSendError(message);
          toast.push(message, "danger", {
            label: "Go to agent",
            onClick: () => { if (detail.agent_id) router.push(`/agents/${detail.agent_id}`); },
          });
        } else {
          const message = "AXIOM couldn't complete that request. Try again.";
          setSendError(message);
          toast.push(message, "danger");
        }
        return;
      }
      const message =
        err instanceof ApiError
          ? "AXIOM couldn't complete that request — it may have tried an action it couldn't format correctly. Try rephrasing, or try again."
          : "Couldn't reach AXIOM. Check your connection and try again.";
      setSendError(message);
      toast.push(message, "danger");
    } finally {
      if (chatGenerationRef.current === myGeneration) setSending(false);
    }
  };

  if (!projectAgentsQuery.isLoading && projectAgents.length === 0) {
    return <NoAgentsEmptyState projectId={projectId} />;
  }

  return (
    <div className="chat-layout">
      <SessionList
        tenantId={null}
        sessions={[]}
        loading={false}
        showDirect={false}
        channels={projectChannels}
        channelsLoading={channelsQuery.isLoading}
        availableAgents={projectAgents.map((a) => ({ id: a.id, name: a.name, sources: [] }))}
        activeSessionId={activeSessionId}
        onSelectSession={selectSession}
        onNewChat={() => {}}
        onCreateChannel={createChannelWithAgents}
        onInsertPrompt={setDraft}
        onDeleteSession={() => {}}
        draft={draft}
      />
      <MessageThread
        messages={messages}
        sending={sending}
        sendError={sendError}
        provider={provider}
        personalityMode={personalityMode}
        operationMode={operationMode}
        onPersonalityChange={setPersonalityMode}
        onOperationChange={setOperationMode}
        attachedContext={attachedContext}
        onClearContext={() => setAttachedContext(null)}
        draft={draft}
        onDraftChange={setDraft}
        onSend={send}
        onGoToApprovals={() => router.push("/approvals")}
        onStartTask={() => setTaskModalOpen(true)}
        channel={activeChannel}
        channelAgents={channelDetailQuery.data?.agents ?? []}
        channelUsers={channelDetailQuery.data?.users ?? []}
        availableAgents={projectAgents.map((a) => ({ id: a.id, name: a.name, sources: [] }))}
        availablePeople={teamQuery.data?.members ?? []}
        currentUserId={currentUserId}
        onAddAgent={addAgentToActiveChannel}
        onRemoveAgent={removeAgentFromActiveChannel}
        onAddPerson={addPersonToActiveChannel}
        onRemovePerson={removePersonFromActiveChannel}
        currentUserRole={currentUserRole}
        uploading={uploading}
        uploadError={uploadError}
        onUploadFile={handleUploadFile}
      />
      <ProjectContextPanel
        token={token}
        projectId={projectId}
        messages={messages}
        attachedContext={attachedContext}
        onAttach={setAttachedContext}
        onClear={() => setAttachedContext(null)}
        onGoToApprovals={() => router.push("/approvals")}
        currentUserRole={currentUserRole}
        sessionId={activeSessionId}
      />
      <TaskCreateModal
        token={token}
        open={taskModalOpen}
        onClose={() => setTaskModalOpen(false)}
        sessionId={activeSessionId ?? undefined}
        channelAgentIds={channelDetailQuery.data?.agents.map((a) => a.id)}
        onCreated={(task: TaskItem) => {
          const taskCardMsg: LocalChatMessage = {
            role: "assistant", content: "", tool_calls: [], timestamp: new Date().toISOString(),
            taskCard: { id: task.id, goal: task.goal },
          };
          setMessages((prev) => [...prev, taskCardMsg]);
        }}
      />
    </div>
  );
}
