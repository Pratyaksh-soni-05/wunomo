"use client";

// Command Center (blueprint §05) -- "Spend this cycle": §05's own mock is a
// big ₹ number against a plan limit. Researched before building (per
// explicit instruction, not assumed): does a credits-to-currency rate
// exist anywhere in this codebase -- PLANS dict (quota_service.py),
// billing models, Stripe integration, a usage_metrics table? It does not.
// credits_for_event() is explicitly documented as "a deliberately simple
// placeholder, not a real-dollar-cost calculation"; every Stripe billing
// call (checkout/change-plan/webhook) 501s; no plan carries a price field
// anywhere. GOTCHAS.md references an external pricing-strategy doc with a
// ₹/turn figure, but it's never parsed or wired into any code path --
// prose for a manual margin check, not a live rate. Inventing one here
// would be exactly the fabrication this codebase's own conventions forbid.
//
// So: no currency. Chosen instead -- the real `percent` field as the
// headline, not the raw credit count ("0 of 11,493,000 credits" is
// meaningless to a business owner; a token-scale ceiling was never meant
// to be read as a number, only as a fraction). Genuine zero usage says so
// in words, not as a bare "0" that reads as broken. The raw used/limit
// figures are still shown, but as the secondary line, not the headline.
//
// Reset date: no stored reset-date column anywhere, but quota_service.py's
// own _month_start() confirms the real reset boundary IS the 1st of the
// next calendar month (UTC) -- computed here from that same real boundary.
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
  const resetFootnote = `Resets in ${days} day${days === 1 ? "" : "s"}${planName ? ` · ${planName} plan` : ""}`;

  return (
    <div className="spend-cycle-card card">
      <div className="spend-cycle-label">Spend this cycle</div>
      {credits ? (
        credits.used === 0 ? (
          <>
            <div className="spend-cycle-value spend-cycle-value-zero">No usage yet</div>
            <Progress value={0} variant="default" />
            <div className="spend-cycle-footnote">{resetFootnote}</div>
          </>
        ) : (
          <>
            <div className="spend-cycle-value">
              {Math.round(credits.percent)}
              <span className="spend-cycle-limit">% of plan used</span>
            </div>
            <Progress value={credits.percent} variant={progressVariant(credits.status)} />
            <div className="spend-cycle-footnote">
              {credits.used.toLocaleString()} of {credits.limit !== null ? credits.limit.toLocaleString() : "∞"} credits · {resetFootnote}
            </div>
          </>
        )
      ) : (
        <div className="chat-empty-note">Usage unavailable.</div>
      )}
    </div>
  );
}
