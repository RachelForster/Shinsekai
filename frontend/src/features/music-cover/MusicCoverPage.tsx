import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, Save, Search } from "lucide-react";

import { configQueryKey, getAppConfig } from "../../entities/config/repository";
import type { SystemConfig } from "../../entities/config/types";
import { fileUrl } from "../../entities/files/repository";
import { runMusicCover, saveMusicCoverConfig, searchMusicCover } from "../../entities/music-cover/repository";
import { useOptionalI18n } from "../../shared/i18n";
import type {
  MusicCoverConfigInput,
  MusicCoverRunResult,
  MusicCoverSource,
  TaskSnapshot,
} from "../../shared/platform/types";
import {
  AsyncButton,
  AudioPlayer,
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
// Shared page layout classes (.page, .section, .form-grid, .field-row) come from shared/theme/settings-base.css (imported in main.tsx)
import "./MusicCoverPage.css";

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
  const { t } = useOptionalI18n();
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
      const message = error instanceof Error ? error.message : t("ops.music.saveError");
      setSaveOutput(message);
      showToast({ kind: "error", message, title: t("ops.music.saveButton") });
    },
    onSuccess(result) {
      setDraft(result.systemConfig);
      setSaveOutput(result.message);
      queryClient.invalidateQueries({ queryKey: configQueryKey });
      showToast({ kind: "success", title: t("ops.music.saveButton") });
    },
  });

  const musicSearchMutation = useMutation({
    mutationFn: () => searchMusicCover({ query: musicQuery.trim(), source: musicSource }),
    onError(error) {
      setMusicLog(error instanceof Error ? error.message : t("ops.music.searchError"));
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
      setMusicLog(error instanceof Error ? error.message : t("ops.music.runError"));
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
        body={t("ops.music.errorBody")}
        error={configQuery.error}
        onRetry={() => void configQuery.refetch()}
        retryLabel={t("ops.music.retry")}
        title={t("ops.music.errorTitle")}
      />
    );
  }

  if (isLoading || !draft) {
    return <EmptyState title={t("ops.music.loading")} />;
  }

  const updateDraft = <K extends keyof SystemConfig>(key: K, value: SystemConfig[K]) => {
    setDraft({ ...draft, [key]: value });
  };

  const busy = saveMutation.isPending || musicSearchMutation.isPending || musicRunMutation.isPending;

  return (
    <div className="page music-cover-page">
      <header className="page__header">
        <div>
          <h1 className="page__title">{t("ops.music.title")}</h1>
        </div>
      </header>

      <div className="music-cover-layout">
        <div className="settings-grid">
          <section className="section">
            <div className="section__header">
              <h2 className="section__title">{t("ops.music.pipelineSection")}</h2>
            </div>
            <div className="form-grid">
              <label className="field-row">
                <span className="field-row__label">{t("ops.music.workDir")}</span>
                <span className="field-row__control">
                  <TextInput
                    disabled={busy}
                    onChange={(event) => updateDraft("music_cover_work_dir", event.target.value)}
                    value={draft.music_cover_work_dir}
                  />
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">{t("ops.music.ytDlpPath")}</span>
                <span className="field-row__control">
                  <TextInput
                    disabled={busy}
                    onChange={(event) => updateDraft("music_cover_yt_dlp_exe", event.target.value)}
                    value={draft.music_cover_yt_dlp_exe}
                  />
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">{t("ops.music.ffmpegPath")}</span>
                <span className="field-row__control">
                  <TextInput
                    disabled={busy}
                    onChange={(event) => updateDraft("music_cover_ffmpeg_exe", event.target.value)}
                    value={draft.music_cover_ffmpeg_exe}
                  />
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">{t("ops.music.uvrCmdTemplate")}</span>
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
                <span className="field-row__label">{t("ops.music.rvcCmdTemplate")}</span>
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
                <span className="field-row__label">{t("ops.music.rvcModel")}</span>
                <span className="field-row__control">
                  <TextInput
                    disabled={busy}
                    onChange={(event) => updateDraft("music_cover_rvc_model_path", event.target.value)}
                    value={draft.music_cover_rvc_model_path}
                  />
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">{t("ops.music.rvcIndex")}</span>
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
              <h2 className="section__title">{t("ops.music.rvcSection")}</h2>
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
                <span className="field-row__label">{t("ops.music.modelVersion")}</span>
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
                <span className="field-row__label">{t("ops.music.f0Method")}</span>
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
                <span className="field-row__label">{t("ops.music.pitch")}</span>
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
                <span className="field-row__label">{t("ops.music.resampleSr")}</span>
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
            <div className="page__actions">
              <AsyncButton
                icon={<Save aria-hidden className="button__icon" />}
                loading={saveMutation.isPending}
                onClick={() => saveMutation.mutate(musicCoverConfigFromSystem(draft))}
              >
                {t("ops.music.saveButton")}
              </AsyncButton>
            </div>
            <TextArea readOnly rows={3} value={saveOutput} />
          </section>
        </div>

        <section className="section">
          <div className="section__header">
            <div>
              <h2 className="section__title">{t("ops.music.execSection")}</h2>
            </div>
            <div className="page__actions">
              <AsyncButton
                icon={<Search aria-hidden className="button__icon" />}
                loading={musicSearchMutation.isPending}
                onClick={() => musicSearchMutation.mutate()}
              >
                {t("ops.music.previewSearch")}
              </AsyncButton>
              <AsyncButton
                icon={<Play aria-hidden className="button__icon" />}
                loading={musicRunMutation.isPending}
                onClick={() => musicRunMutation.mutate()}
                variant="primary"
              >
                {t("ops.music.runFull")}
              </AsyncButton>
            </div>
          </div>
          <div className="form-grid">
            <label className="field-row field-row--stack">
              <span className="field-row__label">{t("ops.music.source")}</span>
              <span className="field-row__control">
                <Select
                  disabled={musicSearchMutation.isPending || musicRunMutation.isPending}
                  onChange={(event) => setMusicSource(event.target.value as MusicCoverSource)}
                  value={musicSource}
                >
                  <option value="youtube">YouTube</option>
                  <option value="bilibili">Bilibili</option>
                  <option value="url">{t("ops.music.sourceFullUrl")}</option>
                </Select>
              </span>
            </label>
            <label className="field-row field-row--stack">
              <span className="field-row__label">{t("ops.music.queryLabel")}</span>
              <span className="field-row__control">
                <TextArea
                  disabled={musicSearchMutation.isPending || musicRunMutation.isPending}
                  onChange={(event) => setMusicQuery(event.target.value)}
                  placeholder={t("ops.music.queryLabel")}
                  rows={3}
                  value={musicQuery}
                />
              </span>
            </label>
            <label className="field-row field-row--stack">
              <span className="field-row__label">{t("ops.music.pickIndex", { index: musicPick })}</span>
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
                  <span>{t("ops.music.skipRvc")}</span>
                </label>
              </span>
            </label>
            <TaskProgress logLimit={0} task={musicTask} />
            <label className="field-row field-row--stack">
              <span className="field-row__label">{t("ops.music.logLabel")}</span>
              <span className="field-row__control">
                <TextArea readOnly rows={12} value={musicLog} />
              </span>
            </label>
            <label className="field-row field-row--stack">
              <span className="field-row__label">{t("ops.music.audioPath")}</span>
              <span className="field-row__control">
                <PathDisplay className="path-display--input" path={musicAudioPath} />
                {musicAudioPath ? (
                  <AudioPlayer
                    className="music-cover-player"
                    label={t("ops.music.audioLabel")}
                    preload="metadata"
                    src={fileUrl(musicAudioPath)}
                  />
                ) : null}
              </span>
            </label>
          </div>
        </section>
      </div>
    </div>
  );
}
