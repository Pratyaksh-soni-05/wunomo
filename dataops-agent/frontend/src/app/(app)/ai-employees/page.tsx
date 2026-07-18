"use client";

import Link from "next/link";
import { Card, CardBody, Badge } from "@/components/ui";

type BadgeVariant = "success" | "danger" | "warning" | "info" | "gray" | "midnight";

interface Employee {
  id: string;
  name: string;
  role: string;
  desc: string;
  caps: string[];
  variant: BadgeVariant;
  active: boolean;
}

// Copy pulled directly from the master design's renderAIEmployees() - no
// pricing (deferred until real Stripe pricing exists, see
// FRONTEND_BUILD_PLAN.md), no waitlist capture (no backend for it this
// phase), no marketplace framing (nothing to browse).
const EMPLOYEES: Employee[] = [
  {
    id: "axiom",
    name: "AXIOM",
    role: "DataOps Engineer",
    desc: "Automates your entire DataOps workflow. Connects databases, runs pipelines, enforces quality, and understands your data.",
    caps: ["SQL Generation", "Pipeline Orchestration", "Schema Drift Detection", "Data Quality", "Incident Response", "CI/CD"],
    variant: "midnight",
    active: true,
  },
  {
    id: "ledger",
    name: "LEDGER",
    role: "Finance Analyst",
    desc: "Automates financial reporting, variance analysis, forecasting, and budget reconciliation.",
    caps: ["P&L Analysis", "Budget Forecasting", "Variance Reports", "Compliance Checks"],
    variant: "success",
    active: false,
  },
  {
    id: "deploy",
    name: "DEPLOY",
    role: "DevOps Engineer",
    desc: "Manages infrastructure, deployment pipelines, monitoring, and incident response.",
    caps: ["CI/CD Automation", "K8s Management", "Incident Response", "SLA Monitoring"],
    variant: "warning",
    active: false,
  },
  {
    id: "insight",
    name: "INSIGHT",
    role: "Analytics Engineer",
    desc: "Builds dashboards, analyzes trends, and generates business intelligence reports automatically.",
    caps: ["Dashboard Builder", "Trend Analysis", "KPI Tracking", "Custom Reports"],
    variant: "info",
    active: false,
  },
  {
    id: "sentinel",
    name: "SENTINEL",
    role: "Security Engineer",
    desc: "Monitors threats, enforces compliance policies, and responds to security incidents.",
    caps: ["Threat Detection", "Compliance Audit", "GDPR/SOC2", "Access Review"],
    variant: "danger",
    active: false,
  },
  {
    id: "pulse",
    name: "PULSE",
    role: "HR Analyst",
    desc: "Handles HR analytics, performance tracking, and workforce intelligence.",
    caps: ["Workforce Analytics", "Attrition Risk", "Performance Metrics", "Org Charting"],
    variant: "gray",
    active: false,
  },
];

export default function AiEmployeesPage() {
  const activeCount = EMPLOYEES.filter((e) => e.active).length;

  return (
    <div>
      <div className="page-header">
        <div className="flex items-center justify-between">
          <h1 className="page-title">AI Employees</h1>
          <Badge variant="midnight">{activeCount} Active</Badge>
        </div>
        <p className="text-muted text-sm" style={{ marginTop: 6 }}>
          AI employees that autonomously handle specialized roles in your organization.
        </p>
      </div>

      <div style={{ padding: "20px 24px" }}>
        <div className="grid grid-3" style={{ gap: 16 }}>
          {EMPLOYEES.map((e) => (
            <Card key={e.id} hover style={{ position: "relative" }}>
              {!e.active && (
                <div className="locked-overlay">
                  <Badge variant="gray">Coming Soon</Badge>
                </div>
              )}
              <CardBody>
                <div className="flex items-start justify-between" style={{ marginBottom: 12 }}>
                  <div className="flex items-center gap-3">
                    <div
                      className={`badge badge-${e.variant}`}
                      style={{ width: 40, height: 40, borderRadius: 10, display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: 14 }}
                    >
                      {e.name.slice(0, 2)}
                    </div>
                    <div>
                      <div className="font-display" style={{ fontSize: 15, fontWeight: 600 }}>{e.name}</div>
                      <div className="text-muted text-sm">{e.role}</div>
                    </div>
                  </div>
                  {e.active && <Badge variant="success">Active</Badge>}
                </div>
                <p className="text-muted text-sm" style={{ marginBottom: 12, lineHeight: 1.5 }}>{e.desc}</p>
                <div className="flex flex-wrap gap-1" style={{ marginBottom: 14 }}>
                  {e.caps.map((c) => (
                    <span key={c} className="badge badge-gray" style={{ fontSize: 11 }}>{c}</span>
                  ))}
                </div>
                {e.active && (
                  <div style={{ paddingTop: 12, borderTop: "1px solid var(--border)" }}>
                    <Link href="/chat" className="btn btn-primary btn-sm">Open AXIOM →</Link>
                  </div>
                )}
              </CardBody>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
}
