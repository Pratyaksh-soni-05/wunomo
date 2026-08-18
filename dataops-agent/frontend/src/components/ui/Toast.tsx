"use client";

import { createContext, ReactNode, useCallback, useContext, useState } from "react";

type ToastVariant = "default" | "success" | "danger" | "warning";

interface ToastItem {
  id: string;
  message: string;
  variant: ToastVariant;
  leaving: boolean;
}

interface ToastContextValue {
  push: (message: string, variant?: ToastVariant) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

// Item 7 (2026-08 walkthrough): both raised from the original 4000ms/no-exit-
// animation values - a toast disappearing mid-read was the complaint, and an
// instant unmount (no exit transition at all, only the entrance had one) is
// why the disappearance read as abrupt rather than just "gone quickly".
const AUTO_DISMISS_MS = 6000;
const EXIT_ANIM_MS = 260;

export function ToastProvider({ children }: { children?: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const push = useCallback((message: string, variant: ToastVariant = "default") => {
    const id = crypto.randomUUID();
    setToasts((prev) => [...prev, { id, message, variant, leaving: false }]);
    setTimeout(() => {
      setToasts((prev) => prev.map((t) => (t.id === id ? { ...t, leaving: true } : t)));
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, EXIT_ANIM_MS);
    }, AUTO_DISMISS_MS);
  }, []);

  return (
    <ToastContext.Provider value={{ push }}>
      {children}
      <div className="toast-container">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={["toast", t.variant !== "default" ? t.variant : "", t.leaving ? "leaving" : ""].filter(Boolean).join(" ")}
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast() must be used inside a <ToastProvider>");
  return ctx;
}
