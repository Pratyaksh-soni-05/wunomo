"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Card, Badge, Button, Modal, Input, Select, Tabs,
  Table, Thead, Tbody, Tr, Th, Td, Skeleton, useToast,
} from "@/components/ui";
import { formatApiDate } from "@/lib/dates";
import {
  getToken, getContracts, createContract, validateContract, getAuditTrail, getSources,
  type DataContract, type AuditEntry,
} from "@/lib/api";

function validationVariant(status: string): "success" | "danger" | "warning" | "gray" {
  switch (status) {
    case "valid": return "success";
    case "violated": return "danger";
    case "pending": return "warning";
    default: return "gray";
  }
}

export default function GovernancePage() {
  const token = getToken() as string;
  const router = useRouter();
  const toast = useToast();
  const qc = useQueryClient();
  // Lineage is no longer this page's own content (see the tab below) --
  // Contracts is the real default now, not Lineage.
  const [tab, setTab] = useState("contracts");
  const [modalOpen, setModalOpen] = useState(false);
  const [name, setName] = useState("");
  const [producerSourceId, setProducerSourceId] = useState("");
  const [consumerDescription, setConsumerDescription] = useState("");

  const contracts = useQuery({ queryKey: ["contracts"], queryFn: () => getContracts(token) });
  const audit = useQuery({ queryKey: ["audit-trail"], queryFn: () => getAuditTrail(token) });
  const sources = useQuery({ queryKey: ["sources"], queryFn: () => getSources(token) });

  const validateMut = useMutation({
    mutationFn: (id: string) => validateContract(token, id),
    onSuccess: () => {
      toast.push("Contract validated.", "success");
      qc.invalidateQueries({ queryKey: ["contracts"] });
      qc.invalidateQueries({ queryKey: ["audit-trail"] });
    },
    onError: () => toast.push("Validation failed.", "danger"),
  });

  const createContractMut = useMutation({
    mutationFn: () => createContract(token, {
      name, producer_source_id: producerSourceId, consumer_description: consumerDescription || undefined,
    }),
    onSuccess: () => {
      toast.push(`Contract "${name}" created.`, "success");
      setModalOpen(false);
      setName(""); setProducerSourceId(""); setConsumerDescription("");
      qc.invalidateQueries({ queryKey: ["contracts"] });
      qc.invalidateQueries({ queryKey: ["audit-trail"] });
    },
    onError: () => toast.push("Failed to create contract.", "danger"),
  });

  const contractList = contracts.data?.contracts ?? [];
  const auditList = audit.data?.entries ?? [];
  const sourceList = sources.data?.sources ?? [];

  return (
    <div>
      <div className="page-header">
        <div className="flex items-center justify-between">
          <h1 className="page-title">Governance</h1>
          {tab === "contracts" && (
            <Button size="sm" onClick={() => setModalOpen(true)} disabled={sourceList.length === 0}>+ New Contract</Button>
          )}
        </div>
      </div>

      <div style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 16 }}>
        <Tabs
          items={[
            { id: "lineage", label: "Lineage" },
            { id: "contracts", label: "Contracts" },
            { id: "audit", label: "Audit Log" },
          ]}
          activeId={tab}
          onChange={setTab}
        />

        {tab === "lineage" && (
          // Not removed outright (slice 6a, 2026-09-14) -- a vanished tab
          // is a silent gap, an inert one that says where it went isn't.
          // The real Lineage view now lives inside each project's
          // Workbench, per-project by construction (Option B); this page
          // is tenant-wide, so it was never going to be the real home for
          // a per-project view anyway.
          <div className="empty-state">
            <h2 className="font-display text-xl">Lineage has moved</h2>
            <p className="text-muted text-sm" style={{ maxWidth: 400 }}>
              Lineage is now scoped to each project — open a project and go to its Workbench tab to
              see it there.
            </p>
            <Button size="sm" onClick={() => router.push("/projects")}>Go to Projects</Button>
          </div>
        )}

        {tab === "contracts" && (
          contracts.isLoading ? (
            <Skeleton style={{ height: 200, borderRadius: 12 }} />
          ) : contractList.length === 0 ? (
            <div className="empty-state">
              <h2 className="font-display text-xl">No data contracts yet</h2>
              <p className="text-muted text-sm" style={{ maxWidth: 380 }}>
                {sourceList.length === 0
                  ? "Add a source first, then define a contract against it."
                  : "Define expectations for a source's schema and quality, then validate them anytime."}
              </p>
              {sourceList.length > 0 && <Button size="sm" onClick={() => setModalOpen(true)}>+ New Contract</Button>}
            </div>
          ) : (
            <Card>
              <Table>
                <Thead>
                  <Tr><Th>Name</Th><Th>Description</Th><Th>Status</Th><Th>Last Validated</Th><Th>Actions</Th></Tr>
                </Thead>
                <Tbody>
                  {contractList.map((c: DataContract) => (
                    <Tr key={c.contract_id}>
                      <Td>{c.name}</Td>
                      <Td>{c.consumer_description || "—"}</Td>
                      <Td><Badge variant={validationVariant(c.validation_status)}>{c.validation_status}</Badge></Td>
                      <Td>{formatApiDate(c.last_validated_at, "Never")}</Td>
                      <Td>
                        <div className="row-actions">
                          <Button
                            variant="ghost" icon title="Validate" aria-label={`Validate ${c.name}`}
                            disabled={validateMut.isPending} onClick={() => validateMut.mutate(c.contract_id)}
                          >
                            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                              <polyline points="20 6 9 17 4 12" />
                            </svg>
                          </Button>
                        </div>
                      </Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            </Card>
          )
        )}

        {tab === "audit" && (
          audit.isLoading ? (
            <Skeleton style={{ height: 200, borderRadius: 12 }} />
          ) : auditList.length === 0 ? (
            <div className="empty-state">
              <h2 className="font-display text-xl">No audit events yet</h2>
              <p className="text-muted text-sm" style={{ maxWidth: 380 }}>
                Every governance and approval action taken in this workspace is logged here.
              </p>
            </div>
          ) : (
            <Card>
              <Table>
                <Thead>
                  <Tr><Th>Actor</Th><Th>Action</Th><Th>Resource</Th><Th>When</Th></Tr>
                </Thead>
                <Tbody>
                  {auditList.map((e: AuditEntry, i: number) => (
                    <Tr key={i}>
                      <Td>{e.actor}</Td>
                      <Td><code>{e.action}</code></Td>
                      <Td>{e.resource_type}{e.resource_id ? ` · ${e.resource_id.slice(0, 8)}` : ""}</Td>
                      <Td>{formatApiDate(e.created_at)}</Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            </Card>
          )
        )}
      </div>

      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title="New Data Contract"
        footer={
          <>
            <Button variant="secondary" onClick={() => setModalOpen(false)}>Cancel</Button>
            <Button disabled={!name || !producerSourceId || createContractMut.isPending} onClick={() => createContractMut.mutate()}>
              {createContractMut.isPending ? "Creating..." : "Create"}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <Input id="contract-name" label="Name" value={name} onChange={(e) => setName(e.target.value)} required />
          <Select id="contract-source" label="Producer source" value={producerSourceId} onChange={(e) => setProducerSourceId(e.target.value)} required>
            <option value="">Select a source</option>
            {sourceList.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </Select>
          <Input
            id="contract-desc" label="Consumer description"
            value={consumerDescription} onChange={(e) => setConsumerDescription(e.target.value)}
          />
        </div>
      </Modal>
    </div>
  );
}
