import Link from "next/link";
import { Instrument_Serif } from "next/font/google";
import { WunomoWordmark } from "@/components/brand";
import { EmployeeCard } from "@/components/EmployeeCard";
import { ScreenshotCarousel } from "@/components/ScreenshotCarousel";
import { ThemeToggle } from "@/components/ThemeToggle";
import { InterestForm } from "@/components/InterestForm";
import { EMPLOYEES } from "@/lib/employees";
import { CAL_LINK, CONTACTS } from "@/lib/config";

// Additive only — a new --font-hero token for the hero headline alone, same
// as the product repo. --font-display (Fraunces) is untouched everywhere
// else. Instrument Serif ships no bold/weight axis, so weight 400 only.
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
    desc: "Ask AXIOM in plain language — it runs real pipelines, quality checks, and incident triage against your actual data.",
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
];

const SCREENSHOTS = [
  { src: "/landing/shot-dashboard.png", title: "Dashboard", desc: "Real pipeline health, quality score, and AXIOM activity — no fabricated numbers." },
  { src: "/landing/shot-chat.png", title: "AXIOM chat", desc: "A real conversation, with a visible trace of every tool call AXIOM made." },
  { src: "/landing/shot-pipelines.png", title: "Pipelines", desc: "Create, schedule, and trigger real pipelines with real run history." },
  { src: "/landing/shot-governance.png", title: "Data lineage", desc: "Source-to-pipeline lineage, auto-populated as you connect data." },
];

export default function LandingPage() {
  return (
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
            <WunomoWordmark className="landing-brand-mark" />
          </Link>
          <div className="landing-nav-anchors">
            <a href="#features">Features</a>
            <a href="#about">About</a>
            <a href="#contact">Contact</a>
          </div>
          <div className="landing-nav-actions">
            <ThemeToggle />
            <a href={CAL_LINK} target="_blank" rel="noopener noreferrer" className="btn btn-primary btn-sm">
              Book a demo
            </a>
          </div>
        </nav>

        <div className="landing-hero-content">
          <div className="landing-hero-content-stack">
            <div className="landing-hero-scrim" aria-hidden="true" />
            <div className="landing-hero-content-visible">
              <div className="landing-hero-pill landing-animate-in">
                <span className="landing-hero-pill-dot" />
                Currently onboarding design partners
              </div>
              <h1 className="landing-animate-in delay-1">The AI workforce for <em>modern</em> companies.</h1>
              <p className="landing-animate-in delay-1">
                We&apos;re building autonomous <b>AI employees</b> that handle real operational work — starting with
                AXIOM, an AI DataOps engineer.
              </p>
              <div className="flex items-center justify-center gap-3 landing-animate-in delay-2">
                <a href={CAL_LINK} target="_blank" rel="noopener noreferrer" className="btn btn-primary">
                  Book a demo
                </a>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="landing-section" aria-label="Product screenshots">
        <ScreenshotCarousel slides={SCREENSHOTS} />
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
                  <a href={CAL_LINK} target="_blank" rel="noopener noreferrer" className="btn btn-primary btn-sm">
                    Book a demo
                  </a>
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
            of operational work — data, finance, DevOps, analytics, security, HR — gets done by
            autonomous AI employees working alongside your team, not another dashboard your team
            has to babysit. We started with the hardest one: AXIOM, an AI DataOps engineer that
            manages pipelines, data quality, and incidents through conversation, with real access
            to your data and real guardrails on what it can do. AXIOM is live today. Five more
            employees are on the way.
          </p>
        </div>
      </section>

      <section className="landing-section" id="contact">
        <div className="landing-section-header">
          <div className="landing-eyebrow">Get in Touch</div>
          <h2 className="font-display">Questions? Reach us directly.</h2>
        </div>
        <div className="landing-contact-cards">
          {CONTACTS.map((c) => (
            <span key={c.email} className="landing-contact-person">
              <a className="landing-contact-card" href={`mailto:${c.email}`}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M22 6 12 13 2 6" />
                  <path d="M2 6h20v12H2z" />
                </svg>
                {c.name} — {c.email}
              </a>
              <a className="landing-contact-card" href={c.whatsappLink} target="_blank" rel="noopener noreferrer">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
                </svg>
                WhatsApp {c.name.split(" ")[0]}
              </a>
            </span>
          ))}
        </div>
        <InterestForm />
      </section>

      <section className="landing-final-cta">
        <h2 className="font-display">Curious what AXIOM could do for your team?</h2>
        <p>We&apos;re working with a small group of design partners now.</p>
        <a href={CAL_LINK} target="_blank" rel="noopener noreferrer" className="btn btn-primary">
          Book a demo
        </a>
      </section>

      <footer className="landing-footer">
        <WunomoWordmark className="landing-footer-mark" />
        <p className="landing-footer-line">Wunomo is a product of Alpha Parallel.</p>
        <span className="landing-footer-copyright">© 2026 Alpha Parallel. All rights reserved.</span>
      </footer>
    </div>
  );
}
