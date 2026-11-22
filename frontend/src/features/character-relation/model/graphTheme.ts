export interface GraphTheme {
  text: string;
  background: string;
  accent: string;
  selected: string;
  muted: string;
}

export function readGraphTheme(container: HTMLElement): GraphTheme {
  const probe = document.createElement("span");
  probe.style.cssText = "position:absolute;visibility:hidden;pointer-events:none";
  container.appendChild(probe);
  // Resolve light-dark()/color-mix() through CSS, then normalize modern color
  // spaces to sRGB because ECharts' color parser expects RGB/hex values.
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 1;
  const context = globalThis.CSS?.supports?.("color", "oklch(50% 0.1 20)") ? canvas.getContext("2d") : null;
  const resolveThemeColor = (token: string, fallback: string): string => {
    probe.style.color = `var(${token}, ${fallback})`;
    const resolved = getComputedStyle(probe).color || fallback;
    if (!context) return resolved;
    context.clearRect(0, 0, 1, 1);
    context.fillStyle = resolved;
    context.fillRect(0, 0, 1, 1);
    const [r, g, b, a] = context.getImageData(0, 0, 1, 1).data;
    return `rgba(${r}, ${g}, ${b}, ${a / 255})`;
  };
  try {
    return {
      text: resolveThemeColor("--color-text-primary", "#241820"),
      background: resolveThemeColor("--color-bg-panel", "#ffffff"),
      accent: resolveThemeColor("--color-accent-secondary", "#a64f67"),
      selected: resolveThemeColor("--color-control-active", "#f0d4dc"),
      muted: resolveThemeColor("--color-text-muted", "#686068"),
    };
  } finally {
    probe.remove();
  }
}
