"use client";

import { useRouter, usePathname } from "next/navigation";
import { isAxiomDomain } from "./navItems";

export function AxiomFab() {
  const router = useRouter();
  const pathname = usePathname();

  // Hides across all of AXIOM's own domain (chat + Tasks, 2026-08 IA
  // restructure), not just the chat route itself - the sidebar's own
  // back-link already covers "how do I get to AXIOM" once you're on a
  // Tasks screen, so a second floating shortcut there is redundant.
  if (isAxiomDomain(pathname)) return null;

  return (
    <button className="axiom-fab" onClick={() => router.push("/chat")}>
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
        <path d="M12 2a8 8 0 0 1 8 8v12l-4-4H4a8 8 0 0 1 0-16" />
      </svg>
      <span>Ask AXIOM</span>
    </button>
  );
}
