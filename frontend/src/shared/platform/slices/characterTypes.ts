import type {
  MouthPose,
  SpriteMouthCorrection,
  SpriteMouthManual,
  SpriteMouthManifest,
} from "../../assets/spriteMouth";
export type {
  MouthPose,
  SpriteMouthCorrection,
  SpriteMouthManual,
  SpriteMouthManifest,
} from "../../assets/spriteMouth";
import type { SpriteTransitionMedia as SpriteTransitionAsset } from "../../assets/spriteTransition";
import type { ImageAutoLabelResult, TaskProgressOptions, TaskSnapshot } from "./taskTypes";

export interface RelationNode {
  key: string;
}

export interface RelationEdge {
  source: string;
  target: string;
  temperature: number;
  content: string;
}

export interface RelationGraph {
  nodes: RelationNode[];
  edges: RelationEdge[];
}

export interface CharacterRelationGraph extends RelationGraph {
  owner: string;
}

export type RelationRequest =
  | { op: "add_node"; node: RelationNode }
  | { op: "delete_node"; key: string }
  | { op: "upsert_edge"; edge: RelationEdge }
  | { op: "delete_edge"; source: string; target: string };

export interface PortraitCrop {
  x: number;
  y: number;
  zoom: number;
}

export interface PlayerPortrait {
  characterName: string;
  url: string;
  crop: PortraitCrop;
}

export type SpriteVoiceType = "fallback" | "preset" | "reference";

export interface Sprite {
  mouth_sync?: string | null;
  portrait_crop?: PortraitCrop | null;
  path: string;
  voice_path?: string;
  voice_text?: string;
  voice_type?: SpriteVoiceType;
}

export interface ModelSprites {
  model_path: string;
  sprites: Sprite[];
  emotion_tags: string;
}

export interface AvatarRuntimeStatus {
  version: string;
  installed: boolean;
  download_url: string;
  license_urls: string[];
}

export interface AvatarRuntimeImport {
  source_path: string;
  accepted_license: boolean;
}

export interface Character {
  sprite_transitions?: SpriteTransition[];
  portrait_crop?: PortraitCrop;
  name: string;
  color: string;
  sprite_prefix: string;
  sprites: Sprite[];
  character_brief?: string;
  relation_graph?: RelationGraph;
  character_setting: string;
  sprite_scale: number;
  emotion_tags: string;
  /** 默认 "static"；模型格式为已注册的格式 id。 */
  avatar_type: string;
  /** 格式 id → 该格式的模型与资源；static 不在此映射中。 */
  avatars: Record<string, ModelSprites>;
  gpt_model_path?: string;
  sovits_model_path?: string;
  refer_audio_path?: string;
  prompt_text?: string;
  prompt_lang?: string;
  speech_speed: number;
  speech_volume: number;
  pronunciation_map: Record<string, string>;
}

export interface CharacterSettingResult {
  characterBrief?: string;
  characterSetting: string;
  message: string;
}

export interface CharacterBriefResult {
  characterBrief: string;
  message: string;
}

export interface CharacterBriefBatchResult {
  characters: Character[];
  generatedNames: string[];
}

export interface CharacterTranslateResult {
  characterSetting: string;
  emotionTags: string;
  error?: string;
  name: string;
}

export interface CharacterMemory {
  id: string;
  memory: string;
}

export interface CharacterMemoryList {
  agentId: string;
  count: number;
  memories: CharacterMemory[];
}

export interface CharacterMemoryImportFilePreview {
  chunkCount: number;
  dialogueCharacters: number;
  dialogueLineCount: number;
  kind: string;
  name: string;
  sourceTokens: number;
}

export interface CharacterMemoryImportPreview {
  chunkCount: number;
  dialogueCharacters: number;
  dialogueLineCount: number;
  estimatedInputTokens: number;
  estimatedOutputTokens: number;
  estimatedTotalTokens: number;
  fileCount: number;
  files: CharacterMemoryImportFilePreview[];
  sourceTokens: number;
  warnings: string[];
}

