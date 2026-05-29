import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, Save, Search } from "lucide-react";

import { configQueryKey, getAppConfig } from "../../entities/config/repository";
import type { SystemConfig } from "../../entities/config/types";
import { runMusicCover, saveMusicCoverConfig, searchMusicCover } from "../../entities/music-cover/repository";
import type {
  MusicCoverConfigInput,
  MusicCoverRunResult,
  MusicCoverSource,
  TaskSnapshot,
} from "../../shared/platform/types";
import {
  AsyncButton,
  EmptyState,
  NumberInput,
  PathDisplay,
  QueryErrorState,
  Select,
  TaskProgress,
  TextArea,
  TextInput,
  useToast,
} from "../../shared/ui";
import "../settings-pages.css";

function musicCoverConfigFromSystem(systemConfig: SystemConfig): MusicCoverConfigInput {
  return {
    music_cover_ffmpeg_exe: systemConfig.music_cover_ffmpeg_exe,
    music_cover_rvc_cmd_template: systemConfig.music_cover_rvc_cmd_template,
    music_cover_rvc_device: systemConfig.music_cover_rvc_device,
    music_cover_rvc_f0_method: systemConfig.music_cover_rvc_f0_method,
    music_cover_rvc_filter_radius: systemConfig.music_cover_rvc_filter_radius,
    music_cover_rvc_index_path: systemConfig.music_cover_rvc_index_path,
    music_cover_rvc_index_rate: systemConfig.music_cover_rvc_index_rate,
    music_cover_rvc_model_path: systemConfig.music_cover_rvc_model_path,
    music_cover_rvc_model_version: systemConfig.music_cover_rvc_model_version,
    music_cover_rvc_pitch: systemConfig.music_cover_rvc_pitch,
    music_cover_rvc_protect: systemConfig.music_cover_rvc_protect,
    music_cover_rvc_resample_sr: systemConfig.music_cover_rvc_resample_sr,
    music_cover_rvc_rms_mix_rate: systemConfig.music_cover_rvc_rms_mix_rate,
    music_cover_uvr_cmd_template: systemConfig.music_cover_uvr_cmd_template,
    music_cover_work_dir: systemConfig.music_cover_work_dir,
    music_cover_yt_dlp_exe: systemConfig.music_cover_yt_dlp_exe,
  };
}

