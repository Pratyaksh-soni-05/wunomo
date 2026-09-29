"use client";

// §7.2 Project header -- now the project container's ONLY header (item 1,
// header-merge pass). It used to be a second, standalone bar rendered by
// the chat page below the container's own "← All Projects / {name} /
// [Hire agent]" row -- two headers, ~180px of chrome before any message,
// the biggest visual divergence from the blueprint's single header. This
// component now renders the breadcrumb itself and is rendered directly by
// layout.tsx, inside the same row the tab bar sits under -- there is no
// second bar anywhere in the project container anymore.
//
// Rendered on all four tabs (Chat/Workbench/Tasks/Agents), not just Chat:
// project name, task count, roster and progress are project-level facts,
// true regardless of which tab is open, and layout.tsx (which now owns the
// channel/roster/mode state via ProjectChatContext) persists across tab
// switches -- so the "⋯" menu's channel switcher, member management, and
// personality/operation mode all work identically from every tab, not just
// Chat. Selecting a channel from a non-Chat tab navigates to Chat, since
// that's the only place a channel's thread actually renders.
//
// Owns its own "+ Hire" modal (same pattern LiveWorkPanel's Team tab
// already uses). Personality/operation mode are PER-EMPLOYEE settings today
// (AgentInstance.personality_mode/operation_mode), not per-channel -- this
// menu still edits them channel-wide for now (no per-employee settings UI
// exists yet to move them to), but they belong on the employee profile page
// once one exists, not here permanently.
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Modal, Input, Select, Progress } from "@/components/ui";
import { EmployeeAvatar } from "./EmployeeAvatar";
import { ChannelMembersModal } from "./ChannelMembersModal";
import { HireAgentModal } from "@/components/agents/HireAgentModal";
import type {
  ChannelItem, ChannelMemberAgent, ChannelMemberUser, ProjectAgentItem, SelectableAgent, TeamMember,
} from "@/lib/api";

type BadgeVariant = "success" | "danger" | "warning" | "info" | "hold" | "gray" | "midnight";

const PERSONALITY_OPTIONS = ["engineer", "founder", "analyst", "auditor"] as const;
const OPERATION_OPTIONS = ["advisory", "assisted", "autonomous", "audit"] as const;

