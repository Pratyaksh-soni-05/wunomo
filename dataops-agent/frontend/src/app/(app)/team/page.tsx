"use client";

import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Card, Badge, Button, Modal, Input, Select, Tabs, Progress,
  Table, Thead, Tbody, Tr, Th, Td, Skeleton, useToast, RowActionsMenu,
} from "@/components/ui";
import { formatApiDateOnly } from "@/lib/dates";
import {
  getToken, decodeUserFromToken,
  getTeamMembers, changeMemberRole, removeTeamMember,
  getTeamInvites, createTeamInvite, revokeTeamInvite,
  getUsage, getCurrentPlan,
  type TeamMember, type TeamInviteItem, type QuotaStatus,
} from "@/lib/api";

const PAGE_TABS = [
  { id: "team", label: "Team" },
  { id: "billing", label: "Billing" },
];
const PAGE_TAB_IDS = new Set(PAGE_TABS.map((t) => t.id));

// Kept in sync manually with backend/services/rbac.py's Role/ALL_ROLES - a
// genuinely locked, rarely-changing set (unlike the AI Model allowlist),
// so hardcoding here doesn't carry the same drift risk.
const ROLE_OPTIONS = [
  { value: "owner", label: "Owner" },
  { value: "admin", label: "Admin" },
  { value: "data_engineer", label: "Data Engineer" },
  { value: "data_analyst", label: "Data Analyst" },
  { value: "viewer", label: "Viewer" },
];

function roleLabel(role: string) {
  return ROLE_OPTIONS.find((r) => r.value === role)?.label ?? role;
}

function inviteStatusVariant(status: string): "success" | "danger" | "warning" | "gray" {
  switch (status) {
    case "accepted": return "success";
    case "revoked": return "danger";
    case "pending": return "warning";
    default: return "gray";
  }
}

