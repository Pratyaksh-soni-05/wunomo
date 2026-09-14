"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useToast } from "@/components/ui";

// Shared by every top-level Workbench-surface route retired in slice 6a
// (Sources, Quality, CI/CD -- the three that resolve cleanly with no
// unscoped population, so unlike Pipelines/Incidents/Transforms they
// don't get repurposed into a tenant-wide "unscoped" view in 6b, they
// just go away). A real redirect with an explanation, not a bare 404 --
// same "don't leave a dead end" rule as the project Chat tab's signpost.
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
