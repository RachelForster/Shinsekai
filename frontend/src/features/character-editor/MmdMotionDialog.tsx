import { useEffect, useRef, useState } from "react";
import type { Character } from "../../entities/config/types";
import { previewMmdMotion, saveMmdMotion } from "../../entities/character/repository";
import { modelFileUrl } from "../../entities/files/repository";
import { avatarAssetUrl, avatarFormat, type AvatarSession } from "../../modules/character-visual";
import { useI18n } from "../../shared/i18n";
import { AsyncButton, Button, Dialog, TextArea, TextInput } from "../../shared/ui";

type MotionPlan = {
  action: "nod" | "shake_head" | "bow" | "wave" | "smile" | "anger" | "denial" | "confusion" | "helpless" | "sadness";
  intensity: number;
  duration_frames: number;
  expression?: "smile" | "anger" | "denial" | "confusion" | "helpless" | "sadness";
};

const FACE_PREVIEW_CAMERA = { yaw: 0, pitch: 0, zoom: 2, panX: 0, panY: 0.07 };

function previewState(base: Record<string, unknown>, faceView: boolean, motion?: string): Record<string, unknown> {
  return {
    ...base,
    camera: faceView ? FACE_PREVIEW_CAMERA : base.camera,
    ...(motion ? { motion, motionBase: "resting" } : {}),
  };
}