export function MusicCoverPage() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const configQuery = useQuery({ queryFn: getAppConfig, queryKey: configQueryKey });
  const { data, isLoading } = configQuery;
  const [draft, setDraft] = useState<SystemConfig | null>(null);
  const [saveOutput, setSaveOutput] = useState("");
  const [musicSource, setMusicSource] = useState<MusicCoverSource>("youtube");
  const [musicQuery, setMusicQuery] = useState("");
  const [musicPick, setMusicPick] = useState(0);
  const [musicSkipRvc, setMusicSkipRvc] = useState(false);
  const [musicLog, setMusicLog] = useState("");
  const [musicAudioPath, setMusicAudioPath] = useState("");
  const [musicTask, setMusicTask] = useState<TaskSnapshot<MusicCoverRunResult> | null>(null);

  useEffect(() => {
    if (data?.system_config) {
      setDraft(data.system_config);
    }
  }, [data?.system_config]);

  const saveMutation = useMutation({
    mutationFn: (config: MusicCoverConfigInput) => saveMusicCoverConfig(config),
    onError(error) {
      const message = error instanceof Error ? error.message : "保存失败。";
      setSaveOutput(message);
      showToast({ kind: "error", message, title: "保存翻唱流水线配置" });
    },
    onSuccess(result) {
      setDraft(result.systemConfig);
      setSaveOutput(result.message);
      queryClient.invalidateQueries({ queryKey: configQueryKey });
      showToast({ kind: "success", title: "保存翻唱流水线配置" });
    },
  });

  const musicSearchMutation = useMutation({
    mutationFn: () => searchMusicCover({ query: musicQuery.trim(), source: musicSource }),
    onError(error) {
      setMusicLog(error instanceof Error ? error.message : "搜索预览失败。");
    },
    onSuccess(result) {
      setMusicLog(result.log);
    },
  });

  const musicRunMutation = useMutation({
    mutationFn: () =>
      runMusicCover(
        {
          pickIndex: musicPick,
          query: musicQuery.trim(),
          skipRvc: musicSkipRvc,
          source: musicSource,
        },
        {
          onTaskUpdate(task) {
            setMusicTask(task);
            if (task.logs.length) {
              setMusicLog(task.logs.join("\n"));
            }
          },
        },
      ),
    onError(error) {
      setMusicLog(error instanceof Error ? error.message : "翻唱流水线执行失败。");
      setMusicAudioPath("");
    },
    onMutate() {
      setMusicTask(null);
      setMusicAudioPath("");
    },
    onSuccess(result) {
      setMusicLog(result.log);
      setMusicAudioPath(result.audioPath);
    },
  });

  if (configQuery.isError) {
    return (
      <QueryErrorState
        body="检查桥接服务后重试。"
        error={configQuery.error}
        onRetry={() => void configQuery.refetch()}
        retryLabel="重试"
        title="读取翻唱流水线配置失败"
      />
    );
  }

  if (isLoading || !draft) {
    return <EmptyState title="正在读取翻唱流水线配置" />;
  }

  const updateDraft = <K extends keyof SystemConfig>(key: K, value: SystemConfig[K]) => {
    setDraft({ ...draft, [key]: value });
  };

  const busy = saveMutation.isPending || musicSearchMutation.isPending || musicRunMutation.isPending;

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1 className="page__title">音乐翻唱流水线</h1>
          <p className="page__description">
            下载 → 歌词/字幕 → UVR 分离 → RVC 翻唱 → 合成。修改路径后请先保存配置，再执行流水线。
          </p>
        </div>
      </header>

      <div className="form-grid form-grid--two">
        <div className="settings-grid">
          <section className="section">
            <div className="section__header">
              <h2 className="section__title">流水线与工具路径</h2>
            </div>
            <div className="form-grid">
              <label className="field-row">
                <span className="field-row__label">工作目录</span>
                <span className="field-row__control">
                  <TextInput
                    disabled={busy}
                    onChange={(event) => updateDraft("music_cover_work_dir", event.target.value)}
                    value={draft.music_cover_work_dir}
                  />
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">yt-dlp 路径（可空=PATH）</span>
                <span className="field-row__control">
                  <TextInput
                    disabled={busy}
                    onChange={(event) => updateDraft("music_cover_yt_dlp_exe", event.target.value)}
                    value={draft.music_cover_yt_dlp_exe}
                  />
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">ffmpeg 路径（可空=PATH）</span>
                <span className="field-row__control">
                  <TextInput
                    disabled={busy}
                    onChange={(event) => updateDraft("music_cover_ffmpeg_exe", event.target.value)}
                    value={draft.music_cover_ffmpeg_exe}
                  />
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">UVR/分离 命令模板</span>
                <span className="field-row__control">
                  <TextArea
                    disabled={busy}
                    onChange={(event) => updateDraft("music_cover_uvr_cmd_template", event.target.value)}
                    rows={3}
                    value={draft.music_cover_uvr_cmd_template}
                  />
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">RVC 命令模板</span>
                <span className="field-row__control">
                  <TextArea
                    disabled={busy}
                    onChange={(event) => updateDraft("music_cover_rvc_cmd_template", event.target.value)}
                    rows={3}
                    value={draft.music_cover_rvc_cmd_template}
                  />
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">RVC 模型 .pth</span>
                <span className="field-row__control">
                  <TextInput
                    disabled={busy}
                    onChange={(event) => updateDraft("music_cover_rvc_model_path", event.target.value)}
                    value={draft.music_cover_rvc_model_path}
                  />
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">RVC 索引 .index（可选）</span>
                <span className="field-row__control">
                  <TextInput
                    disabled={busy}
                    onChange={(event) => updateDraft("music_cover_rvc_index_path", event.target.value)}
                    value={draft.music_cover_rvc_index_path}
                  />
                </span>
              </label>
            </div>
          </section>

          <section className="section">
            <div className="section__header">
              <h2 className="section__title">rvc-python 推理参数</h2>
            </div>
            <div className="form-grid">
              <label className="field-row">
                <span className="field-row__label">device</span>
                <span className="field-row__control">
                  <TextInput
                    disabled={busy}
                    onChange={(event) => updateDraft("music_cover_rvc_device", event.target.value)}
                    value={draft.music_cover_rvc_device}
                  />
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">模型版本</span>
                <span className="field-row__control">
                  <Select
                    disabled={busy}
                    onChange={(event) => updateDraft("music_cover_rvc_model_version", event.target.value)}
                    value={draft.music_cover_rvc_model_version}
                  >
                    <option value="v1">v1</option>
                    <option value="v2">v2</option>
                  </Select>
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">音高 method</span>
                <span className="field-row__control">
                  <Select
                    disabled={busy}
                    onChange={(event) => updateDraft("music_cover_rvc_f0_method", event.target.value)}
                    value={draft.music_cover_rvc_f0_method}
                  >
                    <option value="rmvpe">rmvpe</option>
                    <option value="harvest">harvest</option>
                    <option value="crepe">crepe</option>
                    <option value="pm">pm</option>
                  </Select>
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">变调 pitch（半音）</span>
                <span className="field-row__control">
                  <NumberInput
                    disabled={busy}
                    max={12}
                    min={-12}
                    onChange={(event) => updateDraft("music_cover_rvc_pitch", Number(event.target.value))}
                    step={0.5}
                    value={draft.music_cover_rvc_pitch}
                  />
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">index_rate</span>
                <span className="field-row__control">
                  <NumberInput
                    disabled={busy}
                    max={1}
                    min={0}
                    onChange={(event) => updateDraft("music_cover_rvc_index_rate", Number(event.target.value))}
                    step={0.05}
                    value={draft.music_cover_rvc_index_rate}
                  />
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">filter_radius</span>
                <span className="field-row__control">
                  <NumberInput
                    disabled={busy}
                    max={7}
                    min={0}
                    onChange={(event) => updateDraft("music_cover_rvc_filter_radius", Number(event.target.value))}
                    step={1}
                    value={draft.music_cover_rvc_filter_radius}
                  />
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">resample_sr（0=不重采样）</span>
                <span className="field-row__control">
                  <NumberInput
                    disabled={busy}
                    max={192000}
                    min={0}
                    onChange={(event) => updateDraft("music_cover_rvc_resample_sr", Number(event.target.value))}
                    step={1}
                    value={draft.music_cover_rvc_resample_sr}
                  />
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">rms_mix_rate</span>
                <span className="field-row__control">
                  <NumberInput
                    disabled={busy}
                    max={1}
                    min={0}
                    onChange={(event) => updateDraft("music_cover_rvc_rms_mix_rate", Number(event.target.value))}
                    step={0.05}
                    value={draft.music_cover_rvc_rms_mix_rate}
                  />
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">protect</span>
                <span className="field-row__control">
                  <NumberInput
                    disabled={busy}
                    max={0.5}
                    min={0}
                    onChange={(event) => updateDraft("music_cover_rvc_protect", Number(event.target.value))}
                    step={0.01}
                    value={draft.music_cover_rvc_protect}
                  />
                </span>
              </label>
            </div>
          </section>

          <section className="section">
            <div className="page__actions page__actions--left">
              <AsyncButton
                icon={<Save aria-hidden className="button__icon" />}
                loading={saveMutation.isPending}
                onClick={() => saveMutation.mutate(musicCoverConfigFromSystem(draft))}
              >
                保存翻唱流水线配置
              </AsyncButton>
            </div>
            <TextArea readOnly rows={3} value={saveOutput} />
          </section>
        </div>

        <section className="section">
          <div className="section__header">
            <div>
              <h2 className="section__title">流水线执行</h2>
            </div>
            <div className="page__actions">
              <AsyncButton
                icon={<Search aria-hidden className="button__icon" />}
                loading={musicSearchMutation.isPending}
                onClick={() => musicSearchMutation.mutate()}
              >
                预览搜索结果
              </AsyncButton>
              <AsyncButton
                icon={<Play aria-hidden className="button__icon" />}
                loading={musicRunMutation.isPending}
                onClick={() => musicRunMutation.mutate()}
                variant="primary"
              >
                执行完整流水线
              </AsyncButton>
            </div>
          </div>
          <div className="form-grid">
            <label className="field-row field-row--stack">
              <span className="field-row__label">来源</span>
              <span className="field-row__control">
                <Select
                  disabled={musicSearchMutation.isPending || musicRunMutation.isPending}
                  onChange={(event) => setMusicSource(event.target.value as MusicCoverSource)}
                  value={musicSource}
                >
                  <option value="youtube">YouTube</option>
                  <option value="bilibili">Bilibili</option>
                  <option value="url">完整 URL</option>
                </Select>
              </span>
            </label>
            <label className="field-row field-row--stack">
              <span className="field-row__label">搜索词或 URL</span>
              <span className="field-row__control">
                <TextArea
                  disabled={musicSearchMutation.isPending || musicRunMutation.isPending}
                  onChange={(event) => setMusicQuery(event.target.value)}
                  placeholder="搜索词或 URL"
                  rows={3}
                  value={musicQuery}
                />
              </span>
            </label>
            <label className="field-row field-row--stack">
              <span className="field-row__label">选用第 {musicPick} 条</span>
              <span className="field-row__control">
                <input
                  disabled={musicRunMutation.isPending}
                  max={7}
                  min={0}
                  onChange={(event) => setMusicPick(Number(event.target.value))}
                  type="range"
                  value={musicPick}
                />
              </span>
            </label>
            <label className="field-row field-row--stack">
              <span className="field-row__control">
                <label className="checkbox-row">
                  <input
                    checked={musicSkipRvc}
                    disabled={musicRunMutation.isPending}
                    onChange={(event) => setMusicSkipRvc(event.target.checked)}
                    type="checkbox"
                  />
                  <span>跳过 RVC（仅用分离后人声合成）</span>
                </label>
              </span>
            </label>
            <TaskProgress logLimit={0} task={musicTask} />
            <label className="field-row field-row--stack">
              <span className="field-row__label">日志</span>
              <span className="field-row__control">
                <TextArea readOnly rows={12} value={musicLog} />
              </span>
            </label>
            <label className="field-row field-row--stack">
              <span className="field-row__label">成品试听路径</span>
              <span className="field-row__control">
                <PathDisplay className="path-display--input" path={musicAudioPath} />
              </span>
            </label>
          </div>
        </section>
      </div>
    </div>
  );
}
