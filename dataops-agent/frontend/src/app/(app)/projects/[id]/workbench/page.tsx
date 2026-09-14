"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";

// Bare /projects/[id]/workbench has no content of its own -- redirects to
// Sources, the first item in the sub-nav and the cleanest-scoped surface.
export default function WorkbenchDefaultRedirect() {
  const params = useParams();
  const router = useRouter();
  const projectId = params.id as string;

  useEffect(() => {
    router.replace(`/projects/${projectId}/workbench/sources`);
  }, [projectId, router]);

  return null;
}
