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
  return async (signal: AbortSignal): Promise<CubismSdk> => {
    await loadCore(signal);
    loaded ??= (async () => {
      try {
        const url = "/live2d/cubism-sdk.js";
        const sdk = await importRuntime(url);
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
        throw new Error("Cubism SDK runtime is unavailable. Run pnpm prepare:l2d with your licensed 5-r.4 SDK.", {
          cause: error,
        });
      }
    })();
    const sdk = await loaded;
    signal.throwIfAborted();
    return sdk;
  };
}

export const loadSdk = createSdkLoader((url) => import(/* @vite-ignore */ url));
