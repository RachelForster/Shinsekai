import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { SchemaErrorMap } from "../../../entities/config/schema";
import { configQueryKey, getAppConfig, saveApiConfig, saveSystemConfig } from "../../../entities/config/repository";
import type { ApiConfig, AppConfig, SystemConfig } from "../../../entities/config/types";
import { installMissingRuntimeDependency, resumeLastChat } from "../../../entities/chat/repository";
import { useAppState } from "../../../shared/app-state/AppState";
import { showChatSurface } from "../../../shared/desktop/chatWindow";
import { useI18n } from "../../../shared/i18n";
import { useToast } from "../../../shared/ui";
import { useChatInitialization } from "../../chat-startup/useChatInitialization";
import { useChatLaunchGuard } from "../../chat-startup/useChatLaunchGuard";
import { useMobileAccessPreference } from "../../mobile-access/useMobileAccessPreference";
import {
  apiSchemaWithAdapterOptions,
  normalizeApiConfigForUi,
  normalizeSystemAsrForSave,
  normalizeTtsProvider,
  normalizeUiLanguage,
  syncCompactRatioDraft,
} from "../apiSettingsUtils";
import type { AdapterExtraBucket, ApiSettingsPageContext } from "../apiSettingsContext";
import { validateAndBuildApiSettingsPayload } from "./apiSettingsValidation";

export type { ApiSettingsPageContext } from "../apiSettingsContext";

