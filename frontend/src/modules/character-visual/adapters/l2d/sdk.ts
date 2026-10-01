import { loadCore } from "./core";

/** Shinsekai's narrow runtime boundary, not a copy of the licensed SDK declarations. */
export interface SdkMotion {
  release(): void;
}

export interface SdkMatrix {
  scale(x: number, y: number): void;
  multiplyByMatrix(matrix: SdkMatrix): void;
}

export interface SdkModel {
  getParameterCount(): number;
  getParameterId(index: number): { getString(): { s: string } };
  getParameterMinimumValue(index: number): number;
  getParameterMaximumValue(index: number): number;
  getParameterDefaultValue(index: number): number;
  getParameterValueByIndex(index: number): number;
  setParameterValueByIndex(index: number, value: number): void;
  getPartCount(): number;
  getPartOpacityByIndex(index: number): number;
  setPartOpacityByIndex(index: number, value: number): void;
  getCanvasWidth(): number;
  getCanvasHeight(): number;
  update(): void;
}

export interface SdkRenderer {
  startUp(gl: WebGLRenderingContext): void;
  setIsPremultipliedAlpha(value: boolean): void;
  bindTexture(index: number, texture: WebGLTexture): void;
  setMvpMatrix(matrix: SdkMatrix): void;
  setRenderState(framebuffer: WebGLFramebuffer | null, viewport: number[]): void;
  drawModel(): void;
}

export interface SdkUserModel {
  loadModel(data: ArrayBuffer, check: boolean): void;
  loadMotion(data: ArrayBuffer, size: number, name: string): SdkMotion | null;
  loadPhysics(data: ArrayBuffer, size: number): void;
  loadPose(data: ArrayBuffer, size: number): void;
  getModel(): SdkModel;
  getModelMatrix(): SdkMatrix;
  createRenderer(): void;
  getRenderer(): SdkRenderer;
  resetMotion(): void;
  play(motion: SdkMotion): void;
  motionFinished(): boolean;
  animate(dt: number): void;
  physics(dt: number): void;
  pose(dt: number): void;
  release(): void;
}

export interface CubismSdk {
  SDK_VERSION: "5-r.4";
  initialize(): void;
  createModel(): SdkUserModel;
  createMatrix(): SdkMatrix;
  releaseContext(gl: WebGLRenderingContext, lastModel: boolean): void;
}

/** Only explicitly prepared local SDK resources are used; never download a licensed SDK implicitly. */
export function createSdkLoader(importRuntime: (url: string) => Promise<unknown>) {
  let loaded: Promise<CubismSdk> | undefined;
  let retries = 0;
  const retryUrl = (value: string) => {
    if (!retries) return value;
    const url = new URL(value, window.location.href);
    // Browser module maps can retain a failed import even after SDK installation.
    url.searchParams.set("sdk_retry", String(retries));
    return url.href;
  };
  return async (signal: AbortSignal, runtimeAssetUrl?: (filename: string) => string): Promise<CubismSdk> => {
    if (runtimeAssetUrl) {
      try {
        await loadCore(signal, runtimeAssetUrl("live2dcubismcore.min.js"));
      } catch (error) {
        signal.throwIfAborted();
        // Keep explicitly prepared developer/public runtimes compatible.
        await loadCore(signal);
      }
    } else await loadCore(signal);
    loaded ??= (async () => {
      try {
        // Absolute same-origin URLs avoid Vite rewriting optional public assets to ?import in dev.
        const url = new URL("/live2d/cubism-sdk.js", window.location.href).href;
        let sdk: unknown;
        try {
          sdk = await importRuntime(retryUrl(runtimeAssetUrl ? runtimeAssetUrl("cubism-sdk.js") : url));
        } catch (error) {
          if (!runtimeAssetUrl) throw error;
          sdk = await importRuntime(retryUrl(url));
        }
        const module = sdk as Partial<CubismSdk> | null;
        if (
          !module ||
          module.SDK_VERSION !== "5-r.4" ||
          [module.initialize, module.createModel, module.createMatrix, module.releaseContext].some(
            (value) => typeof value !== "function",
          )
        )
          throw new Error("Incompatible Cubism SDK runtime; expected 5-r.4");
        return module as CubismSdk;
      } catch (error) {
        loaded = undefined;
        ++retries;
        throw new Error(
          "Cubism SDK runtime is unavailable. Open Install SDK in the character model editor (developers: pnpm prepare:l2d).",
          {
            cause: error,
          },
        );
      }
    })();
    const sdk = await loaded;
    signal.throwIfAborted();
    return sdk;
  };
}

export const loadSdk = createSdkLoader((url) => import(/* @vite-ignore */ url));
