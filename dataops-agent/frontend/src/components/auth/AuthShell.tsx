import { ReactNode } from "react";

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
        <h1>{headline}</h1>
        <p>{tagline}</p>
      </div>
      <div className="auth-form-side">
        <div className="auth-card">{children}</div>
      </div>
    </div>
  );
}