export function ProjectHeader({
  token,
  projectId,
  projectName,
  projectDescription,
  tasksDone,
  tasksTotal,
  statusBadge,
  agentRoster,
  availableAgents,
  channels,
  activeChannel,
  onSelectChannel,
  onCreateChannel,
  channelAgents,
  channelUsers,
  availablePeople,
  currentUserId,
  onAddAgent,
  onRemoveAgent,
  onAddPerson,
  onRemovePerson,
  personalityMode,
  operationMode,
  onPersonalityChange,
  onOperationChange,
  liveWorkToggle,
}: {
  token: string;
  projectId: string;
  projectName: string;
  projectDescription: string | null;
  tasksDone: number;
  tasksTotal: number;
  statusBadge: { variant: BadgeVariant; label: string };
  agentRoster: ProjectAgentItem[];
  availableAgents: SelectableAgent[];
  channels: ChannelItem[];
  activeChannel: ChannelItem | null;
  onSelectChannel: (id: string) => void;
  onCreateChannel: (name: string, agentIds: string[]) => void;
  channelAgents?: ChannelMemberAgent[];
  channelUsers?: ChannelMemberUser[];
  availablePeople?: TeamMember[];
  currentUserId?: string | null;
  onAddAgent?: (agentId: string) => void;
  onRemoveAgent?: (agentId: string, agentName: string) => void;
  onAddPerson?: (userId: string) => void;
  onRemovePerson?: (userId: string) => void;
  personalityMode: string;
  operationMode: string;
  onPersonalityChange: (v: string) => void;
  onOperationChange: (v: string) => void;
  // §7.1 Responsive: "Below 1180px the live panel collapses to a toggle in
  // the header." MessageThread's own internal header carries this same
  // toggle for /chat (unchanged) -- this is the project route's equivalent,
  // needed here specifically because hideHeader hides that one. Same prop
  // shape, same .livework-toggle CSS (only visible under 1180px). Found
  // missing live, during this pass's own screenshot-verification loop at a
  // narrow viewport: hiding MessageThread's header also hid the only
  // control that could reopen a collapsed live-work panel.
  liveWorkToggle?: { count: number; open: boolean; onToggle: () => void };
}) {
  const qc = useQueryClient();
  const router = useRouter();
  const pathname = usePathname();
  const isOnChatTab = pathname.endsWith("/chat");
  const [hireOpen, setHireOpen] = useState(false);
  const [membersOpen, setMembersOpen] = useState(false);
  const [newChannelOpen, setNewChannelOpen] = useState(false);
  const [newChannelName, setNewChannelName] = useState("");
  const [newChannelAgentIds, setNewChannelAgentIds] = useState<string[]>([]);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    const t = setTimeout(() => document.addEventListener("click", onClick), 0);
    return () => { clearTimeout(t); document.removeEventListener("click", onClick); };
  }, [menuOpen]);

  const progressPct = tasksTotal > 0 ? Math.round((tasksDone / tasksTotal) * 100) : 0;
  const subline = [
    tasksTotal > 0 ? `${tasksDone} of ${tasksTotal} tasks done` : "No tasks yet",
    projectDescription,
  ].filter(Boolean).join(" · ");

  const resetNewChannel = () => {
    setNewChannelOpen(false);
    setNewChannelName("");
    setNewChannelAgentIds([]);
  };
  const toggleNewChannelAgent = (id: string) => {
    setNewChannelAgentIds((prev) => (prev.includes(id) ? prev.filter((a) => a !== id) : [...prev, id]));
  };

  return (
    <div className="project-header">
      <div className="project-header-identity">
        <Link href="/projects" className="btn btn-text text-sm project-header-breadcrumb">← All Projects</Link>
        <div className="project-header-name-row">
          <span className="project-header-name">{projectName}</span>
          <Badge variant={statusBadge.variant}>{statusBadge.label}</Badge>
        </div>
        <div className="project-header-subline">{subline}</div>
      </div>

      <div className="project-header-roster">
        <div className="project-header-avatars">
          {agentRoster.slice(0, 6).map((a) => (
            <EmployeeAvatar key={a.id} name={a.name} employeeType={a.employee_type} size="sm" />
          ))}
        </div>
        <button type="button" className="btn btn-secondary btn-dense" onClick={() => setHireOpen(true)}>
          + Hire
        </button>
      </div>

      <div className="project-header-right">
        {liveWorkToggle && (
          <button
            type="button"
            className="btn btn-secondary btn-dense livework-toggle"
            onClick={liveWorkToggle.onToggle}
            aria-expanded={liveWorkToggle.open}
          >
            Live work
            {liveWorkToggle.count > 0 && <Badge variant="info">{liveWorkToggle.count}</Badge>}
          </button>
        )}
        <div className="project-header-progress" title={`${progressPct}% of this project's tasks done`}>
          <Progress value={progressPct} className="thin" />
        </div>
        <div className="project-header-menu" ref={menuRef}>
          <button
            type="button"
            className="btn btn-secondary btn-icon btn-dense"
            aria-label="More project options"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((v) => !v)}
          >
            ⋯
          </button>
          {menuOpen && (
            <div className="project-header-dropdown" role="menu">
              <div className="project-header-dropdown-label">Channels</div>
              {channels.length === 0 ? (
                <div className="project-header-dropdown-empty">No channels yet.</div>
              ) : (
                channels.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    role="menuitemradio"
                    aria-checked={c.id === activeChannel?.id}
                    className={["project-header-dropdown-item", c.id === activeChannel?.id ? "active" : ""].filter(Boolean).join(" ")}
                    onClick={() => {
                      onSelectChannel(c.id);
                      setMenuOpen(false);
                      // A channel's thread only ever renders on the Chat
                      // tab -- selecting one from Workbench/Tasks/Agents
                      // still sets it active (context state, shared across
                      // all four tabs), but also has to take you where you
                      // can actually see it.
                      if (!isOnChatTab) router.push(`/projects/${projectId}/chat`);
                    }}
                  >
                    # {c.name}
                  </button>
                ))
              )}
              <button
                type="button"
                className="project-header-dropdown-item"
                onClick={() => { setMenuOpen(false); setNewChannelOpen(true); }}
              >
                + New channel
              </button>

              {activeChannel && (
                <>
                  <div className="project-header-dropdown-sep" />
                  <button
                    type="button"
                    className="project-header-dropdown-item"
                    onClick={() => { setMenuOpen(false); setMembersOpen(true); }}
                  >
                    Manage members
                  </button>
                </>
              )}

              {/* Per-employee settings, not per-channel (AgentInstance.
                  personality_mode/operation_mode) -- tucked in here for now
                  since there's no employee-profile settings UI yet to move
                  them to. Still edits channel-wide, same as before this
                  pass; the real fix is a per-agent settings surface, not a
                  frontend-only relabel. */}
              <div className="project-header-dropdown-sep" />
              <div className="project-header-dropdown-label">Personality &amp; operation mode</div>
              <div className="project-header-dropdown-selects">
                <Select
                  aria-label="Personality mode"
                  value={personalityMode}
                  onChange={(e) => onPersonalityChange(e.target.value)}
                >
                  {PERSONALITY_OPTIONS.map((o) => <option key={o} value={o}>{o[0].toUpperCase() + o.slice(1)}</option>)}
                </Select>
                <Select
                  aria-label="Operation mode"
                  value={operationMode}
                  onChange={(e) => onOperationChange(e.target.value)}
                >
                  {OPERATION_OPTIONS.map((o) => <option key={o} value={o}>{o[0].toUpperCase() + o.slice(1)}</option>)}
                </Select>
              </div>
            </div>
          )}
        </div>
      </div>

      <HireAgentModal
        token={token}
        open={hireOpen}
        onClose={() => setHireOpen(false)}
        initialProjectId={projectId}
        onHired={() => qc.invalidateQueries({ queryKey: ["project-agents", projectId] })}
      />

      {activeChannel && (
        <ChannelMembersModal
          open={membersOpen}
          onClose={() => setMembersOpen(false)}
          channel={activeChannel}
          channelAgents={channelAgents}
          channelUsers={channelUsers}
          availableAgents={availableAgents}
          availablePeople={availablePeople}
          currentUserId={currentUserId}
          onAddAgent={onAddAgent}
          onRemoveAgent={onRemoveAgent}
          onAddPerson={onAddPerson}
          onRemovePerson={onRemovePerson}
        />
      )}

      <Modal
        open={newChannelOpen}
        onClose={resetNewChannel}
        title="New Channel"
        footer={
          <>
            <Button variant="secondary" onClick={resetNewChannel}>Cancel</Button>
            <Button
              disabled={!newChannelName.trim() || newChannelAgentIds.length === 0}
              onClick={() => { onCreateChannel(newChannelName.trim(), newChannelAgentIds); resetNewChannel(); }}
            >
              Create
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <Input
            id="new-channel-name" label="Name" value={newChannelName}
            onChange={(e) => setNewChannelName(e.target.value)}
            placeholder="e.g. pipeline-incidents"
            required
          />
          <div className="input-group">
            <label className="input-label">Agents (at least one required)</label>
            {agentRoster.length === 0 ? (
              <p className="text-muted text-sm">No active agents to add yet — hire one first.</p>
            ) : (
              <div className="flex flex-col gap-2">
                {agentRoster.map((a) => (
                  <label key={a.id} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={newChannelAgentIds.includes(a.id)}
                      onChange={() => toggleNewChannelAgent(a.id)}
                    />
                    {a.name}
                  </label>
                ))}
              </div>
            )}
          </div>
        </div>
      </Modal>
    </div>
  );
}
