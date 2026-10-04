export type ThemePreference = "light" | "dark" | "system";

export const THEME_STORAGE_KEY = "opspilot-theme";

const ORDER: ThemePreference[] = ["light", "dark", "system"];

export function getStoredTheme(): ThemePreference {
  if (typeof window === "undefined") return "system";
  const v = localStorage.getItem(THEME_STORAGE_KEY);
  if (v === "light" || v === "dark" || v === "system") return v;
  return "system";
}

export function applyTheme(pref: ThemePreference) {
  const root = document.documentElement;
  if (pref === "system") {
    root.removeAttribute("data-theme");
    root.style.removeProperty("color-scheme");
  } else {
    root.dataset.theme = pref;
    root.style.colorScheme = pref;
  }
}

export function setTheme(pref: ThemePreference) {
  localStorage.setItem(THEME_STORAGE_KEY, pref);
  applyTheme(pref);
}

export function cycleTheme(current: ThemePreference): ThemePreference {
  const i = ORDER.indexOf(current);
  return ORDER[(i + 1) % ORDER.length];
}

/** Inline in root layout to avoid theme flash before hydration. */
export const themeInitScript = `(function(){try{var k=${JSON.stringify(THEME_STORAGE_KEY)};var v=localStorage.getItem(k);if(v==="light"||v==="dark"){document.documentElement.dataset.theme=v;document.documentElement.style.colorScheme=v;}}catch(e){}})();`;
