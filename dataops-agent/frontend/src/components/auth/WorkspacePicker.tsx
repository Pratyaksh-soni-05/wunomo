import { Modal } from "@/components/ui";
import type { WorkspaceOption } from "@/lib/api";

export function WorkspacePicker({
  open,
  options,
  onClose,
  onPick,
}: {
  open: boolean;
  options: WorkspaceOption[];
  onClose: () => void;
  onPick: (tenantId: string) => void;
}) {
  return (
    <Modal open={open} onClose={onClose} title="Choose a workspace" size="sm">
      <p className="text-sm text-muted mb-4">
        This email is linked to more than one workspace. Pick which one to continue into.
      </p>
      <div className="flex flex-col gap-2">
        {options.map((opt) => (
          <button
            key={opt.tenant_id}
            className="workspace-option card card-hover"
            onClick={() => onPick(opt.tenant_id)}
          >
            <span className="font-medium">{opt.tenant_name}</span>
            <span className="text-muted text-sm">&rarr;</span>
          </button>
        ))}
      </div>
    </Modal>
  );
}
