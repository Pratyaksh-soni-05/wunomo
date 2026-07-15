"use client";

import { useState } from "react";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  Input,
  Modal,
  Progress,
  Select,
  Skeleton,
  StatusDot,
  Table,
  Tabs,
  Tbody,
  Td,
  Th,
  Thead,
  Tr,
  useToast,
} from "@/components/ui";

const TAB_ITEMS = [
  { id: "buttons", label: "Buttons" },
  { id: "cards", label: "Cards & Badges" },
  { id: "forms", label: "Forms" },
  { id: "data", label: "Tables & Progress" },
];

export default function ComponentShowcase() {
  const [activeTab, setActiveTab] = useState("buttons");
  const [modalOpen, setModalOpen] = useState(false);
  const { push } = useToast();

  return (
    <main className="p-6" style={{ maxWidth: 960, margin: "0 auto" }}>
      <h1 className="font-display text-3xl font-semibold mb-2">Wunomo AI — Component Library</h1>
      <p className="text-secondary mb-4">Phase 2 scaffold: locked tokens, self-hosted fonts, core components.</p>

      <div className="flex gap-2 mb-4">
        <button
          className="btn btn-secondary btn-sm"
          onClick={() => document.documentElement.setAttribute("data-theme", "light")}
        >
          Light
        </button>
        <button
          className="btn btn-secondary btn-sm"
          onClick={() => document.documentElement.setAttribute("data-theme", "dark")}
        >
          Dark
        </button>
      </div>

      <Tabs items={TAB_ITEMS} activeId={activeTab} onChange={setActiveTab} />

      <div className="mt-4">
        {activeTab === "buttons" && (
          <Card>
            <CardBody className="flex flex-wrap gap-2 items-center">
              <Button variant="primary">Primary</Button>
              <Button variant="secondary">Secondary</Button>
              <Button variant="ghost">Ghost</Button>
              <Button variant="danger">Danger</Button>
              <Button variant="success">Success</Button>
              <Button variant="primary" size="sm">Small</Button>
              <Button variant="primary" size="lg">Large</Button>
              <Button variant="primary" disabled>Disabled</Button>
              <Button variant="secondary" onClick={() => setModalOpen(true)}>Open Modal</Button>
              <Button variant="primary" onClick={() => push("Pipeline run completed successfully.", "success")}>
                Show Toast
              </Button>
            </CardBody>
          </Card>
        )}

        {activeTab === "cards" && (
          <div className="flex flex-col gap-4">
            <Card hover>
              <CardHeader>
                <span className="font-semibold">Card title</span>
                <Badge variant="success">Active</Badge>
              </CardHeader>
              <CardBody>
                <p className="text-secondary text-base mb-2">Card body content with hover elevation.</p>
                <div className="flex gap-2 flex-wrap">
                  <Badge variant="success">Success</Badge>
                  <Badge variant="danger">Danger</Badge>
                  <Badge variant="warning">Warning</Badge>
                  <Badge variant="info">Info</Badge>
                  <Badge variant="gray">Gray</Badge>
                  <Badge variant="midnight">Midnight</Badge>
                </div>
              </CardBody>
              <CardFooter className="flex gap-2 items-center">
                <StatusDot variant="success" pulse />
                <span className="text-xs text-muted">Live</span>
              </CardFooter>
            </Card>
            <div className="flex gap-2">
              <Skeleton height={20} width={200} />
              <Skeleton height={20} width={100} />
            </div>
          </div>
        )}

        {activeTab === "forms" && (
          <Card>
            <CardBody className="flex flex-col gap-4" style={{ maxWidth: 360 }}>
              <Input label="Pipeline name" placeholder="e.g. orders-daily-sync" hint="Used as the display name." />
              <Input label="Schedule" placeholder="0 6 * * *" error="Invalid cron expression" />
              <Select label="Source type" defaultValue="postgres">
                <option value="postgres">PostgreSQL</option>
                <option value="mysql">MySQL</option>
                <option value="csv">CSV</option>
              </Select>
            </CardBody>
          </Card>
        )}

        {activeTab === "data" && (
          <div className="flex flex-col gap-4">
            <Card>
              <CardBody>
                <Table>
                  <Thead>
                    <Tr>
                      <Th>Pipeline</Th>
                      <Th>Status</Th>
                      <Th>Success rate</Th>
                    </Tr>
                  </Thead>
                  <Tbody>
                    <Tr>
                      <Td>orders-daily-sync</Td>
                      <Td><Badge variant="success">Active</Badge></Td>
                      <Td><Progress value={92} variant="success" /></Td>
                    </Tr>
                    <Tr selected>
                      <Td>inventory-hourly</Td>
                      <Td><Badge variant="warning">Degraded</Badge></Td>
                      <Td><Progress value={54} variant="warning" /></Td>
                    </Tr>
                  </Tbody>
                </Table>
              </CardBody>
            </Card>
          </div>
        )}
      </div>

      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title="Confirm action"
        footer={
          <>
            <Button variant="secondary" onClick={() => setModalOpen(false)}>Cancel</Button>
            <Button variant="primary" onClick={() => setModalOpen(false)}>Confirm</Button>
          </>
        }
      >
        <p className="text-secondary text-base">This is a modal body rendered via a portal.</p>
      </Modal>
    </main>
  );
}
