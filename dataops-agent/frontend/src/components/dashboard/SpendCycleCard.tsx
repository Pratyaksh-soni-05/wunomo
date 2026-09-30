"use client";

// Command Center (blueprint §05) -- "Spend this cycle": big ₹ number, "of
// ₹{limit}", a progress bar, "Resets in {n} days · {plan} plan". Backend
// has no stored reset-date column anywhere, but quota_service.py's own
// _month_start() confirms the real reset boundary IS the 1st of the next
// calendar month (UTC) -- so "days until reset" is computed here from that
// same real boundary, not fabricated.
//
// No ₹ conversion: ai_credits has no real currency exchange rate anywhere
// in this codebase (credits-per-turn calibration is explicitly unfinalized
// per quota_service.py's own commentary) -- shown as credits, not rupees,
// rather than inventing a conversion rate blueprint's mock assumes exists.
import { Progress } from "@/components/ui";
import type { QuotaStatus } from "@/lib/api";

function daysUntilReset(): number {
  const now = new Date();
  const nextMonthStart = Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 1);
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  return Math.round((nextMonthStart - today) / 86400000);
}

function progressVariant(status: QuotaStatus["status"]): "default" | "warning" | "danger" {
  if (status === "exceeded") return "danger";
  if (status === "warning") return "warning";
  return "default";
}

export function SpendCycleCard({ credits, planName }: { credits: QuotaStatus | null; planName: string | null }) {
  const days = daysUntilReset();
  return (
    <div className="spend-cycle-card card">
      <div className="spend-cycle-label">Spend this cycle</div>
      {credits ? (
        <>
          <div className="spend-cycle-value">
            {credits.used.toLocaleString()}
            <span className="spend-cycle-limit"> of {credits.limit !== null ? credits.limit.toLocaleString() : "∞"} credits</span>
          </div>
          <Progress value={credits.percent} variant={progressVariant(credits.status)} />
          <div className="spend-cycle-footnote">
            Resets in {days} day{days === 1 ? "" : "s"}
            {planName ? ` · ${planName} plan` : ""}
          </div>
        </>
      ) : (
        <div className="chat-empty-note">Usage unavailable.</div>
      )}
    </div>
  );
}