export interface CharacterMemoryImportResult {
  chunkCount: number;
  duplicateCount: number;
  estimatedTotalTokens: number;
  extractedCount: number;
  fileCount: number;
  memories?: string[];
  savedCount: number;
}

export interface CharacterMemorySearchInput {
  limit?: number;
  name: string;
  query: string;
}

export interface Mem0Status {
  status: "ready" | "loading" | "not_started" | "error" | "missing_dependency";
  message?: string;
  modelCached?: boolean;
  moduleName?: string;
  packageName?: string;
  task?: TaskSnapshot;
}

export interface SpritePromptPair {
  prompt: string;
  tagging: string;
}

export interface CharacterSpritePlanInput {
  name: string;
  setting: string;
  count: number;
  requirements: string;
  referenceImage?: string;
}

export type H3SpriteResolution = "workflow" | "hd" | "native";

export interface SpriteMatting {
  method: "ai" | "chroma";
  alphaMatting: boolean;
  model?: "toonout" | "isnet-anime";
  requestedModel?: "toonout" | "isnet-anime";
  device?: "cuda" | "cpu";
  fallbackReason?: string;
  screenColor?: [number, number, number];
  reason?: string;
}

export interface SpriteMattingOptions {
  mattingModel?: "toonout" | "isnet-anime";
  autoScreen?: boolean;
  alphaMatting?: boolean;
}

export interface GeneratedCharacterSprite extends SpritePromptPair {
  name: string;
  path: string;
  taskId: string;
  videoPath?: string;
  frameTime?: number;
  originalPath?: string;
  backgroundRemoved?: boolean;
  backgroundRemovalError?: string;
  mouthSyncManifest?: string;
  mouthSyncError?: string;
  animation?: boolean;
  alphaVerified?: boolean;
  h3Resolution?: H3SpriteResolution;
  frameCount?: number;
  duration?: number;
  playbackSpeed?: number;
  matting?: SpriteMatting;
}

export interface CharacterSpriteAnimationInput extends SpriteMattingOptions {
  name: string;
  referenceImage: string;
  tagging: string;
  breathing: boolean;
  blinking: boolean;
  breeze: boolean;
  loop: boolean;
  motion: string;
  playbackSpeed?: number;
  h3Resolution?: H3SpriteResolution;
  customPrompt?: string;
}

export interface SpriteMouthSetup {
  pythonPath: string;
  version: number[];
  missing: string[];
  compatible: boolean;
  runtimeReady: boolean;
  device: "auto" | "cpu" | "cuda";
  modelDirectory: string;
  modelsReady: boolean;
  models: { id: string; ready: boolean; size: number }[];
}

export interface SpriteMouthInput {
  name: string;
  spritePath: string;
  frameCount?: 5 | 22 | 39;
  includeBlink?: boolean;
  speechVideo?: string;
  regenerate?: boolean;
  retryTaskId?: string;
  manual?: SpriteMouthManual | null;
  selectedFrames?: Record<MouthPose, number>;
  correction?: SpriteMouthCorrection;
}

export type SpriteEyeFrames = Partial<Record<MouthPose, number>>;

export interface GeneratedSpriteMouth {
  speechFps?: number;
  correction?: SpriteMouthCorrection;
  name?: string;
  spritePath?: string;
  sourceFingerprint?: string;
  taskId?: string;
  ready: boolean;
  calibrationNeeded?: boolean;
  message?: string;
  manifestPath?: string;
  profile?: SpriteMouthManifest;
  reference?: string;
  speechVideo?: string;
  frames?: { index: number; path: string; time?: number }[];
  selectedFrames?: Record<MouthPose, number>;
  eyeFrames?: SpriteEyeFrames;
  manual?: SpriteMouthManual | null;
  suggestedManual?: SpriteMouthManual;
  cached?: boolean;
}

export interface SpriteTransition {
  frame_count?: number;
  h3_resolution?: H3SpriteResolution;
  from_path: string;
  to_path: string;
  path: string;
  from_fingerprint: string;
  to_fingerprint: string;
}

