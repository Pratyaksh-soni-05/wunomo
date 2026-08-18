"use client";

import { createContext, ReactNode, useCallback, useContext, useState } from "react";

type ToastVariant = "default" | "success" | "danger" | "warning";

interface ToastAction {
  label: string;
  onClick: () => void;
}

interface ToastItem {
  id: string;
  message: string;
  variant: ToastVariant;
  leaving: boolean;
  action?: ToastAction;
}

interface ToastContextValue {
  // action: an optional inline link for toasts that refuse an action rather
  // than just report failure -- a bare "can't do that" is a dead end (see
  // finding 12); this gives the toast a route forward, e.g. deleting a
  // conversation with a pending approval links straight to Approvals.
  push: (message: string, variant?: ToastVariant, action?: ToastAction) => void;
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

  const push = useCallback((message: string, variant: ToastVariant = "default", action?: ToastAction) => {
    const id = crypto.randomUUID();
    setToasts((prev) => [...prev, { id, message, variant, leaving: false, action }]);
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
            <span>{t.message}</span>
            {t.action && (
              <button className="toast-action" onClick={t.action.onClick}>
                {t.action.label}
              </button>
            )}
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
