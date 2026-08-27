"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Instrument_Serif } from "next/font/google";
import { EmployeeCard } from "@/components/shared/EmployeeCard";
import { ScreenshotCarousel } from "@/components/shared/ScreenshotCarousel";
import { WunomoWordmark } from "@/components/brand";
import { EMPLOYEES } from "@/lib/employees";
import { getToken } from "@/lib/api";

// Additive only — a new --font-hero token for the hero headline alone.
// --font-display (Fraunces) is untouched and stays the face for every other
// product heading. Instrument Serif ships with no bold/weight axis and no
// italic-face fallback below ~28px, so this is requested at weight 400 only
// and applied nowhere but a headline already set well above that floor.
const instrumentSerif = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
  variable: "--font-hero",
  display: "swap",
});

const FEATURES = [
  {
    title: "Chat is the whole interface.",
    desc: "Ask AXIOM in plain language, and it runs real pipelines, quality checks, and incident triage against your actual data.",
  },
  {
    title: "Pipelines without the plumbing.",
    desc: "Connect a source and AXIOM handles sync, transform, and quality end to end.",
  },
  {
    title: "Quality and incidents, watched for you.",
    desc: "Scheduled checks and automatic incident tracking, through to resolution.",
  },
  {
    title: "Ships safely.",
    desc: "CI/CD deploy gating and human approval on higher-risk actions, built in.",
  },
  {
    title: "Works like a team tool.",
    desc: "Real roles and permissions, usage-based plans, from day one.",
  },
  {
    title: "Plans the multi-step work, too.",
    desc: "Ask for more than one action and AXIOM turns it into a real plan, executing step by step with your approval on anything risky.",
  },
];

// 2026-08-27 recapture, filenames content-hash-suffixed 2026-08-27 (see
// WALKTHROUGH_FINDINGS_2026-08.md #68): 5 screens, all dark-theme/1440@2x,
// all real and unedited from demo@axiom-yc.ai — the real, long-running demo
// tenant, its real contents exactly as they stand (real 22 open incidents,
// a real failed pipeline run, real task history including QA-verification
// debris; see #67), not a tenant seeded for the capture. Chat's raw
// pipeline/source/run/incident/tenant UUIDs are visually redacted (black
// bars, DOM-level) before the screenshot, not edited out of the underlying
// message. Incidents stays excluded (item 55 still lies about its own
// count) and Analytics stays excluded (dropped from nav) — every other
// screen this tenant can show honestly is here now. Filenames carry a
// content-hash suffix (first 8 hex chars of the file's own sha256) so a
// future recapture at the same logical slot never again collides with a
// still-cached same-path file across Vercel/Cloudflare's two independent
// CDN layers — see #68 for the wunomo.in incident this fixes.
const SCREENSHOTS = [
  { src: "/landing/shot-dashboard-9fa65854.png", title: "Dashboard", desc: "Real pipeline health, quality score, and pending approvals. Nothing fabricated." },
  { src: "/landing/shot-chat-c03e8bc4.png", title: "AXIOM chat", desc: "A real conversation, with a visible trace of every tool call AXIOM made." },
  { src: "/landing/shot-pipelines-33954878.png", title: "Pipelines", desc: "Create, schedule, and trigger real pipelines with real run history." },
  { src: "/landing/shot-tasks-36aa441b.png", title: "Tasks", desc: "Real multi-step plans AXIOM generates, reviews, and executes with human approval on the risky steps." },
  { src: "/landing/shot-quality-f9db6e45.png", title: "Quality", desc: "Real quality rules against real data, with a real pass/fail record." },
];

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