export type SpriteTransitionMedia = SpriteTransitionAsset;

export interface SpriteTransitionInput extends SpriteMattingOptions {
  name: string;
  fromPath: string;
  toPath: string;
  regenerate?: boolean;
  retryTaskId?: string;
  h3Resolution?: H3SpriteResolution;
}

export interface SpriteTransitionRecommendation {
  fromPath: string;
  toPath: string;
  count: number;
  /** Share of all reconstructed changes, used for generation priority. */
  probability: number;
  conditionalProbability: number;
  existing: boolean;
}

export interface SpriteTransitionAnalysis {
  name: string;
  spritePaths: string[];
  basis: "instructions" | "inferred";
  dialogCount: number;
  dialogLimit: number;
  conversationCount: number;
  mappedDialogCount: number;
  inferredDialogCount: number;
  transitionCount: number;
  items: SpriteTransitionRecommendation[];
}

export interface GeneratedSpriteTransition extends SpriteTransitionInput {
  videoPath?: string;
  matting?: SpriteMatting;
  requestedFrames?: number;
  taskId: string;
  path: string;
  alphaVerified: boolean;
  frameCount?: number;
  cached?: boolean;
  backgroundRemovalError?: string;
}

export interface CharacterRelationPlatform {
  getRelationGraph: (owner: string) => Promise<CharacterRelationGraph>;
  applyRelationChanges: (owner: string, operations: RelationRequest[]) => Promise<CharacterRelationGraph>;
}

export interface AvatarRuntimesPlatform {
  status: (format: string) => Promise<AvatarRuntimeStatus>;
  prepare: (format: string, input: AvatarRuntimeImport) => Promise<unknown>;
  install: (format: string, input: AvatarRuntimeImport & { compiled: string }) => Promise<AvatarRuntimeStatus>;
}