export default function TeamPage() {
  const token = getToken() as string;
  const user = decodeUserFromToken(token);
  const canManage = user?.role === "owner" || user?.role === "admin";
  const toast = useToast();
  const qc = useQueryClient();
  const [pageTab, setPageTab] = useState("team");
  const [modalOpen, setModalOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("viewer");
  const [createdInvite, setCreatedInvite] = useState<(TeamInviteItem & { invite_link_token: string }) | null>(null);

  // Billing merged into this page (slice 12, 2026-09-15) -- ?tab=billing
  // is the real deep link the quota-exceeded toast (chat, TaskCreateModal)
  // now points at, so that landing has to work, not just look right by
  // default. Same window.location.search pattern as Settings' own
  // ?tab= reader -- see that file's comment for why not useSearchParams().
  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("tab");
    if (requested && PAGE_TAB_IDS.has(requested)) setPageTab(requested);
  }, []);

  const members = useQuery({ queryKey: ["team-members"], queryFn: () => getTeamMembers(token) });
  const invites = useQuery({ queryKey: ["team-invites"], queryFn: () => getTeamInvites(token), enabled: canManage });

  const memberList = members.data?.members ?? [];
  const inviteList = invites.data?.invites ?? [];
  const activeOwnerCount = memberList.filter((m) => m.role === "owner" && m.is_active).length;

  const invalidateMembers = () => qc.invalidateQueries({ queryKey: ["team-members"] });
  const invalidateInvites = () => qc.invalidateQueries({ queryKey: ["team-invites"] });

  const roleMut = useMutation({
    mutationFn: ({ id, role }: { id: string; role: string }) => changeMemberRole(token, id, role),
    onSuccess: () => { toast.push("Role updated.", "success"); invalidateMembers(); },
    onError: (e: unknown) => toast.push(e instanceof Error ? e.message : "Failed to update role.", "danger"),
  });

  const removeMut = useMutation({
    mutationFn: (id: string) => removeTeamMember(token, id),
    onSuccess: () => { toast.push("Member removed.", "default"); invalidateMembers(); },
    onError: (e: unknown) => toast.push(e instanceof Error ? e.message : "Failed to remove member.", "danger"),
  });

  const inviteMut = useMutation({
    mutationFn: () => createTeamInvite(token, { email: inviteEmail, role: inviteRole }),
    onSuccess: (result) => {
      setCreatedInvite(result);
      setInviteEmail("");
      invalidateInvites();
    },
    onError: (e: unknown) => toast.push(e instanceof Error ? e.message : "Failed to create invite.", "danger"),
  });

  const revokeMut = useMutation({
    mutationFn: (id: string) => revokeTeamInvite(token, id),
    onSuccess: () => { toast.push("Invite revoked.", "default"); invalidateInvites(); },
    onError: () => toast.push("Failed to revoke invite.", "danger"),
  });

  // Mirrors the backend's own guards (change_member_role/remove_team_member,
  // api/v1/team.py) so a blocked action reads as blocked-with-a-reason
  // instead of a plain disabled control - never invents a stricter rule
  // than the backend actually enforces.
  function removeDisabledReason(m: TeamMember): string | null {
    if (m.id === user?.sub) return "You can't remove yourself";
    if (m.role === "owner" && user?.role !== "owner") return "Only an owner can remove an owner";
    if (m.role === "owner" && activeOwnerCount <= 1) return "Cannot remove the last owner";
    return null;
  }

  function roleChangeDisabledReason(m: TeamMember): string | null {
    if (m.role === "owner" && user?.role !== "owner") return "Only an owner can change an owner's role";
    if (m.role === "owner" && activeOwnerCount <= 1) return "Cannot demote the last owner";
    return null;
  }

  return (
    <div>
      <div className="page-header">
        <div className="flex items-center justify-between">
          <h1 className="page-title">Team &amp; Billing</h1>
          {pageTab === "team" && canManage && <Button size="sm" onClick={() => setModalOpen(true)}>+ Invite Member</Button>}
        </div>
      </div>

      <div style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 20 }}>
        <Tabs items={PAGE_TABS} activeId={pageTab} onChange={setPageTab} />
      </div>

      {pageTab === "billing" && (
        <div style={{ padding: "0 24px 20px" }}>
          <BillingTab token={token} />
        </div>
      )}

      {pageTab === "team" && (
      <div style={{ padding: "0 24px 20px", display: "flex", flexDirection: "column", gap: 24 }}>
        {members.isLoading ? (
          <Skeleton style={{ height: 200, borderRadius: 12 }} />
        ) : (
          <Card>
            <div className="card-header text-sm text-muted">Members ({memberList.length})</div>
            <Table>
              <Thead>
                <Tr>
                  <Th>Name</Th><Th>Email</Th><Th>Role</Th><Th>Status</Th><Th>Joined</Th>
                  {canManage && <Th>Actions</Th>}
                </Tr>
              </Thead>
              <Tbody>
                {memberList.map((m) => {
                  const removeReason = removeDisabledReason(m);
                  const roleReason = roleChangeDisabledReason(m);
                  return (
                    <Tr key={m.id}>
                      <Td>{m.full_name || "—"}{m.id === user?.sub && <span className="text-muted text-sm"> (you)</span>}</Td>
                      <Td>{m.email}</Td>
                      <Td>
                        {canManage ? (
                          <Select
                            value={m.role}
                            disabled={roleMut.isPending || !!roleReason}
                            title={roleReason ?? undefined}
                            onChange={(e) => roleMut.mutate({ id: m.id, role: e.target.value })}
                          >
                            {ROLE_OPTIONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                          </Select>
                        ) : (
                          <Badge variant="gray">{roleLabel(m.role)}</Badge>
                        )}
                      </Td>
                      <Td>{m.is_active ? <Badge variant="success">Active</Badge> : <Badge variant="gray">Removed</Badge>}</Td>
                      <Td>{formatApiDateOnly(m.created_at)}</Td>
                      {canManage && (
                        <Td>
                          {m.is_active && (
                            <div className="row-actions">
                              <RowActionsMenu
                                actions={[
                                  {
                                    label: "Remove",
                                    disabled: removeMut.isPending || !!removeReason,
                                    title: removeReason ?? undefined,
                                    onClick: () => removeMut.mutate(m.id),
                                  },
                                ]}
                              />
                            </div>
                          )}
                        </Td>
                      )}
                    </Tr>
                  );
                })}
              </Tbody>
            </Table>
          </Card>
        )}

        {canManage && (
          invites.isLoading ? (
            <Skeleton style={{ height: 160, borderRadius: 12 }} />
          ) : (
            <Card>
              <div className="card-header text-sm text-muted">Pending Invites ({inviteList.filter((i) => i.status === "pending").length})</div>
              {inviteList.length === 0 ? (
                <div className="card-body text-muted text-sm">No invites yet.</div>
              ) : (
                <Table>
                  <Thead><Tr><Th>Email</Th><Th>Role</Th><Th>Status</Th><Th>Expires</Th><Th>Actions</Th></Tr></Thead>
                  <Tbody>
                    {inviteList.map((i) => (
                      <Tr key={i.id}>
                        <Td>{i.email}</Td>
                        <Td>{roleLabel(i.role)}</Td>
                        <Td><Badge variant={inviteStatusVariant(i.status)}>{i.status}</Badge></Td>
                        <Td>{formatApiDateOnly(i.expires_at)}</Td>
                        <Td>
                          {i.status === "pending" && (
                            <div className="row-actions">
                              <RowActionsMenu
                                actions={[
                                  { label: "Revoke", disabled: revokeMut.isPending, onClick: () => revokeMut.mutate(i.id) },
                                ]}
                              />
                            </div>
                          )}
                        </Td>
                      </Tr>
                    ))}
                  </Tbody>
                </Table>
              )}
            </Card>
          )
        )}
      </div>
      )}

      <Modal open={modalOpen} onClose={() => { setModalOpen(false); setCreatedInvite(null); }} title="Invite a team member" size="sm">
        {createdInvite ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <p className="text-sm">
              Invite created for <strong>{createdInvite.email}</strong>. Resend&apos;s sandbox can only deliver to
              this workspace owner&apos;s own verified address today — if that&apos;s not who you invited, share this
              link manually instead:
            </p>
            <code className="code-block" style={{ display: "block", wordBreak: "break-all" }}>
              {typeof window !== "undefined" ? `${window.location.origin}/invite/accept?token=${createdInvite.invite_link_token}` : createdInvite.invite_link_token}
            </code>
            <Button size="sm" variant="secondary" onClick={() => { setModalOpen(false); setCreatedInvite(null); }}>Done</Button>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <Input label="Email" type="email" value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} placeholder="teammate@example.com" />
            <Select label="Role" value={inviteRole} onChange={(e) => setInviteRole(e.target.value)}>
              {ROLE_OPTIONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
            </Select>
            <Button size="sm" disabled={inviteMut.isPending || !inviteEmail.trim()} onClick={() => inviteMut.mutate()}>
              {inviteMut.isPending ? "Sending…" : "Send Invite"}
            </Button>
          </div>
        )}
      </Modal>
    </div>
  );
}

