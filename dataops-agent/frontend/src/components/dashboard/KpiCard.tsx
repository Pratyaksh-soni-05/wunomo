"use client";

import "./chartSetup";
import { Line } from "react-chartjs-2";
import { Card } from "@/components/ui";

export function KpiCard({
  label,
  value,
  subLabel,
  subLabelTone = "neutral",
  color = "var(--text-primary)",
  chartColor = color,
  sparklineData,
}: {
  label: string;
  value: string;
  subLabel?: string;
  subLabelTone?: "up" | "down" | "neutral";
  color?: string;
  /** Sparkline line color — separate from `color` (the metric-value text)
   * since a chart series and body text answer different constraints (AA
   * text contrast vs. just reading distinctly next to other series lines).
   * Defaults to `color` so existing callers passing one value keep
   * rendering both the same, as before this split. */
  chartColor?: string;
  sparklineData?: number[];
}) {
  return (
    <Card hover>
      <div className="metric-card">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm text-muted font-medium">{label}</span>
          {sparklineData && sparklineData.length > 1 && (
            <div className="chart-container" style={{ width: 70, height: 28 }}>
              <Line
                data={{
                  labels: sparklineData.map((_, i) => i),
                  datasets: [
                    {
                      data: sparklineData,
                      borderColor: chartColor,
                      borderWidth: 1.5,
                      pointRadius: 0,
                      tension: 0.35,
                      fill: false,
                    },
                  ],
                }}
                options={{
                  responsive: true,
                  maintainAspectRatio: false,
                  animation: false,
                  scales: { x: { display: false }, y: { display: false } },
                  plugins: { tooltip: { enabled: false } },
                }}
              />
            </div>
          )}
        </div>
        <div className="metric-value" style={{ color }}>
          {value}
        </div>
        {subLabel && (
          <div className={["metric-change", subLabelTone === "up" ? "up" : subLabelTone === "down" ? "down" : ""].join(" ")}>
            {subLabel}
          </div>
        )}
      </div>
    </Card>
  );
}
