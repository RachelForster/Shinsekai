import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Sparkles } from "lucide-react";

import { useI18n } from "../../shared/i18n";
import type { DialogFormatOption, DialogOutputFormatId, MediaSelectionMode } from "../../shared/platform/types";
import { AsyncButton, Button, Dialog, NumberInput, Select, Switch, TextArea } from "../../shared/ui";
import { SemanticMediaSwitch } from "./SemanticMediaSwitch";
import { DEFAULT_NEW_OUTPUT_FORMAT, resolveSupportedOutputFormat } from "./templateFlow";

const FALLBACK_DIALOG_FORMATS: DialogFormatOption[] = [
  { id: "xml_v1", label: "XML / HTML Tags", builtin: true },
  { id: "json_v1", label: "JSON", builtin: true },
];

export function resolveDialogFormatLabel(
  formatId: DialogOutputFormatId,
  dialogFormats: DialogFormatOption[] | undefined,
  t: (key: "template.outputFormat.xml_v1" | "template.outputFormat.json_v1") => string,
): string {
  if (formatId === "xml_v1") {
    return t("template.outputFormat.xml_v1");
  }
  if (formatId === "json_v1") {
    return t("template.outputFormat.json_v1");
  }
  return dialogFormats?.find((item) => item.id === formatId)?.label || formatId;
}

export interface SystemPromptRulesDraft {
  mediaSelectionMode: MediaSelectionMode;
  outputFormat: DialogOutputFormatId;
  useEffectPrompt: boolean;
  useTranslation: boolean;
  useCot: boolean;
  useChoice: boolean;
  useNarration: boolean;
  useStat: boolean;
  maxSpeechChars: number;
  maxDialogItems: number;
}

export interface SystemPromptCommit extends SystemPromptRulesDraft {
  system: string;
  systemManuallyEdited: boolean;
}

interface SystemPromptDialogProps {
  open: boolean;
  dialogFormats?: DialogFormatOption[];
  rules: SystemPromptRulesDraft;
  systemText: string;
  systemManuallyEdited: boolean;
  systemConfigStale: boolean;
  canAutoSync: boolean;
  generating?: boolean;
  onRegenerate: (rules: SystemPromptRulesDraft, options: { silent: boolean }) => Promise<string | null>;
  onClose: () => void;
  onConfirm: (next: SystemPromptCommit) => void;
}

function rulesSignature(rules: SystemPromptRulesDraft): string {
  return [
    rules.mediaSelectionMode,
    rules.outputFormat,
    rules.useEffectPrompt,
    rules.useTranslation,
    rules.useCot,
    rules.useChoice,
    rules.useNarration,
    rules.useStat,
    rules.maxSpeechChars,
    rules.maxDialogItems,
  ].join("|");
}