export function useApiSettingsPageController() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { t } = useI18n();
  const { dispatch } = useAppState();
  const [mobileAccessEnabled] = useMobileAccessPreference();
  const configQuery = useQuery({ queryFn: getAppConfig, queryKey: configQueryKey });
  const { refreshRuntimeStatus, runtimeLaunchDisabled, updateRuntimeStatusFromSnapshot } = useChatLaunchGuard();
  const initialization = useChatInitialization();
  const { runChatInitialization } = initialization;
  const { data, isLoading } = configQuery;

  const [draft, setDraft] = useState<ApiConfig | null>(null);
  const [systemDraft, setSystemDraft] = useState<SystemConfig | null>(null);
  const [errors, setErrors] = useState<SchemaErrorMap<ApiConfig>>({});
  const [configReloadRevision, setConfigReloadRevision] = useState(0);
  const [llmCredentialRevision, setLlmCredentialRevision] = useState(0);

  const installedTtsBundlePathForProvider = useCallback(
    (provider: string) => {
      const normalizedProvider = normalizeTtsProvider(provider);
      return data?.tts_bundle_installed_paths?.[normalizedProvider] ?? "";
    },
    [data?.tts_bundle_installed_paths],
  );

  const installedTtsPathsRef = useRef(installedTtsBundlePathForProvider);
  installedTtsPathsRef.current = installedTtsBundlePathForProvider;

  useEffect(() => {
    if (data?.api_config) {
      setDraft(normalizeApiConfigForUi(data.api_config, installedTtsPathsRef.current(data.api_config.tts_provider)));
      setConfigReloadRevision((value) => value + 1);
      setErrors({});
    }
  }, [data?.api_config, data?.tts_bundle_installed_paths]);

  useEffect(() => {
    if (data?.system_config) {
      setSystemDraft(data.system_config);
      dispatch({ language: normalizeUiLanguage(data.system_config.ui_language), type: "setLanguage" });
    }
  }, [data?.system_config, dispatch]);

  const adapterCatalog = data?.adapter_catalog;
  const apiSchema = useMemo(
    () => apiSchemaWithAdapterOptions(adapterCatalog, draft, t),
    [adapterCatalog, draft?.t2i_provider, draft?.tts_provider, t],
  );

  const saveMutation = useMutation({
    mutationFn: async (payload: { api: ApiConfig; system: SystemConfig }) => {
      const savedApi = await saveApiConfig(payload.api);
      const savedSystem = await saveSystemConfig(payload.system);
      return { api: savedApi, system: savedSystem };
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("api.error.saveFallback"),
        title: t("common.saveFailed"),
      });
    },
    onSuccess({ system }) {
      queryClient.invalidateQueries({ queryKey: configQueryKey });
      setSystemDraft(system);
      dispatch({ language: normalizeUiLanguage(system.ui_language), type: "setLanguage" });
      showToast({ kind: "success", title: t("api.toast.saved") });
    },
  });

  const resumeMutation = useMutation({
    mutationFn: async () => {
      if (runtimeLaunchDisabled) {
        throw new Error(t("launch.runtimeBusy"));
      }
      return runChatInitialization((options) => resumeLastChat(options, { enableMobileAccess: mobileAccessEnabled }));
    },
    onError(error) {
      void refreshRuntimeStatus();
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("api.resume.tip"),
        title: t("api.resume.title"),
      });
    },
    onSuccess(snapshot) {
      void updateRuntimeStatusFromSnapshot(snapshot);
      if (snapshot.runtimeDependencyError) {
        const dependencyError = snapshot.runtimeDependencyError;
        const shouldInstall = window.confirm(
          t("runtimeDeps.installConfirm", {
            module: dependencyError.moduleName,
            package: dependencyError.packageName,
          }),
        );
        if (!shouldInstall) {
          showToast({ kind: "error", message: snapshot.dialogText, title: t("api.resume.title") });
          return;
        }
        void installMissingRuntimeDependency({ moduleName: dependencyError.moduleName })
          .then((result) => {
            showToast({
              kind: "success",
              message: result.message || t("runtimeDeps.installSucceeded"),
              title: t("runtimeDeps.installTitle"),
            });
          })
          .catch((error: unknown) => {
            showToast({
              kind: "error",
              message: error instanceof Error ? error.message : t("runtimeDeps.installFailed"),
              title: t("runtimeDeps.installFailed"),
            });
          });
        return;
      }
      showToast({
        kind: "success",
        message: snapshot.statusMessage || snapshot.dialogText,
        title: t("api.resume.title"),
      });
      void showChatSurface({ snapshot });
    },
  });

  const invalidateLlmCredentials = useCallback(() => {
    setLlmCredentialRevision((value) => value + 1);
  }, []);

  const updateDraft = useCallback((patch: Partial<ApiConfig>) => {
    setDraft((current) => (current ? { ...current, ...patch } : current));
  }, []);

  const updateDraftSynced = useCallback((nextDraft: ApiConfig) => {
    setDraft(syncCompactRatioDraft(nextDraft));
  }, []);

  const updateSystemDraft = useCallback((patch: Partial<SystemConfig>) => {
    setSystemDraft((current) => (current ? { ...current, ...patch } : current));
  }, []);

  const updateAdapterExtra = useCallback(
    (bucket: AdapterExtraBucket, provider: string, key: string, value: unknown) => {
      setDraft((current) =>
        current
          ? {
              ...current,
              [bucket]: {
                ...current[bucket],
                [provider]: {
                  ...(current[bucket]?.[provider] ?? {}),
                  [key]: value,
                },
              },
            }
          : current,
      );
    },
    [],
  );

  const persistSystemDraftForModel = useCallback(async () => {
    if (!systemDraft) return;
    const saved = await saveSystemConfig(normalizeSystemAsrForSave(systemDraft));
    queryClient.setQueryData<AppConfig>(configQueryKey, (current) =>
      current ? { ...current, system_config: saved } : current,
    );
    setSystemDraft(saved);
  }, [queryClient, systemDraft]);

  const handleSave = useCallback(() => {
    if (!draft || !systemDraft) return;
    const result = validateAndBuildApiSettingsPayload({ apiSchema, draft, systemDraft, t });
    setErrors(result.errors);
    if (!result.payload) {
      if (result.errorMessage) {
        showToast({ kind: "error", message: result.errorMessage, title: t("common.validationFailed") });
      }
      return;
    }
    saveMutation.mutate(result.payload);
  }, [apiSchema, draft, saveMutation, showToast, systemDraft, t]);

  const handleResume = useCallback(() => {
    resumeMutation.mutate();
  }, [resumeMutation]);

  const ctx: ApiSettingsPageContext | null =
    !isLoading && data && draft && systemDraft
      ? {
          adapterCatalog,
          apiSchema,
          configReloadRevision,
          data,
          draft,
          errors,
          handleResume,
          handleSave,
          initializationPending: initialization.initializationPending,
          installedTtsBundlePathForProvider,
          invalidateLlmCredentials,
          llmCredentialRevision,
          persistSystemDraftForModel,
          resumeDisabled: runtimeLaunchDisabled || initialization.initializationPending,
          resumePending: resumeMutation.isPending,
          savePending: saveMutation.isPending,
          setDraft,
          setSystemDraft,
          systemDraft,
          updateAdapterExtra,
          updateDraft,
          updateDraftSynced,
          updateSystemDraft,
        }
      : null;

  return {
    ctx,
    initialization,
    isError: configQuery.isError,
    queryError: configQuery.error,
    refetchConfig: () => void configQuery.refetch(),
  };
}
