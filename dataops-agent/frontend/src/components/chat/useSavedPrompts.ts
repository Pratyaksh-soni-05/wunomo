"use client";

import { useCallback, useEffect, useState } from "react";

export interface SavedPrompt {
  id: string;
  text: string;
}

function storageKey(tenantId: string) {
  return `axiom_saved_prompts_${tenantId}`;
}

// Client-side only — saved prompts are a personal composer shortcut, not
// tenant-shared data, so localStorage (namespaced per tenant to avoid
// bleed across accounts on a shared browser) is the right store, not a
// new backend table.
export function useSavedPrompts(tenantId: string | null) {
  const [prompts, setPrompts] = useState<SavedPrompt[]>([]);

  useEffect(() => {
    if (!tenantId) return;
    try {
      const raw = localStorage.getItem(storageKey(tenantId));
      setPrompts(raw ? JSON.parse(raw) : []);
    } catch {
      setPrompts([]);
    }
  }, [tenantId]);

  const persist = useCallback(
    (next: SavedPrompt[]) => {
      setPrompts(next);
      if (tenantId) localStorage.setItem(storageKey(tenantId), JSON.stringify(next));
    },
    [tenantId]
  );

  const addPrompt = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      persist([...prompts, { id: crypto.randomUUID(), text: trimmed }]);
    },
    [prompts, persist]
  );

  const removePrompt = useCallback(
    (id: string) => {
      persist(prompts.filter((p) => p.id !== id));
    },
    [prompts, persist]
  );

  return { prompts, addPrompt, removePrompt };
}
