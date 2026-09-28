import type { ChatMessageItem, PendingApproval } from "@/lib/api";

// Extends the real history-endpoint shape with the richer approval detail
// (risk_level/reason) that's only available on the turn's own fresh send
// response, not on GET /chat/sessions/{id}/history — see ToolCallBlock.
export interface LocalChatMessage extends ChatMessageItem {
  approvals?: PendingApproval[];
  // Client-side-only synthetic entry for a task started from the chat UI
  // (item 6, stage 7) - never sent to or returned by the backend, so it's
  // never present in a real GET /chat/sessions/{id}/history payload and
  // doesn't survive a session switch/reload, same as the rest of this
  // client-only message array.
  taskCard?: { id: string; goal: string };
  // Wunomo Projects Phase 2 frontend, slice 6: a channel routing failure
  // (no such agent, not a channel member, ambiguous/no mention) comes
  // back as a normal assistant turn with provider: null -- flagged here,
  // computed at send time, so it renders distinctly from a real agent
  // reply instead of looking like AXIOM's own voice. Not reconstructable
  // from GET .../history (which carries no per-message provider field),
  // so this doesn't survive a session switch/reload -- an acceptable,
  // cosmetic-only gap; the message text itself is still self-explanatory.
  isSystemNotice?: boolean;
  // Client-side-only routing key for a LIVE supervisor sub-task's own
  // streaming placeholder bubble (Wunomo Projects Phase 4, supervisor
  // streaming pass) -- one bubble per task_id, updated in place as its
  // token/tool_start/tool_end events arrive tagged with the same id.
  // Never present after a history refetch (GET .../history's real
  // ChatMessage rows carry no such column) -- purely a during-the-stream
  // routing key, same lifecycle as taskCard above.
  task_id?: string;
  // Per-message "is this bubble still live" flag -- replaces the old
  // "the streaming message is whichever one is last in the array"
  // assumption, which broke the instant a second concurrent bubble was
  // appended after the first (the first permanently stopped being "last",
  // so it permanently stopped showing as streaming even while its own
  // tokens kept arriving). Set true at creation (the generic single-agent
  // placeholder, or a supervisor task bubble on its first "queued"/
  // "running" event) and false at that same message's own terminal event
  // (onDone for the single-agent placeholder, the terminal supervisor_task
  // status for a task bubble) -- never derived from array position.
  streaming?: boolean;
}