export default function LandingPage() {
  const authed = useIsAuthed();

  return (
    <>
    <script dangerouslySetInnerHTML={{ __html: LANDING_THEME_PREPAINT_SCRIPT }} />
    <div className={`landing-page ${instrumentSerif.variable}`}>
      <section className="landing-hero">
        <div className="landing-hero-mesh" aria-hidden="true" />
        <div className="landing-hero-grain" aria-hidden="true" />

        <div className="landing-band landing-band-a" aria-hidden="true">
          <WunomoWordmark /><WunomoWordmark /><WunomoWordmark />
        </div>
        <div className="landing-band landing-band-b" aria-hidden="true">
          <WunomoWordmark /><WunomoWordmark /><WunomoWordmark />
        </div>

        <nav className="landing-nav">
          <Link href="/" className="landing-brand">
            <WunomoWordmark className="landing-brand-mark" title="Wunomo" />
          </Link>
          <div className="landing-nav-anchors">
            <a href="#features">Features</a>
            <a href="#about">About</a>
            <a href="#contact">Contact</a>
          </div>
          <div className="landing-nav-actions">
            {authed ? (
              <Link href="/dashboard" className="btn btn-primary">Go to Dashboard</Link>
            ) : (
              <>
                <Link href="/login" className="btn btn-secondary">Log in</Link>
                <Link href="/signup" className="btn btn-primary">Try Wunomo</Link>
              </>
            )}
          </div>
        </nav>

        <div className="landing-hero-content">
          <div className="landing-hero-content-stack">
            <div className="landing-hero-content-visible">
              <span className="landing-hero-badge landing-animate-in">
                <span className="dot" />Currently onboarding design partners
              </span>
              <h1 className="landing-animate-in delay-1">The AI workforce for <em>modern</em> companies.</h1>
              <p className="landing-hero-sub landing-animate-in delay-1">
                We&apos;re building autonomous <b>AI employees</b> that handle real operational work,
                beginning with AXIOM, an AI DataOps engineer.
              </p>
              <div className="landing-animate-in delay-2">
                <Link href="/signup" className="btn btn-primary btn-lg">Try Wunomo</Link>
              </div>
            </div>
          </div>
        </div>

        <div className="landing-hero-frame-title">See AXIOM in the product</div>
        <div className="landing-hero-frame">
          <div className="landing-hero-frame-bar"><i /><i /><i /></div>
          <ScreenshotCarousel slides={SCREENSHOTS} />
        </div>
      </section>

      <section className="landing-section" id="features">
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
                    <Link href="/chat" className="btn btn-primary">Open AXIOM →</Link>
                  ) : (
                    <Link href="/signup" className="btn btn-primary">Get Started with AXIOM</Link>
                  )
                ) : undefined
              }
            />
          ))}
        </div>
      </section>

      <section className="landing-section" id="about">
        <div className="landing-section-header">
          <div className="landing-eyebrow">About Wunomo</div>
          <h2 className="font-display">Built for the next generation of operational work</h2>
        </div>
        <div className="landing-about">
          <p>
            Wunomo is building the AI workforce for modern companies. We think the next generation
            of operational work, across data, finance, DevOps, analytics, security, and HR, gets done by
            autonomous AI employees working alongside your team, not another dashboard your team
            has to babysit. We started with the hardest one: AXIOM, an AI DataOps engineer that
            manages pipelines, data quality, and incidents through conversation, with real access
            to your data and real guardrails on what it can do. AXIOM is live today. Five more
            employees are on the way. Wunomo is a product of Alpha Parallel.
          </p>
        </div>
      </section>

      <section className="landing-section" id="contact">
        <div className="landing-section-header">
          <div className="landing-eyebrow">Get in Touch</div>
          <h2 className="font-display">Questions? Reach us directly.</h2>
        </div>
        <div className="landing-contact-cards">
          <a className="landing-contact-card" href="mailto:pratyakshsoni2005@gmail.com">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M4 4h16v16H4z" opacity="0" />
              <path d="M22 6 12 13 2 6" />
              <path d="M2 6h20v12H2z" />
            </svg>
            pratyakshsoni2005@gmail.com
          </a>
          <a className="landing-contact-card" href="mailto:guptadaksh1509@gmail.com">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M22 6 12 13 2 6" />
              <path d="M2 6h20v12H2z" />
            </svg>
            guptadaksh1509@gmail.com
          </a>
        </div>
      </section>

      <section className="landing-final-cta">
        <h2 className="font-display">Put your first AI employee to work.</h2>
        <p>Create a workspace and connect a data source in minutes.</p>
        <Link href="/signup" className="btn btn-primary btn-lg">Try Wunomo</Link>
      </section>

      <footer className="landing-footer">
        <WunomoWordmark className="landing-footer-mark" title="Wunomo" />
        <p className="landing-footer-line">Wunomo is a product of Alpha Parallel.</p>
        <span className="landing-footer-copyright">© 2026 Alpha Parallel. All rights reserved.</span>
      </footer>
    </div>
    </>
  );
}
