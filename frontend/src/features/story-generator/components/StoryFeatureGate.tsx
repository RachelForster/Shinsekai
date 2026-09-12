import { useI18n } from "../../../shared/i18n";
import { Button } from "../../../shared/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { configQueryKey, getAppConfig, saveSystemConfig } from "../../../entities/config/repository";

export function StoryFeatureGate({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const client = useQueryClient();
  const config = useQuery({ queryKey: configQueryKey, queryFn: getAppConfig });
  const enable = useMutation({
    mutationFn: async () => {
      if (!config.data) throw new Error(t("story.enable.loadFirst"));
      await saveSystemConfig({ ...config.data.system_config, story_system_enabled: true });
    },
    onSuccess: () => client.invalidateQueries({ queryKey: configQueryKey }),
  });
  if (config.data?.system_config.story_system_enabled) return children;
  return (
    <section className="section">
      <h2 className="section__title">{t("story.enable.action")}</h2>
      <p className="section__description">{t("story.enable.hint")}</p>
      {config.isPending ? (
        <p className="section__description" role="status">
          {t("story.enable.loading")}
        </p>
      ) : (
        <Button
          variant="primary"
          disabled={enable.isPending || config.isError}
          onClick={() => enable.mutate()}
          type="button"
        >
          {enable.isPending ? t("story.enable.pending") : t("story.enable.action")}
        </Button>
      )}
      {(enable.error || config.error) && (
        <p className="section__description" role="alert">
          {(enable.error || config.error)?.message}
        </p>
      )}
      {config.isError && (
        <Button type="button" onClick={() => void config.refetch()}>
          {t("common.retry")}
        </Button>
      )}
    </section>
  );
}
