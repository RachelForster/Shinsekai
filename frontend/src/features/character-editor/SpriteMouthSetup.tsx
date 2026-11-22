import { useEffect, useState } from "react";

import { useI18n } from "../../shared/i18n";
import { AsyncButton, Button, FilePicker, Select, TextInput } from "../../shared/ui";
import type { SpriteMouthController } from "./useSpriteMouths";

export function SpriteMouthSetup({ controller }: { controller: SpriteMouthController }) {
  const { t } = useI18n();
  const { setup } = controller;
  const busy = controller.busy ?? (controller.externalBusy || controller.pendingPaths.length ? "generate" : null);
  const [python, setPython] = useState("");
  const [device, setDevice] = useState<"auto" | "cpu" | "cuda">("auto");
  useEffect(() => {
    if (setup) {
      setPython(setup.pythonPath);
      setDevice(setup.device);
    }
  }, [setup]);
  return (
    <details className="sprite-mouth-setup" open={!setup?.runtimeReady || !setup?.modelsReady}>
      <summary>{t(setup?.runtimeReady && setup.modelsReady ? "spriteMouth.setupReady" : "spriteMouth.setup")}</summary>
      <p className="sprite-generation__hint">{t("spriteMouth.modelsHint")}</p>
      <div className="sprite-mouth-setup__models">
        {setup?.models.map((model) => (
          <span key={model.id}>
            {model.id} · {(model.size / 1_000_000).toFixed(1)} MB ·{" "}
            {t(model.ready ? "spriteMouth.ready" : "spriteMouth.missing")}
          </span>
        ))}
      </div>
      <div className="sprite-mouth-actions">
        <AsyncButton
          disabled={Boolean(busy) || setup?.modelsReady}
          loading={busy === "setup"}
          onClick={() => void controller.download()}
        >
          {t("spriteMouth.download")}
        </AsyncButton>
        <FilePicker
          multiple
          acceptedExtensions={["safetensors"]}
          disabled={Boolean(busy)}
          value=""
          pickLabel={t("spriteMouth.importModels")}
          onPathsChange={(paths) => void controller.importModels(paths)}
        />
      </div>
      <p className="sprite-generation__hint">{t("spriteMouth.runtimeHint")}</p>
      <label>
        {t("spriteMouth.python")}
        <TextInput value={python} disabled={Boolean(busy)} onChange={(event) => setPython(event.target.value)} />
      </label>
      <label>
        {t("spriteMouth.device")}
        <Select
          value={device}
          disabled={Boolean(busy)}
          onChange={(event) => setDevice(event.target.value as typeof device)}
        >
          <option value="auto">{t("spriteMouth.automatic")}</option>
          <option value="cpu">{t("spriteMouth.cpu")}</option>
          <option value="cuda">{t("spriteMouth.cuda")}</option>
        </Select>
      </label>
      {setup?.missing.length ? <p className="sprite-generation__hint">{setup.missing.join(", ")}</p> : null}
      <div className="sprite-mouth-actions">
        <Button disabled={Boolean(busy)} onClick={() => void controller.configure({ pythonPath: python, device })}>
          {t("spriteMouth.configure")}
        </Button>
        <AsyncButton
          disabled={Boolean(busy) || !setup?.compatible || setup.runtimeReady}
          onClick={() => void controller.install()}
        >
          {t("spriteMouth.install")}
        </AsyncButton>
        <Button disabled={Boolean(busy)} onClick={() => void controller.refresh()}>
          {t("spriteMouth.refresh")}
        </Button>
      </div>
    </details>
  );
}
