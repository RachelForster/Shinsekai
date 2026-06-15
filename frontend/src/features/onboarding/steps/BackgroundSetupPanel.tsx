import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, FileUp, Sparkles } from "lucide-react";

import { backgroundsQueryKey, importBackgrounds, listBackgrounds } from "../../../entities/background/repository";
import type { Background } from "../../../entities/config/types";
import { openExternal } from "../../../entities/files/repository";
import { Button, EmptyState, QueryErrorState, useToast } from "../../../shared/ui";
import { ExistingList, OnboardingPanelLayout } from "../OnboardingPanelLayout";
import type { OnboardingCopy } from "../onboardingCopy";

interface BackgroundSetupPanelProps {
  copy: OnboardingCopy;
}

export function BackgroundSetupPanel({ copy }: BackgroundSetupPanelProps) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const backgroundsQuery = useQuery({ queryFn: listBackgrounds, queryKey: backgroundsQueryKey });

  const importMutation = useMutation({
    mutationFn: (files: File[]) => importBackgrounds(files),
    onError(error) {
      showToast({ kind: "error", message: error instanceof Error ? error.message : "", title: copy.toastFailed });
    },
    onSuccess(imported) {
      void queryClient.invalidateQueries({ queryKey: backgroundsQueryKey });
      showToast({ kind: "success", message: String(imported.length), title: copy.backgrounds.imported });
    },
  });

  if (backgroundsQuery.isLoading) {
    return <EmptyState title={copy.common.loading} />;
  }

  if (backgroundsQuery.isError) {
    return (
      <QueryErrorState
        error={backgroundsQuery.error}
        onRetry={() => void backgroundsQuery.refetch()}
        retryLabel={copy.actions.retry}
        title={copy.toastFailed}
      />
    );
  }

  const backgrounds = backgroundsQuery.data ?? [];

  return (
    <OnboardingPanelLayout
      copy={copy}
      description={copy.backgrounds.description}
      done={backgrounds.length > 0}
      title={copy.backgrounds.title}
    >
      <div className="onboarding-resource-steps">
        <section className="onboarding-resource-step">
          <span className="onboarding-resource-step__index">1</span>
          <div className="onboarding-resource-step__body">
            <h3>{copy.backgrounds.resourceLink}</h3>
            <p>{copy.backgrounds.resourceBody}</p>
          </div>
          <Button
            className="onboarding-compact-button"
            icon={<ExternalLink aria-hidden size={14} />}
            onClick={() => openExternal("https://shinsekai.end0rph1n.icu/resources")}
            variant="ghost"
          >
            {copy.backgrounds.resourceLink}
          </Button>
        </section>
        <section className="onboarding-resource-step">
          <span className="onboarding-resource-step__index">2</span>
          <div className="onboarding-resource-step__body">
            <h3>{copy.actions.import}</h3>
            <p>{copy.backgrounds.description}</p>
            <ExistingList emptyLabel={copy.backgrounds.empty} items={backgrounds.map((item) => item.name)} />
          </div>
          <Button
            className="onboarding-compact-button onboarding-file-picker-button"
            icon={<FileUp aria-hidden size={14} />}
            loading={importMutation.isPending}
            variant="primary"
          >
            {copy.actions.import}
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
          <span>{copy.backgrounds.transparentBody}</span>
        </div>
      </div>
    </OnboardingPanelLayout>
  );
}
