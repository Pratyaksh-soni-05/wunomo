"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";

// Bare /projects/[id] has no content of its own -- it always redirects to
// a real tab. Chat, not Agents, per explicit decision (2026-09-14): the
// default tab is a product statement ("chat is where work gets asked
// for"), not just "whichever tab has real content this slice" -- Chat
// stays the default even though it's a signpost stub until slice 7,
// rather than defaulting to Agents now and re-training everyone once
// Chat is real.
export default function ProjectDefaultTabRedirect() {
  const params = useParams();
  const router = useRouter();
  const projectId = params.id as string;

  useEffect(() => {
    router.replace(`/projects/${projectId}/chat`);
  }, [projectId, router]);

  return null;
}
