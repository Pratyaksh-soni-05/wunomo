"use client";

// Extracted from MessageThread's inline "Members" modal (blueprint chrome
// pass) so both MessageThread (unchanged, still used by /chat) and the
// project route's new ProjectHeader (§7.2's "⋯" overflow menu -- "Members
// → Team tab in LiveWorkPanel (exists)" collapsed the old always-visible
// header button, but per-channel add/remove is a real, separate function
// LiveWorkPanel's Team tab doesn't cover, so it stays reachable, just not
// as a standing button) can open the same real functionality without a
// second copy of this JSX. Behaviour unchanged from the pre-extraction
// version.
import { Button, Modal } from "@/components/ui";
import type { ChannelItem, ChannelMemberAgent, ChannelMemberUser, SelectableAgent, TeamMember } from "@/lib/api";

export function ChannelMembersModal({
  open,
  onClose,
  channel,
  channelAgents,
  channelUsers,
  availableAgents,
  availablePeople,
  currentUserId,
  onAddAgent,
  onRemoveAgent,
  onAddPerson,
  onRemovePerson,
}: {
  open: boolean;
  onClose: () => void;
  channel: ChannelItem;
  channelAgents?: ChannelMemberAgent[];
  channelUsers?: ChannelMemberUser[];
  availableAgents?: SelectableAgent[];
  availablePeople?: TeamMember[];
  currentUserId?: string | null;
  onAddAgent?: (agentId: string) => void;
  onRemoveAgent?: (agentId: string, agentName: string) => void;
  onAddPerson?: (userId: string) => void;
  onRemovePerson?: (userId: string) => void;
}) {
  const channelAgentIds = new Set((channelAgents ?? []).map((a) => a.id));
  const addableAgents = (availableAgents ?? []).filter((a) => !channelAgentIds.has(a.id));
  const channelUserIds = new Set((channelUsers ?? []).map((u) => u.id));
  const addablePeople = (availablePeople ?? []).filter((p) => p.is_active && !channelUserIds.has(p.id));

  return (
    <Modal open={open} onClose={onClose} title={`#${channel.name} members`}>
      <div className="flex flex-col gap-4">
        <div>
          <div className="font-medium text-sm" style={{ marginBottom: 6 }}>Agents</div>
          {(channelAgents ?? []).length === 0 ? (
            <p className="text-muted text-sm">No agents yet.</p>
          ) : (
            <div className="flex flex-col gap-1">
              {(channelAgents ?? []).map((a) => (
                <div key={a.id} className="flex items-center justify-between text-sm" style={{ padding: "4px 0" }}>
                  <span>{a.name}</span>
                  <Button size="sm" variant="secondary" onClick={() => onRemoveAgent?.(a.id, a.name)}>Remove</Button>
                </div>
              ))}
            </div>
          )}
          {addableAgents.length > 0 && (
            <div className="flex flex-col gap-1" style={{ marginTop: 8 }}>
              {addableAgents.map((a) => (
                <div key={a.id} className="flex items-center justify-between text-sm" style={{ padding: "4px 0" }}>
                  <span className="text-muted">{a.name}</span>
                  <Button size="sm" onClick={() => onAddAgent?.(a.id)}>Add</Button>
                </div>
              ))}
            </div>
          )}
        </div>

        <div>
          <div className="font-medium text-sm" style={{ marginBottom: 6 }}>People</div>
          {(channelUsers ?? []).length === 0 ? (
            <p className="text-muted text-sm">No one else here yet.</p>
          ) : (
            <div className="flex flex-col gap-1">
              {(channelUsers ?? []).map((u) => (
                <div key={u.id} className="flex items-center justify-between text-sm" style={{ padding: "4px 0" }}>
                  <span>{u.email}{u.id === currentUserId ? " (you)" : ""}</span>
                  <Button size="sm" variant="secondary" onClick={() => onRemovePerson?.(u.id)}>
                    {u.id === currentUserId ? "Leave" : "Remove"}
                  </Button>
                </div>
              ))}
            </div>
          )}
          {addablePeople.length > 0 && (
            <div className="flex flex-col gap-1" style={{ marginTop: 8 }}>
              {addablePeople.map((p) => (
                <div key={p.id} className="flex items-center justify-between text-sm" style={{ padding: "4px 0" }}>
                  <span className="text-muted">{p.email}</span>
                  <Button size="sm" onClick={() => onAddPerson?.(p.id)}>Add</Button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}
