"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { useToast } from "@/components/ui";
import { MessageThread, LiveWorkPanel, type LocalChatMessage } from "@/components/chat";
import { useProjectChatContext } from "@/components/chat/ProjectChatContext";
import { HireAgentModal } from "@/components/agents/HireAgentModal";
import { NoAgentsEmptyState } from "@/components/workbench/WorkbenchEmptyStates";
import {
  getToken, decodeUserFromToken, getChatHistory, sendChatMessageStream,
  uploadToChannel, addChannelAgent, approveRequest, rejectRequest,
  ApiError, type ChatContext, type ChatToolCall, type HiredAgent,
} from "@/lib/api";

/**
 * The project's real Chat tab (slice 7, 2026-09-15; blueprint chrome pass,
 * feature/blueprint-workspace-chrome; header-merge follow-up). Reuses
 * /chat's own MessageThread (hideHeader=true -- the project container's
 * own header, layout.tsx, now carries §7.2's ProjectHeader as its single
 * header row, merged with the breadcrumb/tab bar rather than a second
 * standalone bar). LiveWorkPanel (renamed from ProjectContextPanel, §7.6)
 * replaces ContextPanel -- a separate component, not that one made
 * configurable, since /chat's own AXIOM Direct sessions and non-project
 * channels have nothing to show a Live work/Team/Data roster for.
 *
 * Channel selection, the agent roster, and personality/operation mode all
 * live in the project container layout now (ProjectChatContext) -- this
 * page consumes them rather than owning its own copies, so the header (in
 * layout.tsx) and this page's own message-sending logic can never disagree
 * about which channel is active. What stays here is genuinely chat-content-
 * specific: the message list itself, the composer draft, and the whole
 * streaming turn.
 */
