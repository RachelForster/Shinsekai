import { useRef, useState, type PointerEvent as ReactPointerEvent, type KeyboardEvent } from "react";

import { fileUrl } from "../../entities/files/repository";
import { SpriteMouthMedia } from "../../modules/character-visual";
import { useI18n } from "../../shared/i18n";
import type { MouthPose, SpriteMouthCorrection, SpriteMouthManual } from "../../shared/platform/types";
import { AsyncButton, Button, Dialog, NumberInput, Select, Switch, VisualMedia } from "../../shared/ui";
import { defaultMouthCorrection, type MouthCandidate, type MouthCalibrationDraft } from "./useSpriteMouths";
import { SpriteMouthCanvas } from "./SpriteMouthCanvas";
import { SpriteMouthTimeline } from "./SpriteMouthTimeline";

type DragMode = "mouth" | "resize" | "chin";
export interface MouthEditorSelection {
  manual?: SpriteMouthManual;
  selectedFrames?: Record<MouthPose, number>;
}
const clamp = (value: number, low = 0, high = 1) => Math.max(low, Math.min(high, value));
const poses: MouthPose[] = ["closed", "half", "open"];

export function moveMouthManual(value: SpriteMouthManual, mode: DragMode, dx: number, dy: number): SpriteMouthManual {
  if (mode === "chin") return { ...value, chin: [clamp(value.chin[0] + dx), clamp(value.chin[1] + dy)] };
  const [x0, y0, x1, y1] = value.mouthBox;
  if (mode === "resize")
    return { ...value, mouthBox: [x0, y0, clamp(x1 + dx, x0 + 0.003, 1), clamp(y1 + dy, y0 + 0.003, 1)] };
  const x = clamp(dx, -x0, 1 - x1);
  const y = clamp(dy, -y0, 1 - y1);
  return { ...value, mouthBox: [x0 + x, y0 + y, x1 + x, y1 + y] };
}

