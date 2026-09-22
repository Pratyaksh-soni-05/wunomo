"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useToast } from "@/components/ui";

// Shared by every top-level route retired outright (Sources/Quality/
// CI-CD in slice 6a; Transforms joined them in the finding-97 fix;
// Catalog and Contracts in slice 12, still into Workbench; AI Employees,
// Governance, the old /audit stub, Billing, Automations, and Analytics
// also in slice 12, each with its own real destination or none at all --
// see `message`/`to` below). A real redirect with an explanation, not a
// bare 404 -- same "don't leave a dead end" rule as the project Chat
// tab's signpost.
//
// message/to default to the original Workbench-migration wording so
// every pre-slice-12 call site (passing only `label`) keeps behaving
// identically -- only a route whose real destination isn't "pick a
// project's Workbench" needs to override either.
export function RetiredRouteRedirect({
  label, message, to = "/projects",
}: { label: string; message?: string; to?: string }) {
  const router = useRouter();
  const toast = useToast();

  useEffect(() => {
    toast.push(message ?? `${label} moved into each project's Workbench — pick a project to see it there.`, "default");
    router.replace(to);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return null;
}
