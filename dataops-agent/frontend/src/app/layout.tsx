import type { Metadata } from "next";
import "@/styles/fonts.css";
import "@/styles/tokens.css";
import "@/styles/components.css";
import { ToastProvider } from "@/components/ui";
import { WunomoWordmarkSymbolDef } from "@/components/brand";

export const metadata: Metadata = {
  title: "Wunomo AI",
  description: "Wunomo AI — an AI workforce platform, starting with AXIOM, an autonomous DataOps AI employee",
};

// Dev-only: Next dev silently falls back to 3001/3002/etc when 3000 is held
// by a stray process — this has already caused two false diagnoses in this
// project (a CORS-blocked Google OAuth button that looked dead, and a "no
// changes visible" report against stale code on 3000 while work was live on
// 3001). Gated on NODE_ENV at render time, not just hidden by CSS, so it
// never ships in a production build. See
// docs/context/WALKTHROUGH_FINDINGS_2026-08.md.
const PORT_WARNING_SCRIPT = `(function(){try{var p=window.location.port;if(p&&p!=='3000'){console.warn('[Wunomo dev] This page is on port '+p+', not 3000. Google OAuth\\'s redirect_uri and the backend CORS allowlist both expect http://localhost:3000 in dev — a stray dev server is probably still holding port 3000. Close it and restart on 3000.');}}catch(e){}})();`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <link rel="preload" href="/fonts/GeneralSans-400.woff2" as="font" type="font/woff2" crossOrigin="anonymous" />
        <link rel="preload" href="/fonts/GeneralSans-600.woff2" as="font" type="font/woff2" crossOrigin="anonymous" />
        <link rel="preload" href="/fonts/Fraunces-600.woff2" as="font" type="font/woff2" crossOrigin="anonymous" />
        {/* Runs before paint to avoid a flash of the wrong theme — reads the
            same localStorage key ThemeToggle writes to. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem('axiom_theme');if(t)document.documentElement.dataset.theme=t;}catch(e){}})();`,
          }}
        />
        {process.env.NODE_ENV !== "production" && (
          <script dangerouslySetInnerHTML={{ __html: PORT_WARNING_SCRIPT }} />
        )}
      </head>
      <body>
        <WunomoWordmarkSymbolDef />
        <ToastProvider>{children}</ToastProvider>
      </body>
    </html>
  );
}
