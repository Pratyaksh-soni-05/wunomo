"use client";

import { type ReactNode } from "react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { getToken } from "@/lib/api";
import { useProjectScope } from "@/lib/projectScope";
import { NoAgentsEmptyState } from "@/components/workbench/WorkbenchEmptyStates";

// All 7, matching wunomo-all-screens.html's WBNAV exactly, even though
// only Sources/Quality/CI-CD are real in slice 6a -- the sub-nav is fully
// populated from the start (the honest StubPage for the rest lives one
// level down, not by hiding the destination here).
const SECTIONS = [
  { slug: "sources", label: "Sources" },
  { slug: "pipelines", label: "Pipelines" },
  { slug: "quality", label: "Quality" },
  { slug: "incidents", label: "Incidents" },
  { slug: "transforms", label: "Transforms" },
  { slug: "lineage", label: "Lineage" },
  { slug: "cicd", label: "CI/CD" },
];

export default function WorkbenchLayout({ children }: { children: ReactNode }) {
  const token = getToken() as string;
  const params = useParams();
  const projectId = params.id as string;
  const pathname = usePathname();
  const activeSection = pathname.split("/")[4] ?? "";

  // Count shown only for Sources for now -- the one section whose number
  // is already computed by this same hook with no further fetch. Quality/
  // CI-CD's own real counts would need their own list fetched here too
  // (rules, commits) just for a sub-nav badge; not worth a fourth query in
  // this layout for a number each page already shows in its own heading.
  const { agentCount, sourceIds, loading } = useProjectScope(token, projectId);

  // No agents at all -- shown instead of the sub-nav + any surface, not
  // per-surface (Q3). Wait for the resolver before deciding, so a fresh
  // page load doesn't flash this and then the real content.
  if (!loading && agentCount === 0) {
    return <NoAgentsEmptyState projectId={projectId} />;
  }

  return (
    <div className="wb">
      <nav className="wbnav">
        {SECTIONS.map((s) => (
          <Link
            key={s.slug}
            href={`/projects/${projectId}/workbench/${s.slug}`}
            className={["wbi", activeSection === s.slug ? "active" : ""].filter(Boolean).join(" ")}
          >
            {s.label}
            {s.slug === "sources" && <span className="c">{sourceIds.size}</span>}
          </Link>
        ))}
      </nav>
      <div className="wbbody">{children}</div>
    </div>
  );
}
