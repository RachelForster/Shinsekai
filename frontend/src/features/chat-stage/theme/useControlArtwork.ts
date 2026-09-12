import { useEffect, useMemo, useState } from "react";
import type { ResolvedChatTheme } from "../../../shared/theme/chatTheme";

/** Keep SVG controls visible until the current theme's artwork has loaded. */
export function useControlArtwork(theme: ResolvedChatTheme): ResolvedChatTheme {
  const [loaded, setLoaded] = useState<{ theme: ResolvedChatTheme; send?: boolean; microphone?: boolean }>();

  useEffect(() => {
    let active = true;
    const images: HTMLImageElement[] = [];
    for (const key of ["send", "microphone"] as const) {
      const url = theme.controlArtwork?.[key];
      if (!url) continue;
      const image = new Image();
      images.push(image);
      image.onload = () => {
        if (active && image.naturalWidth > 0) {
          setLoaded((previous) => ({ ...(previous?.theme === theme ? previous : { theme }), [key]: true }));
        }
      };
      image.src = url;
    }
    return () => {
      active = false;
      for (const image of images) image.onload = null;
    };
  }, [theme]);

  return useMemo(
    () => ({
      ...theme,
      style: {
        ...theme.style,
        "--chat-send-icon-opacity": loaded?.theme === theme && loaded.send ? "0" : "1",
        "--chat-input-microphone-icon-opacity": loaded?.theme === theme && loaded.microphone ? "0" : "1",
      },
    }),
    [loaded, theme],
  );
}
