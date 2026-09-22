"use client";

export interface TabItem {
  id: string;
  label: string;
  // §7.6 -- Files/Data render as tabs before there's anything real behind
  // them (Files) or before this pass's scope covers them. Excluded from
  // tab order (not just visually dimmed) since activating it would do
  // nothing -- a focusable control with no action is worse than one a
  // screen reader / keyboard user can skip entirely.
  disabled?: boolean;
}

interface TabsProps {
  items: TabItem[];
  activeId: string;
  onChange: (id: string) => void;
}

export function Tabs({ items, activeId, onChange }: TabsProps) {
  return (
    <div className="tabs" role="tablist">
      {items.map((item) => (
        <div
          key={item.id}
          role="tab"
          aria-selected={item.id === activeId}
          aria-disabled={item.disabled || undefined}
          tabIndex={item.disabled ? -1 : 0}
          className={[
            "tab",
            item.id === activeId ? "active" : "",
            item.disabled ? "disabled" : "",
          ].filter(Boolean).join(" ")}
          onClick={() => { if (!item.disabled) onChange(item.id); }}
          onKeyDown={(e) => {
            if (item.disabled) return;
            if (e.key === "Enter" || e.key === " ") onChange(item.id);
          }}
        >
          {item.label}
        </div>
      ))}
    </div>
  );
}
