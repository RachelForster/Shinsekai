import { useEffect, useRef, useState } from "react";

import type { AvatarFormat } from "../../modules/character-visual";
import { useI18n } from "../../shared/i18n";
import { getPlatform } from "../../shared/platform/platform";
import { AsyncButton, Button, Dialog, FilePicker, Switch } from "../../shared/ui";

/** Generic setup UI; archive interpretation/compilation is a format capability. */
export function AvatarRuntimeDialog({
  format,
  onClose,
  onInstalled,
  onReload = () => window.location.reload(),
}: {
  format: AvatarFormat<unknown, unknown>;
  onClose(): void;
  onInstalled(): void;
  /** Host navigation, separate from format-local compilation/rendering. */
  onReload?(): void;
}) {
  const { t } = useI18n();
  const runtime = format.runtime!;
  const [source, setSource] = useState("");
  const [accepted, setAccepted] = useState(false);
  const [installed, setInstalled] = useState(false);
  const [checking, setChecking] = useState(true);
  const [pending, setPending] = useState(false);
  const [progress, setProgress] = useState("");
  const [error, setError] = useState("");
  const lifetime = useRef<AbortController | null>(null);
  useEffect(() => {
    const abort = new AbortController();
    lifetime.current = abort;
    void getPlatform()
      .avatarRuntimes.status(format.id)
      .then((status) => {
        if (!abort.signal.aborted) setInstalled(status.installed);
      })
      .catch((failure) => {
        if (!abort.signal.aborted) setError(String(failure));
      })
      .finally(() => {
        if (!abort.signal.aborted) setChecking(false);
      });
    return () => abort.abort();
  }, [format.id]);
  const install = async () => {
    const signal = lifetime.current!.signal;
    setPending(true);
    setError("");
    try {
      const input = { source_path: source, accepted_license: accepted };
      setProgress(t("character.sdk.validating"));
      const prepared = await getPlatform().avatarRuntimes.prepare(format.id, input);
      signal.throwIfAborted();
      setProgress(t("character.sdk.compiling"));
      const compiled = await runtime.compile(prepared, signal);
      signal.throwIfAborted();
      setProgress(t("character.sdk.installing"));
      const result = await getPlatform().avatarRuntimes.install(format.id, { ...input, compiled });
      signal.throwIfAborted();
      if (!result.installed) throw new Error(t("character.sdk.failed"));
      setInstalled(true);
      if (runtime.reloadAfterInstall) onReload();
      else onInstalled();
    } catch (failure) {
      if (!signal.aborted) setError(String(failure));
    } finally {
      if (!signal.aborted) {
        setPending(false);
        setProgress("");
      }
    }
  };
  const open = async (url: string) => {
    try {
      await getPlatform().files.openExternal(url);
    } catch (failure) {
      setError(String(failure));
    }
  };
  return (
    <Dialog
      open
      title={t("character.sdk.title", { format: format.label })}
      onClose={onClose}
      dismissible={!pending}
      footer={
        <>
          <Button disabled={pending} onClick={onClose}>
            {t("common.close")}
          </Button>
          {!installed && (
            <AsyncButton disabled={checking || !source || !accepted} loading={pending} onClick={install}>
              {t(runtime.reloadAfterInstall ? "character.sdk.importReload" : "character.sdk.import")}
            </AsyncButton>
          )}
        </>
      }
    >
      <p>{t("character.sdk.hint", { name: runtime.name, version: runtime.version })}</p>
      <Button onClick={() => void open(runtime.downloadUrl)}>{t("character.sdk.download")}</Button>
      <p className="field-row__hint">{t("character.sdk.localOnly")}</p>
      {!installed && runtime.reloadAfterInstall && <p>{t("character.sdk.reloadHint")}</p>}
      {runtime.licenseUrls.map((url, index) => (
        <Button key={url} variant="ghost" onClick={() => void open(url)}>
          {t("character.sdk.license", { index: index + 1 })}
        </Button>
      ))}
      <p role="status">
        {progress ||
          (checking
            ? t("character.sdk.checking")
            : installed
              ? t("character.sdk.installed")
              : t("character.sdk.missing"))}
      </p>
      {!installed && (
        <>
          <label className="field-row field-row--stack">
            <span className="field-row__label">{t("character.sdk.zip")}</span>
            <FilePicker
              value={source}
              acceptedExtensions={[".zip"]}
              disabled={pending || checking}
              pickLabel={t("character.sdk.zip")}
              onPathChange={setSource}
            />
          </label>
          <Switch
            checked={accepted}
            disabled={pending || checking}
            onChange={(event) => setAccepted(event.target.checked)}
          >
            {t("character.sdk.accept")}
          </Switch>
        </>
      )}
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
    </Dialog>
  );
}
