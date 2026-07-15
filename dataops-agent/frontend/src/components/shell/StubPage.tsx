export function StubPage({ title, phase }: { title: string; phase?: number }) {
  return (
    <div className="empty-state">
      <div className="empty-icon">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="3" y="3" width="18" height="18" rx="2" />
          <path d="M9 9h6v6H9z" />
        </svg>
      </div>
      <h2 className="font-display text-xl">{title}</h2>
      <p className="text-muted text-sm" style={{ maxWidth: 360 }}>
        {phase
          ? `This screen is wired to real data in Phase ${phase} — for now it's just a routable stub, part of Phase 7's app shell.`
          : "This screen is a routable stub for now — real content lands in a later phase."}
      </p>
    </div>
  );
}
