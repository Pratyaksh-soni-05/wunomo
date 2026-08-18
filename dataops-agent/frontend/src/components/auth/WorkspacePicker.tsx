import { Modal } from "@/components/ui";
import type { WorkspaceOption } from "@/lib/api";

// Item 1: also reused in-app (Sidebar's real workspace switcher, not just
// login's forced disambiguation) - title/subtitle/currentTenantId are
// optional so login's original call site (no current workspace, a forced
// choice rather than a deliberate switch) keeps its exact original copy.
export function WorkspacePicker({
  open,
  options,
  onClose,
  onPick,
  title = "Choose a workspace",
  subtitle = "This email is linked to more than one workspace. Pick which one to continue into.",
  currentTenantId,
}: {
  open: boolean;
  options: WorkspaceOption[];
  onClose: () => void;
  onPick: (tenantId: string) => void;
  title?: string;
  subtitle?: string;
  currentTenantId?: string;
}) {
  return (
    <Modal open={open} onClose={onClose} title={title} size="sm">
      <p className="text-sm text-muted mb-4">{subtitle}</p>
      <div className="flex flex-col gap-2">
        {options.map((opt) => {
          const isCurrent = opt.tenant_id === currentTenantId;
          return (
            <button
              key={opt.tenant_id}
              className="workspace-option card card-hover"
              disabled={isCurrent}
              onClick={() => onPick(opt.tenant_id)}
            >
              <span className="font-medium">{opt.tenant_name}</span>
              <span className="text-muted text-sm">{isCurrent ? "Current" : "→"}</span>
            </button>
          );
        })}
      </div>
    </Modal>
  );
}
