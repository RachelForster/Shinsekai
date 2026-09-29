let loaded: Promise<void> | undefined;

export function hasCore(): boolean {
  return typeof (globalThis as { Live2DCubismCore?: unknown }).Live2DCubismCore !== "undefined";
}

/** Core is separately licensed and installed locally, never fetched from a CDN at runtime. */
export async function loadCore(signal: AbortSignal) {
  signal.throwIfAborted();
  if (!hasCore()) {
    loaded ??= new Promise<void>((resolve, reject) => {
      const script = document.createElement("script");
      const timer = window.setTimeout(() => fail(), 15000);
      const fail = () => {
        window.clearTimeout(timer);
        script.remove();
        loaded = undefined;
        reject(new Error("Cubism Core is missing. Install the licensed Core at /live2d/live2dcubismcore.min.js"));
      };
      script.src = "/live2d/live2dcubismcore.min.js";
      script.onerror = fail;
      script.onload = () => {
        window.clearTimeout(timer);
        if (!hasCore()) fail();
        else resolve();
      };
      document.head.append(script);
    });
    await loaded;
  }
  signal.throwIfAborted();
}
