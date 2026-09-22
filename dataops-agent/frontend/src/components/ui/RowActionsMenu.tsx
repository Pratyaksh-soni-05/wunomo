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
  // Viewport coordinates for the dropdown. It is rendered position:fixed
  // rather than absolute-below-the-button because every Table sits inside
  // .table-wrap { overflow-x: auto }, and an overflow-x that isn't
  // `visible` forces overflow-y to clip as well -- so an absolute dropdown
  // opening downward from the LAST row was cut off at the table's bottom
  // edge, leaving an empty ~10px sliver with the label out of view.
  // `top` also flips upward (a separate, independently-found fix) when the
  // trigger is close enough to the bottom of the browser window that the
  // dropdown would render past the visible viewport, not just the table's
  // own clipped edge -- both computed from the same getBoundingClientRect()
  // call below, so there's one source of truth for the trigger's position.
  const [pos, setPos] = useState<{ top: number; right: number } | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    // A fixed-position menu doesn't follow its button if the page scrolls;
    // closing is simpler and matches how native menus behave.
    const onScrollOrResize = () => setOpen(false);
    const t = setTimeout(() => document.addEventListener("click", onClick), 0);
    window.addEventListener("scroll", onScrollOrResize, true);
    window.addEventListener("resize", onScrollOrResize);
    return () => {
      clearTimeout(t);
      document.removeEventListener("click", onClick);
      window.removeEventListener("scroll", onScrollOrResize, true);
      window.removeEventListener("resize", onScrollOrResize);
    };
  }, [open]);

  if (actions.length === 0) return null;

  return (
    <div className="row-actions-menu" ref={ref}>
      <button
        ref={btnRef}
        type="button"
        className="btn btn-ghost btn-icon"
        aria-label="More actions"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation();
          const r = btnRef.current?.getBoundingClientRect();
          if (r) {
            const upward = window.innerHeight - r.bottom < ESTIMATED_DROPDOWN_HEIGHT;
            setPos(
              upward
                ? { top: r.top - ESTIMATED_DROPDOWN_HEIGHT, right: window.innerWidth - r.right }
                : { top: r.bottom + 4, right: window.innerWidth - r.right },
            );
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
        <div
          className="row-actions-dropdown"
          role="menu"
          style={pos ? { position: "fixed", top: pos.top, right: pos.right } : undefined}
        >

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
