// Compiled only by explicit local SDK preparation, not imported by the application build.
import { CubismFramework } from "shinsekai-cubism/live2dcubismframework.ts";
import { CubismUserModel } from "shinsekai-cubism/model/cubismusermodel.ts";
import { CubismMatrix44 } from "shinsekai-cubism/math/cubismmatrix44.ts";
import { CubismShaderManager_WebGL } from "shinsekai-cubism/rendering/cubismshader_webgl.ts";

export const SDK_VERSION = "5-r.4";
export function initialize() {
  if (!CubismFramework.isStarted()) CubismFramework.startUp();
  if (!CubismFramework.isInitialized()) CubismFramework.initialize();
}
export function createModel() {
  return new (class extends CubismUserModel {
    resetMotion() {
      this._motionManager.stopAllMotions();
    }
    play(motion) {
      this._motionManager.startMotionPriority(motion, false, 3);
    }
    motionFinished() {
      return this._motionManager.isFinished();
    }
    animate(dt) {
      this._motionManager.updateMotion(this.getModel(), dt);
    }
    physics(dt) {
      this._physics?.evaluate(this.getModel(), dt);
    }
    pose(dt) {
      this._pose?.updateParameters(this.getModel(), dt);
    }
  })();
}
export function createMatrix() {
  return new CubismMatrix44();
}
export function releaseContext(gl, lastModel) {
  // Pinned R4 compatibility: the shader manager has no per-context removal API.
  const map = CubismShaderManager_WebGL.getInstance()._shaderMap;
  for (const entry = map.begin(); entry.notEqual(map.end()); entry.preIncrement()) {
    if (entry.ptr().first === gl) {
      entry.ptr().second.release();
      map.erase(entry);
      break;
    }
  }
  if (lastModel) CubismShaderManager_WebGL.deleteInstance();
}
