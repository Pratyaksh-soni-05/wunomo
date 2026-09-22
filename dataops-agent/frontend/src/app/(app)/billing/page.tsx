import { RetiredRouteRedirect } from "@/components/shell";

export default function RetiredBillingPage() {
  return (
    <RetiredRouteRedirect
      label="Billing"
      message="Billing is now part of Team & billing."
      to="/team?tab=billing"
    />
  );
}
