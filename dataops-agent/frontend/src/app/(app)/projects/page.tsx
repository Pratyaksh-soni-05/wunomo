"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Button, Card, Modal, Input, Table, Thead, Tbody, Tr, Th, Td, Skeleton, useToast, RowActionsMenu,
} from "@/components/ui";
import { formatApiDate } from "@/lib/dates";
import {
  getToken, listProjects, createProject, renameProject, deleteProject,
  getProjectAgents, getProjectChannels, ProjectItem,
} from "@/lib/api";

// Oxford-comma join for the delete-confirmation copy: ["Nova"] -> "Nova",
// ["Nova","Atlas"] -> "Nova and Atlas", ["Nova","Atlas","Orion"] -> "Nova, Atlas, and Orion".
function joinNames(names: string[]): string {
  if (names.length === 0) return "";
  if (names.length === 1) return names[0];
  if (names.length === 2) return `${names[0]} and ${names[1]}`;
  return `${names.slice(0, -1).join(", ")}, and ${names[names.length - 1]}`;
}

function DeleteProjectSurvivorsCopy({ token, projectId }: { token: string; projectId: string }) {
  const agents = useQuery({ queryKey: ["project-agents", projectId], queryFn: () => getProjectAgents(token, projectId) });
  const channels = useQuery({ queryKey: ["project-channels", projectId], queryFn: () => getProjectChannels(token, projectId) });

  if (agents.isLoading || channels.isLoading) {
    return <Skeleton style={{ height: 40, borderRadius: 8 }} />;
  }

  const agentNames = (agents.data?.agents ?? []).map((a) => a.name);
  const channelNames = (channels.data?.channels ?? []).map((c) => `#${c.name}`);

  const agentSentence = agentNames.length > 0
    ? `${joinNames(agentNames)} ${agentNames.length === 1 ? "stays" : "stay"} on your team and ${agentNames.length === 1 ? "becomes" : "become"} unassigned.`
    : null;
  const channelSentence = channelNames.length > 0
    ? `${joinNames(channelNames)} ${channelNames.length === 1 ? "stays" : "stay"}.`
    : null;

  if (!agentSentence && !channelSentence) {
    return <p className="text-sm text-muted">This project has no agents or channels — deleting it removes only the grouping.</p>;
  }

  return (
    <p className="text-sm">
      {agentSentence} {channelSentence}
    </p>
  );
}

export default function ProjectsPage() {
  const token = getToken() as string;
  const router = useRouter();
  const toast = useToast();
  const qc = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [name, setName] = useState("");
  const [renameTarget, setRenameTarget] = useState<ProjectItem | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<ProjectItem | null>(null);

  const projects = useQuery({ queryKey: ["projects"], queryFn: () => listProjects(token) });

  const createMut = useMutation({
    mutationFn: () => createProject(token, name),
    onSuccess: (p) => {
      toast.push(`Project "${p.name}" created.`, "success");
      setModalOpen(false);
      setName("");
      qc.invalidateQueries({ queryKey: ["projects"] });
      router.push(`/projects/${p.id}`);
    },
    onError: () => toast.push("Failed to create project.", "danger"),
  });

  const renameMut = useMutation({
    mutationFn: () => renameProject(token, renameTarget!.id, renameValue),
    onSuccess: (p) => {
      toast.push(`Renamed to "${p.name}".`, "success");
      setRenameTarget(null);
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
    onError: () => toast.push("Failed to rename project.", "danger"),
  });

  const deleteMut = useMutation({
    mutationFn: () => deleteProject(token, deleteTarget!.id),
    onSuccess: () => {
      toast.push(`"${deleteTarget?.name}" deleted.`, "default");
      setDeleteTarget(null);
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
    onError: () => toast.push("Failed to delete project.", "danger"),
  });

  const list = projects.data?.projects ?? [];

  return (
    <div>
      <div className="page-header">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="page-title">Projects</h1>
            <p className="text-muted text-sm" style={{ marginTop: 6 }}>
              A project groups the agents scoped to work on it — a single warehouse, a single
              ingestion pipeline, whatever boundary makes sense for your team.
            </p>
          </div>
          <Button size="sm" onClick={() => setModalOpen(true)}>+ New Project</Button>
        </div>
      </div>

      <div style={{ padding: "20px 24px" }}>
        {projects.isLoading ? (
          <Skeleton style={{ height: 200, borderRadius: 12 }} />
        ) : list.length === 0 ? (
          <div className="empty-state">
            <h2 className="font-display text-xl">No projects yet</h2>
            <p className="text-muted text-sm" style={{ maxWidth: 360 }}>
              Create a project, then hire the agents it needs and scope each one to the
              sources it should touch.
            </p>
            <Button size="sm" onClick={() => setModalOpen(true)}>+ New Project</Button>
          </div>
        ) : (
          <Card>
            <Table>
              <Thead>
                <Tr>
                  <Th>Name</Th>
                  <Th>Created</Th>
                  <Th></Th>
                </Tr>
              </Thead>
              <Tbody>
                {list.map((p) => (
                  <Tr key={p.id}>
                    <Td>
                      <button className="auth-link-btn" onClick={() => router.push(`/projects/${p.id}`)}>
                        {p.name}
                      </button>
                    </Td>
                    <Td className="text-muted text-sm">{formatApiDate(p.created_at)}</Td>
                    <Td style={{ textAlign: "right" }}>
                      <RowActionsMenu
                        actions={[
                          { label: "Rename", onClick: () => { setRenameTarget(p); setRenameValue(p.name); } },
                          { label: "Delete", onClick: () => setDeleteTarget(p) },
                        ]}
                      />
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          </Card>
        )}
      </div>

      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title="New Project"
        footer={
          <>
            <Button variant="secondary" onClick={() => setModalOpen(false)}>Cancel</Button>
            <Button disabled={!name.trim() || createMut.isPending} onClick={() => createMut.mutate()}>
              {createMut.isPending ? "Creating…" : "Create"}
            </Button>
          </>
        }
      >
        <Input
          id="project-name" label="Name" value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Q3 Revenue Migration"
          required
        />
      </Modal>

      <Modal
        open={renameTarget !== null}
        onClose={() => setRenameTarget(null)}
        title="Rename project"
        footer={
          <>
            <Button variant="secondary" onClick={() => setRenameTarget(null)}>Cancel</Button>
            <Button
              disabled={!renameValue.trim() || renameValue.trim() === renameTarget?.name || renameMut.isPending}
              onClick={() => renameMut.mutate()}
            >
              {renameMut.isPending ? "Renaming…" : "Rename"}
            </Button>
          </>
        }
      >
        <Input
          id="project-rename" label="Name" value={renameValue}
          onChange={(e) => setRenameValue(e.target.value)}
          required
        />
      </Modal>

      <Modal
        open={deleteTarget !== null}
        onClose={() => setDeleteTarget(null)}
        title="Delete this project?"
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeleteTarget(null)}>Cancel</Button>
            <Button variant="danger" disabled={deleteMut.isPending} onClick={() => deleteMut.mutate()}>
              {deleteMut.isPending ? "Deleting…" : "Delete"}
            </Button>
          </>
        }
      >
        {deleteTarget && (
          <div className="flex flex-col gap-2">
            <p className="text-sm">
              This removes the <strong>{deleteTarget.name}</strong> grouping. This can&apos;t be undone.
            </p>
            <DeleteProjectSurvivorsCopy token={token} projectId={deleteTarget.id} />
          </div>
        )}
      </Modal>
    </div>
  );
}
