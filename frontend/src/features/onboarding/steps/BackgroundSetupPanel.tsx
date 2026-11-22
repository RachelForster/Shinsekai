import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, FileUp, Sparkles } from "lucide-react";

import { backgroundsQueryKey, importBackgrounds, listBackgrounds } from "../../../entities/background/repository";
import { openExternal } from "../../../entities/files/repository";
import { formatBackgroundName, useI18n } from "../../../shared/i18n";
import { Button, EmptyState, QueryErrorState, useToast } from "../../../shared/ui";
import { ExistingList, OnboardingPanelLayout } from "../OnboardingPanelLayout";

export function BackgroundSetupPanel() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const backgroundsQuery = useQuery({ queryFn: listBackgrounds, queryKey: backgroundsQueryKey });

  const importMutation = useMutation({
    mutationFn: (files: File[]) => importBackgrounds(files),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : "",
        title: t("onboarding.toastFailed"),
      });
    },
    onSuccess(imported) {
      void queryClient.invalidateQueries({ queryKey: backgroundsQueryKey });
      showToast({
        kind: "success",
        message: String(imported.length),
        title: t("onboarding.backgrounds.imported"),
      });
    },
  });

  if (backgroundsQuery.isLoading) {
    return <EmptyState title={t("onboarding.common.loading")} />;
  }

  if (backgroundsQuery.isError) {
    return (
      <QueryErrorState
        error={backgroundsQuery.error}
        onRetry={() => void backgroundsQuery.refetch()}
        retryLabel={t("onboarding.actions.retry")}
        title={t("onboarding.toastFailed")}
      />
    );
  }

  const backgrounds = backgroundsQuery.data ?? [];

  return (
    <OnboardingPanelLayout
      description={t("onboarding.backgrounds.description")}
      done={backgrounds.length > 0}
      title={t("onboarding.backgrounds.title")}
    >
      <div className="onboarding-resource-steps">
        <section className="onboarding-resource-step">
          <span className="onboarding-resource-step__index">1</span>
          <div className="onboarding-resource-step__body">
            <h3>{t("onboarding.backgrounds.resourceLink")}</h3>
            <p>{t("onboarding.backgrounds.resourceBody")}</p>
          </div>
          <Button
            className="onboarding-compact-button"
            icon={<ExternalLink aria-hidden size={14} />}
            onClick={() => openExternal("https://shinsekai.end0rph1n.icu/resources")}
            variant="ghost"
          >
            {t("onboarding.backgrounds.resourceLink")}
          </Button>
        </section>
        <section className="onboarding-resource-step">
          <span className="onboarding-resource-step__index">2</span>
          <div className="onboarding-resource-step__body">
            <h3>{t("onboarding.actions.import")}</h3>
            <p>{t("onboarding.backgrounds.description")}</p>
            <ExistingList
              emptyLabel={t("onboarding.backgrounds.empty")}
              items={backgrounds.map((item) => formatBackgroundName(item.name, t))}
            />
          </div>
          <Button
            className="onboarding-compact-button onboarding-file-picker-button"
            icon={<FileUp aria-hidden size={14} />}
            loading={importMutation.isPending}
            variant="primary"
          >
            {t("onboarding.actions.import")}
            <input
              accept=".bg"
              multiple
              onChange={(event) => {
                const files = Array.from(event.target.files ?? []);
                if (files.length) {
                  importMutation.mutate(files);
                }
                event.currentTarget.value = "";
              }}
              type="file"
            />
          </Button>
        </section>
      </div>
      <div className="onboarding-resource-transparent">
        <div className="onboarding-resource-note onboarding-resource-note--soft">
          <Sparkles aria-hidden size={18} />
          <span>{t("onboarding.backgrounds.transparentBody")}</span>
        </div>
      </div>
    </OnboardingPanelLayout>
  );
}
