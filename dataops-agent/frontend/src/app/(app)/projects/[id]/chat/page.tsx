import Link from "next/link";

// A signpost, not a dead end (explicit instruction, 2026-09-14): this
// project's own chat/channels live here once slice 7 wires it up. Until
// then, point at the real, working chat that already exists rather than
// a bare "coming soon."
export default function ProjectChatTab() {
  return (
    <div className="empty-state">
      <div className="empty-icon">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
      </div>
      <h2 className="font-display text-xl">This project's chat is coming here</h2>
      <p className="text-muted text-sm" style={{ maxWidth: 380 }}>
        Soon this tab will hold this project's own channels and conversations, in place. Until then,
        this project's channels are still reachable from the sidebar, or open AXIOM chat directly.
      </p>
      <Link href="/chat" className="btn btn-primary">Open AXIOM chat</Link>
    </div>
  );
}
