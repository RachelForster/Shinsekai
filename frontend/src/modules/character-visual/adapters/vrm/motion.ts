import { AnimationMixer, LoopOnce, type AnimationAction, type AnimationClip, type Object3D } from "three";
import type { ApplyMode } from "../../contracts";

interface MotionRequest {
  clip?: AnimationClip;
  ready: boolean;
  mode: ApplyMode;
  immediate: boolean;
  reducedMotion: boolean;
  basePose: () => void;
  onStart: () => void;
}

/** Preload in parallel and play complete clips in the order they were requested. */
export function createMotionPlayer(root: Object3D, bones: Object3D[], expressions: { weight: number }[]) {
  const mixer = new AnimationMixer(root);
  let action: AnimationAction | undefined;
  let queue: MotionRequest[] = [];
  let generation = 0;
  let disposed = false;
  const sampledBones = bones.map((bone) => ({
    position: bone.position.clone(),
    rotation: bone.quaternion.clone(),
    scale: bone.scale.clone(),
  }));
  const sampledExpressions = expressions.map((expression) => expression.weight);
  const playing = () => Boolean(action && !action.paused && action.isRunning());

  function rememberPose() {
    bones.forEach((bone, i) => {
      sampledBones[i].position.copy(bone.position);
      sampledBones[i].rotation.copy(bone.quaternion);
      sampledBones[i].scale.copy(bone.scale);
    });
    expressions.forEach((expression, i) => {
      sampledExpressions[i] = expression.weight;
    });
  }

  function sample(delta: number) {
    // Restore values overridden by speech/blinks, including constant animation tracks.
    bones.forEach((bone, i) => {
      bone.position.copy(sampledBones[i].position);
      bone.quaternion.copy(sampledBones[i].rotation);
      bone.scale.copy(sampledBones[i].scale);
    });
    expressions.forEach((expression, i) => {
      expression.weight = sampledExpressions[i];
    });
    mixer.update(delta);
    rememberPose();
  }

  function start(request: MotionRequest) {
    mixer.stopAllAction();
    if (action) mixer.uncacheClip(action.getClip());
    action = undefined;
    request.basePose();
    rememberPose();
    if (request.clip) {
      action = mixer.clipAction(request.clip);
      action.setLoop(LoopOnce, 1);
      action.clampWhenFinished = true;
      action.play();
      if (request.mode !== "play" || request.reducedMotion) {
        action.time = request.mode === "edit" ? 0 : request.clip.duration;
        action.paused = true;
      }
    }
    request.onStart();
    sample(0);
  }

  function drain() {
    while (queue[0]?.ready && (queue[0].immediate || !playing())) start(queue.shift()!);
  }

  return {
    get playing() {
      return playing();
    },
    async apply(
      clip: AnimationClip | undefined | Promise<AnimationClip | undefined>,
      mode: ApplyMode,
      basePose: () => void,
      onStart: () => void = () => {},
      restart = false,
      reducedMotion = false,
    ) {
      if (disposed) return;
      const immediate = mode !== "play" || restart || reducedMotion;
      if (immediate) {
        generation++;
        queue = [];
      }
      const sequence = generation;
      const request: MotionRequest = { ready: false, mode, immediate, reducedMotion, basePose, onStart };
      queue.push(request);
      try {
        request.clip = await clip;
        if (disposed || sequence !== generation) return;
        request.ready = true;
        drain();
      } catch (error) {
        if (disposed || sequence !== generation) return;
        queue = queue.filter((item) => item !== request);
        drain();
        throw error;
      }
    },
    update(delta: number) {
      if (disposed) return;
      sample(delta);
      drain();
    },
    dispose() {
      disposed = true;
      generation++;
      queue = [];
      mixer.stopAllAction();
      mixer.uncacheRoot(root);
    },
  };
}