export function SystemPromptDialog({
  open,
  dialogFormats,
  rules,
  systemText,
  systemManuallyEdited,
  systemConfigStale,
  canAutoSync,
  generating = false,
  onRegenerate,
  onClose,
  onConfirm,
}: SystemPromptDialogProps) {
  const { t } = useI18n();

  const [draftRules, setDraftRules] = useState<SystemPromptRulesDraft>(rules);
  const [draftSystem, setDraftSystem] = useState(systemText);
  const [draftManuallyEdited, setDraftManuallyEdited] = useState(systemManuallyEdited);
  const [draftLocalStale, setDraftLocalStale] = useState(systemConfigStale);
  const [localGenerating, setLocalGenerating] = useState(false);

  const wasOpenRef = useRef(false);
  const initialSigRef = useRef("");
  const lastSyncedSigRef = useRef("");

  const formatOptions = useMemo(
    () => (dialogFormats?.length ? dialogFormats : FALLBACK_DIALOG_FORMATS),
    [dialogFormats],
  );

  useEffect(() => {
    if (!open) {
      wasOpenRef.current = false;
      return;
    }
    if (wasOpenRef.current) {
      return;
    }
    wasOpenRef.current = true;
    const normalizedRules: SystemPromptRulesDraft = {
      ...rules,
      outputFormat: resolveSupportedOutputFormat(rules.outputFormat, formatOptions, DEFAULT_NEW_OUTPUT_FORMAT),
    };
    setDraftRules(normalizedRules);
    setDraftSystem(systemText);
    setDraftManuallyEdited(systemManuallyEdited);
    setDraftLocalStale(systemConfigStale);
    const sig = rulesSignature(normalizedRules);
    initialSigRef.current = sig;
    lastSyncedSigRef.current = sig;
  }, [formatOptions, open, rules, systemConfigStale, systemManuallyEdited, systemText]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const supported = resolveSupportedOutputFormat(draftRules.outputFormat, formatOptions, DEFAULT_NEW_OUTPUT_FORMAT);
    if (supported !== draftRules.outputFormat) {
      setDraftRules((curr) => ({ ...curr, outputFormat: supported }));
    }
  }, [draftRules.outputFormat, formatOptions, open]);

  const currentSig = useMemo(() => rulesSignature(draftRules), [draftRules]);

  useEffect(() => {
    if (!open) {
      return;
    }
    if (draftManuallyEdited) {
      if (currentSig !== initialSigRef.current || systemConfigStale) {
        setDraftLocalStale(true);
      }
      return;
    }
    if (!canAutoSync || currentSig === lastSyncedSigRef.current) {
      return;
    }
    lastSyncedSigRef.current = currentSig;
    let active = true;
    const timer = window.setTimeout(async () => {
      setLocalGenerating(true);
      try {
        const nextSystem = await onRegenerate(draftRules, { silent: true });
        if (active && nextSystem !== null) {
          setDraftSystem(nextSystem);
          setDraftLocalStale(false);
        }
      } finally {
        if (active) {
          setLocalGenerating(false);
        }
      }
    }, 160);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [canAutoSync, currentSig, draftManuallyEdited, draftRules, onRegenerate, open, systemConfigStale]);

  const handleManualRegenerate = async () => {
    setLocalGenerating(true);
    try {
      const nextSystem = await onRegenerate(draftRules, { silent: false });
      if (nextSystem !== null) {
        setDraftSystem(nextSystem);
        setDraftManuallyEdited(false);
        setDraftLocalStale(false);
        lastSyncedSigRef.current = currentSig;
        initialSigRef.current = currentSig;
      }
    } finally {
      setLocalGenerating(false);
    }
  };

  const busy = generating || localGenerating;

  const toggleRows = [
    {
      key: "effect",
      label: t("template.field.useEffect"),
      value: draftRules.useEffectPrompt,
      onChange: (checked: boolean) => setDraftRules((curr) => ({ ...curr, useEffectPrompt: checked })),
    },
    {
      key: "translation",
      label: t("template.field.useTranslation"),
      value: draftRules.useTranslation,
      onChange: (checked: boolean) => setDraftRules((curr) => ({ ...curr, useTranslation: checked })),
    },
    {
      key: "cot",
      label: t("template.field.useCot"),
      value: draftRules.useCot,
      onChange: (checked: boolean) => setDraftRules((curr) => ({ ...curr, useCot: checked })),
    },
    {
      key: "choice",
      label: t("template.field.useChoice"),
      value: draftRules.useChoice,
      onChange: (checked: boolean) => setDraftRules((curr) => ({ ...curr, useChoice: checked })),
    },
    {
      key: "narration",
      label: t("template.field.useNarration"),
      value: draftRules.useNarration,
      onChange: (checked: boolean) => setDraftRules((curr) => ({ ...curr, useNarration: checked })),
    },
    {
      key: "stat",
      label: t("template.field.useStat"),
      value: draftRules.useStat,
      onChange: (checked: boolean) => setDraftRules((curr) => ({ ...curr, useStat: checked })),
    },
  ];

  return (
    <Dialog
      bodyClassName="template-editor-dialog__body"
      className="template-editor-dialog template-editor-dialog--system-prompt"
      closeLabel={t("common.close")}
      dismissible={!busy}
      footer={
        <>
          <Button disabled={busy} onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            disabled={busy}
            icon={<Check aria-hidden className="button__icon" />}
            onClick={() =>
              onConfirm({
                ...draftRules,
                system: draftSystem,
                systemManuallyEdited: draftManuallyEdited,
              })
            }
            variant="primary"
          >
            {t("common.confirm")}
          </Button>
        </>
      }
      onClose={onClose}
      open={open}
      title={t("template.systemDialog.title")}
    >
      <section className="template-dialog-subsection">
        <div className="template-dialog-subsection__header">
          <div className="template-system-dialog__title-row">
            <h3 className="template-dialog-subsection__title">{t("template.systemDialog.rulesTitle")}</h3>
            <span
              className={`template-status-pill${
                draftManuallyEdited ? (draftLocalStale ? " is-warning" : " is-manual") : " is-auto"
              }`}
            >
              {draftManuallyEdited
                ? t(draftLocalStale ? "template.bar.systemManualStale" : "template.bar.systemManual")
                : t("template.bar.systemAuto")}
            </span>
          </div>
          <AsyncButton
            className="template-generate-button"
            icon={<Sparkles aria-hidden className="button__icon" />}
            loading={busy}
            onClick={() => void handleManualRegenerate()}
            variant="primary"
          >
            {t("template.systemDialog.regenerate")}
          </AsyncButton>
        </div>

        <p className="template-options-panel__hint">
          {draftManuallyEdited
            ? t(draftLocalStale ? "template.systemDialog.staleHint" : "template.systemDialog.manualHint")
            : t("template.systemDialog.autoHint")}
        </p>

        <label className="template-side-field">
          <span className="template-side-field__label">{t("template.field.outputFormat")}</span>
          <Select
            aria-label={t("template.field.outputFormat")}
            onChange={(event) =>
              setDraftRules((curr) => ({
                ...curr,
                outputFormat: event.target.value || formatOptions[0]?.id || DEFAULT_NEW_OUTPUT_FORMAT,
              }))
            }
            value={draftRules.outputFormat}
          >
            {formatOptions.map((option) => (
              <option key={option.id} value={option.id}>
                {resolveDialogFormatLabel(option.id, formatOptions, t)}
              </option>
            ))}
          </Select>
          <span className="template-options-panel__hint">{t("template.field.outputFormatHint")}</span>
        </label>

        <div className="template-option-list template-option-list--dialog">
          <SemanticMediaSwitch
            checked={draftRules.mediaSelectionMode === "semantic"}
            onChange={(enabled) =>
              setDraftRules((curr) => ({ ...curr, mediaSelectionMode: enabled ? "semantic" : "indexed" }))
            }
            verifyOnMount={false}
          />
          {toggleRows.map((option) => (
            <label className="template-toggle-row" key={option.key}>
              <span>{option.label}</span>
              <Switch checked={option.value} onChange={(event) => option.onChange(event.target.checked)} />
            </label>
          ))}
        </div>

        <div className="template-number-grid">
          <label className="template-side-field">
            <span className="template-side-field__label">{t("template.field.maxSpeechChars")}</span>
            <NumberInput
              max={500000}
              min={0}
              onChange={(event) =>
                setDraftRules((curr) => ({
                  ...curr,
                  maxSpeechChars: Number.parseInt(event.target.value, 10) || 0,
                }))
              }
              step={10}
              value={draftRules.maxSpeechChars}
            />
          </label>
          <label className="template-side-field">
            <span className="template-side-field__label">{t("template.field.maxDialogItems")}</span>
            <NumberInput
              max={500}
              min={0}
              onChange={(event) =>
                setDraftRules((curr) => ({
                  ...curr,
                  maxDialogItems: Number.parseInt(event.target.value, 10) || 0,
                }))
              }
              value={draftRules.maxDialogItems}
            />
          </label>
        </div>
      </section>

      <section className="template-dialog-subsection">
        <label className="template-stack-field">
          <span className="template-panel__label">{t("template.field.system")}</span>
          <TextArea
            className="template-system-textarea"
            onChange={(event) => {
              setDraftSystem(event.target.value);
              setDraftManuallyEdited(true);
              setDraftLocalStale(false);
            }}
            rows={14}
            value={draftSystem}
          />
        </label>
      </section>
    </Dialog>
  );
}
