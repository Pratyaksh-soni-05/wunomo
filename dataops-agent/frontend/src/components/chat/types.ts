import type { ChatMessageItem, PendingApproval } from "@/lib/api";

// Extends the real history-endpoint shape with the richer approval detail
// (risk_level/reason) that's only available on the turn's own fresh send
// response, not on GET /chat/sessions/{id}/history — see ToolCallBlock.
export interface LocalChatMessage extends ChatMessageItem {
  approvals?: PendingApproval[];
}