export default function ProjectChatTab() {
  const token = getToken() as string;
  const decoded = decodeUserFromToken(token);
  const currentUserRole = decoded?.role ?? null;
  const params = useParams();
  const projectId = params.id as string;
  const toast = useToast();
  const router = useRouter();
  const qc = useQueryClient();

  const {
    activeSessionId, activeChannel,
    channelAgents, channelUsers, agentRoster, agentRosterLoading, selectableAgents, availablePeople,
    currentUserId, addAgentToActiveChannel, removeAgentFromActiveChannel,
    addPersonToActiveChannel, removePersonFromActiveChannel,
    personalityMode, operationMode,
    liveWorkOpen,
  } = useProjectChatContext();

  const [messages, setMessages] = useState<LocalChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [provider, setProvider] = useState<string | null>(null);
  const [attachedContext, setAttachedContext] = useState<ChatContext | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [liveNotice, setLiveNotice] = useState<string | null>(null);
  // §7.5 mention picker's "Not hired yet — tag to hire" row -- there is no
  // real one-click/no-modal hire flow anywhere in this codebase (hiring
  // always requires a name, via HireAgentModal); tagging an unhired type
  // opens that same real modal instead of faking an inline action that
  // doesn't exist.
  const [inlineHireOpen, setInlineHireOpen] = useState(false);
  // §7.3.E's inline action row. A single pair, not a set -- only one
  // approve/reject click can be in flight from this composer at a time.
  const [busyApprovalId, setBusyApprovalId] = useState<string | null>(null);
  const [busyApprovalAction, setBusyApprovalAction] = useState<"approving" | "rejecting" | null>(null);

  const chatGenerationRef = useRef(0);

  // Replaces the old selectSession() function -- activeSessionId now lives
  // in the container layout (ProjectChatContext), set from the header's
  // "⋯" menu, the auto-select-first-channel effect, or channel creation.
  // Whatever set it, this is the one place that reacts: fetch history,
  // populate messages, same staleness guard send() already uses so a rapid
  // switch can't have an in-flight fetch for the PREVIOUS channel land
  // after this one's and show the wrong thread (a real, disclosed bug in
  // the previous two-owner version, now structurally impossible -- there's
  // only one effect that ever changes `messages` in response to a channel
  // switch, not two independent call sites racing).
  useEffect(() => {
    chatGenerationRef.current += 1;
    const myGeneration = chatGenerationRef.current;
    setSendError(null);
    setUploadError(null);
    setSending(false);
    if (!activeSessionId) {
      setMessages([]);
      return;
    }
    (async () => {
      try {
        const history = await getChatHistory(token, activeSessionId);
        if (chatGenerationRef.current === myGeneration) setMessages(history.messages);
      } catch {
        if (chatGenerationRef.current === myGeneration) {
          toast.push("Failed to load conversation history.", "danger");
        }
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSessionId]);

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
      qc.invalidateQueries({ queryKey: ["project-agents", projectId] });
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

  // §7.3.E's inline action row. approveRequest()/rejectRequest() (the
  // already-shipped Approvals-screen actions, reused rather than a second
  // implementation) both resolve only once resolve_task_approval()'s own
  // wave-drain is fully done server-side -- by the time either promise
  // settles, this task AND any dependent it released have already reached
  // their real, persisted final state, so a plain history refetch is the
  // whole job here, not a second stream or a hand-rolled poll.
  const resolveApprovalCard = async (approvalRequestId: string, action: "approving" | "rejecting") => {
    if (!activeSessionId) return;
    const myGeneration = chatGenerationRef.current;
    setBusyApprovalId(approvalRequestId);
    setBusyApprovalAction(action);
    try {
      if (action === "approving") await approveRequest(token, approvalRequestId);
      else await rejectRequest(token, approvalRequestId);
      if (chatGenerationRef.current !== myGeneration) return;
      const history = await getChatHistory(token, activeSessionId);
      if (chatGenerationRef.current === myGeneration) {
        // Preserve any OTHER still-pending approval card in this channel
        // (a different task, paused on its own gate) -- only the one just
        // resolved is guaranteed to have real history behind it now.
        setMessages((prev) => {
          const stillPaused = prev.filter(
            (m) => !!m.approvalCard && m.approvalCard.approval_request_id !== approvalRequestId,
          );
          return [...history.messages, ...stillPaused];
        });
      }
      qc.invalidateQueries({ queryKey: ["active-tasks"] });
    } catch {
      toast.push(
        action === "approving" ? "Failed to approve — try again." : "Failed to reject — try again.",
        "danger",
      );
    } finally {
      if (chatGenerationRef.current === myGeneration) {
        setBusyApprovalId(null);
        setBusyApprovalAction(null);
      }
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
    let isSupervisorTurn = false;
    const ensureTaskMessage = (taskId: string, agentId: string) => {
      if (isStale()) return;
      isSupervisorTurn = true;
      setMessages((prev) => {
        if (prev.some((m) => m.task_id === taskId)) return prev;
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
              console.warn(`[supervisor] refusal (${kind}) has no shape-H UI built for it yet:`, message);
            }
            setSendError(message);
          },
          onSupervisorTask: (data) => {
            if (isStale()) return;
            if (data.status === "queued") {
              ensureTaskMessage(data.task_id, data.agent_id);
              return;
            }
            if (data.status === "running") {
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
              taskFailed: data.status === "failed",
              approvalCard: data.status === "paused_needs_approval"
                ? {
                    approval_request_id: data.approval_request_id ?? "",
                    risk_level: data.risk_level ?? "high",
                    reason: data.reason ?? "",
                    unblocks: data.unblocks ?? null,
                  }
                : undefined,
            }));
            // §7.2's header status badge (and the live-work toggle's own
            // count) both read ["active-tasks"] -- that query polls
            // independently, so without this a task pausing for approval
            // left the header showing "working" for up to 20 real seconds
            // after the approval card itself had already appeared live.
            qc.invalidateQueries({ queryKey: ["active-tasks"] });
          },
          onSystemLine: ({ text }) => {
            if (isStale()) return;
            setMessages((prev) => [...prev, {
              role: "assistant", content: text, tool_calls: [],
              timestamp: new Date().toISOString(), isSystemNotice: true,
            }]);
          },
          onHandoff: ({ from_agent_id, from_agent_name, to_agent_id, to_agent_name, payload_summary, withheld }) => {
            if (isStale()) return;
            setMessages((prev) => [...prev, {
              role: "system_notice", content: "", tool_calls: [],
              timestamp: new Date().toISOString(),
              from_agent_id, from_agent_name, to_agent_id, to_agent_name,
              payload_summary, withheld,
            }]);
          },
          onNeedsClarification: (data) => {
            console.warn("[supervisor] needs_clarification has no shape-G UI built for it yet:", data);
          },
          onDone: (doneData) => {
            if (isStale()) return;
            setProvider(doneData.provider);
            doneSessionId = doneData.session_id;
            if (!isSupervisorTurn) {
              updatePlaceholder((msg) => ({ ...msg, agent_id: doneData.agent_id, streaming: false }));
            }
          },
        },
      );

      if (isStale()) return;
      const historySessionId = doneSessionId ?? sessionAtSendTime;
      if (historySessionId) {
        try {
          const history = await getChatHistory(token, historySessionId);
          if (!isStale()) {
            setMessages((prev) => {
              const stillPaused = prev.filter((m) => !!m.approvalCard);
              return [...history.messages, ...stillPaused];
            });
          }
        } catch {
          // Keep the locally-accumulated placeholder rather than losing
          // the turn the user just watched complete.
        }
      }
      qc.invalidateQueries({ queryKey: ["chat-sessions"] });
    } catch (err) {
      if (isStale()) return;
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

  if (!agentRosterLoading && agentRoster.length === 0) {
    return <NoAgentsEmptyState projectId={projectId} />;
  }

  return (
    <div className="chat-layout">
      <MessageThread
        hideHeader
        messages={messages}
        sending={sending}
        sendError={sendError}
        provider={provider}
        liveNotice={liveNotice}
        personalityMode={personalityMode}
        operationMode={operationMode}
        onPersonalityChange={() => {}}
        onOperationChange={() => {}}
        attachedContext={attachedContext}
        onClearContext={() => setAttachedContext(null)}
        draft={draft}
        onDraftChange={setDraft}
        onSend={send}
        onGoToApprovals={() => router.push("/approvals")}
        // "+ Start a Task" removed from this route (§7.2: "you start work
        // by typing") -- MessageThread's own header (and this prop's only
        // caller) is hidden here via hideHeader, so this is structurally
        // unreachable, kept only because the prop itself stays required
        // for /chat, which still uses it.
        onStartTask={() => {}}
        channel={activeChannel}
        channelAgents={channelAgents}
        channelUsers={channelUsers}
        availableAgents={selectableAgents}
        availablePeople={availablePeople}
        currentUserId={currentUserId}
        onAddAgent={addAgentToActiveChannel}
        onRemoveAgent={removeAgentFromActiveChannel}
        onAddPerson={addPersonToActiveChannel}
        onRemovePerson={removePersonFromActiveChannel}
        currentUserRole={currentUserRole}
        uploading={uploading}
        uploadError={uploadError}
        onUploadFile={handleUploadFile}
        onTagUnhiredType={() => setInlineHireOpen(true)}
        onApproveTask={(id) => resolveApprovalCard(id, "approving")}
        onRejectTask={(id) => resolveApprovalCard(id, "rejecting")}
        busyApprovalId={busyApprovalId}
        busyApprovalAction={busyApprovalAction}
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
        channelAgents={channelAgents}
        mobileOpen={liveWorkOpen}
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
