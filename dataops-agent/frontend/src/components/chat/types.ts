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
}
