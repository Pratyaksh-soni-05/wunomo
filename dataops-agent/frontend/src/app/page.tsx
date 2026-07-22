"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { EmployeeCard } from "@/components/shared/EmployeeCard";
import { EMPLOYEES } from "@/lib/employees";
import { getToken } from "@/lib/api";

const FEATURES = [
  {
    title: "Pipelines, without the orchestration work",
    desc: "Connect your data sources and AXIOM runs the pipeline end-to-end — sync, transform, and quality checks — without you hand-wiring the steps yourself.",
  },
  {
    title: "Quality checks and incidents, handled automatically",
    desc: "AXIOM runs quality checks on a schedule, opens an incident the moment something breaks, and tracks it through to resolution.",
  },
  {
    title: "Ask it anything, in plain language",
    desc: "“List my data sources.” “Why did this pipeline fail?” AXIOM answers by actually calling the real tools against your real data — not a scripted response.",
  },
  {
    title: "Built for a team, not just one user",
    desc: "Roles, approval gates on higher-risk actions, and usage tracking are built in from day one, so AXIOM fits into how your team already works.",
  },
];

// Renders the logged-out state on both server and first client render (no
// synchronous pre-hydration DOM writes, unlike the theme script) - the auth
// check only runs in an effect after mount, so there is nothing for React's
// hydration diff to catch a mismatch on. This is the safe pattern; the
// theme pre-paint script's approach is what caused the hydration Gotcha
// documented in CLAUDE.md, and this deliberately avoids repeating it.
function useIsAuthed(): boolean {
  const [authed, setAuthed] = useState(false);
  useEffect(() => {
    setAuthed(!!getToken());
  }, []);
  return authed;
}

// The landing page is the signed-off, light-tuned "public mode" and must
// default to light for any visitor who hasn't made an explicit choice -
// unlike the authenticated app, which falls through to the OS's
// prefers-color-scheme when nothing is stored (tokens.css's
// `:root:not([data-theme="light"])` dark rule under `@media
// (prefers-color-scheme: dark)`). Runs synchronously, before paint, as the
// first thing in <body> - same FOUC-prevention technique as the root
// layout's own pre-paint script, just overriding its result specifically on
// this route. Only an explicit prior "light"/"dark" choice (the toggle,
// wherever set) is honored; anything else (nothing stored, or a stray
// "system" value from the authenticated Settings tab) resolves to light here.
const LANDING_THEME_PREPAINT_SCRIPT = `(function(){try{var t=localStorage.getItem('axiom_theme');document.documentElement.dataset.theme=(t==='light'||t==='dark')?t:'light';}catch(e){document.documentElement.dataset.theme='light';}})();`;

export default function LandingPage() {
  const authed = useIsAuthed();

  return (
    <>
    <script dangerouslySetInnerHTML={{ __html: LANDING_THEME_PREPAINT_SCRIPT }} />
    <div className="landing-page">
      <nav className="landing-nav">
        <span className="landing-brand">Wunomo AI</span>
        {authed ? (
          <Link href="/dashboard" className="btn btn-primary btn-sm">Go to Dashboard</Link>
        ) : (
          <div className="flex items-center gap-2">
            <Link href="/login" className="btn btn-secondary btn-sm">Log in</Link>
            <Link href="/signup" className="btn btn-primary btn-sm">Get Started</Link>
          </div>
        )}
      </nav>

      <section className="landing-hero">
        <h1 className="font-display">Hire AI employees that work autonomously for your company.</h1>
        <p>Wunomo is building a full workforce of them. The first one, AXIOM, is ready today.</p>
        <div className="flex items-center justify-center gap-3">
          <Link href="/signup" className="btn btn-primary">Get Started</Link>
          <Link href="/login" className="btn btn-secondary">Log in</Link>
        </div>
      </section>

      <section className="landing-section">
        <div className="landing-section-header">
          <div className="landing-eyebrow">The Wunomo Workforce</div>
          <h2 className="font-display">One employee is active today. Five more are on the way.</h2>
        </div>
        <div className="grid grid-3" style={{ gap: 16 }}>
          {EMPLOYEES.map((e) => (
            <EmployeeCard
              key={e.id}
              employee={e}
              cta={
                e.active ? (
                  authed ? (
                    <Link href="/chat" className="btn btn-primary btn-sm">Open AXIOM →</Link>
                  ) : (
                    <Link href="/signup" className="btn btn-primary btn-sm">Get Started with AXIOM</Link>
                  )
                ) : undefined
              }
            />
          ))}
        </div>
      </section>

      <section className="landing-section">
        <div className="landing-section-header">
          <div className="landing-eyebrow">What AXIOM Actually Does</div>
          <h2 className="font-display">Not a demo. A real employee, working now.</h2>
        </div>
        <div className="landing-feature-grid">
          {FEATURES.map((f) => (
            <div key={f.title} className="landing-feature">
              <h3 className="font-display">{f.title}</h3>
              <p>{f.desc}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="landing-final-cta">
        <h2 className="font-display">Put your first AI employee to work.</h2>
        <p>Create a workspace and connect a data source in minutes.</p>
        <Link href="/signup" className="btn btn-primary">Get Started</Link>
      </section>

      <footer className="landing-footer">
        <span className="landing-brand">Wunomo AI</span>
        <div className="landing-footer-links">
          <Link href="/login">Log in</Link>
          <Link href="/signup">Get Started</Link>
        </div>
        <span className="landing-footer-copyright">© 2026 Wunomo AI.</span>
      </footer>
    </div>
    </>
  );
}
