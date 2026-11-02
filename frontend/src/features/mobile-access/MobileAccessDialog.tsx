import { Copy, MonitorPlay, Smartphone } from "lucide-react";

import { useI18n } from "../../shared/i18n";
import type { MobileAccessInfo } from "../../shared/platform/types";
import { Button, Dialog, useToast } from "../../shared/ui";
import "./MobileAccessDialog.css";

export function MobileAccessDialog({
  info,
  onClose,
  onOpenLocalChat,
}: {
  info: MobileAccessInfo | null;
  onClose: () => void;
  onOpenLocalChat: () => void | Promise<void>;
}) {
  const { t } = useI18n();
  const { showToast } = useToast();

  const copyUrl = async () => {
    if (!info) {
      return;
    }
    await navigator.clipboard.writeText(info.url);
    showToast({ kind: "success", title: t("mobileAccess.copied") });
  };

  return (
    <Dialog
      className="mobile-access-dialog"
      closeLabel={t("common.close")}
      footer={
        <>
          <Button icon={<Copy aria-hidden className="button__icon" />} onClick={() => void copyUrl()}>
            {t("mobileAccess.copy")}
          </Button>
          <Button
            icon={<MonitorPlay aria-hidden className="button__icon" />}
            onClick={() => void onOpenLocalChat()}
            variant="primary"
          >
            {t("mobileAccess.openLocalChat")}
          </Button>
        </>
      }
      onClose={onClose}
      open={Boolean(info)}
      title={t("mobileAccess.title")}
    >
      {info ? (
        <div className="mobile-access-dialog__content">
          <div className="mobile-access-dialog__lead">
            <Smartphone aria-hidden />
            <p>{t("mobileAccess.description")}</p>
          </div>
          <img alt={t("mobileAccess.qrAlt")} className="mobile-access-dialog__qr" src={info.qrCodeDataUrl} />
          <code className="mobile-access-dialog__url">{info.url}</code>
          <p className="mobile-access-dialog__firewall" role="note">
            {t("mobileAccess.firewall", {
              httpPort: info.httpPort,
              websocketPort: info.websocketPort,
            })}
          </p>
        </div>
      ) : null}
    </Dialog>
  );
}
