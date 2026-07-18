"use client";

import Link from "next/link";
import { Badge } from "@/components/ui";
import { EmployeeCard } from "@/components/shared/EmployeeCard";
import { EMPLOYEES } from "@/lib/employees";

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
            <EmployeeCard
              key={e.id}
              employee={e}
              cta={e.active ? <Link href="/chat" className="btn btn-primary btn-sm">Open AXIOM →</Link> : undefined}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
