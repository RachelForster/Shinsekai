/** Keep previews and stage playback at the same speed, including already saved clips. */
export const SPRITE_TRANSITION_PLAYBACK_RATE = 1;
export const SPRITE_TRANSITION_FRAME_COUNT = 22;
export const SPRITE_TRANSITION_FPS = 24;

export interface SpriteFramePresentation {
  width: number;
  height: number;
  bounds: [number, number, number, number];
  luma: number;
}

export interface SpriteTransitionPresentation {
  from: SpriteFramePresentation;
  first: SpriteFramePresentation;
  last: SpriteFramePresentation;
  to: SpriteFramePresentation;
}

export interface SpriteTransitionMedia {
  fromUrl: string;
  url: string;
  presentation?: SpriteTransitionPresentation;
}
