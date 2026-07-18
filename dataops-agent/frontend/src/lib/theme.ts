// Shared by ThemeToggle, the (app) shell's server-reconciliation effect, and
// the Settings > Theme tab, so all three apply/read theme the same way.
//
// "system" is intentionally never written as a literal data-theme value that
// CSS branches on beyond "light"/"dark" - tokens.css's dark rule is
// `:root:not([data-theme="light"])` under `@media (prefers-color-scheme:
// dark)`, so any value other than "light" (including "system", including no
// attribute at all) already falls through to the OS-driven default. Setting
// data-theme="system" is therefore safe and requires no special-casing here.
export type ThemePreference = "light" | "dark" | "system";

const STORAGE_KEY = "axiom_theme";

export function applyTheme(value: ThemePreference) {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.theme = value;
  try {
    localStorage.setItem(STORAGE_KEY, value);
  } catch {
    // localStorage unavailable (private mode, etc.) - theme still applies
    // for this page load via the DOM attribute, just won't persist.
  }
}

export function getStoredTheme(): ThemePreference {
  if (typeof document === "undefined") return "system";
  return (document.documentElement.dataset.theme as ThemePreference) || "system";
}

// Resolves "system" to the OS's actual current preference - used only for
// deciding which sun/moon icon to show, never for deciding which CSS rule
// applies (that's tokens.css's job via the media query).
export function resolveEffectiveTheme(pref: ThemePreference): "light" | "dark" {
  if (pref === "light" || pref === "dark") return pref;
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}
