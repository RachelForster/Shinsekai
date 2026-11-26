import type { Dispatch, SetStateAction } from "react";

import type { SchemaErrorMap } from "../../entities/config/schema";
import type { AdapterCatalog, ApiConfig, AppConfig, SystemConfig } from "../../entities/config/types";
import type { FormGroupSchema } from "../../shared/form-schema";

export type AdapterExtraBucket =
  | "llm_extra_configs"
  | "t2i_extra_configs"
  | "tts_extra_configs"
  | "vision_extra_configs";

export interface ApiSettingsPageContext {
  adapterCatalog: AdapterCatalog | undefined;
  apiSchema: Array<FormGroupSchema<ApiConfig>>;
  configReloadRevision: number;
  data: AppConfig;
  draft: ApiConfig;
  errors: SchemaErrorMap<ApiConfig>;
  handleResume: () => void;
  handleSave: () => void;
  initializationPending: boolean;
  installedTtsBundlePathForProvider: (provider: string) => string;
  invalidateLlmCredentials: () => void;
  llmCredentialRevision: number;
  persistSystemDraftForModel: () => Promise<void>;
  resumeDisabled: boolean;
  resumePending: boolean;
  savePending: boolean;
  setDraft: Dispatch<SetStateAction<ApiConfig | null>>;
  setSystemDraft: Dispatch<SetStateAction<SystemConfig | null>>;
  systemDraft: SystemConfig;
  updateAdapterExtra: (bucket: AdapterExtraBucket, provider: string, key: string, value: unknown) => void;
  updateDraft: (patch: Partial<ApiConfig>) => void;
  updateDraftSynced: (nextDraft: ApiConfig) => void;
  updateSystemDraft: (patch: Partial<SystemConfig>) => void;
}
