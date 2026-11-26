import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, KeyRound, Laptop, PlugZap, Sparkles, Upload } from "lucide-react";
import { useNavigate } from "react-router-dom";

import {
  charactersQueryKey,
  exportCharacter,
  importCharacters,
  listCharacters,
} from "../../entities/character/repository";
import { configQueryKey, getAppConfig, saveApiConfig, testLlmConnection } from "../../entities/config/repository";
import type { Character } from "../../entities/config/types";
import { llmDefaultBaseUrls, llmProviderOptions } from "../../entities/config/schema";
import { LLM_PROVIDER_SILICONFLOW } from "../../shared/constants";
import { resolveFormOptionLabel } from "../../shared/form-schema";
import { useOptionalI18n } from "../../shared/i18n";
import { resetPlatformForModeSwitch } from "../../shared/platform/platform";
import {
  canConnectRemotePc,
  getRemoteBridgeConfig,
  getRuntimeTarget,
  isRemotePcActive,
  saveRemoteBridgeConfig,
  type MobileConnectionMode,
} from "../../shared/platform/runtimeTarget";
import {
  listRemotePcCharacters,
  syncCharacterFromRemotePc,
  testRemotePcBridge,
} from "../../shared/platform/standalone";
import { getLlmProviderPreset } from "../../shared/platform/standalone/ai/adapters/llm/presets";
import {
  buildStandaloneAdapterCatalog,
  listRegisteredTtsAdapters,
} from "../../shared/platform/standalone/ai/adapters/registry";
import { Button, Dialog, Select, TextInput, useToast } from "../../shared/ui";
import "./RuntimeModeDialog.css";

interface RuntimeModeDialogProps {
  open: boolean;
  onClose: () => void;
}

type DialogTab = "keys" | "characters" | "remote";

