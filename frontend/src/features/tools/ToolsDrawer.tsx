import { useEffect } from "react";
import { X } from "lucide-react";

import { useI18n } from "../../shared/i18n";
import { ToolsPanelContent } from "./ToolsPage";

interface ToolsDrawerProps {
  open: boolean;
  onClose: () => void;
}

export function ToolsDrawer({ onClose, open }: ToolsDrawerProps) {
  const { t } = useI18n();

  useEffect(() => {
    if (!open) {
      return undefined;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, open]);

  if (!open) {
    return null;
  }

  return (
    <div className="tools-drawer-layer">
      <button aria-label={t("common.close")} className="tools-drawer-scrim" onClick={onClose} type="button" />
      <aside aria-label={t("nav.tools")} aria-modal="true" className="tools-drawer" role="dialog">
        <header className="tools-drawer__header">
          <h2 className="tools-drawer__title">{t("nav.tools")}</h2>
          <button aria-label={t("common.close")} className="tools-drawer__close" onClick={onClose} type="button">
            <X aria-hidden />
          </button>
        </header>
        <div className="tools-drawer__body">
          <ToolsPanelContent embedded />
        </div>
      </aside>
    </div>
  );
}
