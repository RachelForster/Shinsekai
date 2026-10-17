import { AlertTriangle } from "lucide-react";

import { useI18n } from "../i18n";
import type { CharacterMemoryImportPreview } from "../platform/types";
import "./ImportPreview.css";

export function ImportPreview({
  preview,
  target,
  sourceLabel,
}: {
  preview: CharacterMemoryImportPreview;
  target?: string;
  sourceLabel?: string;
}) {
  const { language, t } = useI18n();
  const formatNumber = (value: number) =>
    new Intl.NumberFormat(language === "zh_CN" ? "zh-CN" : language).format(value);

  return (
    <div className="memory-import-preview">
      {target ? <p className="memory-import-preview__lead">{target}</p> : null}
      <p className="memory-import-preview__lead">
        {t("character.memory.importPreviewSummary", {
          chunks: formatNumber(preview.chunkCount),
          files: formatNumber(preview.fileCount),
          tokens: formatNumber(preview.estimatedTotalTokens),
        })}
      </p>
      <dl className="memory-import-preview__metrics">
        <div>
          <dt>{sourceLabel ?? t("character.memory.importDialogue")}</dt>
          <dd>
            {t("character.memory.importDialogueValue", {
              characters: formatNumber(preview.dialogueCharacters),
              lines: formatNumber(preview.dialogueLineCount),
            })}
          </dd>
        </div>
        <div>
          <dt>{t("character.memory.importSourceTokens")}</dt>
          <dd>≈ {formatNumber(preview.sourceTokens)}</dd>
        </div>
        <div>
          <dt>{t("character.memory.importChunks")}</dt>
          <dd>
            {t("character.memory.importChunksValue", {
              chunks: formatNumber(preview.chunkCount),
              requests: formatNumber(preview.chunkCount),
            })}
          </dd>
        </div>
        <div>
          <dt>{t("character.memory.importEstimatedInput")}</dt>
          <dd>≈ {formatNumber(preview.estimatedInputTokens)}</dd>
        </div>
        <div>
          <dt>{t("character.memory.importEstimatedOutput")}</dt>
          <dd>≈ {formatNumber(preview.estimatedOutputTokens)}</dd>
        </div>
        <div className="memory-import-preview__metric--total">
          <dt>{t("character.memory.importEstimatedTotal")}</dt>
          <dd>≈ {formatNumber(preview.estimatedTotalTokens)}</dd>
        </div>
      </dl>
      <p className="memory-import-preview__notice">
        <AlertTriangle aria-hidden size={18} />
        <span>{t("character.memory.importBillingNote")}</span>
      </p>
      {preview.files.some((file) => file.kind.toLowerCase() === "json") ? (
        <p className="inline-status">{t("character.memory.importJsonNote")}</p>
      ) : null}
      {preview.warnings.length ? (
        <ul className="memory-import-preview__warnings">
          {preview.warnings.map((warning, index) => (
            <li key={`${warning}-${index}`}>{warning}</li>
          ))}
        </ul>
      ) : null}
      <div className="memory-import-preview__files">
        {preview.files.map((file, index) => (
          <div className="memory-import-preview__file" key={`${file.name}-${index}`}>
            <strong>{file.name}</strong>
            <span>
              {t("character.memory.importFileDetail", {
                chunks: formatNumber(file.chunkCount),
                kind: file.kind.toUpperCase(),
                tokens: formatNumber(file.sourceTokens),
              })}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
