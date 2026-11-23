import type { Effect } from "../../entities/config/types";
import type { AutoSavePhase } from "../../shared/hooks/useDebouncedAutoSave";

export interface EnsureSavedOptions {
  requireNonEmptyNameWhenSaved?: boolean;
  toastTitle?: string;
}

export interface EffectPageContext {
  autoSaveError: string;
  autoSavePhase: AutoSavePhase;
  autoSaveRetry: () => void;
  cancelCreatingEffect: () => void;
  cancelDeleteEffect: () => void;
  cancelIdentityName: () => void;
  confirmDeleteEffect: () => void;
  confirmIdentityName: () => void;
  currentEffectName: string;
  data: Effect[];
  draft: Effect;
  ensureSavedForAction: (onReady: () => void, options?: EnsureSavedOptions) => void;
  exportCurrentEffect: () => void;
  exportPending: boolean;
  identityPending: boolean;
  importEffects: (paths: string[]) => void;
  importPending: boolean;
  inCreateMode: boolean;
  invalidateEffects: () => void;
  isCreating: boolean;
  isLoading: boolean;
  liveNameError: string;
  nameDirty: boolean;
  patchDraft: (updater: (current: Effect) => Effect) => void;
  pendingEffectDelete: string | null;
  requestDeleteEffect: () => void;
  saveDraft: () => void;
  savePending: boolean;
  selectedEffectKey: string;
  selectedName: string;
  selectEffect: (name: string) => void;
  setSectionBusy: (sectionId: string, busy: boolean) => void;
  startCreatingEffect: () => void;
  syncSavedEffect: (
    effect: Effect,
    patchDraftFromEffect: (current: Effect, saved: Effect) => Effect,
    options?: { invalidate?: boolean },
  ) => void;
  updateField: <K extends keyof Effect>(name: K, value: Effect[K]) => void;
}
