import { Play, RotateCw } from "lucide-react";

import { useI18n } from "../../shared/i18n";
import { AlertDialog, AsyncButton, Button } from "../../shared/ui";
import type { TemplateEditorContext } from "./templateContext";

interface TemplatePageFooterProps {
  ctx: TemplateEditorContext;
}

export function TemplatePageFooter({ ctx }: TemplatePageFooterProps) {
  const { t } = useI18n();

  return (
    <>
      <footer
        className={`template-page__footer${ctx.createOnly || ctx.conversationId ? " template-page__footer--single" : ""}`}
      >
        <AsyncButton
          disabled={
            !ctx.sessionRestored ||
            ctx.runtimeClosing ||
            (!ctx.conversationId && ctx.runtimeLaunchDisabled) ||
            ctx.initializationPending
          }
          icon={<Play aria-hidden className="button__icon" />}
          loading={ctx.launchPending}
          onClick={() => ctx.handleLaunch(false)}
          variant="primary"
        >
          {t(
            ctx.conversationId
              ? "conversation.saveAndContinue"
              : ctx.createOnly
                ? "conversation.createAndStart"
                : "template.action.launch",
          )}
        </AsyncButton>
        {!ctx.createOnly && !ctx.conversationId && (
          <Button
            disabled={!ctx.sessionRestored || ctx.runtimeLaunchDisabled || ctx.initializationPending}
            icon={<RotateCw aria-hidden className="button__icon" />}
            onClick={() => ctx.setQuickRestartOpen(true)}
            variant="ghost"
          >
            {t("template.action.quickRestart")}
          </Button>
        )}
      </footer>

      <AlertDialog
        body={t("template.quickRestart.body")}
        cancelLabel={t("common.cancel")}
        closeLabel={t("common.close")}
        confirmLabel={t("template.action.quickRestart")}
        onCancel={() => ctx.setQuickRestartOpen(false)}
        onConfirm={() => {
          ctx.setQuickRestartOpen(false);
          ctx.handleLaunch(true);
        }}
        open={ctx.quickRestartOpen}
        title={t("template.quickRestart.title")}
      />
    </>
  );
}
