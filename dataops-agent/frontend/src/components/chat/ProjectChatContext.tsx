"use client";

// Header-merge pass (item 1): the project container's own header (breadcrumb
// + name + Hire) and §7.2's ProjectHeader used to be two separate rows,
// rendered by two separate components (layout.tsx and the chat page) with
// no shared state -- the chat page owned channel selection, the roster
// query, personality/operation mode, entirely locally. Merging into one row
// meant one of the two owners had to give up that state, and it had to be
// the page: layout.tsx wraps all four project tabs (Chat/Workbench/Tasks/
// Agents) and is the one that persists across navigating between them, so
// it's the natural owner of "which channel is active" -- as a bonus, that
// also means the active channel now survives switching to Workbench and
// back, which it didn't before (the chat page fully unmounted on tab
// change, losing the selection).
//
// This context is how layout.tsx (the provider, in the real React sense --
// data flows down from parent to child, never the other way) hands that
// state to the chat page (the consumer) without either owning a copy the
// other could drift from.
import { createContext, useContext } from "react";
import type {
  ChannelItem, ChannelMemberAgent, ChannelMemberUser, ProjectAgentItem, SelectableAgent, TeamMember,
} from "@/lib/api";

export interface ProjectChatContextValue {
  activeSessionId: string | null;
  setActiveSessionId: (id: string | null) => void;
  channels: ChannelItem[];
  channelsLoading: boolean;
  activeChannel: ChannelItem | null;
  channelAgents: ChannelMemberAgent[];
  channelUsers: ChannelMemberUser[];
  agentRoster: ProjectAgentItem[];
  agentRosterLoading: boolean;
  selectableAgents: SelectableAgent[];
  availablePeople: TeamMember[];
  currentUserId: string | null;
  createChannelWithAgents: (name: string, agentIds: string[]) => Promise<void>;
  addAgentToActiveChannel: (agentId: string) => Promise<void>;
  removeAgentFromActiveChannel: (agentId: string, agentName: string) => Promise<void>;
  addPersonToActiveChannel: (userId: string) => Promise<void>;
  removePersonFromActiveChannel: (userId: string) => Promise<void>;
  personalityMode: string;
  operationMode: string;
  setPersonalityMode: (v: string) => void;
  setOperationMode: (v: string) => void;
  liveWorkOpen: boolean;
  setLiveWorkOpen: (v: boolean | ((prev: boolean) => boolean)) => void;
  sessionActiveTaskCount: number;
}

export const ProjectChatContext = createContext<ProjectChatContextValue | null>(null);

// Thrown, not defaulted -- every current consumer (the chat page) only ever
// renders inside layout.tsx's provider. A silent default would hide a real
// wiring mistake behind empty arrays and no-op callbacks instead of a clear
// error at the exact place it happened.
export function useProjectChatContext(): ProjectChatContextValue {
  const ctx = useContext(ProjectChatContext);
  if (!ctx) throw new Error("useProjectChatContext must be used inside the project container layout.");
  return ctx;
}
