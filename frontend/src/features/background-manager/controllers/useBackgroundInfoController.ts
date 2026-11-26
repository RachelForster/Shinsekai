import { useCallback } from "react";
import { useMutation } from "@tanstack/react-query";

import { translateBackgroundFields } from "../../../entities/background/repository";
import { tagContents, numberedTags } from "../../../shared/assets/assetText";
import { TAG_PREFIX_MUSIC } from "../../../shared/constants";
import { useI18n } from "../../../shared/i18n";
import { useToast } from "../../../shared/ui";
import type { BackgroundPageContext } from "../backgroundContext";

export function useBackgroundInfoController(ctx: BackgroundPageContext) {
  const { showToast } = useToast();
  const { t } = useI18n();

  const translateMutation = useMutation({
    mutationFn: () =>
      translateBackgroundFields({
        bgTags: ctx.currentDraft.bg_tags,
        bgmRowTags: tagContents(ctx.currentDraft.bgm_tags, ctx.currentDraft.bgm_list.length),
        bgmTags: ctx.currentDraft.bgm_tags,
        name: ctx.currentDraft.name,
      }),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("background.error.translateFallback"),
        title: t("background.action.aiTranslate"),
      });
    },
    onSuccess(result) {
      if (result.error) {
        showToast({ kind: "error", message: result.error, title: t("background.action.aiTranslate") });
        return;
      }
      ctx.patchDraft((current) => ({
        ...current,
        bg_tags: result.bgTags,
        bgm_tags:
          result.bgmRowTags && result.bgmRowTags.length === current.bgm_list.length
            ? numberedTags(TAG_PREFIX_MUSIC, result.bgmRowTags)
            : result.bgmTags,
        name: result.name,
      }));
      if (result.name.trim()) {
        ctx.setNameError("");
      }
      showToast({ kind: "success", title: t("background.action.aiTranslate") });
    },
  });

  const handleTranslate = useCallback(() => {
    if (!ctx.currentDraft.name.trim() && !ctx.currentDraft.bg_tags.trim() && !ctx.currentDraft.bgm_tags.trim()) {
      showToast({
        kind: "error",
        message: t("common.fixInvalidFields"),
        title: t("common.validationFailed"),
      });
      return;
    }
    translateMutation.mutate();
  }, [ctx.currentDraft.bg_tags, ctx.currentDraft.bgm_tags, ctx.currentDraft.name, showToast, t, translateMutation]);

  return {
    handleTranslate,
    translatePending: translateMutation.isPending,
  };
}
