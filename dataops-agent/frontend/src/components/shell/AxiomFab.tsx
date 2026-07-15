"use client";

import { useRouter, usePathname } from "next/navigation";

export function AxiomFab() {
  const router = useRouter();
  const pathname = usePathname();

  if (pathname === "/chat") return null;

  return (
    <button className="axiom-fab" onClick={() => router.push("/chat")}>
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
        <path d="M12 2a8 8 0 0 1 8 8v12l-4-4H4a8 8 0 0 1 0-16" />
      </svg>
      <span>Ask AXIOM</span>
    </button>
  );
}
