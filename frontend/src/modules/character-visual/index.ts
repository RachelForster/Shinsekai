/** Public rendering API. No concrete format or character persistence dependency. */
export { CharacterVisual, type CharacterVisualProps } from "./CharacterVisual";
export { avatarAssetUrl, avatarRuntimeAssetUrl } from "./assetUrl";
export { avatarFormat, registeredAvatarFormats, registerAvatarFormat } from "./registry";
export { routeAvatarVoice, routeAvatarSpeechEvent } from "./voiceRoute";
export { STATIC_AVATAR_TYPE } from "./contracts";
export { defaultVisualFraming, normalizeVisualFraming, visualFramingMinRatio } from "./framing";
export type { VisualFraming } from "./framing";
export type {
  ApplyMode,
  AvatarAttention,
  AvatarSpeechEvent,
  AvatarCapabilities,
  AvatarEditorProps,
  AvatarFormat,
  AvatarModule,
  AvatarMount,
  AvatarSession,
  CharacterVisualAsset,
} from "./contracts";
