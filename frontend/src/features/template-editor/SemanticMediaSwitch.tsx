import { useEffect, useRef, useState } from "react";

import { installMissingRuntimeDependency } from "../../entities/chat/repository";
import { getMemoryStatus } from "../../entities/config/repository";
import { useI18n } from "../../shared/i18n";
import type { Mem0Status } from "../../shared/platform/types";
import { Switch, useToast } from "../../shared/ui";

interface SemanticMediaSwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  verifyOnMount?: boolean;
}

const POLL_INTERVAL_MS = 1_000;
const MAX_POLL_ATTEMPTS = 300;

function waitForNextPoll() {
  return new Promise<void>((resolve) => window.setTimeout(resolve, POLL_INTERVAL_MS));
}

export function useSemanticMediaController({ checked, onChange, verifyOnMount = true }: SemanticMediaSwitchProps) {
  const { t } = useI18n();
  const { showToast } = useToast();
  const [pending, setPending] = useState(false);
  const mountedRef = useRef(true);
  const ensuredCheckedRef = useRef(verifyOnMount ? false : checked);
  const checkedRef = useRef(checked);
  checkedRef.current = checked;
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const waitUntilReady = async (initial: Mem0Status) => {
    let status = initial;
    for (let attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt += 1) {
      if (!mountedRef.current) {
        return status;
      }
      if (status.status === "ready") {
        return status;
      }
      if (status.status === "error" || status.status === "missing_dependency") {
        return status;
      }
      await waitForNextPoll();
      status = await getMemoryStatus({ startLoading: true });
    }
    return status;
  };

  const enableSemanticMedia = async () => {
    setPending(true);
    try {
      let status = await getMemoryStatus({ startLoading: true });
      if (status.status === "missing_dependency") {
        const shouldInstall = window.confirm(
          t("runtimeDeps.installConfirm", {
            module: status.moduleName || "mem0",
            package: status.packageName || "mem0ai",
          }),
        );
        if (!shouldInstall) {
          if (mountedRef.current) {
            onChangeRef.current(false);
          }
          return;
        }
        await installMissingRuntimeDependency({ moduleName: status.moduleName || "mem0" });
        status = await getMemoryStatus({ startLoading: true });
      }
      status = await waitUntilReady(status);
      if (status.status !== "ready") {
        throw new Error(status.message || t("template.semanticMedia.error"));
      }
      if (mountedRef.current) {
        onChangeRef.current(true);
      }
    } catch (error) {
      if (mountedRef.current) {
        if (checkedRef.current) {
          onChangeRef.current(false);
        }
        showToast({
          kind: "error",
          message: error instanceof Error ? error.message : t("template.semanticMedia.error"),
          title: t("template.semanticMedia.label"),
        });
      }
    } finally {
      if (mountedRef.current) {
        setPending(false);
      }
    }
  };

  useEffect(() => {
    if (!checked) {
      ensuredCheckedRef.current = false;
      return;
    }
    if (ensuredCheckedRef.current) {
      return;
    }
    ensuredCheckedRef.current = true;
    void enableSemanticMedia();
  }, [checked]);

  const toggle = (nextChecked: boolean) => {
    if (!nextChecked) {
      ensuredCheckedRef.current = false;
      onChangeRef.current(false);
      return;
    }
    ensuredCheckedRef.current = true;
    void enableSemanticMedia();
  };

  return { pending, toggle };
}

export function SemanticMediaSwitch({ checked, onChange, verifyOnMount = true }: SemanticMediaSwitchProps) {
  const { t } = useI18n();
  const { pending, toggle } = useSemanticMediaController({ checked, onChange, verifyOnMount });

  return (
    <label className="template-toggle-row" data-standalone-gpu="true" title={t("template.semanticMedia.hint")}>
      <span>{pending ? t("template.semanticMedia.preparing") : t("template.semanticMedia.label")}</span>
      <Switch
        aria-busy={pending}
        checked={checked || pending}
        disabled={pending}
        onChange={(event) => toggle(event.target.checked)}
      />
    </label>
  );
}