export function SpriteMouthEditor({
  item,
  busy,
  onClose,
  onAdjust,
  onApply,
  onDraftChange,
  queued = false,
}: {
  item: MouthCandidate;
  busy: boolean;
  onClose: (selection?: MouthEditorSelection) => void;
  onAdjust: (change: SpriteMouthCorrection) => void;
  onApply: (manual: SpriteMouthManual | undefined, frames: Record<MouthPose, number> | undefined) => void;
  onDraftChange: (draft: MouthCalibrationDraft) => void;
  queued?: boolean;
}) {
  const { t } = useI18n();
  const result = item.result;
  const choices = result?.frames ?? [];
  const manual: SpriteMouthManual = item.draft?.manual ??
    result?.manual ??
    result?.suggestedManual ?? { mouthBox: [0.45, 0.35, 0.55, 0.38], chin: [0.5, 0.42] };
  const manualEnabled = item.draft?.manualEnabled ?? Boolean(result?.manual);
  const [showGuides, setShowGuides] = useState(Boolean(item.draft?.manualEnabled));
  const frames = item.draft?.selectedFrames ??
    result?.selectedFrames ?? {
      closed: choices[0]?.index ?? 0,
      half: choices[Math.floor(choices.length / 3)]?.index ?? 1,
      open: choices[Math.floor((choices.length * 2) / 3)]?.index ?? 2,
    };
  const [speaking, setSpeaking] = useState(true);
  const [size, setSize] = useState<[number, number]>([result?.profile?.width ?? 512, result?.profile?.height ?? 672]);
  const [requestedFrame, setRequestedFrame] = useState<{ index: number; sequence: number }>();
  const viewport = useRef<HTMLDivElement>(null);
  const drag = useRef<{ mode: DragMode; x: number; y: number; value: SpriteMouthManual } | null>(null);
  const changeManual = (value: SpriteMouthManual) =>
    onDraftChange({ manual: value, manualEnabled: true, selectedFrames: frames });
  const pickFrame = (pose: MouthPose, index: number) => {
    onDraftChange({ manual, manualEnabled, selectedFrames: { ...frames, [pose]: index } });
    setRequestedFrame((value) => ({ index, sequence: (value?.sequence ?? 0) + 1 }));
  };
  const start = (event: ReactPointerEvent<HTMLButtonElement>, mode: DragMode) => {
    if (busy || event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { mode, x: event.clientX, y: event.clientY, value: manual };
  };
  const move = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const state = drag.current;
    const bounds = viewport.current?.getBoundingClientRect();
    if (!state || !bounds?.width || !bounds.height) return;
    changeManual(
      moveMouthManual(
        state.value,
        state.mode,
        (event.clientX - state.x) / bounds.width,
        (event.clientY - state.y) / bounds.height,
      ),
    );
  };
  const key = (event: KeyboardEvent<HTMLButtonElement>, mode: DragMode) => {
    const directions: Record<string, [number, number]> = {
      ArrowLeft: [-1, 0],
      ArrowRight: [1, 0],
      ArrowUp: [0, -1],
      ArrowDown: [0, 1],
    };
    const direction = directions[event.key];
    if (!direction || busy) return;
    event.preventDefault();
    changeManual(moveMouthManual(manual, mode, direction[0] / size[0], direction[1] / size[1]));
  };
  const handlers = (mode: DragMode) => ({
    onPointerDown: (event: ReactPointerEvent<HTMLButtonElement>) => start(event, mode),
    onPointerMove: move,
    onPointerUp: () => {
      drag.current = null;
    },
    onPointerCancel: () => {
      drag.current = null;
    },
    onKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => key(event, mode),
  });
  const [x0, y0, x1, y1] = manual.mouthBox;
  const profile =
    result?.profile && (!showGuides || !item.calibrationDirty)
      ? {
          ...result.profile,
          correction: item.correction,
          mouths: {
            closed: fileUrl(result.profile.mouths.closed),
            half: fileUrl(result.profile.mouths.half),
            open: fileUrl(result.profile.mouths.open),
          },
        }
      : undefined;
  const reference = fileUrl(result?.reference || item.path);
  const validFrames =
    choices.length > 0 &&
    poses.every((pose) => choices.some((frame) => frame.index === frames[pose])) &&
    new Set(Object.values(frames)).size === 3;
  const canApply = choices.length ? validFrames : manualEnabled;
  const selection = { manual: manualEnabled ? manual : undefined, selectedFrames: validFrames ? frames : undefined };
  const close = () => onClose(canApply ? selection : undefined);
  return (
    <Dialog
      open
      title={t("spriteMouth.edit")}
      onClose={close}
      closeLabel={t("spriteMouth.closeSave")}
      dismissible
      trapFocus
      className="sprite-mouth-dialog"
      footer={
        <>
          <AsyncButton
            disabled={busy || !canApply || (result?.ready && !item.calibrationDirty)}
            loading={busy && !queued}
            onClick={() => onApply(selection.manual, selection.selectedFrames)}
          >
            {t(queued ? "spriteMouth.queued" : "spriteMouth.apply")}
          </AsyncButton>
          <Button onClick={close}>{t("spriteMouth.done")}</Button>
        </>
      }
    >
      <div className="sprite-mouth-editor">
        <div className="sprite-mouth-editor__preview">
          <SpriteMouthCanvas
            size={size}
            focus={[(manual.mouthBox[0] + manual.mouthBox[2]) / 2, (manual.mouthBox[1] + manual.mouthBox[3]) / 2]}
            contentRef={viewport}
          >
            {!profile ? (
              <VisualMedia
                src={reference}
                alt={t("spriteMouth.manual")}
                autoPlay={false}
                onDimensions={(width, height) => setSize([width, height])}
                className="sprite-mouth-editor__media"
              />
            ) : (
              <SpriteMouthMedia
                src={showGuides ? reference : fileUrl(item.path)}
                autoPlay={!showGuides}
                mouthProfile={profile}
                previewSpeaking={speaking}
                alt={t("spriteMouth.previewSpeaking")}
                onDimensions={(width, height) => setSize([width, height])}
                className="sprite-mouth-editor__media"
              />
            )}
            {showGuides ? (
              <div className="sprite-mouth-editor__anchors">
                <button
                  type="button"
                  aria-label={t("spriteMouth.mouthBox")}
                  disabled={busy}
                  className="sprite-mouth-editor__mouth"
                  style={{
                    left: `${x0 * 100}%`,
                    top: `${y0 * 100}%`,
                    width: `${(x1 - x0) * 100}%`,
                    height: `${(y1 - y0) * 100}%`,
                  }}
                  {...handlers("mouth")}
                />
                <button
                  type="button"
                  aria-label={t("spriteMouth.resize")}
                  disabled={busy}
                  className="sprite-mouth-editor__resize"
                  style={{ left: `${x1 * 100}%`, top: `${y1 * 100}%` }}
                  {...handlers("resize")}
                />
                <button
                  type="button"
                  aria-label={t("spriteMouth.chin")}
                  disabled={busy}
                  className="sprite-mouth-editor__chin"
                  style={{ left: `${manual.chin[0] * 100}%`, top: `${manual.chin[1] * 100}%` }}
                  {...handlers("chin")}
                />
              </div>
            ) : null}
          </SpriteMouthCanvas>
          <p className="sprite-generation__hint">{t("spriteMouth.panHint")}</p>
          <Switch checked={speaking} onChange={(event) => setSpeaking(event.target.checked)} disabled={!profile}>
            {t("spriteMouth.previewSpeaking")}
          </Switch>
          <Switch checked={showGuides} onChange={(event) => setShowGuides(event.target.checked)}>
            {t("spriteMouth.showGuides")}
          </Switch>
          {showGuides ? <p className="sprite-generation__hint">{t("spriteMouth.manualHint")}</p> : null}
          {manualEnabled ? (
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => onDraftChange({ manual, manualEnabled: false, selectedFrames: frames })}
            >
              {t("spriteMouth.restoreAutomatic")}
            </Button>
          ) : null}
        </div>
        <div className="sprite-mouth-editor__controls">
          {queued ? <p role="status">{t("spriteMouth.queued")}</p> : null}
          {!busy && !item.calibrationDirty && result?.ready && !item.applyFailed ? (
            <p role="status">{t("spriteMouth.resultReady")}</p>
          ) : null}
          {item.error || result?.message ? (
            <p role="alert" className="sprite-generation__error">
              {item.error || result?.message}
            </p>
          ) : null}
          <div className="sprite-mouth-editor__adjustments">
            {(["offsetX", "offsetY", "scale", "rotation", "gain"] as const).map((field) => (
              <label key={field}>
                {t(`spriteMouth.${field}`)}
                <NumberInput
                  disabled={busy}
                  value={item.correction[field]}
                  min={field === "scale" ? 0.25 : field === "gain" ? 0.1 : field === "rotation" ? -90 : -4096}
                  max={field === "scale" ? 4 : field === "gain" ? 5 : field === "rotation" ? 90 : 4096}
                  step={field === "scale" ? 0.05 : field === "gain" ? 0.1 : 1}
                  onChange={(event) => {
                    const value = Number(event.target.value);
                    if (Number.isFinite(value)) onAdjust({ ...item.correction, [field]: value });
                  }}
                />
              </label>
            ))}
          </div>
          <Button variant="ghost" disabled={busy} onClick={() => onAdjust({ ...defaultMouthCorrection })}>
            {t("spriteMouth.reset")}
          </Button>
          <h4>{t("spriteMouth.chooseFrames")}</h4>
          {choices.length && !validFrames ? (
            <p role="status" className="sprite-generation__hint">
              {t("spriteMouth.distinctFrames")}
            </p>
          ) : null}
          {choices.length ? (
            <div className="sprite-mouth-editor__poses">
              {poses.map((pose) => (
                <label key={pose}>
                  {t(`spriteMouth.${pose}`)}
                  <button
                    type="button"
                    className="sprite-mouth-editor__pose-frame"
                    aria-label={t("spriteMouth.previewFrame", { pose: t(`spriteMouth.${pose}`) })}
                    onClick={() =>
                      setRequestedFrame((value) => ({ index: frames[pose], sequence: (value?.sequence ?? 0) + 1 }))
                    }
                  >
                    <img
                      alt={t(`spriteMouth.${pose}`)}
                      src={fileUrl(choices.find((frame) => frame.index === frames[pose])?.path ?? "")}
                    />
                  </button>
                  <Select
                    value={frames[pose]}
                    disabled={busy}
                    aria-label={t(`spriteMouth.${pose}`)}
                    onChange={(event) => pickFrame(pose, Number(event.target.value))}
                  >
                    {choices.map((frame) => (
                      <option key={frame.index} value={frame.index}>
                        {t("spriteMouth.frame", { n: frame.index + 1 })}
                      </option>
                    ))}
                  </Select>
                </label>
              ))}
            </div>
          ) : (
            <p>{t("spriteMouth.noFrames")}</p>
          )}
          {result?.speechVideo ? (
            <SpriteMouthTimeline
              src={result.speechVideo}
              frames={choices}
              fps={result.speechFps}
              disabled={busy}
              requestedFrame={requestedFrame}
              onPick={pickFrame}
            />
          ) : null}
        </div>
      </div>
    </Dialog>
  );
}
