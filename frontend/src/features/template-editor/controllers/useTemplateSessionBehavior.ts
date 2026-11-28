import { useCallback, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listPluginSessionBehaviors, pluginSessionBehaviorsQueryKey } from "../../../entities/plugin/repository";

export function useTemplateSessionBehavior() {
  const sessionBehaviorsQuery = useQuery({
    queryFn: listPluginSessionBehaviors,
    queryKey: pluginSessionBehaviorsQueryKey,
    retry: false,
  });
  const sessionBehaviors = sessionBehaviorsQuery.data ?? [];
  const [behaviorId, setBehaviorId] = useState("");
  const [behaviorConfig, setBehaviorConfig] = useState<Record<string, unknown>>({});

  const selectBehaviorId = useCallback(
    (nextId: string) => {
      const normalizedId = nextId.trim();
      setBehaviorId(normalizedId);
      if (!normalizedId) {
        setBehaviorConfig({});
        return;
      }
      const match = sessionBehaviors.find((item) => item.behaviorId === normalizedId);
      setBehaviorConfig(match ? { ...match.defaultConfig } : {});
    },
    [sessionBehaviors],
  );

  return {
    behaviorConfig,
    behaviorId,
    selectBehaviorId,
    sessionBehaviors,
    setBehaviorConfig,
    setBehaviorId,
  };
}
