"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Input, Progress, useToast } from "@/components/ui";
import { getToken, getOnboarding, submitOnboarding } from "@/lib/api";

const ROLE_OPTIONS = ["Data Engineer", "Data Analyst", "Data Scientist", "Engineering Manager", "Founder / CEO", "Other"];
const SIZE_OPTIONS = ["1-10", "11-50", "51-200", "201-1000", "1000+"];
const USE_CASE_OPTIONS = ["Pipeline monitoring", "Data quality checks", "Incident response", "Reporting & KPIs", "CI/CD for data", "Governance & lineage"];
const DATA_STACK_OPTIONS = ["Postgres", "MySQL", "Snowflake", "BigQuery", "Redshift", "S3 / GCS", "Airflow", "dbt", "Google Sheets", "Custom API"];

function Chip({ label, selected, onClick }: { label: string; selected: boolean; onClick: () => void }) {
  return (
    <button type="button" className={["chip", selected ? "chip-selected" : ""].join(" ")} onClick={onClick}>
      {label}
    </button>
  );
}

function toggle(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

export default function OnboardingPage() {
  const router = useRouter();
  const toast = useToast();
  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState(true);

  const [role, setRole] = useState("");
  const [industry, setIndustry] = useState("");
  const [companySize, setCompanySize] = useState("");
  const [useCases, setUseCases] = useState<string[]>([]);
  const [dataStack, setDataStack] = useState<string[]>([]);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      router.push("/login");
      return;
    }
    getOnboarding(token)
      .then((profile) => {
        if (profile.completed) router.push("/dashboard");
        else setChecking(false);
      })
      .catch(() => setChecking(false));
  }, [router]);

  if (checking) return null;

  const totalSteps = 4;
  const canAdvance =
    (step === 1 && role) ||
    (step === 2 && industry) ||
    (step === 3 && companySize) ||
    (step === 4 && useCases.length > 0);

  async function handleNext() {
    if (step < totalSteps) {
      setStep(step + 1);
      return;
    }
    const token = getToken();
    if (!token) {
      router.push("/login");
      return;
    }
    setLoading(true);
    try {
      await submitOnboarding(token, { role, industry, company_size: companySize, use_cases: useCases, data_stack: dataStack });
      router.push("/dashboard");
    } catch {
      toast.push("Couldn't save your answers. Try again.", "danger");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="onboarding-shell">
      <div className="onboarding-progress-wrap">
        <div className="onboarding-step-label">Step {step} of {totalSteps}</div>
        <Progress value={(step / totalSteps) * 100} />
      </div>

      <div className="onboarding-card card p-6">
        {step === 1 && (
          <>
            <h2>What&apos;s your role?</h2>
            <div className="chip-grid">
              {ROLE_OPTIONS.map((r) => (
                <Chip key={r} label={r} selected={role === r} onClick={() => setRole(r)} />
              ))}
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <h2>What industry are you in?</h2>
            <Input placeholder="e.g. SaaS, Healthcare, Finance" value={industry} onChange={(e) => setIndustry(e.target.value)} />
          </>
        )}

        {step === 3 && (
          <>
            <h2>How big is your company?</h2>
            <div className="chip-grid">
              {SIZE_OPTIONS.map((s) => (
                <Chip key={s} label={s} selected={companySize === s} onClick={() => setCompanySize(s)} />
              ))}
            </div>
          </>
        )}

        {step === 4 && (
          <>
            <h2>How will Wunomo AI help you?</h2>
            <div className="chip-grid mb-4">
              {USE_CASE_OPTIONS.map((u) => (
                <Chip key={u} label={u} selected={useCases.includes(u)} onClick={() => setUseCases(toggle(useCases, u))} />
              ))}
            </div>
            <p className="text-sm text-muted mb-2">Which of these does your data stack include? (optional)</p>
            <div className="chip-grid">
              {DATA_STACK_OPTIONS.map((d) => (
                <Chip key={d} label={d} selected={dataStack.includes(d)} onClick={() => setDataStack(toggle(dataStack, d))} />
              ))}
            </div>
          </>
        )}

        <div className="onboarding-actions">
          <Button variant="ghost" disabled={step === 1} onClick={() => setStep(step - 1)}>Back</Button>
          <Button disabled={!canAdvance || loading} onClick={handleNext}>
            {step === totalSteps ? "Finish" : "Next"}
          </Button>
        </div>
      </div>
    </div>
  );
}
