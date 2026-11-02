import { useEffect, useState } from "react";

import { normalizeThemeColor } from "../../../shared/theme/appTheme";

function readMainThemeColor() {
  if (typeof window === "undefined") {
    return normalizeThemeColor(undefined);
  }
  return normalizeThemeColor(getComputedStyle(document.documentElement).getPropertyValue("--theme-accent"));
}

export function useMainThemeColor() {
  const [mainThemeColor, setMainThemeColor] = useState(readMainThemeColor);

  useEffect(() => {
    const syncMainThemeColor = () => setMainThemeColor(readMainThemeColor());
    setMainThemeColor(readMainThemeColor());
    const observer = typeof MutationObserver === "undefined" ? null : new MutationObserver(syncMainThemeColor);
    observer?.observe(document.documentElement, { attributeFilter: ["class", "style"], attributes: true });
    window.addEventListener("storage", syncMainThemeColor);
    return () => {
      observer?.disconnect();
      window.removeEventListener("storage", syncMainThemeColor);
    };
  }, []);

  return mainThemeColor;
}
