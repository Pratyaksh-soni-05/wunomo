// Single source of truth for the AI Employees roster copy shown on this
// site. Mirrors dataops-agent/frontend/src/lib/employees.ts (the app's own
// copy of the same roster) - kept as a separate copy here deliberately,
// since this app has no dependency on the product app's source at all.
export type BadgeVariant = "success" | "danger" | "warning" | "info" | "gray" | "midnight";

export interface Employee {
  id: string;
  name: string;
  role: string;
  desc: string;
  caps: string[];
  variant: BadgeVariant;
  active: boolean;
}

export const EMPLOYEES: Employee[] = [
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
