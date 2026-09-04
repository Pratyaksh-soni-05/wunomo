"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Button, Card, Modal, Input, Table, Thead, Tbody, Tr, Th, Td, Skeleton, useToast,
} from "@/components/ui";
import { formatApiDate } from "@/lib/dates";
import { getToken, listProjects, createProject } from "@/lib/api";

export default function ProjectsPage() {
  const token = getToken() as string;
  const router = useRouter();
  const toast = useToast();
  const qc = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [name, setName] = useState("");

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
    </div>
  );
}
