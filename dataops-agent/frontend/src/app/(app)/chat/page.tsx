"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useToast } from "@/components/ui";
import { SessionList, MessageThread, ContextPanel, type LocalChatMessage } from "@/components/chat";
import {
  getToken, decodeUserFromToken, getChatSessions, getChatHistory, sendChatMessage, getSources,
  ApiError, type ChatContext,
} from "@/lib/api";

export default function ChatPage() {
  const token = getToken() as string;
  const tenantId = decodeUserFromToken(token)?.tenant_id ?? null;
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

  const sessionsQuery = useQuery({ queryKey: ["chat-sessions"], queryFn: () => getChatSessions(token) });
  const sourcesQuery = useQuery({ queryKey: ["sources"], queryFn: () => getSources(token) });

  const selectSession = async (id: string) => {
    setActiveSessionId(id);
    setSendError(null);
    try {
      const history = await getChatHistory(token, id);
      setMessages(history.messages);
    } catch {
      toast.push("Failed to load conversation history.", "danger");
    }
  };

  const newChat = () => {
    setActiveSessionId(null);
    setMessages([]);
    setDraft("");
    setSendError(null);
    setAttachedContext(null);
  };

  const send = async () => {
    const text = draft.trim();
    if (!text || sending) return;

    const userMsg: LocalChatMessage = { role: "user", content: text, tool_calls: [], timestamp: new Date().toISOString() };
    setMessages((prev) => [...prev, userMsg]);
    setDraft("");
    setSendError(null);
    setSending(true);

    try {
      const res = await sendChatMessage(token, {
        message: text,
        session_id: activeSessionId ?? undefined,
        personality_mode: personalityMode,
        operation_mode: operationMode,
        context: attachedContext ?? undefined,
      });
      const assistantMsg: LocalChatMessage = {
        role: "assistant", content: res.response, tool_calls: res.tool_calls,
        timestamp: res.timestamp, approvals: res.pending_approvals,
      };
      setMessages((prev) => [...prev, assistantMsg]);
      setProvider(res.provider);
      if (!activeSessionId) setActiveSessionId(res.session_id);
      qc.invalidateQueries({ queryKey: ["chat-sessions"] });
    } catch (err) {
      const message =
        err instanceof ApiError
          ? "AXIOM couldn't complete that request — it may have tried an action it couldn't format correctly. Try rephrasing, or try again."
          : "Couldn't reach AXIOM. Check your connection and try again.";
      setSendError(message);
      toast.push(message, "danger");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="chat-layout">
      <SessionList
        tenantId={tenantId}
        sessions={sessionsQuery.data?.sessions ?? []}
        loading={sessionsQuery.isLoading}
        activeSessionId={activeSessionId}
        onSelectSession={selectSession}
        onNewChat={newChat}
        onInsertPrompt={setDraft}
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
      />
      <ContextPanel
        messages={messages}
        sources={sourcesQuery.data?.sources ?? []}
        attachedContext={attachedContext}
        onAttach={setAttachedContext}
        onClear={() => setAttachedContext(null)}
        onGoToApprovals={() => router.push("/approvals")}
      />
    </div>
  );
}
