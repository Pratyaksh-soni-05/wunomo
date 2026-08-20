import type { Metadata } from "next";
import { Analytics } from "@vercel/analytics/next";
import "@/styles/fonts.css";
import "@/styles/tokens.css";
import "@/styles/components.css";
import { WunomoWordmarkSymbolDef } from "@/components/brand";

export const metadata: Metadata = {
  title: "Wunomo — AI employees for modern companies",
  description:
    "Wunomo is building autonomous AI employees for real operational work, starting with AXIOM, an AI DataOps engineer. Currently onboarding design partners — book a demo.",
};

// This site has no auth and no "system" theme option (that's a Settings-tab
// concept from the product app, which doesn't exist here) - light is always
// the default unless a visitor has explicitly toggled dark before, matching
// requirement 6 (light-mode default, with a toggle). Runs synchronously
// before paint to avoid a flash of the wrong theme.
const THEME_PREPAINT_SCRIPT = `(function(){try{var t=localStorage.getItem('wunomo_marketing_theme');document.documentElement.dataset.theme=(t==='dark')?'dark':'light';}catch(e){document.documentElement.dataset.theme='light';}})();`;

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
        <script dangerouslySetInnerHTML={{ __html: THEME_PREPAINT_SCRIPT }} />
      </head>
      <body>
        <WunomoWordmarkSymbolDef />
        {children}
        <Analytics />
      </body>
    </html>
  );
}
