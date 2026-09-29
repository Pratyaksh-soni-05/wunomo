"use client";

// §7.5 Mention picker -- extracted from MessageThread/Composer per the
// blueprint's own component boundaries (DESIGN_SPEC.md §7.5: "Composer"
// and "Mention picker" are named as two separate anatomies). Pure
// presentational: Composer.tsx owns the draft/cursor logic and the row
// computation (findActiveMention, agentRows/hireTypeRows), this only
// renders whatever it's handed and reports back which row was picked.
// Behaviour is unchanged from the pre-extraction inline JSX -- same two
// groups, same "everyone" omission (see Composer's own comment for why),
// same keyboard-driven highlight index owned by the parent.
import { Badge } from "@/components/ui";
import { EmployeeAvatar } from "./EmployeeAvatar";
import { EMPLOYEE_TYPE_LABEL } from "@/lib/employeeTypes";
import type { ChannelMemberAgent } from "@/lib/api";

export type MentionNavigableRow =
  | { kind: "agent"; agent: ChannelMemberAgent }
  | { kind: "hire"; employeeType: string; label: string };

export function MentionPicker({
  rows,
  highlightIndex,
  onHighlight,
  onSelect,
}: {
  rows: MentionNavigableRow[];
  highlightIndex: number;
  onHighlight: (index: number) => void;
  onSelect: (row: MentionNavigableRow) => void;
}) {
  const agentRows = rows.filter((r): r is Extract<MentionNavigableRow, { kind: "agent" }> => r.kind === "agent");
  const hireRows = rows.filter((r): r is Extract<MentionNavigableRow, { kind: "hire" }> => r.kind === "hire");

  return (
    <div className="mention-picker" role="listbox" aria-label="Mention someone">
      {agentRows.length > 0 && (
        <div className="mention-picker-group">
          <div className="mention-picker-group-label">On this project</div>
          {agentRows.map(({ agent }) => {
            const idx = rows.findIndex((r) => r.kind === "agent" && r.agent.id === agent.id);
            return (
              <div
                key={agent.id}
                role="option"
                aria-selected={idx === highlightIndex}
                className={["mention-row", idx === highlightIndex ? "active" : ""].filter(Boolean).join(" ")}
                onMouseEnter={() => onHighlight(idx)}
                onClick={() => onSelect({ kind: "agent", agent })}
              >
                <EmployeeAvatar name={agent.name} employeeType={agent.employee_type} size="sm" />
                <div className="mention-row-text">
                  <div className="mention-row-name">{agent.name}</div>
                  <div className="mention-row-meta">
                    {EMPLOYEE_TYPE_LABEL[agent.employee_type] ?? agent.employee_type} · {agent.operation_mode}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
      {hireRows.length > 0 && (
        <div className="mention-picker-group">
          <div className="mention-picker-group-label">Not hired yet — tag to hire</div>
          {hireRows.map((r) => {
            const idx = rows.findIndex((row) => row.kind === "hire" && row.employeeType === r.employeeType);
            return (
              <div
                key={r.employeeType}
                role="option"
                aria-selected={idx === highlightIndex}
                className={["mention-row", idx === highlightIndex ? "active" : ""].filter(Boolean).join(" ")}
                onMouseEnter={() => onHighlight(idx)}
                onClick={() => onSelect({ kind: "hire", employeeType: r.employeeType, label: r.label })}
              >
                <span className="mention-row-name">{r.label}</span>
                <Badge variant="info">+ hire</Badge>
              </div>
            );
          })}
        </div>
      )}
      {/* No "everyone" broadcast row here -- removed, a visible dead
          control teaches users a feature exists that doesn't. Restoring
          it needs a real broadcast target first: services/channel_
          routing.py's resolve_channel_message_target() only ever resolves
          a single named agent or a channel's sole member today, nothing
          that means "every member." */}
    </div>
  );
}
