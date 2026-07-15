"use client";

export interface TabItem {
  id: string;
  label: string;
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
          tabIndex={0}
          className={["tab", item.id === activeId ? "active" : ""].filter(Boolean).join(" ")}
          onClick={() => onChange(item.id)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") onChange(item.id);
          }}
        >
          {item.label}
        </div>
      ))}
    </div>
  );
}
