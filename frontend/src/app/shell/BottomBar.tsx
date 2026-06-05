import { useIsFetching, useIsMutating } from "@tanstack/react-query";

import { useI18n } from "../../shared/i18n";
import { useAppUpdateInfo } from "./useAppUpdateInfo";

export function BottomBar() {
  const fetching = useIsFetching();
  const mutating = useIsMutating();
  const { t } = useI18n();
  const versionQuery = useAppUpdateInfo();
  const status = mutating ? t("bottom.saving") : fetching ? t("bottom.syncing") : "";
  const rawVersion = versionQuery.data?.version?.trim() ?? "";
  const version = rawVersion ? (rawVersion.toLowerCase().startsWith("v") ? rawVersion : `v${rawVersion}`) : "";

  return (
    <footer className="bottombar">
      <span>{t("bottom.author")}</span>
      {status ? <span className="bottombar__status">{status}</span> : null}
      <span className="bottombar__version">{version}</span>
    </footer>
  );
}
