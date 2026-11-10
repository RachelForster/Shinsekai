import { useId } from "react";

import { useI18n } from "../../../shared/i18n";
import { ChatStageModal } from "../components/ChatStageModal";
import type { HistoryExportResult } from "./historyExport";

export function HistoryExportDialog({ result, onClose }: { result: HistoryExportResult; onClose: () => void }) {
  const titleId = useId();
  const { t } = useI18n();
  const image = result.format === "png";
  const title = t(image ? "chat.history.selection.imageReady" : "chat.history.selection.videoReady");
  return (
    <ChatStageModal
      backdropClassName="chat-history-backdrop"
      closeLabel={t("common.close")}
      dialogClassName="chat-history-dialog chat-history-export"
      labelledBy={titleId}
      onClose={onClose}
      open
      title={title}
    >
      <div className="chat-stage-modal__body chat-history-export__body">
        {result.previewUrl &&
          (image ? (
            <img alt={title} className="chat-history-export__media" src={result.previewUrl} />
          ) : (
            <video className="chat-history-export__media" controls playsInline src={result.previewUrl} />
          ))}
        <div className="chat-history-export__location">
          <span>{t(result.path ? "chat.history.selection.savedPath" : "chat.history.selection.downloadedName")}</span>
          <code>{result.path ?? result.name}</code>
        </div>
      </div>
    </ChatStageModal>
  );
}
