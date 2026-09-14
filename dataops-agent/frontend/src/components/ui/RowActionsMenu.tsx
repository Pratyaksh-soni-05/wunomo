"use client";

import { useEffect, useRef, useState } from "react";

// Rough dropdown height estimate for the collision check below -- doesn't
// need to be exact, just enough to decide "will this realistically fit
// below the trigger." Real menus here run 1-3 items at ~40px each plus
// padding; overestimating slightly is the safe direction (flips up a
// little earlier than strictly necessary, never flips down into the fold).
const ESTIMATED_DROPDOWN_HEIGHT = 160;

/**
 * The overflow half of Phase 6's density hybrid: destructive/irreversible
 * row actions (Delete, Reject, Remove, Revoke...) live here instead of as a
 * standing icon, so an accidental click costs two deliberate actions, not
 * one. Frequent, non-destructive actions stay inline as icon-only buttons
 * at each call site — this component is only for the destructive half.
 *
 * Viewport-collision flip added (Wunomo UI-rebuild slice 5, 2026-09-14,
 * findings item 83): the dropdown used to open downward unconditionally
 * (top: calc(100% + 4px)), so a row near the bottom of a long table opened
 * its menu off-screen, below the fold. Fixed at the component level, not
 * per call site, since every list page with row actions (Sources,
 * Pipelines, Quality, Incidents, Projects, Team, Approvals, CI/CD) shares
 * this one component and inherited the identical gap.
 */
export function RowActionsMenu({
  actions,
}: {
  actions: { label: string; onClick: () => void; disabled?: boolean; title?: string }[];
}) {
  const [open, setOpen] = useState(false);
  const [openUpward, setOpenUpward] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const t = setTimeout(() => document.addEventListener("click", onClick), 0);
    return () => {
      clearTimeout(t);
      document.removeEventListener("click", onClick);
    };
  }, [open]);

  if (actions.length === 0) return null;

  return (
    <div className="row-actions-menu" ref={ref}>
      <button
        ref={triggerRef}
        type="button"
        className="btn btn-ghost btn-icon"
        aria-label="More actions"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation();
          if (!open && triggerRef.current) {
            const rect = triggerRef.current.getBoundingClientRect();
            setOpenUpward(window.innerHeight - rect.bottom < ESTIMATED_DROPDOWN_HEIGHT);
          }
          setOpen((v) => !v);
        }}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" stroke="none">
          <circle cx="12" cy="5" r="1.75" />
          <circle cx="12" cy="12" r="1.75" />
          <circle cx="12" cy="19" r="1.75" />
        </svg>
      </button>
      {open && (
        <div className={["row-actions-dropdown", openUpward ? "flip-up" : ""].filter(Boolean).join(" ")} role="menu">
          {actions.map((a) => (
            <button
              key={a.label}
              type="button"
              role="menuitem"
              disabled={a.disabled}
              title={a.title}
              onClick={(e) => {
                e.stopPropagation();
                setOpen(false);
                a.onClick();
              }}
            >
              {a.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
