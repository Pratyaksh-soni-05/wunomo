type ProgressVariant = "default" | "success" | "danger" | "warning";

interface ProgressProps {
  value: number;
  variant?: ProgressVariant;
  className?: string;
}

export function Progress({ value, variant = "default", className = "" }: ProgressProps) {
  const clamped = Math.max(0, Math.min(100, value));
  return (
    <div
      className={["progress-bar", className].filter(Boolean).join(" ")}
      role="progressbar"
      aria-valuenow={clamped}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className={["progress-fill", variant !== "default" ? variant : ""].filter(Boolean).join(" ")}
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}
