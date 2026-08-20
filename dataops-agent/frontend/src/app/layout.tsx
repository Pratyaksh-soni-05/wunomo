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
      </head>
      <body>
        <WunomoWordmarkSymbolDef />
        <ToastProvider>{children}</ToastProvider>
      </body>
    </html>
  );
}
