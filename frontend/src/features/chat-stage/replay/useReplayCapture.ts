import { useEffect, useRef, useState } from "react";

import { useI18n } from "../../../shared/i18n";
import { useToast } from "../../../shared/ui";
import type { HistoryExportFormat, ReplayCapture } from "./historyExport";

export function useReplayCapture(
  capture: ReplayCapture | undefined,
  ended: boolean,
  onExport: (blob: Blob, format: HistoryExportFormat) => Promise<void>,
) {
  const { t } = useI18n();
  const { showToast } = useToast();
  const notices = useRef({ t, showToast, onExport });
  notices.current = { t, showToast, onExport };
  const [finished, setFinished] = useState<ReplayCapture>();
  const mounted = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (!capture) return;
    let active = true;
    // Let the history modal leave the stage before capturing the first frame.
    const frame = requestAnimationFrame(capture.start);
    void capture.result.then((result) => {
      if (!mounted.current) return;
      const { t, showToast, onExport } = notices.current;
      if (active) setFinished(capture);
      if (result.kind === "saved") {
        // The recorder can flush its final chunk after replay has already exited.
        const format = result.blob.type.startsWith("video/mp4") ? "mp4" : "webm";
        void onExport(result.blob, format).catch(() => {
          showToast({ kind: "error", title: t("chat.history.selection.exportFailed") });
        });
      } else if (active && result.kind === "failed") {
        showToast({ kind: "error", title: t("chat.history.selection.videoFailed") });
      }
    });
    return () => {
      active = false;
      cancelAnimationFrame(frame);
      capture.stop(false);
    };
  }, [capture]);

  useEffect(() => {
    if (ended) capture?.stop(true);
  }, [capture, ended]);

  return Boolean(capture && capture !== finished);
}
