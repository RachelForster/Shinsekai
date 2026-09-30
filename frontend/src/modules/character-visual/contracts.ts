import type { ComponentType } from "react";

/** 状态应用模式：play 播放动作、restore 恢复快照、edit 编辑预览。 */
export type ApplyMode = "play" | "restore" | "edit";

/** 一个格式对共享层声明的能力；共享层据此降级而不是按格式名假设。 */
export interface AvatarCapabilities {
  mouth: boolean;
  blink: boolean;
  motion: boolean;
  sampling: "none" | "single" | "multi";
}

/** 共享加载器交给格式模块的宿主环境。 */
export interface AvatarMount {
  element: HTMLElement;
  modelUrl: string;
  assetUrl(relativePath: string): string;
  reportError(error: Error): void;
}

/** 一个已加载的模型实例。泛型 S 是状态文件内容，C 是该格式的临时编辑描述。 */
export interface AvatarSession<S, C> {
  /** Actual bindings available on this loaded model, within the format's capabilities. */
  readonly capabilities: AvatarCapabilities;
  readonly controls: C;
  apply(state: S, mode: ApplyMode, signal: AbortSignal): Promise<void>;
  readState(): S;
  setMouthOpen(value: number): void;
  resize(width: number, height: number): void;
  dispose(): void;
}

export interface AvatarEditorProps<S, C> {
  session: AvatarSession<S, C>;
  value: S;
  onChange(value: S): void;
}

export interface AvatarModule<S, C> {
  create(mount: AvatarMount, signal: AbortSignal): Promise<AvatarSession<S, C>>;
  Editor: ComponentType<AvatarEditorProps<S, C>>;
}

/** 一个模型形象格式的完整描述，注册进 registry 后即可被选中 / 渲染。 */
export interface AvatarFormat<S, C> {
  id: string;
  label: string;
  /** Entry-file filters for the shared picker; omitted formats allow all files. */
  modelExtensions?: string[];
  capabilities: AvatarCapabilities;
  load(): Promise<AvatarModule<S, C>>;
}

/** 舞台 / 预览交给 CharacterVisual 的资源引用，与具体格式无关。 */
export interface CharacterVisualAsset {
  id: string;
  label: string;
  /** static 为图片 URL；模型格式为状态 JSON URL。 */
  url: string;
  /** 默认 "static"。 */
  avatarType: string;
  /** 模型入口 URL；static 为空。 */
  modelUrl: string;
}

export const STATIC_AVATAR_TYPE = "static";
