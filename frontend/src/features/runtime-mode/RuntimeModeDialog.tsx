import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Download,
  ImageUp,
  KeyRound,
  Laptop,
  PlugZap,
  QrCode,
  RefreshCw,
  ScanLine,
  Sparkles,
  Upload,
  X,
} from "lucide-react";
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
import { decodeQrFromImageFile, decodeQrFromVideoFrame, parseRemoteBridgeQrPayload } from "./remoteQrScanner";
import "./RuntimeModeDialog.css";

interface RuntimeModeDialogProps {
  open: boolean;
  onClose: () => void;
}

type DialogTab = "keys" | "characters" | "remote";

export function RuntimeModeDialog({ open, onClose }: RuntimeModeDialogProps) {
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
  const [llmProvider, setLlmProvider] = useState("硅基流动");
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
  const [scanningQr, setScanningQr] = useState(false);
  const [cameraFacing, setCameraFacing] = useState<"environment" | "user">("environment");
  const [qrErrorMsg, setQrErrorMsg] = useState("");
  const [decodingQrImage, setDecodingQrImage] = useState(false);
  const [manualExpanded, setManualExpanded] = useState(Boolean(initialBridge.url));
  const videoRef = useRef<HTMLVideoElement>(null);
  const qrFileInputRef = useRef<HTMLInputElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const applyQrHandlerRef = useRef<(rawText: string) => Promise<void>>(async () => {});

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
    const provider = api.llm_provider || "硅基流动";
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
        title: "配置已保存",
        message: "对话模型与云端语音配置已生效。",
      });
    } catch (error) {
      showToast({
        kind: "error",
        title: "保存失败",
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
        title: "测试连接成功",
        message: result.message,
      });
    } catch (error) {
      showToast({
        kind: "error",
        title: "测试连接失败",
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
        title: "角色导入成功",
        message: `已导入 ${imported.map((c) => c.name).join("、")}，可在角色工坊查看或发起新对话。`,
      });
    } catch (error) {
      showToast({
        kind: "error",
        title: "导入角色包失败",
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
        title: "角色包已导出",
        message: `已生成 ${name}.char`,
      });
    } catch (error) {
      showToast({
        kind: "error",
        title: "导出失败",
        message: error instanceof Error ? error.message : String(error),
      });
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
        title: "电脑端连接正常",
        message: result.message,
      });
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      setRemoteStatusMsg(msg);
      showToast({
        kind: "error",
        title: "无法连接电脑端",
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
        title: "请填写电脑端地址",
        message: "例如 http://192.168.1.100:8787",
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
      title: nextMode === "remote-pc" ? "已切换为连电脑端模式" : "已切换为手机独立模式",
      message:
        nextMode === "remote-pc"
          ? "正在直接使用电脑端的本地模型、记忆与资产库。"
          : "已切换至本机 Standalone 存储与自带 API Key 模式。",
    });
  };

  const applyScannedQrPayload = async (rawText: string) => {
    let parsed: { url: string; token: string };
    try {
      parsed = parseRemoteBridgeQrPayload(rawText);
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      setQrErrorMsg(msg);
      showToast({
        kind: "error",
        title: "二维码无效",
        message: msg,
      });
      return;
    }

    const { url, token } = parsed;
    setRemoteUrl(url);
    setRemoteToken(token);
    setQrErrorMsg("");
    setTestingRemote(true);
    setRemoteStatusMsg("");
    try {
      const result = await testRemotePcBridge({
        bridgeUrl: url,
        token,
      });
      const remoteChars = await listRemotePcCharacters({
        bridgeUrl: url,
        token,
      });
      setRemoteCharacters(remoteChars);
      setRemoteStatusMsg(result.message);
      setConnectionMode("remote-pc");
      saveRemoteBridgeConfig({
        mode: "remote-pc",
        url,
        token,
      });
      resetPlatformForModeSwitch();
      await queryClient.invalidateQueries();
      showToast({
        kind: "success",
        title: "扫码连接成功",
        message: `${result.message}，已自动切换至电脑端满血模式。`,
      });
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      setManualExpanded(true);
      setRemoteStatusMsg(msg);
      showToast({
        kind: "error",
        title: "无法连接电脑端",
        message: `${msg}（已自动填入扫码地址，可检查电脑防火墙后重测）`,
      });
    } finally {
      setTestingRemote(false);
    }
  };

  applyQrHandlerRef.current = applyScannedQrPayload;

  useEffect(() => {
    const stopActiveStream = () => {
      if (streamRef.current) {
        for (const track of streamRef.current.getTracks()) {
          track.stop();
        }
        streamRef.current = null;
      }
      if (videoRef.current) {
        videoRef.current.srcObject = null;
      }
    };

    if (!open || activeTab !== "remote" || !scanningQr) {
      stopActiveStream();
      return;
    }

    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setScanningQr(false);
      setQrErrorMsg("当前环境不支持实时调用摄像头，请点击「相册识别二维码」选择电脑端二维码截图。");
      return;
    }

    let cancelled = false;
    let pollTimer: number | undefined;
    let inFlight = false;
    const workCanvas = document.createElement("canvas");

    void (async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: false,
          video: {
            facingMode: { ideal: cameraFacing },
            width: { ideal: 1280 },
            height: { ideal: 720 },
          },
        });
        if (cancelled) {
          for (const track of stream.getTracks()) {
            track.stop();
          }
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play().catch(() => {});
        }
        pollTimer = window.setInterval(() => {
          if (cancelled || inFlight || !videoRef.current) {
            return;
          }
          inFlight = true;
          void decodeQrFromVideoFrame(videoRef.current, workCanvas)
            .then((decoded) => {
              if (decoded && !cancelled) {
                cancelled = true;
                if (pollTimer !== undefined) {
                  window.clearInterval(pollTimer);
                }
                stopActiveStream();
                setScanningQr(false);
                void applyQrHandlerRef.current(decoded);
              }
            })
            .finally(() => {
              inFlight = false;
            });
        }, 200);
      } catch {
        if (!cancelled) {
          setScanningQr(false);
          setQrErrorMsg("无法开启摄像头（请授予相机权限，或点击「相册识别二维码」选择电脑端二维码截图）");
        }
      }
    })();

    return () => {
      cancelled = true;
      if (pollTimer !== undefined) {
        window.clearInterval(pollTimer);
      }
      stopActiveStream();
    };
  }, [open, activeTab, scanningQr, cameraFacing]);

  const handleQrImageUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setDecodingQrImage(true);
    setQrErrorMsg("");
    try {
      const decoded = await decodeQrFromImageFile(file);
      if (!decoded) {
        const msg = "未在图片中识别到二维码，请确保二维码清晰完整";
        setQrErrorMsg(msg);
        showToast({
          kind: "error",
          title: "未识别到二维码",
          message: msg,
        });
        return;
      }
      await applyScannedQrPayload(decoded);
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      setQrErrorMsg(msg);
      showToast({
        kind: "error",
        title: "识别二维码失败",
        message: msg,
      });
    } finally {
      setDecodingQrImage(false);
    }
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
        title: "已离线缓存到本机",
        message: `角色「${imported[0]?.name || name}」已写入手机本地存储。`,
      });
    } catch (error) {
      showToast({
        kind: "error",
        title: "同步角色失败",
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

  const handleCloseDialog = () => {
    setScanningQr(false);
    onClose();
  };

  return (
    <Dialog
      bodyClassName="runtime-mode-dialog__body"
      className="runtime-mode-dialog"
      closeLabel="关闭"
      footer={
        <div className="runtime-mode-dialog__footer">
          <Button
            onClick={() => {
              handleCloseDialog();
              navigate("/settings/api");
            }}
            type="button"
          >
            完整设置工作台
          </Button>
          <Button onClick={handleCloseDialog} type="button" variant="primary">
            完成
          </Button>
        </div>
      }
      onClose={handleCloseDialog}
      open={open}
      title="AI / 语音与跨端运行配置"
    >
      <div className="runtime-mode-dialog__tabs" role="tablist">
        <button
          aria-selected={activeTab === "keys"}
          className="runtime-mode-dialog__tab"
          data-active={activeTab === "keys" ? "true" : "false"}
          onClick={() => {
            setScanningQr(false);
            setActiveTab("keys");
          }}
          role="tab"
          type="button"
        >
          <KeyRound aria-hidden size={15} />
          <span>配 Key / 语音</span>
        </button>
        <button
          aria-selected={activeTab === "characters"}
          className="runtime-mode-dialog__tab"
          data-active={activeTab === "characters" ? "true" : "false"}
          onClick={() => {
            setScanningQr(false);
            setActiveTab("characters");
          }}
          role="tab"
          type="button"
        >
          <Sparkles aria-hidden size={15} />
          <span>角色包 (.char)</span>
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
            <span>{remoteActive ? "已连电脑端" : "连接电脑端"}</span>
          </button>
        ) : null}
      </div>

      {activeTab === "keys" ? (
        <div className="runtime-mode-dialog__section">
          <p className="runtime-mode-dialog__hint">
            所有 API Key 仅保存在你的当前设备本地，不会上传第三方。推荐使用「硅基流动」一个 Key 同时驱动 DeepSeek 对话与
            CosyVoice2 实时口型配音。
          </p>

          <div className="runtime-mode-dialog__grid">
            <label className="runtime-mode-dialog__field">
              <span>对话模型厂商 (LLM)</span>
              <Select onChange={(e) => handleLlmProviderSwitch(e.target.value)} value={llmProvider}>
                {llmProviderOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </Select>
            </label>

            <label className="runtime-mode-dialog__field">
              <span>模型 ID</span>
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
              <span>API Base URL（可填自定义中转地址）</span>
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
              <span>云端语音合成 (TTS)</span>
              <Select onChange={(e) => handleTtsProviderSwitch(e.target.value)} value={ttsProvider}>
                {catalogTtsOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </Select>
            </label>

            {selectedTtsNeedsCorsProxy ? (
              <p className="runtime-mode-dialog__warn">
                当前为纯网页/Toy 沙盒，{ttsProvider} 默认接口可能限制浏览器跨域；建议选择「OpenAI 兼容语音
                (硅基流动)」或「MiniMax」，或安装手机 App 端走原生无跨域直连。
              </p>
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
                    <span>与对话复用同一个硅基流动 / LLM API Key</span>
                  </label>
                ) : null}

                {!(ttsProvider === "openai-speech" && ttsReuseLlmKey) ? (
                  <label className="runtime-mode-dialog__field runtime-mode-dialog__field--full">
                    <span>语音 API Key</span>
                    <TextInput
                      autoComplete="off"
                      onChange={(e) => setTtsApiKey(e.target.value)}
                      placeholder="语音服务 API Key"
                      type="password"
                      value={ttsApiKey}
                    />
                  </label>
                ) : null}

                <label className="runtime-mode-dialog__field">
                  <span>音色 Voice ID</span>
                  <TextInput
                    onChange={(e) => setTtsVoiceId(e.target.value)}
                    placeholder="FunAudioLLM/CosyVoice2-0.5B:claire"
                    value={ttsVoiceId}
                  />
                </label>

                <label className="runtime-mode-dialog__field">
                  <span>语音接口地址 (Base URL)</span>
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
                      placeholder="输入 Group ID"
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
              {testingLlm ? "测试中..." : "测试对话连通"}
            </Button>
            <Button
              disabled={savingKeys || !configQuery.data}
              onClick={() => void handleSaveKeys()}
              type="button"
              variant="primary"
            >
              {savingKeys ? "保存中..." : "保存配置"}
            </Button>
          </div>
        </div>
      ) : null}

      {activeTab === "characters" ? (
        <div className="runtime-mode-dialog__section">
          <p className="runtime-mode-dialog__hint">
            支持直接导入电脑版新世界导出的 <code>.char</code>（或 <code>.zip</code>
            ）角色包，保留人设、多表情立绘、口型配置与参考音频并存于当前设备本地。
          </p>

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
              {importingChar ? "解析角色包中..." : "导入 .char 角色包"}
            </Button>
            <Button
              onClick={() => {
                onClose();
                navigate("/settings/characters");
              }}
              type="button"
            >
              打开角色工坊 (新建/编辑立绘)
            </Button>
          </div>

          <div className="runtime-mode-dialog__char-list">
            {(charactersQuery.data ?? []).map((char) => (
              <div className="runtime-mode-dialog__char-item" key={char.name}>
                <div>
                  <strong>{char.name}</strong>
                  <span className="runtime-mode-dialog__char-meta">
                    立绘 {char.sprites?.length ?? 0} 张 · {char.avatar_type || "static"}
                  </span>
                </div>
                <Button
                  icon={<Download aria-hidden className="button__icon" />}
                  onClick={() => void handleExportChar(char.name)}
                  type="button"
                >
                  导出 .char
                </Button>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {activeTab === "remote" && allowRemotePc ? (
        <div className="runtime-mode-dialog__section">
          <p className="runtime-mode-dialog__hint">
            {remoteActive
              ? "当前已连接电脑端满血后端，正直接使用电脑的本地 GPT-SoVITS、记忆库与全部角色。"
              : "在电脑端开启「手机访问」弹出连接二维码后，直接用手机扫码即可自动填入地址与认证 Token 并一键连接，无需手动输入。"}
          </p>

          <input
            accept="image/*"
            className="runtime-mode-dialog__file-input"
            onChange={(e) => void handleQrImageUpload(e)}
            ref={qrFileInputRef}
            type="file"
          />

          <div className="runtime-mode-dialog__qr-card">
            <div className="runtime-mode-dialog__qr-cta">
              <Button
                icon={<QrCode aria-hidden className="button__icon" />}
                onClick={() => {
                  setQrErrorMsg("");
                  setScanningQr((prev) => !prev);
                }}
                type="button"
                variant="primary"
              >
                {scanningQr ? "关闭扫码镜头" : "扫描电脑二维码"}
              </Button>
              <Button
                disabled={decodingQrImage}
                icon={<ImageUp aria-hidden className="button__icon" />}
                onClick={() => qrFileInputRef.current?.click()}
                type="button"
              >
                {decodingQrImage ? "识别图片中..." : "相册识别二维码"}
              </Button>
            </div>

            {scanningQr ? (
              <div className="runtime-mode-dialog__qr-scanner">
                <div className="runtime-mode-dialog__qr-viewport">
                  <video autoPlay className="runtime-mode-dialog__qr-video" muted playsInline ref={videoRef} />
                  <div aria-hidden className="runtime-mode-dialog__qr-reticle">
                    <ScanLine aria-hidden className="runtime-mode-dialog__qr-scan-icon" size={20} />
                  </div>
                </div>
                <p className="runtime-mode-dialog__qr-caption">将取景框对准电脑屏幕上的「手机访问」二维码</p>
                <div className="runtime-mode-dialog__qr-toolbar">
                  <Button
                    icon={<RefreshCw aria-hidden className="button__icon" />}
                    onClick={() => setCameraFacing((prev) => (prev === "environment" ? "user" : "environment"))}
                    type="button"
                  >
                    切换镜头
                  </Button>
                  <Button
                    icon={<X aria-hidden className="button__icon" />}
                    onClick={() => setScanningQr(false)}
                    type="button"
                  >
                    取消
                  </Button>
                </div>
              </div>
            ) : null}

            {qrErrorMsg ? <p className="runtime-mode-dialog__warn">{qrErrorMsg}</p> : null}
          </div>

          {remoteUrl || remoteActive ? (
            <div className="runtime-mode-dialog__paired-pill">
              <span>
                {remoteActive ? "已连电脑端：" : "已配对地址："}
                <code>{remoteUrl || "未配置"}</code>
              </span>
              {connectionMode === "remote-pc" || remoteActive ? (
                <Button onClick={() => void handleApplyConnectionMode("standalone")} type="button">
                  切回手机独立模式
                </Button>
              ) : null}
            </div>
          ) : null}

          {remoteStatusMsg ? <p className="runtime-mode-dialog__hint">{remoteStatusMsg}</p> : null}

          <details
            className="runtime-mode-dialog__manual"
            onToggle={(e) => setManualExpanded(e.currentTarget.open)}
            open={manualExpanded}
          >
            <summary>手动填写或查看连接参数（备用）</summary>
            <div className="runtime-mode-dialog__grid">
              <label className="runtime-mode-dialog__field runtime-mode-dialog__field--full">
                <span>电脑端 Shinsekai 地址</span>
                <TextInput
                  onChange={(e) => setRemoteUrl(e.target.value)}
                  placeholder="http://192.168.1.100:8787"
                  value={remoteUrl}
                />
              </label>
              <label className="runtime-mode-dialog__field runtime-mode-dialog__field--full">
                <span>Bridge 访问 Token（如电脑端已开启认证则填写）</span>
                <TextInput
                  autoComplete="off"
                  onChange={(e) => setRemoteToken(e.target.value)}
                  placeholder="留空表示无 Token"
                  type="password"
                  value={remoteToken}
                />
              </label>
            </div>

            <div className="runtime-mode-dialog__actions" style={{ marginTop: "10px" }}>
              <Button
                disabled={testingRemote}
                icon={<PlugZap aria-hidden className="button__icon" />}
                onClick={() => void handleTestRemoteBridge()}
                type="button"
              >
                {testingRemote ? "测试中..." : "测试并拉取角色清单"}
              </Button>
              {connectionMode === "remote-pc" || remoteActive ? (
                <Button onClick={() => void handleApplyConnectionMode("standalone")} type="button">
                  切回手机独立模式
                </Button>
              ) : null}
              <Button onClick={() => void handleApplyConnectionMode("remote-pc")} type="button" variant="primary">
                连接电脑端满血模式
              </Button>
            </div>
          </details>

          {remoteCharacters.length > 0 ? (
            <div className="runtime-mode-dialog__char-list">
              {remoteCharacters.map((char) => (
                <div className="runtime-mode-dialog__char-item" key={char.name}>
                  <div>
                    <strong>{char.name}</strong>
                    <span className="runtime-mode-dialog__char-meta">立绘 {char.sprites?.length ?? 0} 张</span>
                  </div>
                  <Button
                    disabled={syncingCharName === char.name}
                    icon={<Download aria-hidden className="button__icon" />}
                    onClick={() => void handleSyncCharacterFromPc(char.name)}
                    type="button"
                  >
                    {syncingCharName === char.name ? "下载缓存中..." : "缓存到手机离线"}
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
