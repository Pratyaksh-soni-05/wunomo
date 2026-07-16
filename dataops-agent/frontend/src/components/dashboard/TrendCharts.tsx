"use client";

import "./chartSetup";
import { Line } from "react-chartjs-2";
import { Card, CardHeader, CardBody, Badge } from "@/components/ui";
import type { QualityTrendPoint } from "@/lib/api";

const gridColor = "rgba(107,124,148,0.15)";

function baseOptions() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { grid: { display: false }, ticks: { color: "var(--text-muted)", font: { size: 10 } } },
      y: { grid: { color: gridColor }, ticks: { color: "var(--text-muted)", font: { size: 10 } } },
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
                  borderColor: "var(--success)",
                  backgroundColor: "rgba(22,163,74,0.12)",
                  fill: true,
                  tension: 0.3,
                },
                {
                  label: "Failed",
                  data: trends.map((t) => t.fail_count),
                  borderColor: "var(--danger)",
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
                  borderColor: "var(--ocean-600)",
                  backgroundColor: "rgba(91,136,178,0.12)",
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
