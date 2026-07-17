"use client";

import { useEffect, useRef, useState } from "react";
import { Card, Select } from "@/components/ui";
import { ToolCallBlock } from "./ToolCallBlock";
import type { LocalChatMessage } from "./types";
import type { ChatContext } from "@/lib/api";

const QUICK_PROMPTS = [
  "List my data sources",
  "Show failed pipeline runs",
  "Run quality checks on a pipeline",
  "List open incidents",
  "Generate a status report",
];

const PERSONALITY_OPTIONS = ["engineer", "founder", "analyst", "auditor"] as const;
const OPERATION_OPTIONS = ["advisory", "assisted", "autonomous", "audit"] as const;

function formatAssistantText(text: string) {
  return text
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");
}

function ThinkingIndicator() {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(id);
  }, []);
  return (
    <div className="chat-thinking">
      <span className="status-dot info pulse" />
      {elapsed < 5 ? "AXIOM is thinking…" : `AXIOM is still thinking… (${elapsed}s)`}
    </div>
  );
}

export function MessageThread({
  messages,
  sending,
  sendError,
  provider,
  personalityMode,
  operationMode,
  onPersonalityChange,
  onOperationChange,
  attachedContext,
  onClearContext,
  draft,
  onDraftChange,
  onSend,
  onGoToApprovals,
}: {
  messages: LocalChatMessage[];
  sending: boolean;
  sendError: string | null;
  provider: string | null;
  personalityMode: string;
  operationMode: string;
  onPersonalityChange: (v: string) => void;
  onOperationChange: (v: string) => void;
  attachedContext: ChatContext | null;
  onClearContext: () => void;
  draft: string;
  onDraftChange: (v: string) => void;
  onSend: () => void;
  onGoToApprovals: () => void;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, sending]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (draft.trim() && !sending) onSend();
    }
  };

  return (
    <div className="chat-main">
      <div className="chat-header">
        <div className="chat-header-identity">
          <div className="chat-avatar">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 2a8 8 0 0 1 8 8v12l-4-4H4a8 8 0 0 1 0-16" />
            </svg>
          </div>
          <div>
            <div className="font-semibold" style={{ fontSize: 13 }}>AXIOM DataOps Agent</div>
            <div className="flex items-center gap-2" style={{ gap: 6 }}>
              <span className={["status-dot", sending ? "warning pulse" : "success"].join(" ")} />
              <span className="text-xs text-muted">
                {sending ? "Working…" : provider ? `Ready · last reply via ${provider}` : "Ready"}
              </span>
            </div>
          </div>
        </div>
        <div className="chat-header-controls">
          <Select
            aria-label="Personality mode"
            value={personalityMode}
            onChange={(e) => onPersonalityChange(e.target.value)}
            style={{ width: "auto", fontSize: 11, padding: "4px 24px 4px 8px" }}
          >
            {PERSONALITY_OPTIONS.map((o) => <option key={o} value={o}>{o[0].toUpperCase() + o.slice(1)}</option>)}
          </Select>
          <Select
            aria-label="Operation mode"
            value={operationMode}
            onChange={(e) => onOperationChange(e.target.value)}
            style={{ width: "auto", fontSize: 11, padding: "4px 24px 4px 8px" }}
          >
            {OPERATION_OPTIONS.map((o) => <option key={o} value={o}>{o[0].toUpperCase() + o.slice(1)}</option>)}
          </Select>
        </div>
      </div>

      <div className="chat-messages">
        {messages.length === 0 && !sending && (
          <div className="empty-state" style={{ minHeight: "auto", padding: "40px 20px" }}>
            <h2 className="font-display text-xl">Ask AXIOM anything</h2>
            <p className="text-muted text-sm" style={{ maxWidth: 360 }}>
              Query your data, check pipeline health, run quality checks, or investigate an incident —
              AXIOM has real tool access to your tenant&apos;s data.
            </p>
          </div>
        )}

        {messages.map((m, i) =>
          m.role === "user" ? (
            <div className="chat-bubble-user" key={i}>
              <div className="chat-bubble-user-inner">{m.content}</div>
            </div>
          ) : (
            <div className="chat-bubble-assistant" key={i}>
              <div className="chat-avatar" style={{ marginTop: 2 }}>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 2a8 8 0 0 1 8 8v12l-4-4H4a8 8 0 0 1 0-16" />
                </svg>
              </div>
              <div className="chat-bubble-assistant-inner">
                <Card className="chat-bubble-assistant-text">
                  <span dangerouslySetInnerHTML={{ __html: formatAssistantText(m.content) }} />
                </Card>
                {m.tool_calls.map((call, ci) => (
                  <ToolCallBlock
                    key={ci}
                    call={call}
                    approval={m.approvals?.find((a) => a.name === call.tool)}
                    onGoToApprovals={onGoToApprovals}
                  />
                ))}
              </div>
            </div>
          )
        )}

        {sending && <ThinkingIndicator />}
        <div ref={bottomRef} />
      </div>

      <div className="chat-composer">
        {attachedContext && (
          <div className="chat-context-chip">
            <span>📎 {attachedContext.source_name}</span>
            <button onClick={onClearContext} title="Remove context">✕</button>
          </div>
        )}
        {sendError && (
          <div className="text-xs" style={{ color: "var(--danger)", marginBottom: 6 }}>{sendError}</div>
        )}
        <div className="chat-composer-box">
          <textarea
            placeholder="Ask AXIOM anything about your data... (↵ to send, Shift+↵ for newline)"
            rows={1}
            value={draft}
            disabled={sending}
            onChange={(e) => onDraftChange(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          <div className="chat-composer-actions">
            <span className="text-xs text-muted">Enter to send</span>
            <button
              className="btn btn-primary btn-sm"
              disabled={!draft.trim() || sending}
              onClick={onSend}
            >
              Send
            </button>
          </div>
        </div>
        <div className="chat-quick-prompts">
          {QUICK_PROMPTS.map((p) => (
            <button key={p} className="btn btn-secondary btn-sm" style={{ fontSize: 11 }} onClick={() => onDraftChange(p)}>
              {p}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
