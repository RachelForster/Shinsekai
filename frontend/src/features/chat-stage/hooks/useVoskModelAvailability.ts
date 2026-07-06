import { useEffect, useState } from "react";

import { getAppConfig } from "../../../entities/config/repository";
import { browseFiles } from "../../../entities/files/repository";
import type { FileBrowserSnapshot } from "../../../shared/platform/types";
import { VOSK_MODEL_PATH } from "../../api-settings/apiSettingsUtils";

function snapshotLooksLikeVoskModel(snapshot: FileBrowserSnapshot) {
  const names = new Set(snapshot.entries.map((entry) => entry.name.toLocaleLowerCase()));
  return names.has("am") && names.has("conf") && names.has("graph");
}

export function useVoskModelAvailability() {
  const [voskModelState, setVoskModelState] = useState({
    available: false,
    loading: true,
    path: VOSK_MODEL_PATH,
  });

  useEffect(() => {
    let cancelled = false;
    const probeVoskModel = async () => {
      let modelPath = VOSK_MODEL_PATH;
      try {
        const appConfig = await getAppConfig();
        const configuredPath = String(appConfig.api_config.asr_extra_configs?.vosk?.model_path ?? "").trim();
        modelPath = configuredPath || VOSK_MODEL_PATH;
        const snapshot = await browseFiles({ path: modelPath, showHidden: false });
        if (!cancelled) {
          setVoskModelState({ available: snapshotLooksLikeVoskModel(snapshot), loading: false, path: modelPath });
        }
      } catch {
        if (!cancelled) {
          setVoskModelState({ available: false, loading: false, path: modelPath });
        }
      }
    };
    void probeVoskModel();
    return () => {
      cancelled = true;
    };
  }, []);

  return voskModelState;
}
