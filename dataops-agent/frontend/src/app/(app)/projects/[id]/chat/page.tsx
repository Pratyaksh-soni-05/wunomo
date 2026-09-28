"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useToast } from "@/components/ui";
import { SessionList, MessageThread, LiveWorkPanel, type LocalChatMessage } from "@/components/chat";
import { TaskCreateModal } from "@/components/tasks/TaskCreateModal";
import { HireAgentModal } from "@/components/agents/HireAgentModal";
import { NoAgentsEmptyState } from "@/components/workbench/WorkbenchEmptyStates";
import {
  getToken, decodeUserFromToken, getChatHistory, sendChatMessageStream,
  listChannels, createChannel, getChannel, addChannelAgent, removeChannelAgent,
  addChannelUser, removeChannelUser, getProjectAgents, getTeamMembers, uploadToChannel,
  getActiveTasks, ApiError, type ChatContext, type ChatToolCall, type HiredAgent, type TaskItem,
} from "@/lib/api";

/**
 * The project's real Chat tab (slice 7, 2026-09-15) -- replaces the
 * slice-5 signpost stub. Reuses /chat's own MessageThread unchanged (it
 * takes everything as props, doesn't care what scopes its channel list)
 * and a narrower SessionList (showDirect=false -- AXIOM Direct has no
 * project concept anywhere in the schema, see SessionList's own comment).
 * LiveWorkPanel (renamed from ProjectContextPanel, §7.6) replaces
 * ContextPanel -- a separate component, not that one made configurable,
 * since /chat's own AXIOM Direct sessions and non-project channels have
 * nothing to show a Live work/Team/Data roster for.
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
  const [liveNotice, setLiveNotice] = useState<string | null>(null);
  // §7.1 Responsive: below 1180px the live work panel is a hidden-by-
  // default overlay/bottom-sheet, toggled from the header -- see
  // MessageThread's liveWorkToggle prop and LiveWorkPanel's mobileOpen.
  const [liveWorkOpen, setLiveWorkOpen] = useState(false);
  // §7.5 mention picker's "Not hired yet — tag to hire" row -- there is no
  // real one-click/no-modal hire flow anywhere in this codebase (hiring
  // always requires a name, via HireAgentModal); tagging an unhired type
  // opens that same real modal instead of faking an inline action that
  // doesn't exist.
  const [inlineHireOpen, setInlineHireOpen] = useState(false);

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
  // Same query key LiveWorkPanel itself uses ("active-tasks") -- react-
  // query dedupes this into one real request, not two -- so the header
  // toggle's count badge can never disagree with what the panel shows
  // once opened.
  const activeTasksQuery = useQuery({ queryKey: ["active-tasks"], queryFn: () => getActiveTasks(token), enabled: !!token });
  const sessionActiveTaskCount = activeSessionId
    ? (activeTasksQuery.data ?? []).filter((t) => t.originating_session_id === activeSessionId).length
    : 0;

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

  // §7.5's "tag an unhired type to hire it" -- HireAgentModal handles the
  // real naming step (there's no zero-input hire anywhere in this app);
  // once that succeeds, this adds the new agent to the channel the user
  // was actually tagging in and posts a real system line (shape I) for it
  // -- "Hire Axiom" -> "Axiom joined #general.", matching the copy rule
  // ("a button's name survives the whole flow") applied to the channel
  // the action actually happened in, not just "this project."
  const handleInlineHired = async (agent: HiredAgent) => {
    if (!activeSessionId) return;
    try {
      await addChannelAgent(token, activeSessionId, agent.id);
      qc.invalidateQueries({ queryKey: ["channel-detail", activeSessionId] });
      qc.invalidateQueries({ queryKey: ["channels"] });
      setMessages((prev) => [...prev, {
        role: "assistant", content: `${agent.name} joined #${activeChannel?.name ?? "this channel"}.`,
        tool_calls: [], timestamp: new Date().toISOString(), isSystemNotice: true,
      }]);
    } catch {
      toast.push(
        `Hired "${agent.name}", but couldn't add them to this channel automatically — add them from Members.`,
        "danger",
      );
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

  // Streaming (POST /api/v1/chat/stream, Stage 1) -- see DESIGN_SPEC.md
  // §1/§3 for the type sizes/badge styling this reuses (ToolCallBlock's
  // existing "info"/"danger" badges via its new running/failed statuses,
  // MessageThread's new liveNotice prop reusing .chat-approval-notice) --
  // no new colour/radius/font-size introduced anywhere in this turn's
  // rendering. The direct 1:1 AXIOM chat page (app/(app)/chat/page.tsx)
  // stays on the old sendChatMessage() path until this one is proven.
  const send = async () => {
    const text = draft.trim();
    if (!text || sending) return;

    const myGeneration = chatGenerationRef.current;
    const sessionAtSendTime = activeSessionId;
    const isStale = () => chatGenerationRef.current !== myGeneration;

    // Captured before anything is appended -- the hard-failure catch
    // below trims back to exactly this length regardless of how many
    // messages this attempt added (the single-agent path adds exactly
    // one placeholder; the supervisor path can add several per-task
    // placeholders plus system lines/handoffs, so a hardcoded "remove the
    // last 2" no longer covers every case).
    const lengthBeforeSend = messages.length;

    const userMsg: LocalChatMessage = { role: "user", content: text, tool_calls: [], timestamp: new Date().toISOString() };
    const placeholderMsg: LocalChatMessage = {
      role: "assistant", content: "", tool_calls: [], timestamp: new Date().toISOString(), streaming: true,
    };
    setMessages((prev) => [...prev, userMsg, placeholderMsg]);
    setDraft("");
    setSendError(null);
    setLiveNotice(null);
    setSending(true);

    // Mutates only the trailing placeholder assistant message pushed
    // above -- safe because nothing else can be appended to `messages`
    // for this generation until this turn resolves (the composer/session
    // switch race is what chatGenerationRef/isStale() guards against).
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
    // moment its "queued" ack arrives (before any work has started --
    // §7.3.B) and updated in place by every later token/tool_start/
    // tool_end/terminal event carrying the same task_id. Parallel tasks
    // stream concurrently with genuinely interleaved events, so lookup is
    // always by id, never "the last message".
    // Set the moment the first supervisor_task event of this turn arrives
    // -- onDone (below) must never mutate "the last message" once this is
    // true, since the last message by then is a real per-task bubble, not
    // the generic placeholder onDone was written to update. A plain
    // closure variable is fine for this one (isStale() reads chatGenerationRef
    // the same way) -- it's never read or written from inside a setState
    // updater, unlike the mistake this replaces just below.
    let isSupervisorTurn = false;
    const ensureTaskMessage = (taskId: string, agentId: string) => {
      if (isStale()) return;
      isSupervisorTurn = true;
      setMessages((prev) => {
        if (prev.some((m) => m.task_id === taskId)) return prev;
        // The first supervisor_task event of this turn -- the generic
        // single-agent placeholder pushed at send() turned out to be
        // premature (this is a multi-agent turn); drop it rather than
        // leave an orphaned empty bubble alongside the real per-task
        // ones. Re-derived from `prev` on every call (never a "have we
        // already done this" flag closed over outside setState) -- React
        // 18 Strict Mode double-invokes a setState updater in development
        // to catch exactly this shape of impurity, and a flag mutated
        // inside the updater desyncs across the two invocations: the
        // first run filters and flips the flag, the discarded-and-replayed
        // second run then sees the flag already set and skips filtering,
        // so the placeholder never actually leaves `prev`. Filtering
        // unconditionally is idempotent instead -- a no-op once the
        // placeholder is already gone, on every replay.
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
          // The responding agent is now known before the first token
          // (start is always the first event) -- the placeholder carries
          // the correct avatar for the whole turn, not just from `done`
          // onward.
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
          onApprovalRequired: ({ risk_level, reason }) => {
            if (isStale()) return;
            setLiveNotice(
              `AXIOM paused an action for your approval instead of running it (${risk_level} risk).` +
              (reason ? ` ${reason}` : "")
            );
          },
          onError: ({ message, kind }) => {
            if (isStale()) return;
            if (kind) {
              // Shape H (§7.3.H, the refusal card + "restore raw text to
              // the composer") isn't built yet -- logged so the data is
              // visible while this wiring is new, rather than silently
              // dropped or faked. The generic error banner below is what
              // the user actually sees for now; see this pass's own report.
              console.warn(`[supervisor] refusal (${kind}) has no shape-H UI built for it yet:`, message);
            }
            setSendError(message);
          },
          // supervisor_task now fires up to three times per task --
          // "queued" (the moment dispatch happens, before any work has
          // started: §7.3.B's acknowledgement), "running", then exactly
          // one terminal status. token/tool_start/tool_end above stream
          // this same message live in between, routed by task_id.
          onSupervisorTask: (data) => {
            if (isStale()) return;
            if (data.status === "queued") {
              ensureTaskMessage(data.task_id, data.agent_id);
              return;
            }
            if (data.status === "running") {
              // Not every task_id reaches "queued" first from THIS
              // client's point of view (a page that (re)connects after
              // dispatch already happened never saw it) -- ensure here
              // too rather than assuming ordering.
              ensureTaskMessage(data.task_id, data.agent_id);
              return;
            }
            // Terminal: completed/failed/paused_needs_approval/blocked.
            // `response`, when present, is the complete authoritative
            // text (byte-identical to what's persisted) -- assigned
            // outright rather than trusting only accumulated token
            // deltas, since a model turn with no live token stream at all
            // (still possible; not every provider path streams) would
            // otherwise leave this bubble permanently empty.
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
          onSystemLine: ({ text }) => {
            if (isStale()) return;
            // Some system lines persist (an inferred-edge explanation)
            // and reappear via the history refetch below unchanged;
            // others never do (an unresolved @mention -- the multi-agent
            // equivalent of the single-mention path's own never-
            // persisted routing failure). Pushed here regardless, so
            // it's visible for this turn either way.
            setMessages((prev) => [...prev, {
              role: "assistant", content: text, tool_calls: [],
              timestamp: new Date().toISOString(), isSystemNotice: true,
            }]);
          },
          onHandoff: ({ from_agent_name, to_agent_name, payload_summary, withheld }) => {
            if (isStale()) return;
            // Shape F (§7.3.F, a dedicated handoff card) isn't built yet
            // -- approximated with shape I's plain-text treatment
            // (§7.3.I already covers "handoffs" in its own list of what
            // a system line is used for) rather than inventing a new
            // shape this pass. The real Handoff row already persists
            // (api/v1/chat.py's _handoff_entries reconstructs this exact
            // text on refetch), so this is purely the pre-refetch, live
            // view of it.
            const text = `${from_agent_name} handed over to ${to_agent_name}. ${payload_summary}`
              + (withheld.length > 0 ? ` (${to_agent_name} did not receive: ${withheld.join(", ")}.)` : "");
            setMessages((prev) => [...prev, {
              role: "assistant", content: text, tool_calls: [],
              timestamp: new Date().toISOString(), isSystemNotice: true,
            }]);
          },
          onNeedsClarification: (data) => {
            // Shape G (§7.3.G, the clarification card) isn't built yet --
            // logged so the data is flowing and visible before that
            // component exists, per this pass's explicit instruction, not
            // rendered as a fake ask UI. A clarification-only turn (zero
            // tasks dispatched) currently shows nothing else in the
            // thread besides this console warning -- see this pass's own
            // report.
            console.warn("[supervisor] needs_clarification has no shape-G UI built for it yet:", data);
          },
          onDone: (doneData) => {
            if (isStale()) return;
            setProvider(doneData.provider);
            doneSessionId = doneData.session_id;
            // Real per-message identity (§7.4) only reaches the client on
            // `done` -- nothing streamed before it (token/tool_start/
            // tool_end) carries agent_id. The placeholder shows the
            // generic AXIOM avatar for the duration of the stream itself
            // (a real, disclosed gap -- see this build's own report), but
            // must not keep doing so for the tail end between `done` and
            // the history refetch below finishing.
            //
            // Supervisor turns skip this entirely: by the time `done`
            // fires every dispatched task has already reached its own
            // terminal supervisor_task event (run_supervisor() doesn't
            // return, and this event doesn't fire, until every wave has
            // drained), and doneData.agent_id is always null on this path
            // (no single agent "is" the responder) -- applying it here
            // would overwrite whichever task bubble happens to be last in
            // the array with a null agent_id, discarding its real avatar.
            if (!isSupervisorTurn) {
              updatePlaceholder((msg) => ({ ...msg, agent_id: doneData.agent_id, streaming: false }));
            }
          },
        },
      );

      if (isStale()) return;
      // `done` always carries the real, server-generated session_id
      // (Stage 1 follow-up -- previously omitted, so a brand-new session
      // had no way to learn its id from the stream at all). Adopt it the
      // same way the buffered path's `if (!sessionAtSendTime)
      // setActiveSessionId(res.session_id)` already does.
      if (!sessionAtSendTime && doneSessionId) setActiveSessionId(doneSessionId);
      const historySessionId = doneSessionId ?? sessionAtSendTime;
      // Replace the locally-accumulated placeholder with the real
      // persisted turn (full args/results, real approval risk_level/
      // reason, correctly-resolved denial statuses) -- the same
      // full-fidelity data GET .../history always has, rather than
      // trying to perfectly rebuild _extract_tool_trace's exact shape
      // client-side from six minimal live SSE events.
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
      // failure (e.g. the 402s below) -- matching the buffered path,
      // which never added them in the first place when sendChatMessage()
      // itself threw. Trimmed back to the length captured before this
      // attempt touched `messages` at all, not a hardcoded "last 2": a
      // supervisor turn can add several per-task placeholders plus system
      // lines/handoffs before failing.
      setMessages((prev) => prev.slice(0, lengthBeforeSend));
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
        liveNotice={liveNotice}
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
        liveWorkToggle={{
          count: sessionActiveTaskCount,
          open: liveWorkOpen,
          onToggle: () => setLiveWorkOpen((v) => !v),
        }}
        onTagUnhiredType={() => setInlineHireOpen(true)}
      />
      <LiveWorkPanel
        token={token}
        projectId={projectId}
        messages={messages}
        attachedContext={attachedContext}
        onAttach={setAttachedContext}
        onClear={() => setAttachedContext(null)}
        onGoToApprovals={() => router.push("/approvals")}
        currentUserRole={currentUserRole}
        sessionId={activeSessionId}
        channelAgents={channelDetailQuery.data?.agents ?? []}
        mobileOpen={liveWorkOpen}
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
      <HireAgentModal
        token={token}
        open={inlineHireOpen}
        onClose={() => setInlineHireOpen(false)}
        initialProjectId={projectId}
        onHired={handleInlineHired}
      />
    </div>
  );
}
