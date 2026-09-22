import { RetiredRouteRedirect } from "@/components/shell";

export default function RetiredAutomationsPage() {
  return (
    <RetiredRouteRedirect
      label="Automations"
      message="Automations isn't available in this workspace."
      to="/home"
    />
  );
}
