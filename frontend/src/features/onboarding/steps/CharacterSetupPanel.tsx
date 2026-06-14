import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, FileUp } from "lucide-react";

import { openExternal } from "../../../entities/files/repository";
import { charactersQueryKey, importCharacters, listCharacters } from "../../../entities/character/repository";
import type { Character } from "../../../entities/config/types";
import { Button, EmptyState, QueryErrorState, useToast } from "../../../shared/ui";
import { CHARACTER_RESOURCES_URL } from "../../character-editor/characterEditorUtils";
import { ExistingList, OnboardingPanelLayout } from "../OnboardingPanelLayout";
import type { OnboardingCopy } from "../onboardingCopy";

interface CharacterSetupPanelProps {
  copy: OnboardingCopy;
}

export function CharacterSetupPanel({ copy }: CharacterSetupPanelProps) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const charactersQuery = useQuery({ queryFn: listCharacters, queryKey: charactersQueryKey });

  const importMutation = useMutation({
    mutationFn: (files: File[]) => importCharacters(files),
    onError(error) {
      showToast({ kind: "error", message: error instanceof Error ? error.message : "", title: copy.toastFailed });
    },
    onSuccess(imported) {
      void queryClient.invalidateQueries({ queryKey: charactersQueryKey });
      showToast({ kind: "success", message: String(imported.length), title: copy.characters.imported });
    },
  });

  if (charactersQuery.isLoading) {
    return <EmptyState title={copy.common.loading} />;
  }

  if (charactersQuery.isError) {
    return (
      <QueryErrorState
        error={charactersQuery.error}
        onRetry={() => void charactersQuery.refetch()}
        retryLabel={copy.actions.retry}
        title={copy.toastFailed}
      />
    );
  }

  const characters = charactersQuery.data ?? [];

  return (
    <OnboardingPanelLayout
      copy={copy}
      description={copy.characters.description}
      done={characters.length > 0}
      title={copy.characters.title}
    >
      <div className="onboarding-resource-steps">
        <section className="onboarding-resource-step">
          <span className="onboarding-resource-step__index">1</span>
          <div className="onboarding-resource-step__body">
            <h3>{copy.characters.resourceLink}</h3>
            <p>{copy.characters.resourceBody}</p>
          </div>
          <Button
            className="onboarding-compact-button"
            icon={<ExternalLink aria-hidden size={14} />}
            onClick={() => openExternal(CHARACTER_RESOURCES_URL)}
            variant="ghost"
          >
            {copy.characters.resourceLink}
          </Button>
        </section>
        <section className="onboarding-resource-step">
          <span className="onboarding-resource-step__index">2</span>
          <div className="onboarding-resource-step__body">
            <h3>{copy.actions.import}</h3>
            <p>{copy.characters.description}</p>
            <ExistingList emptyLabel={copy.characters.empty} items={characters.map((item) => item.name)} />
          </div>
          <Button
            className="onboarding-compact-button onboarding-file-picker-button"
            icon={<FileUp aria-hidden size={14} />}
            loading={importMutation.isPending}
            variant="primary"
          >
            {copy.actions.import}
            <input
              accept=".char,.cha"
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
    </OnboardingPanelLayout>
  );
}
