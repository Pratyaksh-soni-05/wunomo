"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useToast } from "@/components/ui";

// Shared by every top-level Workbench-surface route retired outright
// (Sources/Quality/CI-CD in slice 6a; Transforms joined them after slice
// 6b shipped, findings item 97 -- its "unscoped" population turned out to
// be schema-possible but structurally unreachable, since every code path
// that ever runs a transform requires a real source_id, so the repurposed
// tenant-wide view could only ever show empty. Pipelines/Incidents keep
// the real two-tier Unscoped treatment -- both have a genuine, reachable
// "no source"/"no pipeline" case today). A real redirect with an
// explanation, not a bare 404 -- same "don't leave a dead end" rule as
// the project Chat tab's signpost.
export function RetiredRouteRedirect({ label }: { label: string }) {
  const router = useRouter();
  const toast = useToast();

  useEffect(() => {
    toast.push(`${label} moved into each project's Workbench — pick a project to see it there.`, "default");
    router.replace("/projects");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return null;
}
