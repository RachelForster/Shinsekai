import type { Background } from "../../entities/config/types";
import type { AutoSavePhase } from "../../shared/hooks/useDebouncedAutoSave";

export const BACKGROUND_RESOURCES_URL = "https://shinsekai.end0rph1n.icu/resources";

export interface BackgroundSyncOptions {
  invalidate?: boolean;
  mode?: "none" | "replace" | "upsert";
}

export interface BackgroundPageContext {
  autoSaveError: string;
  autoSavePhase: AutoSavePhase;
  autoSaveRetry: () => void;
  cancelCreatingBackground: () => void;
  cancelDeleteBackground: () => void;
  cancelIdentityField: (field: "name" | "sprite_prefix") => void;
  confirmDeleteBackground: () => void;
  confirmIdentityField: (field: "name" | "sprite_prefix") => void;
  currentBackgroundName: string;
  currentDraft: Background;
  data: Background[];
  draftMatchesSelection: boolean;
  exportCurrentBackground: () => void;
  exportPending: boolean;
  identitySavingField: "name" | "sprite_prefix" | null;
  importBackgrounds: (paths: string[]) => void;
  importPending: boolean;
  inCreateMode: boolean;
  invalidateBackgrounds: () => void;
  isCreating: boolean;
  isError: boolean;
  isLoading: boolean;
  isSavedBackground: boolean;
  liveNameError: string;
  liveSpritePrefixError: string;
  nameDirty: boolean;
  patchActiveDraft: (updater: (baseDraft: Background) => Background) => void;
  patchDraft: (updater: (current: Background) => Background) => void;
  pendingBackgroundDelete: string | null;
  queryError: unknown;
  refetchBackgrounds: () => void;
  requestDeleteBackground: () => void;
  saveBulkTags: (field: "bg_tags" | "bgm_tags", nextTags: string) => void;
  saveDraft: () => void;
  savePending: boolean;
  selected: Background | undefined;
  selectedBackgroundKey: string;
  selectedName: string;
  selectBackground: (name: string) => void;
  setNameError: (message: string) => void;
  setSectionBusy: (sectionId: string, busy: boolean) => void;
  spritePrefixDirty: boolean;
  startCreatingBackground: () => void;
  syncSavedBackground: (
    background: Background,
    patchDraftFromBackground: (current: Background, saved: Background) => Background,
    options?: BackgroundSyncOptions,
  ) => void;
  updateField: <K extends keyof Background>(name: K, value: Background[K]) => void;
  visionAvailable: boolean;
}
