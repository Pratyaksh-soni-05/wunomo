"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Card, Badge, Button, Modal, Input, Select, Table, Thead, Tbody, Tr, Th, Td, Skeleton, useToast,
} from "@/components/ui";
import {
  getToken, decodeUserFromToken,
  getTeamMembers, changeMemberRole, removeTeamMember,
  getTeamInvites, createTeamInvite, revokeTeamInvite,
  type TeamMember, type TeamInviteItem,
} from "@/lib/api";

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
  const [modalOpen, setModalOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("viewer");
  const [createdInvite, setCreatedInvite] = useState<(TeamInviteItem & { invite_link_token: string }) | null>(null);

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
          <h1 className="page-title">Team</h1>
          {canManage && <Button size="sm" onClick={() => setModalOpen(true)}>+ Invite Member</Button>}
        </div>
      </div>

      <div style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 24 }}>
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
                      <Td>{new Date(m.created_at).toLocaleDateString()}</Td>
                      {canManage && (
                        <Td>
                          {m.is_active && (
                            <Button
                              size="sm" variant="danger"
                              disabled={removeMut.isPending || !!removeReason}
                              title={removeReason ?? undefined}
                              onClick={() => removeMut.mutate(m.id)}
                            >
                              Remove
                            </Button>
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
                        <Td>{new Date(i.expires_at).toLocaleDateString()}</Td>
                        <Td>
                          {i.status === "pending" && (
                            <Button size="sm" variant="secondary" disabled={revokeMut.isPending} onClick={() => revokeMut.mutate(i.id)}>Revoke</Button>
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
