"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Sidebar, Topbar, CommandPalette } from "@/components/shell";
import { getToken, decodeUserFromToken, getMe, getSettings, type DecodedUser } from "@/lib/api";
import { QueryProvider } from "@/lib/queryClient";
import { applyTheme, getStoredTheme, type ThemePreference } from "@/lib/theme";
import { applyTimezone, getStoredTimezone } from "@/lib/timezone";

export default function AppShellLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [checked, setChecked] = useState(false);
  const [user, setUser] = useState<DecodedUser | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [cmdOpen, setCmdOpen] = useState(false);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      router.push("/login");
      return;
    }
    setUser(decodeUserFromToken(token));
    setChecked(true);

    // Server is the durable source of truth for theme once it's loaded -
    // localStorage/the pre-paint script are only the synchronous fast path
    // to avoid a flash of the wrong theme before this fetch can land.
    getMe(token)
      .then((me) => {
        if (me.theme && me.theme !== getStoredTheme()) {
          applyTheme(me.theme as ThemePreference);
        }
      })
      .catch(() => {
        // Non-fatal - keep whatever localStorage already applied.
      });

    // Item 22: same reasoning as theme above, but the workspace's timezone
    // (not per-user) is the source of truth here - getSettings() over
    // getMe(). A workspace that's never set one yet gets timezone: null/""
    // back, which must NOT overwrite the browser-detected default already
    // sitting in localStorage.
    getSettings(token)
      .then((res) => {
        const tz = res.settings.timezone;
        if (tz && tz !== getStoredTimezone()) {
          applyTimezone(tz);
        }
      })
      .catch(() => {
        // Non-fatal - keep whatever localStorage/browser-detected zone is
        // already in effect.
      });
  }, [router]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        setCmdOpen(true);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  if (!checked) return null;

  return (
    <QueryProvider>
      <div className="app-layout">
        <Sidebar
          collapsed={collapsed}
          onToggle={() => setCollapsed((v) => !v)}
          mobileOpen={mobileOpen}
          user={user}
        />
        <div className={["main-content", collapsed ? "expanded" : ""].filter(Boolean).join(" ")}>
          <Topbar
            onToggleSidebar={() => setMobileOpen((v) => !v)}
            onOpenCommandPalette={() => setCmdOpen(true)}
            user={user}
          />
          <main className="page-content">{children}</main>
        </div>
        <CommandPalette open={cmdOpen} onClose={() => setCmdOpen(false)} />
      </div>
    </QueryProvider>
  );
}
