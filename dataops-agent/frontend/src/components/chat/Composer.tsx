"use client";

// §7.5 Composer -- extracted from MessageThread (blueprint chrome pass,
// feature/blueprint-workspace-chrome) into its own component per the
// blueprint's stated boundaries ("Composer" / "Mention picker" as two
// named anatomies, DESIGN_SPEC.md §7.5). Behaviour is byte-for-byte the
// same as the inline version it replaces -- the findActiveMention
// cursor-position logic in particular is copied verbatim, not rewritten,
// per this pass's explicit instruction.
//
// Dropped in this extraction, not carried forward: the hardcoded
// QUICK_PROMPTS chip row and "/ Command" button were already dead (no
// slash-command parser exists anywhere in this codebase, see the removed
// button's own prior comment) and saved-prompts belonged to SessionList,
// which this screen no longer renders (§7.1's two-pane layout has no
// third sidebar column for it to live in). Neither is named in the
// blueprint's own composer anatomy (§7.2/§7.5) -- disclosed here as a
// deliberate scope decision, not an oversight, see this pass's own report.
import { useEffect, useRef, useState } from "react";
import { MentionPicker, type MentionNavigableRow } from "./MentionPicker";
import { KNOWN_EMPLOYEE_TYPES, EMPLOYEE_TYPE_LABEL } from "@/lib/employeeTypes";
import type { ChannelItem, ChannelMemberAgent, ChatContext } from "@/lib/api";

// Finds the @mention the cursor is currently inside of, anywhere in the
// text -- not just a mention at the very start of the message. Scans
// backward from the cursor through non-whitespace; an "@" only counts as
// a trigger if it starts a word (string start or preceded by whitespace)
// -- an "@" mid-word (an email address) is correctly ignored. Unchanged
// from the pre-extraction implementation.
function findActiveMention(text: string, cursor: number): { start: number; query: string } | null {
  let i = cursor - 1;
  while (i >= 0) {
    const ch = text[i];
    if (/\s/.test(ch)) return null;
    if (ch === "@") {
      if (i === 0 || /\s/.test(text[i - 1])) return { start: i, query: text.slice(i + 1, cursor) };
      return null;
    }
    i--;
  }
  return null;
}

