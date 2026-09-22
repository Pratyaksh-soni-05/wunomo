"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Card, Badge, Button, Modal, Input, Select, Table, Thead, Tbody, Tr, Th, Td, Skeleton, useToast,
} from "@/components/ui";
import { formatApiDate } from "@/lib/dates";
import { useProjectScope } from "@/lib/projectScope";
import { NoSourcesGrantedEmptyState } from "@/components/workbench/WorkbenchEmptyStates";
import {
  getToken, getContracts, createContract, validateContract, getSources,
  type DataContract,
} from "@/lib/api";

function validationVariant(status: string): "success" | "danger" | "warning" | "gray" {
  switch (status) {
    case "valid": return "success";
    case "violated": return "danger";
    case "pending": return "warning";
    default: return "gray";
  }
}

// Filtered copy of /governance's old Contracts tab (Wunomo UI-rebuild
// slice 12, 2026-09-15) -- moved into Workbench, source-scoped, same
// pattern as Sources. ContractCreate.producer_source_id is required at
// the API layer (api/v1/governance.py) even though the column is
// nullable in the schema -- same shape as findings item 97's Transform
// Runs check, confirmed before assuming: no code path ever creates a
// sourceless contract, so unlike Pipelines/Incidents there's no
// unscoped population to handle here.
export default function ProjectContractsTab() {
  const token = getToken() as string;
  const params = useParams();
  const projectId = params.id as string;
  const toast = useToast();
  const qc = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [name, setName] = useState("");
  const [producerSourceId, setProducerSourceId] = useState("");
  const [consumerDescription, setConsumerDescription] = useState("");

  const { sourceIds, loading: scopeLoading } = useProjectScope(token, projectId);
  const contracts = useQuery({ queryKey: ["contracts"], queryFn: () => getContracts(token) });
  const sources = useQuery({ queryKey: ["sources"], queryFn: () => getSources(token) });
  const projectSources = (sources.data?.sources ?? []).filter((s) => sourceIds.has(s.id));

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["contracts"] });
    qc.invalidateQueries({ queryKey: ["audit-trail"] });
  };

  const validateMut = useMutation({
    mutationFn: (id: string) => validateContract(token, id),
    onSuccess: () => { toast.push("Contract validated.", "success"); invalidate(); },
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
      invalidate();
    },
    onError: () => toast.push("Failed to create contract.", "danger"),
  });

  const list = (contracts.data?.contracts ?? []).filter((c) => c.producer_source_id && sourceIds.has(c.producer_source_id));
  const loading = contracts.isLoading || sources.isLoading || scopeLoading;

  if (loading) return <Skeleton style={{ height: 200, borderRadius: 12 }} />;
  if (sourceIds.size === 0) return <NoSourcesGrantedEmptyState projectId={projectId} surface="contracts" />;

  return (
    <div>
      <div className="flex items-center justify-between" style={{ marginBottom: 16 }}>
        <span className="text-muted text-sm">Data contracts on this project&apos;s sources.</span>
        <Button size="sm" onClick={() => setModalOpen(true)}>+ New Contract</Button>
      </div>

      {list.length === 0 ? (
        <div className="empty-state">
          <h2 className="font-display text-xl">No data contracts yet</h2>
          <p className="text-muted text-sm" style={{ maxWidth: 380 }}>
            Define expectations for a source&apos;s schema and quality, then validate them anytime.
          </p>
          <Button size="sm" onClick={() => setModalOpen(true)}>+ New Contract</Button>
        </div>
      ) : (
        <Card>
          <Table>
            <Thead>
              <Tr><Th>Name</Th><Th>Description</Th><Th>Status</Th><Th>Last Validated</Th><Th>Actions</Th></Tr>
            </Thead>
            <Tbody>
              {list.map((c: DataContract) => (
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
      )}

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
            {projectSources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
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
