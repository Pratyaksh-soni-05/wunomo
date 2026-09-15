import { RetiredRouteRedirect } from "@/components/shell";

export default function RetiredAiEmployeesPage() {
  return (
    <RetiredRouteRedirect
      label="AI Employees"
      message="AI Employees isn't its own screen anymore — the same roster shows up when you hire an agent."
      to="/agents"
    />
  );
}
