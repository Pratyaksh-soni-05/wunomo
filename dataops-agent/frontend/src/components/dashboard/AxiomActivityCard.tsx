"use client";

import { useRouter } from "next/navigation";
import { Card, CardHeader, CardBody, Button } from "@/components/ui";
import type { ChatSessionSummary } from "@/lib/api";
import { parseApiDate } from "@/lib/dates";

function timeAgo(iso: string): string {
  const d = parseApiDate(iso);
  const diffMs = Date.now() - (d ? d.getTime() : 0);
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export function AxiomActivityCard({ sessions }: { sessions: ChatSessionSummary[] }) {
  const router = useRouter();
  return (
    <Card>
      <CardHeader className="flex items-center justify-between">
        <span className="font-semibold text-sm">AXIOM Activity</span>
        <Button size="sm" onClick={() => router.push("/chat")}>
          Open
        </Button>
      </CardHeader>
      <CardBody className="flex flex-col gap-1">
        {sessions.length === 0 ? (
          <div className="text-sm text-muted">No conversations with AXIOM yet.</div>
        ) : (
          <>
            {sessions.slice(0, 5).map((s) => (
              <div
                key={s.session_id}
                className="flex items-center gap-2"
                style={{ padding: 8, background: "var(--surface-hover)", borderRadius: "var(--radius-sm)", cursor: "pointer" }}
                onClick={() => router.push(`/chat?session=${encodeURIComponent(s.session_id)}`)}
              >
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="var(--midnight-500)" strokeWidth="2" style={{ flexShrink: 0 }}>
                  <path d="M12 2a8 8 0 0 1 8 8v12l-4-4H4a8 8 0 0 1 0-16" />
                </svg>
                <span className="text-xs font-medium truncate" style={{ flex: 1 }}>
                  {s.title || "New conversation"}
                </span>
                <span className="text-xs text-muted">{timeAgo(s.last_activity)}</span>
              </div>
            ))}
            <Button variant="ghost" style={{ width: "100%", fontSize: 12, marginTop: 4 }} onClick={() => router.push("/chat")}>
              View all conversations →
            </Button>
          </>
        )}
      </CardBody>
    </Card>
  );
}
