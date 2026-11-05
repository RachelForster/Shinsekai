import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { fileUrl } from "../../entities/files/repository";
import { SpriteMouthMedia } from "../../modules/character-visual";
import { tagContents } from "../../shared/assets/assetText";
import { useI18n } from "../../shared/i18n";
import type { Character } from "../../shared/platform/types";
import {
  AsyncButton,
  Button,
  EmptyState,
  FilePicker,
  ImageAssetCornerLabel,
  Select,
  Switch,
  TaskProgress,
} from "../../shared/ui";
import { SpriteAnimationSourcePicker } from "./SpriteAnimationSourcePicker";
import { SpriteMouthSetup } from "./SpriteMouthSetup";
import { SpriteMouthEditor, type MouthEditorSelection } from "./SpriteMouthEditor";
import type { SpriteMouthController } from "./useSpriteMouths";
import "./SpriteMouthWorkspace.css";

export function SpriteMouthWorkspace({
  character,
  controller,
}: {
  character: Character;
  controller: SpriteMouthController;
}) {
  const { t } = useI18n();
  const [speechVideo, setSpeechVideo] = useState("");
  const [frameCount, setFrameCount] = useState<5 | 22 | 39>(22);
  const [blinkRequested, setBlinkRequested] = useState(false);
  const includeBlink = blinkRequested && frameCount !== 5 && !speechVideo;
  const [editing, setEditing] = useState("");
  const [hovered, setHovered] = useState<{ path: string; bounds: DOMRect }>();
  const [sourcesOpen, setSourcesOpen] = useState(true);
  useEffect(() => {
    void controller.refresh();
  }, []);
  useEffect(() => {
    if (!hovered) return;
    const hide = () => setHovered(undefined);
    window.addEventListener("scroll", hide, true);
    window.addEventListener("resize", hide);
    return () => {
      window.removeEventListener("scroll", hide, true);
      window.removeEventListener("resize", hide);
    };
  }, [hovered]);
  const tags = tagContents(character.emotion_tags, character.sprites.length);
  const sources = character.sprites.map((sprite, index) => ({
    id: sprite.path,
    referenceImage: sprite.path,
    tagging: tags[index],
    mouthSync: Boolean(sprite.mouth_sync),
    index,
    origin: "existing" as const,
  }));
  const selectedSources = sources.filter((source) => controller.selection.includes(source.id));
  const readySetup = controller.setup?.runtimeReady && controller.setup.modelsReady;
  const canReuseAll =
    !includeBlink &&
    selectedSources.length > 0 &&
    selectedSources.every((source) => character.sprites[source.index].mouth_sync);
  const busy = Boolean(controller.busy || controller.externalBusy || controller.pendingPaths.length);
  const busyFor = (path: string) => controller.activePath === path || controller.pendingPaths.includes(path);
  const editingItem = controller.items.find((item) => item.path === editing);
  const applyOptions = (selection: MouthEditorSelection) => ({
    frameCount,
    retryTaskId: editingItem?.result?.taskId,
    manual: selection.manual ?? null,
    selectedFrames: selection.selectedFrames,
    correction: editingItem?.correction,
  });
  const label = (path: string) => {
    const index = character.sprites.findIndex((sprite) => sprite.path === path);
    return `${t("spriteGeneration.sprite", { n: index + 1 })}${tags[index] ? ` · ${tags[index]}` : ""}`;
  };
  return (
    <div className="sprite-generation__layout sprite-mouth-workspace">
      <aside className="sprite-generation__settings">
        <h3 className="sprite-generation__section-title">{t("spriteMouth.tab")}</h3>
        <div className="sprite-generation__settings-fields">
          <p className="sprite-generation__hint">{t("spriteMouth.spec")}</p>
          <label>
            {t("spriteMouth.frameCount")}
            <Select
              value={frameCount}
              disabled={busy || Boolean(speechVideo)}
              onChange={(event) => setFrameCount(Number(event.target.value) as 5 | 22 | 39)}
            >
              <option value={5}>{t("spriteMouth.frames5")}</option>
              <option value={22}>{t("spriteMouth.frames22")}</option>
              <option value={39}>{t("spriteMouth.frames39")}</option>
            </Select>
          </label>
          <p className="sprite-generation__hint">
            {t(frameCount === 5 ? "spriteMouth.shortClipHint" : "spriteMouth.frameCountHint")}
          </p>
          <Switch
            checked={includeBlink}
            disabled={busy || frameCount === 5 || Boolean(speechVideo)}
            onChange={(event) => setBlinkRequested(event.target.checked)}
          >
            {t("spriteMouth.includeBlink")}
          </Switch>
          <p className="sprite-generation__hint">{t("spriteMouth.blinkHint")}</p>
          <label>
            {t("spriteMouth.speechVideo")}
            <FilePicker
              acceptedExtensions={["mp4", "webm", "mov", "mkv"]}
              value={speechVideo}
              onPathChange={setSpeechVideo}
              disabled={busy}
              pickLabel={t("spriteMouth.speechVideo")}
            />
          </label>
          {speechVideo ? (
            <Button variant="ghost" disabled={busy} onClick={() => setSpeechVideo("")}>
              {t("spriteAnimation.clearSources")}
            </Button>
          ) : null}
          <p className="sprite-generation__hint">{t("spriteMouth.speechVideoHint")}</p>
          <SpriteMouthSetup controller={controller} />
        </div>
        <div className="sprite-generation__settings-action">
          <AsyncButton
            variant="primary"
            disabled={busy || !selectedSources.length || (!readySetup && !canReuseAll)}
            loading={controller.busy === "generate"}
            onClick={() => {
              setSourcesOpen(false);
              void controller.generate(
                selectedSources.map((source) => source.id),
                { frameCount, ...(speechVideo ? { speechVideo } : {}), ...(includeBlink ? { includeBlink } : {}) },
              );
            }}
          >
            {t("spriteMouth.generate", { count: selectedSources.length })}
          </AsyncButton>
          {controller.busy === "generate" ? (
            <Button disabled={controller.stopping} onClick={controller.stop}>
              {t(controller.stopping ? "spriteMouth.stopping" : "spriteMouth.stop")}
            </Button>
          ) : null}
        </div>
      </aside>
      <section className="sprite-generation__workspace">
        <div className="sprite-generation__workspace-header">
          <h3>{t("spriteMouth.stepSave")}</h3>
          <Button variant="ghost" disabled={busy} onClick={() => setSourcesOpen((value) => !value)}>
            {t("spriteMouth.stepSource")}
          </Button>
        </div>
        {controller.queue.total > 0 ? <p role="status">{t("spriteMouth.queue", controller.queue)}</p> : null}
        <TaskProgress task={controller.task} />
        {controller.error ? (
          <p role="alert" className="sprite-generation__error">
            {controller.error}
          </p>
        ) : null}
        <div className="sprite-generation__workspace-body">
          {sourcesOpen ? (
            <SpriteAnimationSourcePicker
              sources={sources}
              selectedSources={controller.selection}
              onSourceSelectionChange={controller.setSelection}
              busy={busy}
              remaining={sources.length}
              title={t("spriteMouth.stepSource")}
              hint={t("spriteMouth.selectHint")}
            />
          ) : null}
          {!controller.items.length ? (
            <EmptyState title={t("spriteMouth.tab")} body={t("spriteMouth.empty")} />
          ) : (
            <div className="sprite-generation__grid sprite-mouth-grid">
              {controller.items.map((item) => {
                const result = item.result;
                const active = controller.activePath === item.path;
                const failed = item.error || result?.message;
                const status = controller.pendingPaths.includes(item.path)
                  ? "spriteMouth.queued"
                  : active
                    ? "spriteMouth.processing"
                    : item.applyFailed
                      ? "spriteMouth.applyFailed"
                      : item.calibrationDirty
                        ? "spriteMouth.applyPending"
                        : item.saved
                          ? "spriteMouth.saved"
                          : result?.ready
                            ? "spriteMouth.resultReady"
                            : "spriteMouth.needsCalibration";
                const profile = result?.profile
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
                const hoverBounds = !editing && profile && hovered?.path === item.path ? hovered.bounds : undefined;
                const previewWidth = Math.min(460, window.innerWidth - 24);
                const previewHeight = Math.min(640, window.innerHeight - 24);
                const showPreview = (element: HTMLElement) => {
                  if (profile && !editing) setHovered({ path: item.path, bounds: element.getBoundingClientRect() });
                };
                const hidePreview = () => setHovered((current) => (current?.path === item.path ? undefined : current));
                return (
                  <article
                    key={item.path}
                    className="sprite-mouth-card"
                    data-active={active}
                    onMouseEnter={(event) => showPreview(event.currentTarget)}
                    onMouseLeave={hidePreview}
                  >
                    <header>
                      <label>
                        <input
                          type="checkbox"
                          checked={item.selected}
                          disabled={
                            busyFor(item.path) ||
                            item.saved ||
                            item.calibrationDirty ||
                            !result?.ready ||
                            !result.taskId
                          }
                          onChange={(event) => controller.select(item.path, event.target.checked)}
                          aria-label={`${t("spriteMouth.select")} · ${label(item.path)}`}
                        />
                        {label(item.path)}
                      </label>
                      <Button
                        variant="ghost"
                        disabled={busyFor(item.path)}
                        onClick={() => controller.discard(item.path)}
                        aria-label={t("spriteGeneration.remove")}
                      >
                        ×
                      </Button>
                    </header>
                    <div
                      className="sprite-mouth-card__preview"
                      tabIndex={profile ? 0 : undefined}
                      aria-label={profile ? t("spriteMouth.hoverPreview") : undefined}
                      onFocus={(event) => showPreview(event.currentTarget)}
                      onBlur={hidePreview}
                    >
                      <SpriteMouthMedia
                        src={fileUrl(item.path)}
                        mouthProfile={profile}
                        autoPlay={false}
                        alt={label(item.path)}
                        className="sprite-mouth-card__media"
                      />
                      {result?.ready && profile ? (
                        <ImageAssetCornerLabel>{t("spriteMouth.tab")}</ImageAssetCornerLabel>
                      ) : null}
                    </div>
                    <p role="status">{t(status)}</p>
                    {failed ? <p className="sprite-generation__error">{failed}</p> : null}
                    <div className="sprite-mouth-actions">
                      <Button
                        disabled={!result}
                        onClick={() => {
                          setHovered(undefined);
                          setEditing(item.path);
                        }}
                      >
                        {t("spriteMouth.edit")}
                      </Button>
                      <Button
                        disabled={busy || !readySetup}
                        onClick={() =>
                          void controller.generate([item.path], {
                            regenerate: true,
                            frameCount,
                            ...(includeBlink ? { includeBlink } : {}),
                          })
                        }
                      >
                        {t("spriteMouth.redraw")}
                      </Button>
                      {character.sprites.some((sprite) => sprite.path === item.path && sprite.mouth_sync) ? (
                        <Button disabled={busy} variant="ghost" onClick={() => void controller.remove(item.path)}>
                          {t("spriteMouth.remove")}
                        </Button>
                      ) : null}
                    </div>
                    {hoverBounds &&
                      createPortal(
                        <div
                          className="sprite-mouth-hover-preview"
                          aria-hidden="true"
                          style={{
                            width: previewWidth,
                            height: previewHeight,
                            left:
                              hoverBounds.right + 12 + previewWidth <= window.innerWidth - 12
                                ? hoverBounds.right + 12
                                : hoverBounds.left - 12 - previewWidth >= 12
                                  ? hoverBounds.left - 12 - previewWidth
                                  : (window.innerWidth - previewWidth) / 2,
                            top: Math.max(12, Math.min(window.innerHeight - previewHeight - 12, hoverBounds.top)),
                          }}
                        >
                          <SpriteMouthMedia
                            src={fileUrl(item.path)}
                            mouthProfile={profile}
                            previewSpeaking
                            alt=""
                            className="sprite-mouth-card__media"
                          />
                        </div>,
                        document.body,
                      )}
                  </article>
                );
              })}
            </div>
          )}
        </div>
      </section>
      {editingItem ? (
        <SpriteMouthEditor
          key={editingItem.path}
          item={editingItem}
          busy={busyFor(editingItem.path)}
          queued={controller.pendingPaths.includes(editingItem.path)}
          onClose={(selection) => {
            controller.finish(
              editingItem.path,
              selection ? applyOptions(selection) : undefined,
              t("spriteMouth.distinctFrames"),
            );
            setEditing("");
          }}
          onAdjust={(change) => controller.adjust(editingItem.path, change)}
          onDraftChange={(draft) => controller.editDraft(editingItem.path, draft)}
          onApply={(manual, selectedFrames) =>
            void controller.reanalyse(editingItem.path, applyOptions({ manual, selectedFrames }))
          }
        />
      ) : null}
    </div>
  );
}