export function RuntimeModeDialog({ open, onClose }: RuntimeModeDialogProps) {
  const { t } = useOptionalI18n();
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const target = getRuntimeTarget();
  const allowRemotePc = canConnectRemotePc();
  const remoteActive = isRemotePcActive();

  const [activeTab, setActiveTab] = useState<DialogTab>("keys");
  const configQuery = useQuery({
    queryFn: getAppConfig,
    queryKey: configQueryKey,
    enabled: open,
  });
  const charactersQuery = useQuery({
    queryFn: listCharacters,
    queryKey: charactersQueryKey,
    enabled: open,
  });

  // Quick Key state
  const [llmProvider, setLlmProvider] = useState(LLM_PROVIDER_SILICONFLOW);
  const [llmApiKey, setLlmApiKey] = useState("");
  const [llmBaseUrl, setLlmBaseUrl] = useState("https://api.siliconflow.cn/v1");
  const [llmModel, setLlmModel] = useState("deepseek-ai/DeepSeek-V3");
  const [ttsProvider, setTtsProvider] = useState("openai-speech");
  const [ttsReuseLlmKey, setTtsReuseLlmKey] = useState(true);
  const [ttsApiKey, setTtsApiKey] = useState("");
  const [ttsBaseUrl, setTtsBaseUrl] = useState("https://api.siliconflow.cn/v1");
  const [ttsVoiceId, setTtsVoiceId] = useState("FunAudioLLM/CosyVoice2-0.5B:claire");
  const [ttsGroupId, setTtsGroupId] = useState("");
  const [savingKeys, setSavingKeys] = useState(false);
  const [testingLlm, setTestingLlm] = useState(false);

  // Remote PC bridge state
  const initialBridge = getRemoteBridgeConfig();
  const [connectionMode, setConnectionMode] = useState<MobileConnectionMode>(initialBridge.mode);
  const [remoteUrl, setRemoteUrl] = useState(initialBridge.url);
  const [remoteToken, setRemoteToken] = useState(initialBridge.token);
  const [testingRemote, setTestingRemote] = useState(false);
  const [remoteStatusMsg, setRemoteStatusMsg] = useState("");
  const [remoteCharacters, setRemoteCharacters] = useState<Character[]>([]);
  const [syncingCharName, setSyncingCharName] = useState<string | null>(null);

  // Character import state
  const charFileInputRef = useRef<HTMLInputElement>(null);
  const [importingChar, setImportingChar] = useState(false);

  const loadTtsFieldsFromConfig = (
    providerId: string,
    extraConfigs: Record<string, Record<string, unknown>> | undefined,
  ) => {
    const adapter = listRegisteredTtsAdapters().find((item) => item.id === providerId);
    const extra = extraConfigs?.[providerId] ?? {};
    setTtsReuseLlmKey(extra.reuse_llm_key !== false);
    setTtsApiKey(typeof extra.api_key === "string" ? extra.api_key : "");
    setTtsBaseUrl(
      typeof extra.base_api_url === "string" && extra.base_api_url
        ? extra.base_api_url
        : String(adapter?.schema.base_api_url?.default ?? ""),
    );
    setTtsVoiceId(
      typeof extra.default_voice_id === "string" && extra.default_voice_id
        ? extra.default_voice_id
        : String(adapter?.schema.default_voice_id?.default ?? ""),
    );
    setTtsGroupId(typeof extra.group_id === "string" ? extra.group_id : "");
  };

  useEffect(() => {
    if (!open || !configQuery.data) return;
    const api = configQuery.data.api_config;
    const provider = api.llm_provider || LLM_PROVIDER_SILICONFLOW;
    const preset = getLlmProviderPreset(provider);
    setLlmProvider(provider);
    setLlmApiKey(api.llm_api_key?.[provider] ?? "");
    setLlmBaseUrl(
      api.llm_base_urls?.[provider] || api.llm_base_url || llmDefaultBaseUrls[provider] || preset.defaultBaseUrl,
    );
    setLlmModel(api.llm_model?.[provider] || preset.defaultModel);

    const activeTts = api.tts_provider || "openai-speech";
    setTtsProvider(activeTts);
    loadTtsFieldsFromConfig(activeTts, api.tts_extra_configs);
  }, [open, configQuery.data]);

  const handleLlmProviderSwitch = (nextProvider: string) => {
    const api = configQuery.data?.api_config;
    const preset = getLlmProviderPreset(nextProvider);
    setLlmProvider(nextProvider);
    setLlmApiKey(api?.llm_api_key?.[nextProvider] ?? "");
    setLlmBaseUrl(api?.llm_base_urls?.[nextProvider] || llmDefaultBaseUrls[nextProvider] || preset.defaultBaseUrl);
    setLlmModel(api?.llm_model?.[nextProvider] || preset.defaultModel);
  };

  const handleTtsProviderSwitch = (nextTts: string) => {
    setTtsProvider(nextTts);
    loadTtsFieldsFromConfig(nextTts, configQuery.data?.api_config.tts_extra_configs);
  };

  const handleSaveKeys = async () => {
    const currentConfig = configQuery.data;
    if (!currentConfig) return;
    setSavingKeys(true);
    try {
      const currentApi = currentConfig.api_config;
      const nextApi = {
        ...currentApi,
        llm_provider: llmProvider,
        llm_base_url: llmBaseUrl.trim(),
        llm_api_key: {
          ...currentApi.llm_api_key,
          [llmProvider]: llmApiKey.trim(),
        },
        llm_base_urls: {
          ...currentApi.llm_base_urls,
          [llmProvider]: llmBaseUrl.trim(),
        },
        llm_model: {
          ...currentApi.llm_model,
          [llmProvider]: llmModel.trim(),
        },
        tts_provider: ttsProvider,
        tts_extra_configs: {
          ...currentApi.tts_extra_configs,
          ...(ttsProvider !== "none"
            ? {
                [ttsProvider]: {
                  ...(currentApi.tts_extra_configs?.[ttsProvider] ?? {}),
                  reuse_llm_key: ttsReuseLlmKey,
                  api_key: ttsApiKey.trim(),
                  base_api_url: ttsBaseUrl.trim(),
                  default_voice_id: ttsVoiceId.trim(),
                  ...(ttsProvider === "minimax-tts" ? { group_id: ttsGroupId.trim() } : {}),
                },
              }
            : {}),
        },
      };

      await saveApiConfig(nextApi);
      await queryClient.invalidateQueries({ queryKey: configQueryKey });
      showToast({
        kind: "success",
        title: t("ops.runtime.keysSavedTitle"),
        message: t("ops.runtime.keysSavedMsg"),
      });
    } catch (error) {
      showToast({
        kind: "error",
        title: t("ops.runtime.saveFailed"),
        message: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setSavingKeys(false);
    }
  };

  const handleTestLlm = async () => {
    setTestingLlm(true);
    try {
      const result = await testLlmConnection({
        provider: llmProvider,
        apiKey: llmApiKey.trim(),
        baseUrl: llmBaseUrl.trim(),
        model: llmModel.trim(),
      });
      showToast({
        kind: "success",
        title: t("ops.runtime.testPassed"),
        message: result.message,
      });
    } catch (error) {
      showToast({
        kind: "error",
        title: t("ops.runtime.testFailed"),
        message: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setTestingLlm(false);
    }
  };

  const handleImportCharFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (!files.length) return;
    setImportingChar(true);
    try {
      const imported = await importCharacters(files);
      await queryClient.invalidateQueries({ queryKey: charactersQueryKey });
      await queryClient.invalidateQueries({ queryKey: configQueryKey });
      showToast({
        kind: "success",
        title: t("ops.runtime.charImportedTitle"),
        message: t("ops.runtime.charImportedMsg", {
          names: imported.map((c) => c.name).join(t("ops.runtime.listSeparator")),
        }),
      });
    } catch (error) {
      showToast({
        kind: "error",
        title: t("ops.runtime.charImportFailed"),
        message: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setImportingChar(false);
    }
  };

  const handleExportChar = async (name: string) => {
    try {
      await exportCharacter(name);
      showToast({
        kind: "success",
        title: t("ops.runtime.charExportedTitle"),
        message: t("ops.runtime.charExportedMsg", { name }),
      });
    } catch (error) {
      showToast({
        kind: "error",
        title: t("ops.runtime.charExportFailed"),
        message: error instanceof Error ? error.message : String(error),
      });
    } finally {
      // no-op
    }
  };

  const handleTestRemoteBridge = async () => {
    setTestingRemote(true);
    setRemoteStatusMsg("");
    try {
      const result = await testRemotePcBridge({
        bridgeUrl: remoteUrl,
        token: remoteToken,
      });
      setRemoteStatusMsg(result.message);
      const remoteChars = await listRemotePcCharacters({
        bridgeUrl: remoteUrl,
        token: remoteToken,
      });
      setRemoteCharacters(remoteChars);
      showToast({
        kind: "success",
        title: t("ops.runtime.pcConnected"),
        message: result.message,
      });
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      setRemoteStatusMsg(msg);
      showToast({
        kind: "error",
        title: t("ops.runtime.pcConnectFailed"),
        message: msg,
      });
    } finally {
      setTestingRemote(false);
    }
  };

  const handleApplyConnectionMode = async (nextMode: MobileConnectionMode) => {
    const cleanUrl = remoteUrl.trim().replace(/\/+$/, "");
    if (nextMode === "remote-pc" && !cleanUrl) {
      showToast({
        kind: "error",
        title: t("ops.runtime.pcAddressRequiredTitle"),
        message: t("ops.runtime.pcAddressRequiredMsg"),
      });
      return;
    }
    setConnectionMode(nextMode);
    saveRemoteBridgeConfig({
      mode: nextMode,
      url: cleanUrl,
      token: remoteToken.trim(),
    });
    resetPlatformForModeSwitch();
    await queryClient.invalidateQueries();
    showToast({
      kind: "success",
      title: nextMode === "remote-pc" ? t("ops.runtime.switchedPcTitle") : t("ops.runtime.switchedStandaloneTitle"),
      message: nextMode === "remote-pc" ? t("ops.runtime.switchedPcMsg") : t("ops.runtime.switchedStandaloneMsg"),
    });
  };

  const handleSyncCharacterFromPc = async (name: string) => {
    setSyncingCharName(name);
    try {
      const imported = await syncCharacterFromRemotePc({
        bridgeUrl: remoteUrl,
        token: remoteToken,
        characterName: name,
      });
      if (connectionMode === "standalone") {
        await queryClient.invalidateQueries({ queryKey: charactersQueryKey });
        await queryClient.invalidateQueries({ queryKey: configQueryKey });
      }
      showToast({
        kind: "success",
        title: t("ops.runtime.syncCharTitle"),
        message: t("ops.runtime.syncCharMsg", { name: imported[0]?.name || name }),
      });
    } catch (error) {
      showToast({
        kind: "error",
        title: t("ops.runtime.syncCharFailed"),
        message: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setSyncingCharName(null);
    }
  };

  const catalogTtsOptions = configQuery.data?.adapter_catalog?.tts ?? buildStandaloneAdapterCatalog(target).tts;
  const selectedTtsAdapter = listRegisteredTtsAdapters().find((a) => a.id === ttsProvider);
  const selectedTtsNeedsCorsProxy =
    (target === "toy" || target === "web") && selectedTtsAdapter?.browserCors === "proxy-only";

  return (
    <Dialog
      bodyClassName="runtime-mode-dialog__body"
      className="runtime-mode-dialog"
      closeLabel={t("ops.runtime.close")}
      footer={
        <div className="runtime-mode-dialog__footer">
          <Button
            onClick={() => {
              onClose();
              navigate("/settings/api");
            }}
            type="button"
          >
            {t("ops.runtime.fullWorkbench")}
          </Button>
          <Button onClick={onClose} type="button" variant="primary">
            {t("ops.runtime.done")}
          </Button>
        </div>
      }
      onClose={onClose}
      open={open}
      title={t("ops.runtime.title")}
    >
      <div className="runtime-mode-dialog__tabs" role="tablist">
        <button
          aria-selected={activeTab === "keys"}
          className="runtime-mode-dialog__tab"
          data-active={activeTab === "keys" ? "true" : "false"}
          onClick={() => setActiveTab("keys")}
          role="tab"
          type="button"
        >
          <KeyRound aria-hidden size={15} />
          <span>{t("ops.runtime.tabKeys")}</span>
        </button>
        <button
          aria-selected={activeTab === "characters"}
          className="runtime-mode-dialog__tab"
          data-active={activeTab === "characters" ? "true" : "false"}
          onClick={() => setActiveTab("characters")}
          role="tab"
          type="button"
        >
          <Sparkles aria-hidden size={15} />
          <span>{t("ops.runtime.tabCharacters")}</span>
        </button>
        {allowRemotePc ? (
          <button
            aria-selected={activeTab === "remote"}
            className="runtime-mode-dialog__tab"
            data-active={activeTab === "remote" ? "true" : "false"}
            onClick={() => setActiveTab("remote")}
            role="tab"
            type="button"
          >
            <Laptop aria-hidden size={15} />
            <span>{remoteActive ? t("ops.runtime.tabRemoteActive") : t("ops.runtime.tabRemoteIdle")}</span>
          </button>
        ) : null}
      </div>

      {activeTab === "keys" ? (
        <div className="runtime-mode-dialog__section">
          <p className="runtime-mode-dialog__hint">{t("ops.runtime.keysHint")}</p>

          <div className="runtime-mode-dialog__grid">
            <label className="runtime-mode-dialog__field">
              <span>{t("ops.runtime.llmProviderLabel")}</span>
              <Select onChange={(e) => handleLlmProviderSwitch(e.target.value)} value={llmProvider}>
                {llmProviderOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {resolveFormOptionLabel(opt, t)}
                  </option>
                ))}
              </Select>
            </label>

            <label className="runtime-mode-dialog__field">
              <span>{t("ops.runtime.modelIdLabel")}</span>
              <TextInput
                onChange={(e) => setLlmModel(e.target.value)}
                placeholder="deepseek-ai/DeepSeek-V3"
                value={llmModel}
              />
            </label>

            <label className="runtime-mode-dialog__field runtime-mode-dialog__field--full">
              <span>LLM API Key</span>
              <TextInput
                autoComplete="off"
                onChange={(e) => setLlmApiKey(e.target.value)}
                placeholder="sk-..."
                type="password"
                value={llmApiKey}
              />
            </label>

            <label className="runtime-mode-dialog__field runtime-mode-dialog__field--full">
              <span>{t("ops.runtime.baseUrlLabel")}</span>
              <TextInput
                onChange={(e) => setLlmBaseUrl(e.target.value)}
                placeholder="https://api.siliconflow.cn/v1"
                value={llmBaseUrl}
              />
            </label>
          </div>

          <hr className="runtime-mode-dialog__divider" />

          <div className="runtime-mode-dialog__grid">
            <label className="runtime-mode-dialog__field runtime-mode-dialog__field--full">
              <span>{t("ops.runtime.ttsProviderLabel")}</span>
              <Select onChange={(e) => handleTtsProviderSwitch(e.target.value)} value={ttsProvider}>
                {catalogTtsOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </Select>
            </label>

            {selectedTtsNeedsCorsProxy ? (
              <p className="runtime-mode-dialog__warn">{t("ops.runtime.corsWarn", { provider: ttsProvider })}</p>
            ) : null}

            {ttsProvider !== "none" && ttsProvider !== "browser-speech" ? (
              <>
                {ttsProvider === "openai-speech" ? (
                  <label className="runtime-mode-dialog__checkbox runtime-mode-dialog__field--full">
                    <input
                      checked={ttsReuseLlmKey}
                      onChange={(e) => setTtsReuseLlmKey(e.target.checked)}
                      type="checkbox"
                    />
                    <span>{t("ops.runtime.reuseLlmKey")}</span>
                  </label>
                ) : null}

                {!(ttsProvider === "openai-speech" && ttsReuseLlmKey) ? (
                  <label className="runtime-mode-dialog__field runtime-mode-dialog__field--full">
                    <span>{t("ops.runtime.ttsApiKeyLabel")}</span>
                    <TextInput
                      autoComplete="off"
                      onChange={(e) => setTtsApiKey(e.target.value)}
                      placeholder={t("ops.runtime.ttsApiKeyPlaceholder")}
                      type="password"
                      value={ttsApiKey}
                    />
                  </label>
                ) : null}

                <label className="runtime-mode-dialog__field">
                  <span>{t("ops.runtime.ttsVoiceIdLabel")}</span>
                  <TextInput
                    onChange={(e) => setTtsVoiceId(e.target.value)}
                    placeholder="FunAudioLLM/CosyVoice2-0.5B:claire"
                    value={ttsVoiceId}
                  />
                </label>

                <label className="runtime-mode-dialog__field">
                  <span>{t("ops.runtime.ttsBaseUrlLabel")}</span>
                  <TextInput
                    onChange={(e) => setTtsBaseUrl(e.target.value)}
                    placeholder="https://api.siliconflow.cn/v1"
                    value={ttsBaseUrl}
                  />
                </label>

                {ttsProvider === "minimax-tts" ? (
                  <label className="runtime-mode-dialog__field runtime-mode-dialog__field--full">
                    <span>MiniMax Group ID</span>
                    <TextInput
                      onChange={(e) => setTtsGroupId(e.target.value)}
                      placeholder={t("ops.runtime.groupIdPlaceholder")}
                      value={ttsGroupId}
                    />
                  </label>
                ) : null}
              </>
            ) : null}
          </div>

          <div className="runtime-mode-dialog__actions">
            <Button
              disabled={testingLlm}
              icon={<PlugZap aria-hidden className="button__icon" />}
              onClick={() => void handleTestLlm()}
              type="button"
            >
              {testingLlm ? t("ops.runtime.testing") : t("ops.runtime.testLlm")}
            </Button>
            <Button
              disabled={savingKeys || !configQuery.data}
              onClick={() => void handleSaveKeys()}
              type="button"
              variant="primary"
            >
              {savingKeys ? t("ops.runtime.saving") : t("ops.runtime.saveConfig")}
            </Button>
          </div>
        </div>
      ) : null}

      {activeTab === "characters" ? (
        <div className="runtime-mode-dialog__section">
          <p className="runtime-mode-dialog__hint">{t("ops.runtime.charHint")}</p>

          <input
            accept=".char,.zip,application/zip,application/octet-stream"
            className="runtime-mode-dialog__file-input"
            multiple
            onChange={(e) => void handleImportCharFile(e)}
            ref={charFileInputRef}
            type="file"
          />

          <div className="runtime-mode-dialog__actions">
            <Button
              disabled={importingChar}
              icon={<Upload aria-hidden className="button__icon" />}
              onClick={() => charFileInputRef.current?.click()}
              type="button"
              variant="primary"
            >
              {importingChar ? t("ops.runtime.importingChar") : t("ops.runtime.importChar")}
            </Button>
            <Button
              onClick={() => {
                onClose();
                navigate("/settings/characters");
              }}
              type="button"
            >
              {t("ops.runtime.openCharacterStudio")}
            </Button>
          </div>

          <div className="runtime-mode-dialog__char-list">
            {(charactersQuery.data ?? []).map((char) => (
              <div className="runtime-mode-dialog__char-item" key={char.name}>
                <div>
                  <strong>{char.name}</strong>
                  <span className="runtime-mode-dialog__char-meta">
                    {t("ops.runtime.charSpriteCount", { count: char.sprites?.length ?? 0 })} ·{" "}
                    {char.avatar_type || "static"}
                  </span>
                </div>
                <Button
                  icon={<Download aria-hidden className="button__icon" />}
                  onClick={() => void handleExportChar(char.name)}
                  type="button"
                >
                  {t("ops.runtime.exportChar")}
                </Button>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {activeTab === "remote" && allowRemotePc ? (
        <div className="runtime-mode-dialog__section">
          <p className="runtime-mode-dialog__hint">
            {remoteActive ? t("ops.runtime.pcHintActive") : t("ops.runtime.pcHintIdle")}
          </p>

          <div className="runtime-mode-dialog__grid">
            <label className="runtime-mode-dialog__field runtime-mode-dialog__field--full">
              <span>{t("ops.runtime.pcAddressLabel")}</span>
              <TextInput
                onChange={(e) => setRemoteUrl(e.target.value)}
                placeholder="http://192.168.1.100:8787"
                value={remoteUrl}
              />
            </label>
            <label className="runtime-mode-dialog__field runtime-mode-dialog__field--full">
              <span>{t("ops.runtime.pcTokenLabel")}</span>
              <TextInput
                autoComplete="off"
                onChange={(e) => setRemoteToken(e.target.value)}
                placeholder={t("ops.runtime.pcTokenPlaceholder")}
                type="password"
                value={remoteToken}
              />
            </label>
          </div>

          {remoteStatusMsg ? <p className="runtime-mode-dialog__hint">{remoteStatusMsg}</p> : null}

          <div className="runtime-mode-dialog__actions">
            <Button
              disabled={testingRemote}
              icon={<PlugZap aria-hidden className="button__icon" />}
              onClick={() => void handleTestRemoteBridge()}
              type="button"
            >
              {testingRemote ? t("ops.runtime.testing") : t("ops.runtime.testAndFetchChars")}
            </Button>
            {connectionMode === "remote-pc" || remoteActive ? (
              <Button onClick={() => void handleApplyConnectionMode("standalone")} type="button">
                {t("ops.runtime.switchToMobile")}
              </Button>
            ) : null}
            <Button onClick={() => void handleApplyConnectionMode("remote-pc")} type="button" variant="primary">
              {t("ops.runtime.connectPcFull")}
            </Button>
          </div>

          {remoteCharacters.length > 0 ? (
            <div className="runtime-mode-dialog__char-list">
              {remoteCharacters.map((char) => (
                <div className="runtime-mode-dialog__char-item" key={char.name}>
                  <div>
                    <strong>{char.name}</strong>
                    <span className="runtime-mode-dialog__char-meta">
                      {t("ops.runtime.charSpriteCount", { count: char.sprites?.length ?? 0 })}
                    </span>
                  </div>
                  <Button
                    disabled={syncingCharName === char.name}
                    icon={<Download aria-hidden className="button__icon" />}
                    onClick={() => void handleSyncCharacterFromPc(char.name)}
                    type="button"
                  >
                    {syncingCharName === char.name
                      ? t("ops.runtime.cachingCharacter")
                      : t("ops.runtime.cacheCharacter")}
                  </Button>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </Dialog>
  );
}
