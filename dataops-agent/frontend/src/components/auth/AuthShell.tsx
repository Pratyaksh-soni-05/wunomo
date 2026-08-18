import { ReactNode } from "react";
import { WunomoWordmark } from "@/components/brand";

/**
 * Phase 3 (2026-08-19): the brand panel carries the wordmark plus one
 * constant line of copy (sourced from the approved marketing-site landing
 * hero, not invented here — see the Phase 3 report for where it came from).
 * `headline`/`tagline` are the per-page context login/signup have always
 * passed ("Welcome back to Wunomo AI" vs "Set up your workspace on Wunomo
 * AI", etc.) — rendered for real on the right panel, above the form, in
 * the body font (General Sans), distinct from the form's own <h2> (e.g.
 * "Log in"), which correctly uses --font-display — Fraunces is the
 * established heading face across the whole product (Correction 1,
 * 2026-08-19), not confined to this brand-panel line; only a
 * since-superseded Instrument Serif plan would have required that
 * confinement, and that plan isn't the one in use.
 * An earlier pass hid headline/tagline in a visually-hidden span instead of
 * rendering them, which was a regression: it removed the only visual
 * difference between the login and signup screens, and put a heading in
 * front of screen-reader users that sighted users never see.
 */
export function AuthShell({
  headline,
  tagline,
  children,
}: {
  headline: string;
  tagline: string;
  children: ReactNode;
}) {
  return (
    <div className="auth-shell">
      <div className="auth-brand">
        <WunomoWordmark className="auth-brand-wordmark" />
        <p className="auth-brand-copy">The AI workforce for modern companies.</p>
      </div>
      <div className="auth-form-side">
        <div className="auth-card">
          <div className="auth-context">
            <h1 className="auth-context-headline">{headline}</h1>
            <p className="auth-context-tagline">{tagline}</p>
          </div>
          {children}
        </div>
      </div>
    </div>
  );
}