/** Preview bytes remain in a revocable browser blob; no preset is published until Save. */
export function MmdMotionDialog({
  character,
  modelPath,
  onClose,
  onSaved,
}: {
  character: Character;
  modelPath: string;
  onClose: () => void;
  onSaved: (value: Character) => void;
}) {
  const { t } = useI18n();
  const host = useRef<HTMLDivElement>(null);
  const session = useRef<AvatarSession<unknown, unknown> | null>(null);
  const baseState = useRef<Record<string, unknown> | null>(null);
  const lifetime = useRef<AbortController | null>(null);
  const urls = useRef(new Map<string, string>());
  const previewPath = useRef<string | null>(null);
  const sequence = useRef(0);
  const [ready, setReady] = useState(false);
  const [faceView, setFaceView] = useState(true);
  const [prompt, setPrompt] = useState("");
  const [tag, setTag] = useState("");
  const [plan, setPlan] = useState<MotionPlan | null>(null);
  const [settingDigest, setSettingDigest] = useState("");
  const [pending, setPending] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const target = host.current;
    const format = avatarFormat("mmd");
    if (!target || !format) return;
    const abort = new AbortController();
    lifetime.current = abort;
    let observer: ResizeObserver | null = null;
    void (async () => {
      const module = await format.load();
      abort.signal.throwIfAborted();
      const modelUrl = modelFileUrl(modelPath);
      const created = await module.create(
        {
          element: target,
          modelUrl,
          assetUrl: (path) => urls.current.get(path) ?? avatarAssetUrl(modelUrl, path),
          reportError: (failure) => {
            if (!abort.signal.aborted) setError(failure.message);
          },
        },
        abort.signal,
      );
      if (abort.signal.aborted) {
        created.dispose();
        return;
      }
      session.current = created;
      baseState.current = created.readState() as Record<string, unknown>;
      await created.apply(previewState(baseState.current, true), "edit", abort.signal);
      if (abort.signal.aborted) return;
      const resize = () => created.resize(target.clientWidth, target.clientHeight);
      resize();
      observer = new ResizeObserver(resize);
      observer.observe(target);
      setReady(true);
    })().catch((failure) => {
      if (!abort.signal.aborted) setError(String(failure));
    });
    return () => {
      abort.abort();
      ++sequence.current;
      observer?.disconnect();
      session.current?.dispose();
      session.current = null;
      for (const url of urls.current.values()) URL.revokeObjectURL(url);
      urls.current.clear();
    };
  }, [modelPath]);

  const toggleCamera = async () => {
    const active = lifetime.current;
    if (!active || !session.current || !baseState.current) return;
    const nextFaceView = !faceView;
    const motion = plan ? (previewPath.current ?? undefined) : undefined;
    setPending(true);
    setError("");
    try {
      await session.current.apply(
        previewState(baseState.current, nextFaceView, motion),
        motion ? "play" : "edit",
        active.signal,
      );
      if (!active.signal.aborted) setFaceView(nextFaceView);
    } catch (failure) {
      if (!active.signal.aborted) setError(String(failure));
    } finally {
      if (!active.signal.aborted) setPending(false);
    }
  };

  const generate = async () => {
    const active = lifetime.current;
    if (!active || !session.current || !baseState.current) return;
    const request = ++sequence.current;
    setPending(true);
    setPlan(null);
    previewPath.current = null;
    setError("");
    try {
      const result = await previewMmdMotion({ name: character.name, model_path: modelPath, prompt: prompt.trim() });
      if (active.signal.aborted || sequence.current !== request) return;
      if (result.vmd_base64.length > 100_000) throw new Error("Generated motion is too large");
      const binary = atob(result.vmd_base64);
      const bytes = Uint8Array.from(binary, (letter) => letter.charCodeAt(0));
      const path = `preview-${request}.vmd`;
      const url = URL.createObjectURL(new Blob([bytes], { type: "application/octet-stream" }));
      urls.current.set(path, url);
      try {
        await session.current.apply(previewState(baseState.current, faceView, path), "play", active.signal);
      } catch (failure) {
        urls.current.delete(path);
        URL.revokeObjectURL(url);
        throw failure;
      }
      if (active.signal.aborted || sequence.current !== request) return;
      previewPath.current = path;
      setPlan(result.plan);
      setSettingDigest(result.setting_digest);
      setTag(prompt.trim().replace(/\s+/g, " ").slice(0, 100));
      for (const [key, old] of urls.current) {
        if (key !== path) {
          URL.revokeObjectURL(old);
          urls.current.delete(key);
        }
      }
    } catch (failure) {
      if (!active.signal.aborted && sequence.current === request) setError(String(failure));
    } finally {
      if (!active.signal.aborted && sequence.current === request) setPending(false);
    }
  };

  const replay = async () => {
    const path = previewPath.current;
    const active = lifetime.current;
    if (!path || !active || !session.current || !baseState.current) return;
    setPending(true);
    setError("");
    try {
      await session.current.apply(previewState(baseState.current, faceView, path), "play", active.signal);
    } catch (failure) {
      if (!active.signal.aborted) setError(String(failure));
    } finally {
      if (!active.signal.aborted) setPending(false);
    }
  };

  const save = async () => {
    if (!plan || !baseState.current || !lifetime.current) return;
    const signal = lifetime.current.signal;
    setPending(true);
    setSaving(true);
    setError("");
    try {
      const result = await saveMmdMotion({
        name: character.name,
        model_path: modelPath,
        plan,
        setting_digest: settingDigest,
        state: baseState.current,
        tag: tag.trim(),
      });
      if (!signal.aborted) onSaved(result);
    } catch (failure) {
      if (!signal.aborted) setError(String(failure));
    } finally {
      if (!signal.aborted) {
        setPending(false);
        setSaving(false);
      }
    }
  };

  return (
    <Dialog
      open
      title={t("character.avatar.mmd.generateTitle")}
      className="model-state-dialog"
      closeLabel={t("common.close")}
      dismissible={!saving}
      onClose={onClose}
      footer={
        <>
          <Button disabled={saving} onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <AsyncButton loading={pending} disabled={pending || !plan || !tag.trim()} onClick={() => void save()}>
            {t("character.avatar.mmd.saveGenerated")}
          </AsyncButton>
        </>
      }
    >
      <div className="model-state-dialog__layout">
        <div className="model-state-dialog__parameters">
          <p className="field-row__hint">{t("character.avatar.mmd.generateHint")}</p>
          <label className="field-row field-row--stack">
            <span className="field-row__label">{t("character.avatar.mmd.motionPrompt")}</span>
            <span className="field-row__control">
              <TextArea
                aria-label={t("character.avatar.mmd.motionPrompt")}
                value={prompt}
                maxLength={500}
                disabled={pending}
                onChange={(event) => {
                  setPrompt(event.target.value);
                  setPlan(null);
                }}
              />
            </span>
          </label>
          <AsyncButton loading={pending} disabled={pending || !ready || !prompt.trim()} onClick={() => void generate()}>
            {t("character.avatar.mmd.generatePreview")}
          </AsyncButton>
          <Button disabled={pending || !ready} onClick={() => void toggleCamera()}>
            {t(faceView ? "character.avatar.mmd.viewFullBody" : "character.avatar.mmd.viewFace")}
          </Button>
          {plan && (
            <>
              <p role="status">
                {t("character.avatar.mmd.previewSummary", {
                  action: [plan.action, plan.expression]
                    .filter((value): value is NonNullable<typeof value> => Boolean(value))
                    .map((value) => t(`character.avatar.mmd.action.${value}`))
                    .join(" + "),
                  seconds: (plan.duration_frames / 30).toFixed(1),
                })}
              </p>
              <Button disabled={pending} onClick={() => void replay()}>
                {t("character.avatar.mmd.replayPreview")}
              </Button>
              <label className="field-row field-row--stack">
                <span className="field-row__label">{t("character.sprite.tag")}</span>
                <span className="field-row__control">
                  <TextInput
                    aria-label={t("character.sprite.tag")}
                    value={tag}
                    maxLength={100}
                    disabled={pending}
                    onChange={(event) => setTag(event.target.value)}
                  />
                </span>
              </label>
            </>
          )}
          {error && (
            <p className="field-error" role="alert">
              {error}
            </p>
          )}
        </div>
        <div ref={host} className="model-state-dialog__preview" role="img" aria-label={t("character.avatar.preview")} />
      </div>
    </Dialog>
  );
}
