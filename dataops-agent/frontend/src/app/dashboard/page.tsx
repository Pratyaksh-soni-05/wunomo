'use client';
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import Link from "next/link";

export default function Dashboard() {
  const [health, setHealth] = useState<any>(null);
  const [freshness, setFreshness] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.get("/api/v1/analytics/health").catch(() => ({ data: null })),
      api.get("/api/v1/analytics/freshness").catch(() => ({ data: null })),
    ]).then(([h, f]) => {
      setHealth(h.data);
      setFreshness(f.data);
      setLoading(false);
    });
  }, []);

  const statusColor = (s: string) =>
    s === "healthy" ? "text-green-400" : s === "degraded" ? "text-yellow-400" : "text-red-400";

  const cards = [
    { label: "Pipeline Runs (24h)", value: health?.pipeline_runs_24h ?? "—" },
    { label: "Success Rate", value: health ? `${health.success_rate_24h}%` : "—" },
    { label: "Open Incidents",  value: health?.open_incidents ?? "—" },
    { label: "Stale Sources",   value: freshness?.stale_count ?? "—" },
  ];

  return (
    <div className="min-h-screen bg-gray-950 p-6">
      <div className="max-w-6xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-white">DataOps Dashboard</h1>
            <p className="text-gray-500 text-sm">Powered by AXIOM</p>
          </div>
          <Link href="/chat"
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm transition">
            Chat with AXIOM
          </Link>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          {cards.map(c => (
            <div key={c.label} className="bg-gray-900 border border-gray-800 rounded-xl p-5">
              <p className="text-gray-500 text-xs mb-1">{c.label}</p>
              <p className="text-2xl font-bold text-white">{loading ? "…" : c.value}</p>
            </div>
          ))}
        </div>

        {health && (
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 mb-6">
            <p className="text-gray-400 text-sm mb-1">System Health</p>
            <p className={`text-lg font-semibold capitalize ${statusColor(health.health_status)}`}>
              {health.health_status}
              {health.critical_incidents > 0 && (
                <span className="ml-2 text-xs bg-red-900/50 text-red-300 px-2 py-0.5 rounded-full">
                  {health.critical_incidents} critical
                </span>
              )}
            </p>
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {[
            { title: "Data Sources", href: "/sources", desc: "Manage connections and sync status", icon: "🗄️" },
            { title: "Pipelines",    href: "/pipelines", desc: "View, trigger, and schedule pipelines", icon: "⚡" },
            { title: "Incidents",    href: "/incidents", desc: "Active data incidents and triage", icon: "🚨" },
            { title: "Quality",      href: "/quality",   desc: "Rules, checks, and business validation", icon: "✅" },
            { title: "Governance",   href: "/governance", desc: "Lineage, contracts, and audit trail", icon: "🔍" },
            { title: "Chat",         href: "/chat",      desc: "Talk to AXIOM in any personality mode", icon: "💬" },
          ].map(c => (
            <Link key={c.title} href={c.href}
              className="bg-gray-900 border border-gray-800 rounded-xl p-5 hover:border-gray-600 transition group">
              <div className="text-2xl mb-2">{c.icon}</div>
              <h3 className="font-semibold text-white mb-1 group-hover:text-blue-400 transition">{c.title}</h3>
              <p className="text-sm text-gray-500">{c.desc}</p>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