export function Composer({
  draft,
  onDraftChange,
  onSend,
  sending,
  sendError,
  channel,
  channelAgents,
  attachedContext,
  onClearContext,
  uploading,
  uploadError,
  onUploadFile,
  onTagUnhiredType,
}: {
  draft: string;
  onDraftChange: (v: string) => void;
  onSend: () => void;
  sending: boolean;
  sendError?: string | null;
  channel?: ChannelItem | null;
  channelAgents?: ChannelMemberAgent[];
  attachedContext?: ChatContext | null;
  onClearContext?: () => void;
  uploading?: boolean;
  uploadError?: string | null;
  onUploadFile?: (file: File) => void;
  onTagUnhiredType?: (employeeType: string) => void;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [mentionHighlight, setMentionHighlight] = useState(0);
  const [mentionDismissed, setMentionDismissed] = useState(false);
  const [cursorPos, setCursorPos] = useState(0);
  const [dragOver, setDragOver] = useState(false);
  const [dropRefusedReason, setDropRefusedReason] = useState<string | null>(null);
  const pendingCursorRef = useRef<number | null>(null);

  const canUpload = !!channel && !!onUploadFile;

  const handleFile = (file: File) => {
    setDropRefusedReason(null);
    if (!canUpload) {
      setDropRefusedReason(
        channel
          ? "File uploads aren't available here."
          : "File uploads are only supported inside a channel right now — open or create one first."
      );
      return;
    }
    onUploadFile!(file);
  };

  // Mention picker (§7.5). resolve_mentioned_agent() requires an exact,
  // complete name match -- there's no partial/prefix matching server-side
  // -- so selecting a row always inserts the agent's FULL name, never
  // leaves a partial one for the parser to guess at. Agent rows are
  // scoped to this channel's own current members, never every tenant
  // agent -- mentioning one that isn't a member yet is exactly the dead
  // end an earlier pass already built a real error message for; the
  // picker shouldn't offer a name that's guaranteed to fail.
  const activeMention = channel ? findActiveMention(draft, cursorPos) : null;
  const mentionQuery = activeMention?.query ?? null;
  const queryLower = mentionQuery?.toLowerCase() ?? "";

  const agentRows = mentionQuery !== null
    ? (channelAgents ?? []).filter((a) => a.name.toLowerCase().startsWith(queryLower))
    : [];
  const hiredTypes = new Set((channelAgents ?? []).map((a) => a.employee_type));
  const hireTypeRows = mentionQuery !== null
    ? KNOWN_EMPLOYEE_TYPES
        .filter((t) => !hiredTypes.has(t))
        .map((t) => ({ employeeType: t, label: EMPLOYEE_TYPE_LABEL[t] ?? t }))
        .filter((r) => r.label.toLowerCase().startsWith(queryLower))
    : [];

  const navigableRows: MentionNavigableRow[] = [
    ...agentRows.map((agent) => ({ kind: "agent" as const, agent })),
    ...hireTypeRows.map((r) => ({ kind: "hire" as const, ...r })),
  ];
  const showMentionPicker = activeMention !== null && !mentionDismissed && navigableRows.length > 0;

  const selectMentionRow = (row: MentionNavigableRow) => {
    if (row.kind === "hire") {
      onTagUnhiredType?.(row.employeeType);
      setMentionDismissed(true);
      return;
    }
    if (!activeMention) return;
    const before = draft.slice(0, activeMention.start);
    const after = draft.slice(cursorPos);
    const inserted = `@${row.agent.name} `;
    onDraftChange(before + inserted + after);
    pendingCursorRef.current = before.length + inserted.length;
  };

  // Inserted by the toolbar's "@ Tag" button -- at the cursor, with a
  // leading space only if not already preceded by whitespace/the start of
  // the message, so it never fuses onto an existing word.
  const insertAtCursor = (char: string) => {
    const before = draft.slice(0, cursorPos);
    const after = draft.slice(cursorPos);
    const insertion = (before.length > 0 && !/\s$/.test(before) ? " " : "") + char;
    onDraftChange(before + insertion + after);
    pendingCursorRef.current = before.length + insertion.length;
  };

  const updateCursor = (e: React.SyntheticEvent<HTMLTextAreaElement>) => {
    setCursorPos(e.currentTarget.selectionStart ?? 0);
  };

  // Applies a cursor position set by selectMentionRow/insertAtCursor once
  // the just-inserted text has actually landed in the DOM.
  useEffect(() => {
    if (pendingCursorRef.current !== null && textareaRef.current) {
      const pos = pendingCursorRef.current;
      textareaRef.current.setSelectionRange(pos, pos);
      textareaRef.current.focus();
      pendingCursorRef.current = null;
      setCursorPos(pos);
    }
  }, [draft]);

  useEffect(() => {
    setMentionHighlight(0);
  }, [mentionQuery]);

  // Dismissal belongs to ONE mention context (identified by where it
  // starts in the text), not to the whole session.
  useEffect(() => {
    setMentionDismissed(false);
  }, [activeMention?.start]);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "40px";
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
  }, [draft]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (showMentionPicker && navigableRows.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setMentionHighlight((i) => (i + 1) % navigableRows.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setMentionHighlight((i) => (i - 1 + navigableRows.length) % navigableRows.length);
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        selectMentionRow(navigableRows[mentionHighlight]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setMentionDismissed(true);
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (draft.trim() && !sending) onSend();
    }
  };

  return (
    <div className="chat-composer">
      {sendError && (
        <div className="text-xs" style={{ color: "var(--danger)", marginBottom: 6 }}>{sendError}</div>
      )}
      {uploadError && (
        <div className="text-xs" style={{ color: "var(--danger)", marginBottom: 6 }}>{uploadError}</div>
      )}
      {dropRefusedReason && (
        <div className="text-xs text-muted" style={{ marginBottom: 6 }}>{dropRefusedReason}</div>
      )}
      {uploading && (
        <div className="text-xs text-muted" style={{ marginBottom: 6 }}>Uploading…</div>
      )}

      {/* §7.5 -- Card, three rows: attachments (hidden when empty), input,
          toolbar. */}
      <div
        className={["composer-card", dragOver ? "drag-over" : ""].join(" ")}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          const file = e.dataTransfer.files?.[0];
          if (file) handleFile(file);
        }}
      >
        {attachedContext && (
          <div className="composer-row composer-row-attachments">
            <div className="chat-context-chip" style={{ marginBottom: 0 }}>
              <span>📎 {attachedContext.source_name}</span>
              <button onClick={onClearContext} title="Remove attachment">✕</button>
            </div>
          </div>
        )}

        <div className="composer-row composer-row-input">
          {showMentionPicker && (
            <MentionPicker
              rows={navigableRows}
              highlightIndex={mentionHighlight}
              onHighlight={setMentionHighlight}
              onSelect={selectMentionRow}
            />
          )}
          <textarea
            ref={textareaRef}
            placeholder={
              channel
                ? (channelAgents?.length ?? 0) > 1
                  ? "@mention who you're talking to... (↵ to send, Shift+↵ for newline)"
                  : `Message #${channel.name}... (↵ to send, Shift+↵ for newline)`
                : "Message your team… use @ to tag someone (↵ to send, Shift+↵ for newline)"
            }
            rows={1}
            value={draft}
            disabled={sending}
            onChange={(e) => { onDraftChange(e.target.value); setCursorPos(e.target.selectionStart ?? 0); }}
            onSelect={updateCursor}
            onClick={updateCursor}
            onKeyUp={updateCursor}
            onKeyDown={handleKeyDown}
          />
        </div>

        <div className="composer-row composer-row-toolbar">
          <div className="composer-toolbar-left">
            <input
              ref={fileInputRef}
              type="file"
              style={{ display: "none" }}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleFile(file);
                e.target.value = "";
              }}
            />
            <button
              type="button"
              className="btn btn-secondary btn-icon btn-dense"
              title={canUpload ? "Attach a file" : "File uploads are only supported inside a channel"}
              disabled={uploading || sending}
              onClick={() => fileInputRef.current?.click()}
            >
              📎
            </button>
            <button
              type="button"
              className="btn btn-secondary btn-dense"
              disabled={sending}
              onClick={() => insertAtCursor("@")}
            >
              @ Tag
            </button>
          </div>
          <div className="composer-toolbar-right">
            <span className="composer-hint">
              {channel ? "Everyone tagged runs in parallel" : "Enter to send"}
            </span>
            <button
              type="button"
              className="btn btn-primary btn-icon btn-dense"
              aria-label="Send message"
              disabled={!draft.trim() || sending}
              onClick={onSend}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="22" y1="2" x2="11" y2="13" />
                <polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
            </button>
          </div>
        </div>
      </div>

      {canUpload && (
        <div className="composer-drop-hint">
          Drop any file here — CSV, PDF, Excel, a proposal doc. It attaches to this project automatically.
        </div>
      )}
    </div>
  );
}
