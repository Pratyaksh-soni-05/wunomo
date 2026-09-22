// The complete set of REAL, hireable employee types -- mirrors backend
// AgentEmployeeType exactly (models/all_models.py). ANALYST joined DATAOPS
// as the second real member ("Add Analyst as a second employee type") --
// a read-only business-analyst persona built from the existing DataOps
// tools (agent/dataops_agent.py's _employee_type_tools()), not a new tool
// surface. Used by the mention picker's "Not hired yet" group (§7.5) and
// LiveWorkPanel's Team tab -- previously duplicated as a local literal in
// LiveWorkPanel.tsx.
export const KNOWN_EMPLOYEE_TYPES = ["dataops", "analyst"] as const;

export const EMPLOYEE_TYPE_LABEL: Record<string, string> = {
  dataops: "DataOps Engineer",
  analyst: "Business Analyst",
};
