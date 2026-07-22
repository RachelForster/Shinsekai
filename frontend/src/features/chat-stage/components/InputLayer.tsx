import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import { FileText, ImagePlus, LoaderCircle, Mic, MicOff, Plus, Send, X } from "lucide-react";

import { useI18n } from "../../../shared/i18n";
import type { ChatAttachmentInput, ChatCommand } from "../../../shared/platform/types";
import { Button, IconButton, TextArea, TextInput, ThemeBackground, ThemeFrame } from "../../../shared/ui";
import { useDismissableLayer } from "../hooks/useDismissableLayer";
import { useAutoHideRegion } from "../hooks/useAutoHideRegion";

export function InputLayer({
  attachments,
  autoHide = false,
  asrEnabled,
  asrLoading,
  asrRunning,
  batchEnabled,
  disabled,
  hidden,
  inputLayout = "default",
  onChange,
  onCommand,
  onDropFiles,
  onFlushBatch,
  onInputActivity,
  onPickAttachments,
  onRemoveAttachment,
  onSubmit,
  value,
}: {
  asrEnabled: boolean;
  asrLoading: boolean;
  asrRunning: boolean;
  attachments: ChatAttachmentInput[];
  autoHide?: boolean;
  batchEnabled: boolean;
  disabled: boolean;
  hidden: boolean;
  inputLayout?: "default" | "pill";
  onChange: (value: string) => void;
  onCommand: (command: ChatCommand) => void | Promise<void>;
  onDropFiles?: (files: File[]) => void | Promise<void>;
  onFlushBatch: () => void | Promise<void>;
  onInputActivity: (state: { composing: boolean; hasText: boolean }) => void;
  onSubmit: (textOverride?: string) => void | Promise<void>;
  onPickAttachments: (kind: ChatAttachmentInput["kind"]) => void;
  onRemoveAttachment: (attachment: ChatAttachmentInput) => void;
  value: string;
}) {
  const { t } = useI18n();
  const [panelOpen, setPanelOpen] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const inputActivityRef = useRef("");
  const pillLayout = inputLayout === "pill";
  const canSubmit = Boolean(value.trim() || attachments.length) && !disabled;
  const closePanel = useCallback(() => setPanelOpen(false), []);
  const forceVisible = Boolean(value.trim() || attachments.length) || asrEnabled || panelOpen;
  const autoHideRegion = useAutoHideRegion({ active: !hidden, enabled: autoHide, forceVisible });

  useEffect(() => {
    if (!value.trim()) {
      inputActivityRef.current = "false:false";
    }
  }, [value]);

  const reportInputActivity = (nextValue: string, composing: boolean) => {
    if (!batchEnabled) {
      return;
    }
    const activity = { composing, hasText: Boolean(nextValue.trim()) };
    const key = `${activity.hasText}:${activity.composing}`;
    if (inputActivityRef.current === key) {
      return;
    }
    inputActivityRef.current = key;
    onInputActivity(activity);
  };

  const handleInputChange = (nextValue: string) => {
    onChange(nextValue);
    reportInputActivity(nextValue, false);
  };

  const canDropFiles = Boolean(onDropFiles) && !disabled;
  const handleDragOver = (event: DragEvent<HTMLDivElement>) => {
    if (!canDropFiles || !Array.from(event.dataTransfer.types).includes("Files")) {
      return;
    }
    event.preventDefault();
    setDragActive(true);
  };
  const handleDragLeave = (event: DragEvent<HTMLDivElement>) => {
    if (event.currentTarget === event.target) {
      setDragActive(false);
    }
  };
  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    if (!canDropFiles) {
      return;
    }
    event.preventDefault();
    setDragActive(false);
    const files = Array.from(event.dataTransfer.files);
    if (files.length) {
      void onDropFiles?.(files);
    }
  };

  const submitFromKeyboard = async (flushBatch: boolean) => {
    await onSubmit();
    if (flushBatch && batchEnabled) {
      await onFlushBatch();
    }
  };

  const toggleAsr = () => {
    void onCommand({ type: asrEnabled ? "pause-asr" : "resume-asr" });
  };
  const asrButtonClassName = [
    "input-layer__asr-button",
    asrEnabled ? "input-layer__asr-button--enabled" : "",
    asrRunning ? "input-layer__asr-button--listening" : "",
    asrLoading ? "input-layer__asr-button--loading" : "",
  ]
    .filter(Boolean)
    .join(" ");
  const asrLabel = t(asrEnabled ? "chat.toolbar.pauseAsr" : "chat.toolbar.resumeAsr");
  const asrIcon = asrLoading ? (
    <LoaderCircle aria-hidden className="icon-button__icon input-layer__asr-spinner" />
  ) : asrEnabled ? (
    <MicOff aria-hidden className="icon-button__icon" />
  ) : (
    <Mic aria-hidden className="icon-button__icon" />
  );

  useDismissableLayer({ active: panelOpen, onDismiss: closePanel, rootRef });

  useEffect(() => {
    if (hidden || !pillLayout) {
      setPanelOpen(false);
    }
  }, [hidden, pillLayout]);

  if (hidden) {
    return null;
  }

  return (
    <div
      ref={rootRef}
      className="input-layer"
      data-auto-hide={autoHide ? "true" : "false"}
      data-chat-stage-hitbox="true"
      data-force-visible={forceVisible ? "true" : "false"}
      data-layout={inputLayout}
      data-asr-enabled={asrEnabled ? "true" : "false"}
      data-asr-loading={asrLoading ? "true" : "false"}
      data-listening={asrRunning ? "true" : "false"}
      data-has-attachments={attachments.length ? "true" : "false"}
      data-panel-open={panelOpen ? "true" : "false"}
      data-drag-active={dragActive ? "true" : "false"}
      data-visible={autoHideRegion.visible ? "true" : "false"}
      onBlurCapture={autoHideRegion.handleBlur}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      onFocusCapture={autoHideRegion.handleFocus}
      onPointerEnter={autoHideRegion.show}
      onPointerLeave={autoHideRegion.scheduleHide}
      style={autoHideRegion.visible ? undefined : { pointerEvents: "none" }}
    >
      <ThemeBackground prefix="chat-input" />
      <ThemeFrame prefix="chat-input" />
      {pillLayout ? (
        <IconButton
          aria-busy={asrLoading}
          aria-pressed={asrEnabled}
          className={`input-layer__press ${asrButtonClassName}`}
          data-active={asrEnabled ? "true" : "false"}
          disabled={disabled && !asrEnabled}
          label={asrLabel}
          onClick={toggleAsr}
        >
          {asrIcon}
        </IconButton>
      ) : null}
      <div className="input-layer__field">
        {attachments.length ? (
          <div aria-label={t("chat.input.attachments")} className="input-layer__attachments">
            {attachments.map((attachment) => (
              <button
                aria-label={t("chat.input.removeAttachment", { name: attachment.name })}
                className="input-layer__attachment"
                data-kind={attachment.kind}
                disabled={disabled}
                key={`${attachment.kind}:${attachment.path}`}
                onClick={() => onRemoveAttachment(attachment)}
                title={attachment.name}
                type="button"
              >
                <span className="input-layer__attachment-name">{attachment.name}</span>
                <X aria-hidden className="input-layer__attachment-remove" />
              </button>
            ))}
          </div>
        ) : null}
        {pillLayout ? (
          <TextInput
            autoComplete="off"
            className="input-layer__input input-layer__input--single"
            disabled={disabled}
            onChange={(event) => handleInputChange(event.target.value)}
            onCompositionEnd={(event) => reportInputActivity(event.currentTarget.value, false)}
            onCompositionStart={(event) => reportInputActivity(event.currentTarget.value, true)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.nativeEvent.isComposing) {
                event.preventDefault();
                void submitFromKeyboard(event.ctrlKey);
              }
            }}
            placeholder={t("chat.input.placeholder")}
            value={value}
          />
        ) : (
          <TextArea
            className="input-layer__input"
            disabled={disabled}
            onChange={(event) => handleInputChange(event.target.value)}
            onCompositionEnd={(event) => reportInputActivity(event.currentTarget.value, false)}
            onCompositionStart={(event) => reportInputActivity(event.currentTarget.value, true)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                void submitFromKeyboard(event.ctrlKey);
              }
            }}
            placeholder={t("chat.input.placeholder")}
            value={value}
          />
        )}
        {!pillLayout ? (
          <Button
            aria-label={t("chat.input.send")}
            backgroundLayer={<ThemeBackground prefix="chat-send" />}
            className="input-layer__send"
            disabled={!canSubmit}
            icon={<Send aria-hidden className="button__icon" />}
            onClick={() => void onSubmit()}
            variant="primary"
          >
            {t("chat.input.send")}
          </Button>
        ) : null}
      </div>
      {!pillLayout ? (
        <div aria-label={t("chat.input.attachments")} className="input-layer__attachment-stack" role="group">
          <IconButton
            className="input-layer__attachment-button"
            disabled={disabled}
            label={t("chat.input.attachImage")}
            onClick={() => onPickAttachments("image")}
          >
            <ImagePlus aria-hidden className="icon-button__icon" />
          </IconButton>
          <IconButton
            className="input-layer__attachment-button"
            disabled={disabled}
            label={t("chat.input.attachFile")}
            onClick={() => onPickAttachments("file")}
          >
            <FileText aria-hidden className="icon-button__icon" />
          </IconButton>
        </div>
      ) : null}
      {pillLayout ? (
        <>
          <div className="input-layer__pill-actions" role="group">
            <IconButton
              className="input-layer__quick-submit"
              backgroundLayer={<ThemeBackground prefix="chat-send" />}
              disabled={!canSubmit}
              label={t("chat.input.send")}
              onClick={() => void onSubmit()}
            >
              <Send aria-hidden className="icon-button__icon" />
            </IconButton>
            <IconButton
              aria-expanded={panelOpen}
              className="input-layer__extra-toggle"
              label={t("chat.input.moreActions")}
              onClick={() => setPanelOpen((current) => !current)}
            >
              <Plus aria-hidden className="icon-button__icon" />
            </IconButton>
          </div>
          <div
            aria-hidden={!panelOpen}
            className="input-layer__panel"
            data-open={panelOpen ? "true" : "false"}
            role="group"
          >
            <button
              className="input-layer__panel-button"
              disabled={disabled}
              onClick={() => {
                setPanelOpen(false);
                onPickAttachments("image");
              }}
              tabIndex={panelOpen ? undefined : -1}
              type="button"
            >
              <ImagePlus aria-hidden className="input-layer__panel-icon" />
              <span>{t("chat.input.attachImage")}</span>
            </button>
            <button
              className="input-layer__panel-button"
              disabled={disabled}
              onClick={() => {
                setPanelOpen(false);
                onPickAttachments("file");
              }}
              tabIndex={panelOpen ? undefined : -1}
              type="button"
            >
              <FileText aria-hidden className="input-layer__panel-icon" />
              <span>{t("chat.input.attachFile")}</span>
            </button>
          </div>
        </>
      ) : null}
      {!pillLayout ? (
        <div className="input-layer__voice-stack" role="group">
          <IconButton
            aria-busy={asrLoading}
            aria-pressed={asrEnabled}
            className={`input-layer__voice-button ${asrButtonClassName}`}
            disabled={disabled && !asrEnabled}
            label={asrLabel}
            onClick={toggleAsr}
          >
            {asrIcon}
          </IconButton>
        </div>
      ) : null}
    </div>
  );
}
