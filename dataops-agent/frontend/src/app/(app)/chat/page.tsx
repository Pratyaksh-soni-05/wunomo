"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useToast } from "@/components/ui";
import { SessionList, MessageThread, ContextPanel, type LocalChatMessage } from "@/components/chat";
import { TaskCreateModal } from "@/components/tasks/TaskCreateModal";
import {
  getToken, decodeUserFromToken, getChatSessions, getChatHistory, sendChatMessageStream, getSources,
  deleteChatSession, listChannels, createChannel, getChannel, addChannelAgent, removeChannelAgent,
  addChannelUser, removeChannelUser, listSelectableAgents, getTeamMembers, uploadToChannel,
  ApiError, type ChatContext, type ChatToolCall, type TaskItem,
} from "@/lib/api";

export default function ChatPage() {
  const token = getToken() as string;
  const decoded = decodeUserFromToken(token);
  const tenantId = decoded?.tenant_id ?? null;
  const currentUserId = decoded?.sub ?? null;
  const currentUserRole = decoded?.role ?? null;
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

  // Bumped by newChat() so a response from a request sent before "New Chat"
  // was clicked can be detected as stale and dropped instead of silently
  // reattaching its session_id / messages onto the fresh thread.
  const chatGenerationRef = useRef(0);

  const sessionsQuery = useQuery({ queryKey: ["chat-sessions"], queryFn: () => getChatSessions(token) });
  const sourcesQuery = useQuery({ queryKey: ["sources"], queryFn: () => getSources(token) });
  const channelsQuery = useQuery({ queryKey: ["channels"], queryFn: () => listChannels(token) });
  // Wunomo Projects Phase 4: was listAgents() (agents.manage-gated) --
  // confirmed live that gave a data_analyst (or any non-Owner/Admin role)
  // a real 403 here, so this channel-creation picker came up empty for
  // every such role since channels shipped. listSelectableAgents() is the
  // fix (any authenticated member, ACTIVE agents only -- already excludes
  // offboarded ones, so no separate filter is needed below anymore); same
  // queryKey the task-create modal's own agent picker uses, so the two
  // share one cached fetch instead of two independent ones.
  const agentsQuery = useQuery({ queryKey: ["selectable-agents"], queryFn: () => listSelectableAgents(token) });
  const teamQuery = useQuery({ queryKey: ["team-members"], queryFn: () => getTeamMembers(token) });

  const activeChannel = channelsQuery.data?.channels.find((c) => c.id === activeSessionId) ?? null;
  const channelDetailQuery = useQuery({
    queryKey: ["channel-detail", activeSessionId],
    queryFn: () => getChannel(token, activeSessionId as string),
    enabled: !!activeChannel,
  });
  const activeAgents = agentsQuery.data?.agents ?? [];

  const selectSession = async (id: string) => {
    // Same stale-response hazard newChat() guards against: switching
    // threads while a send from the previous thread is still in flight
    // must not let that response land in the newly-selected thread.
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

  // Finding 18: clicking a conversation row in the Dashboard's AXIOM
  // Activity card (or any other future "open this specific chat" link)
  // carries the real session id as a ?session= query param - consume it
  // once on mount, then strip it from the URL so a later refresh of /chat
  // doesn't keep re-selecting it. Reads window.location.search directly
  // rather than next/navigation's useSearchParams() - same reason the
  // login page's own ?expired=1 marker does the same (see that file):
  // useSearchParams() requires a <Suspense> boundary around the page or
  // the production build fails, which nothing in this app's shell sets
  // up today; window.location.search needs none and this only ever runs
  // client-side anyway ("use client" at the top of this file).
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("session");
    if (id) {
      selectSession(id);
      router.replace("/chat");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Item 4: hard delete, tenant+user+session scoped server-side. A 409
  // means a pending approval still traces back to this session (see
  // chat.py's delete_session) - that gets a route forward (Approvals),
  // not just a refusal, per finding 12's "dead end" lesson. Success
  // invalidates ["chat-sessions"] so SessionList refreshes with no
  // manual reload, and if the deleted session was the open thread, drops
  // back to a blank "new chat" state since its history is now gone.
  const deleteSession = async (id: string) => {
    try {
      await deleteChatSession(token, id);
      qc.invalidateQueries({ queryKey: ["chat-sessions"] });
      if (id === activeSessionId) {
        chatGenerationRef.current += 1;
        setActiveSessionId(null);
        setMessages([]);
        setSendError(null);
      }
      toast.push("Conversation deleted.", "default");
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        toast.push(typeof err.detail === "string" ? err.detail : err.message, "warning", {
          label: "Go to Approvals",
          onClick: () => router.push("/approvals"),
        });
      } else {
        toast.push("Failed to delete conversation.", "danger");
      }
    }
  };

  const newChat = () => {
    const alreadyEmpty = !activeSessionId && messages.length === 0 && !sending;
    chatGenerationRef.current += 1;
    setActiveSessionId(null);
    setMessages([]);
    setDraft("");
    setSendError(null);
    setUploadError(null);
    setAttachedContext(null);
    setSending(false);
    setProvider(null);
    toast.push(alreadyEmpty ? "Already a new chat." : "Started a new chat.", "success");
  };

  // A channel with zero agents is a guaranteed dead end (resolve_mentioned_
  // agent/channel_agent_members both refuse to route into one) -- creation
  // and adding at least one agent happen as one flow, never a bare
  // name-only create that leaves a channel unusable until a separate step.
  const createChannelWithAgents = async (name: string, agentIds: string[]) => {
    try {
      const channel = await createChannel(token, { name });
      for (const agentId of agentIds) {
        await addChannelAgent(token, channel.id, agentId);
      }
      qc.invalidateQueries({ queryKey: ["channels"] });
      chatGenerationRef.current += 1;
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

  // Backend refuses (409) removing the channel's only human member -- the
  // real, honest way out named in that refusal is "add someone else
  // first" (there is no delete-channel or dedicated leave endpoint in
  // this codebase). Removing yourself drops you out of the channel view
  // entirely, since GET .../{id} requires membership.
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

  // Chat-first data upload (Wunomo Projects Phase 4, item 4): channels
  // only in v1 (finding 80). No LLM call here -- upload/register/profile/
  // grant is silent; the resolved agent is only "ready" once a real
  // message is sent, which is why success just populates attachedContext
  // (the existing "attach this source to my next message" chip) instead
  // of injecting a synthetic message into the thread. draft is passed
  // through as the accompanying message so an in-progress "@Nova ..." in
  // the composer resolves the same target a real send would.
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

  // Streaming (POST /api/v1/chat/stream) -- this page stayed on the
  // buffered sendChatMessage() until the per-task_id concurrent-rendering
  // path (projects/[id]/chat/page.tsx) was live-verified with two real
  // agents streaming at once; see that page's own history for the fix
  // this port already carries (streaming keyed per-message, never by
  // array position; ensureTaskMessage's setState updater kept pure against
  // React 18 Strict Mode's double-invoke). Ported logic, not a rewrite --
  // this page's own extras (1:1 AXIOM Direct sessions, New Chat, session
  // deletion, ?session= deep-link) are untouched, none of them live inside
  // send() itself.
  const send = async () => {
    const text = draft.trim();
    if (!text || sending) return;

    const myGeneration = chatGenerationRef.current;
    const sessionAtSendTime = activeSessionId;
    const isStale = () => chatGenerationRef.current !== myGeneration;

    // Captured before anything is appended -- a hard failure below trims
    // back to exactly this length regardless of how many messages this
    // attempt added (a supervisor turn can add several per-task
    // placeholders plus system lines/handoffs, not just one).
    const lengthBeforeSend = messages.length;

    const userMsg: LocalChatMessage = { role: "user", content: text, tool_calls: [], timestamp: new Date().toISOString() };
    const placeholderMsg: LocalChatMessage = {
      role: "assistant", content: "", tool_calls: [], timestamp: new Date().toISOString(), streaming: true,
    };
    setMessages((prev) => [...prev, userMsg, placeholderMsg]);
    setDraft("");
    setSendError(null);
    setSending(true);

    // Single-agent path only -- a supervisor turn routes by task_id via
    // updateTaskMessage below instead, since more than one message can be
    // live at once.
    const updatePlaceholder = (fn: (msg: LocalChatMessage) => LocalChatMessage) => {
      if (isStale()) return;
      setMessages((prev) => {
        if (prev.length === 0 || prev[prev.length - 1].role !== "assistant") return prev;
        return [...prev.slice(0, -1), fn(prev[prev.length - 1])];
      });
    };

    // Supervisor path: one streaming bubble per task_id, created the
    // moment its "queued" ack arrives and updated in place by every later
    // token/tool_start/tool_end/terminal event carrying the same task_id.
    // Parallel tasks stream concurrently with genuinely interleaved
    // events, so lookup is always by id, never "the last message".
    let isSupervisorTurn = false;
    const ensureTaskMessage = (taskId: string, agentId: string) => {
      if (isStale()) return;
      isSupervisorTurn = true;
      setMessages((prev) => {
        if (prev.some((m) => m.task_id === taskId)) return prev;
        // The generic single-agent placeholder pushed above turned out to
        // be premature (this is a multi-agent turn) -- drop it rather than
        // leave an orphaned empty bubble alongside the real per-task ones.
        // Re-derived from `prev` on every call, never a "have we already
        // done this" flag closed over outside setState -- see this pass's
        // own commit for why that shape breaks under Strict Mode.
        const base = prev.filter((m) => !(m.role === "assistant" && m.content === "" && !m.task_id && !m.isSystemNotice));
        return [...base, {
          role: "assistant", content: "", tool_calls: [], timestamp: new Date().toISOString(),
          agent_id: agentId, task_id: taskId, streaming: true,
        }];
      });
    };
    const updateTaskMessage = (taskId: string, fn: (msg: LocalChatMessage) => LocalChatMessage) => {
      if (isStale()) return;
      setMessages((prev) => {
        const idx = prev.findIndex((m) => m.task_id === taskId);
        if (idx === -1) return prev;
        const next = [...prev];
        next[idx] = fn(next[idx]);
        return next;
      });
    };

    let doneSessionId: string | null = null;
    try {
      await sendChatMessageStream(
        token,
        {
          message: text,
          session_id: sessionAtSendTime ?? undefined,
          personality_mode: personalityMode,
          operation_mode: operationMode,
          context: attachedContext ?? undefined,
        },
        {
          onStart: ({ agent_id }) => updatePlaceholder((msg) => ({ ...msg, agent_id })),
          onToken: ({ delta, task_id }) => {
            if (task_id) { updateTaskMessage(task_id, (msg) => ({ ...msg, content: msg.content + delta })); return; }
            updatePlaceholder((msg) => ({ ...msg, content: msg.content + delta }));
          },
          onToolStart: ({ name, args_summary, task_id }) => {
            const appendTool = (msg: LocalChatMessage): LocalChatMessage => ({
              ...msg,
              tool_calls: [
                ...msg.tool_calls,
                { tool: name, args: {}, args_summary, result: null, status: "running" } as ChatToolCall,
              ],
            });
            if (task_id) { updateTaskMessage(task_id, appendTool); return; }
            updatePlaceholder(appendTool);
          },
          onToolEnd: ({ name, result_summary, ok, task_id }) => {
            const resolveTool = (msg: LocalChatMessage): LocalChatMessage => {
              const lastRunningIdx = msg.tool_calls.map((c, i) => ({ c, i }))
                .reverse().find(({ c }) => c.tool === name && c.status === "running")?.i;
              if (lastRunningIdx === undefined) return msg;
              const tool_calls = [...msg.tool_calls];
              tool_calls[lastRunningIdx] = { ...tool_calls[lastRunningIdx], status: ok ? "completed" : "failed", result_summary };
              return { ...msg, tool_calls };
            };
            if (task_id) { updateTaskMessage(task_id, resolveTool); return; }
            updatePlaceholder(resolveTool);
          },
          onError: ({ message, kind }) => {
            if (isStale()) return;
            if (kind) {
              console.warn(`[supervisor] refusal (${kind}) has no shape-H UI built for it yet:`, message);
            }
            setSendError(message);
          },
          onSupervisorTask: (data) => {
            if (isStale()) return;
            if (data.status === "queued" || data.status === "running") {
              ensureTaskMessage(data.task_id, data.agent_id);
              return;
            }
            ensureTaskMessage(data.task_id, data.agent_id);
            const fallbackText = data.status === "paused_needs_approval"
              ? "Paused, waiting for approval."
              : data.status === "failed"
              ? "This task failed."
              : null;
            updateTaskMessage(data.task_id, (msg) => ({
              ...msg, agent_id: data.agent_id, content: data.response ?? fallbackText ?? msg.content, streaming: false,
            }));
          },
          onSystemLine: ({ text: lineText }) => {
            if (isStale()) return;
            setMessages((prev) => [...prev, {
              role: "assistant", content: lineText, tool_calls: [],
              timestamp: new Date().toISOString(), isSystemNotice: true,
            }]);
          },
          onHandoff: ({ from_agent_name, to_agent_name, payload_summary, withheld }) => {
            if (isStale()) return;
            const text = `${from_agent_name} handed over to ${to_agent_name}. ${payload_summary}`
              + (withheld.length > 0 ? ` (${to_agent_name} did not receive: ${withheld.join(", ")}.)` : "");
            setMessages((prev) => [...prev, {
              role: "assistant", content: text, tool_calls: [],
              timestamp: new Date().toISOString(), isSystemNotice: true,
            }]);
          },
          onNeedsClarification: (data) => {
            console.warn("[supervisor] needs_clarification has no shape-G UI built for it yet:", data);
          },
          onDone: (doneData) => {
            if (isStale()) return;
            setProvider(doneData.provider);
            doneSessionId = doneData.session_id;
            // Supervisor turns skip this: doneData.agent_id is always null
            // on that path, and applying it here would overwrite whichever
            // task bubble happens to be last in the array.
            if (!isSupervisorTurn) {
              updatePlaceholder((msg) => ({ ...msg, agent_id: doneData.agent_id, streaming: false }));
            }
          },
        },
      );

      if (isStale()) return;
      if (!sessionAtSendTime && doneSessionId) setActiveSessionId(doneSessionId);
      const historySessionId = doneSessionId ?? sessionAtSendTime;
      // Replace the locally-accumulated placeholder(s) with the real
      // persisted turn (full args/results, real approval risk_level/
      // reason) -- the same full-fidelity data GET .../history always has.
      if (historySessionId) {
        try {
          const history = await getChatHistory(token, historySessionId);
          if (!isStale()) setMessages(history.messages);
        } catch {
          // Keep the locally-accumulated placeholder rather than losing
          // the turn the user just watched complete.
        }
      }
      qc.invalidateQueries({ queryKey: ["chat-sessions"] });
    } catch (err) {
      if (isStale()) return;
      // Remove everything this attempt optimistically added on a hard
      // failure -- matching the old buffered path, which never added
      // anything when sendChatMessage() itself threw.
      setMessages((prev) => prev.slice(0, lengthBeforeSend));
      // Wunomo Projects Phase 2 frontend, slice 9: every ApiError used to
      // collapse to the same "try rephrasing" text regardless of status --
      // actively wrong for a 402, since rephrasing can't fix an exhausted
      // quota. Two distinct causes share this status (enforce_quota's
      // tenant-wide "ai_credits" gate vs. enforce_agent_budget's per-agent
      // gate) with two different fixes, so a single generic message would
      // send whoever reads it to the wrong screen.
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
      if (!isStale()) setSending(false);
    }
  };

  return (
    <div className="chat-layout">
      <SessionList
        tenantId={tenantId}
        sessions={sessionsQuery.data?.sessions ?? []}
        loading={sessionsQuery.isLoading}
        channels={channelsQuery.data?.channels ?? []}
        channelsLoading={channelsQuery.isLoading}
        availableAgents={activeAgents}
        activeSessionId={activeSessionId}
        onSelectSession={selectSession}
        onNewChat={newChat}
        onCreateChannel={createChannelWithAgents}
        onInsertPrompt={setDraft}
        onDeleteSession={deleteSession}
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
        availableAgents={activeAgents}
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
      <ContextPanel
        messages={messages}
        sources={sourcesQuery.data?.sources ?? []}
        attachedContext={attachedContext}
        onAttach={setAttachedContext}
        onClear={() => setAttachedContext(null)}
        onGoToApprovals={() => router.push("/approvals")}
        currentUserRole={currentUserRole}
        token={token}
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