export interface CharactersPlatform {
  importModel: (input: { name: string; avatar_type: string; source_path: string }) => Promise<Character>;
  importModelStates: (input: {
    name: string;
    avatar_type: string;
    model_path: string;
    source_paths: string[];
    state: unknown;
  }) => Promise<Character>;
  saveModelState: (input: {
    name: string;
    avatar_type: string;
    model_path: string;
    sprite_index: number;
    path: string;
    state: unknown;
    tags: string;
  }) => Promise<Character>;
  autoLabelSprites: (
    name: string,
    options?: TaskProgressOptions<ImageAutoLabelResult>,
  ) => Promise<ImageAutoLabelResult>;
  planSprites: (
    input: CharacterSpritePlanInput,
    options?: TaskProgressOptions<{ items: SpritePromptPair[] }>,
  ) => Promise<{ items: SpritePromptPair[] }>;
  renderSprite: (
    input: SpritePromptPair & {
      name: string;
      referenceImage?: string;
      removeBackground?: boolean;
      h3Resolution?: H3SpriteResolution;
    } & SpriteMattingOptions,
    options?: TaskProgressOptions<GeneratedCharacterSprite>,
  ) => Promise<GeneratedCharacterSprite>;
  animateSprite: (
    input: CharacterSpriteAnimationInput,
    options?: TaskProgressOptions<GeneratedCharacterSprite>,
  ) => Promise<GeneratedCharacterSprite>;
  getSpriteMouthSetup: () => Promise<SpriteMouthSetup>;
  configureSpriteMouth: (input: { pythonPath?: string; device?: "auto" | "cpu" | "cuda" }) => Promise<SpriteMouthSetup>;
  importSpriteMouthModels: (input: { paths: string[] }) => Promise<SpriteMouthSetup>;
  downloadSpriteMouthModels: (options?: TaskProgressOptions<SpriteMouthSetup>) => Promise<SpriteMouthSetup>;
  installSpriteMouthRuntime: (options?: TaskProgressOptions<SpriteMouthSetup>) => Promise<SpriteMouthSetup>;
  generateSpriteMouth: (
    input: SpriteMouthInput,
    options?: TaskProgressOptions<GeneratedSpriteMouth>,
  ) => Promise<GeneratedSpriteMouth>;
  readSpriteMouth: (path: string) => Promise<GeneratedSpriteMouth>;
  saveSpriteMouths: (input: {
    name: string;
    eyesOnly?: boolean;
    items: { taskId: string; correction?: SpriteMouthCorrection; eyeFrames?: SpriteEyeFrames }[];
  }) => Promise<Character>;
  removeSpriteMouth: (input: { name: string; spritePath: string }) => Promise<Character>;
  analyzeSpriteTransitions: (
    input: { name: string },
    options?: TaskProgressOptions<SpriteTransitionAnalysis>,
  ) => Promise<SpriteTransitionAnalysis>;
  generateSpriteTransition: (
    input: SpriteTransitionInput,
    options?: TaskProgressOptions<GeneratedSpriteTransition>,
  ) => Promise<GeneratedSpriteTransition>;
  saveSpriteTransitions: (input: { name: string; items: { taskId: string }[] }) => Promise<Character>;
  importGeneratedSprites: (input: {
    name: string;
    items: { taskId: string; tagging: string; replace?: { index: number; path: string } }[];
    replace?: { index: number; path: string };
  }) => Promise<Character>;
  captureSpriteFrame: (
    input: { name: string; taskId: string; seconds: number; removeBackground?: boolean } & SpriteMattingOptions,
    options?: TaskProgressOptions<GeneratedCharacterSprite>,
  ) => Promise<GeneratedCharacterSprite>;
  removeSpriteBackground: (
    input: { name: string; taskId: string } & SpriteMattingOptions,
    options?: TaskProgressOptions<GeneratedCharacterSprite>,
  ) => Promise<GeneratedCharacterSprite>;
  delete: (name: string) => Promise<void>;
  deleteMemory: (name: string, memoryId: string) => Promise<CharacterMemoryList>;
  deleteSpriteVoice: (name: string, spriteIndex: number) => Promise<Character>;
  ensureBriefs: (names: string[]) => Promise<CharacterBriefBatchResult>;
  export: (name: string) => Promise<string>;
  generateBrief: (input: { name: string; setting: string }) => Promise<CharacterBriefResult>;
  generateSetting: (input: { name: string; setting: string }) => Promise<CharacterSettingResult>;
  import: (items: File[] | string[]) => Promise<Character[]>;
  list: () => Promise<Character[]>;
  revision: () => Promise<string>;
  getMem0Status: () => Promise<Mem0Status>;
  importMemories: (
    name: string,
    items: File[],
    options?: TaskProgressOptions<CharacterMemoryImportResult>,
  ) => Promise<CharacterMemoryImportResult>;
  listMemories: (name: string) => Promise<CharacterMemoryList>;
  previewMemoryImport: (name: string, items: File[]) => Promise<CharacterMemoryImportPreview>;
  remember: (name: string, content: string) => Promise<CharacterMemoryList>;
  searchMemories: (input: CharacterMemorySearchInput) => Promise<CharacterMemoryList>;
  save: (character: Character, originalName?: string) => Promise<Character>;
  saveEmotionTags: (name: string, emotionTags: string) => Promise<Character>;
  saveSpriteScale: (name: string, scale: number) => Promise<Character>;
  saveSpriteVoiceText: (name: string, spriteIndex: number, voiceText: string) => Promise<Character>;
  saveSpriteVoiceType: (name: string, spriteIndex: number, voiceType: SpriteVoiceType) => Promise<Character>;
  deleteAllSprites: (name: string) => Promise<Character>;
  deleteSprite: (name: string, spriteIndex: number) => Promise<Character>;
  translateFields: (input: {
    characterSetting: string;
    emotionTags: string;
    name: string;
  }) => Promise<CharacterTranslateResult>;
  uploadSprites: (input: { emotionTags: string; name: string; paths: string[] }) => Promise<Character>;
  uploadSpriteVoice: (input: {
    name: string;
    spriteIndex: number;
    voicePath: string;
    voiceText: string;
    voiceType?: SpriteVoiceType;
  }) => Promise<Character>;
}