// ---------- Billing (moved from the retired /billing page, slice 12) ----------

const RESOURCE_LABELS: Record<string, string> = {
  ai_credits: "AI Credits",
  pipeline_runs: "Pipeline Runs",
  data_sources: "Data Sources",
  team_members: "Team Members",
};

function progressVariant(status: QuotaStatus["status"]): "default" | "success" | "warning" | "danger" {
  if (status === "exceeded") return "danger";
  if (status === "warning") return "warning";
  return "success";
}

function planLabel(name: string) {
  return name.charAt(0).toUpperCase() + name.slice(1);
}

function BillingTab({ token }: { token: string }) {
  const usage = useQuery({ queryKey: ["billing-usage"], queryFn: () => getUsage(token) });
  const plan = useQuery({ queryKey: ["billing-plan"], queryFn: () => getCurrentPlan(token) });

  const usageEntries = Object.entries(usage.data?.usage ?? {}) as [string, QuotaStatus][];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20, maxWidth: 640 }}>
      {plan.isLoading ? (
        <Skeleton style={{ height: 100, borderRadius: 12 }} />
      ) : (
        <Card>
          <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div>
              <div className="text-muted text-sm">Current plan</div>
              <div className="font-display text-xl">{plan.data ? planLabel(plan.data.plan) : "—"}</div>
            </div>
            <p className="text-muted text-sm">
              Plan changes are handled manually by the AXIOM team for now — self-serve upgrades are
              disabled until Stripe billing is live. Contact us if you&apos;d like to change your plan.
            </p>
          </div>
        </Card>
      )}

      {usage.isLoading ? (
        <Skeleton style={{ height: 220, borderRadius: 12 }} />
      ) : (
        <Card>
          <div className="card-header text-sm text-muted">Usage this month</div>
          <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 18 }}>
            {usageEntries.map(([key, q]) => (
              <div key={key}>
                <div className="flex items-center justify-between text-sm" style={{ marginBottom: 6 }}>
                  <span>{RESOURCE_LABELS[key] ?? key}</span>
                  <span className="text-muted">
                    {q.used.toLocaleString()} {q.limit === null ? "· Unlimited" : `/ ${q.limit.toLocaleString()}`}
                  </span>
                </div>
                <Progress value={q.limit === null ? 0 : q.percent} variant={progressVariant(q.status)} />
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card>
        <div className="card-body">
          <div className="font-display" style={{ marginBottom: 4 }}>Checkout &amp; invoices</div>
          <p className="text-muted text-sm">Coming soon — Stripe billing isn&apos;t wired up yet.</p>
        </div>
      </Card>
    </div>
  );
}
