"use client";

import "./chartSetup";
import { Line } from "react-chartjs-2";
import { Card, CardHeader, CardBody, Badge } from "@/components/ui";
import type { QualityTrendPoint } from "@/lib/api";

// Sourced from the token layer at render time, same as every other color in
// this file — was a hardcoded JS literal duplicating --text-muted's light-
// mode RGB. Kept theme-invariant on purpose (see --chart-grid's comment in
// tokens.css): unlike tickColor below, this never actually flipped with
// theme even before this change.
const gridColor = () => resolveToken("--chart-grid", "rgba(107,124,148,0.15)");

// Canvas 2D silently rejects unresolved CSS var() strings (confirmed live -
// assigning ctx.strokeStyle = "var(--x)" is a no-op, not an error, so the
// previous/default color quietly stays instead) - Chart.js draws straight to
// canvas, so every color here must be a real resolved value, not a raw
// var() reference. Read fresh at render time so light/dark both work
// correctly on load (a live theme toggle without a page reload won't
// re-resolve these until the component next re-renders - a known, narrower
// gap than the "colors don't render at all" bug this fixes).
function resolveToken(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

function baseOptions() {
  const tickColor = resolveToken("--text-muted", "#6B7C94");
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { grid: { display: false }, ticks: { color: tickColor, font: { size: 10 } } },
      y: { grid: { color: gridColor() }, ticks: { color: tickColor, font: { size: 10 } } },
    },
  };
}

export function RunHistoryChart({ trends }: { trends: QualityTrendPoint[] }) {
  return (
    <Card>
      <CardHeader className="flex items-center justify-between">
        <span className="font-semibold text-sm">Pipeline Run History (7 days)</span>
        <Badge variant="success">Live</Badge>
      </CardHeader>
      <CardBody style={{ paddingTop: 8 }}>
        <div className="chart-container" style={{ height: 180 }}>
          <Line
            data={{
              labels: trends.map((t) => t.date.slice(5)),
              datasets: [
                {
                  label: "Passed",
                  data: trends.map((t) => t.pass_count),
                  borderColor: resolveToken("--success", "#16a34a"),
                  backgroundColor: "rgba(22,163,74,0.12)",
                  fill: true,
                  tension: 0.3,
                },
                {
                  label: "Failed",
                  data: trends.map((t) => t.fail_count),
                  borderColor: resolveToken("--danger", "#dc2626"),
                  backgroundColor: "rgba(220,38,38,0.1)",
                  fill: true,
                  tension: 0.3,
                },
              ],
            }}
            options={baseOptions()}
          />
        </div>
      </CardBody>
    </Card>
  );
}

export function QualityTrendChart({ trends }: { trends: QualityTrendPoint[] }) {
  return (
    <Card>
      <CardHeader>
        <span className="font-semibold text-sm">Quality Score Trend</span>
      </CardHeader>
      <CardBody style={{ paddingTop: 8 }}>
        <div className="chart-container" style={{ height: 180 }}>
          <Line
            data={{
              labels: trends.map((t) => t.date.slice(5)),
              datasets: [
                {
                  label: "Avg quality score",
                  data: trends.map((t) => t.avg_quality_score),
                  borderColor: resolveToken("--chart-accent", "#4C76A0"),
                  backgroundColor: resolveToken("--chart-accent-fill-a12", "rgba(91,136,178,0.12)"),
                  fill: true,
                  tension: 0.3,
                  spanGaps: true,
                },
              ],
            }}
            options={baseOptions()}
          />
        </div>
      </CardBody>
    </Card>
  );
}
