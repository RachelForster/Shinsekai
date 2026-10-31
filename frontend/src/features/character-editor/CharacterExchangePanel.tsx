import { useState } from "react";
import type { Character } from "../../entities/config/types";
import { Download, Upload } from "lucide-react";
import { getPlatform } from "../../shared/platform/platform";
import { useI18n } from "../../shared/i18n";
import { AsyncButton, Button, EmptyState, PathPickerDialog, Select } from "../../shared/ui";
import "./CharacterExchangePanel.css";

interface Props {
  compact?: boolean;
  characters: Character[];
  selectedName: string;
  onPrepared: (character: Character, originalName: string) => void;
}

export function CharacterExchangePanel({ characters, selectedName, onPrepared, compact = false }: Props) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [picker, setPicker] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [rows, setRows] = useState<Array<{ id?: string; index?: number; name: string; persona: string }>>([]);
  const [path, setPath] = useState("");
  const [index, setIndex] = useState(0);
  const [target, setTarget] = useState("");
  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await work();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.importFailed"));
    } finally {
      setBusy(false);
    }
  };
  const loadDoki = () =>
    run(async () => {
      const operation = getPlatform().characters.listDoki;
      if (!operation) throw new Error(t("character.exchange.unavailable"));
      const result = await operation();
      setRows(result.characters);
      setPath("");
      setIndex(0);
      setOpen(true);
    });
  const previewFile = (value: string) =>
    run(async () => {
      const operation = getPlatform().characters.prepareExchange;
      if (!operation) throw new Error(t("character.exchange.unavailable"));
      const result = await operation({ path: value, previewOnly: true });
      setRows(result.characters || []);
      setPath(value);
      setIndex(0);
      setOpen(true);
      setPicker(false);
    });
  const prepare = () =>
    run(async () => {
      const operation = getPlatform().characters.prepareExchange;
      if (!operation || !rows[index]) throw new Error(t("character.exchange.choose"));
      const result = await operation({
        ...(path ? { path, index: rows[index].index } : { dokiId: rows[index].id }),
        targetName: target,
      });
      if (!result.character) throw new Error(t("character.exchange.invalid"));
      onPrepared(result.character, result.originalName || "");
      setOpen(false);
    });
  return (
    <section className={`section character-exchange${compact ? " character-exchange--compact" : ""}`} aria-busy={busy}>
      <div className="section__header">
        <h2 className="section__title">{t("character.exchange.title")}</h2>
        <div className="page__actions">
          <AsyncButton
            loading={busy && !open}
            disabled={busy}
            icon={<Download aria-hidden className="button__icon" />}
            onClick={loadDoki}
          >
            {t("character.exchange.fromDoki")}
          </AsyncButton>
          {!compact && (
            <Button
              disabled={busy}
              icon={<Upload aria-hidden className="button__icon" />}
              onClick={() => setPicker(true)}
            >
              {t("character.exchange.package")}
            </Button>
          )}
        </div>
      </div>
      <p className="field-row__hint">{t("character.exchange.hint")}</p>
      {error ? (
        <div role="alert" className="inline-status character-exchange__error">
          <span>
            {error}
            {!path ? ` ${t("character.exchange.serviceHint")}` : ""}
          </span>
        </div>
      ) : null}
      {open ? (
        <div className="character-exchange__content">
          {rows.length ? (
            <>
              <div className="form-grid form-grid--one">
                <label className="field-row field-row--stack">
                  <span className="field-row__label">{t("character.exchange.source")}</span>
                  <span className="field-row__control">
                    <Select
                      aria-label={t("character.exchange.source")}
                      disabled={busy}
                      value={index}
                      onChange={(e) => setIndex(Number(e.target.value))}
                    >
                      {rows.map((r, i) => (
                        <option key={r.id || i} value={i}>
                          {r.name}
                        </option>
                      ))}
                    </Select>
                  </span>
                </label>
                <label className="field-row field-row--stack">
                  <span className="field-row__label">{t("character.exchange.target")}</span>
                  <span className="field-row__control">
                    <Select
                      aria-label={t("character.exchange.target")}
                      disabled={busy}
                      value={target}
                      onChange={(e) => setTarget(e.target.value)}
                    >
                      <option value="">{t("common.new")}</option>
                      {characters.map((c) => (
                        <option key={c.name} value={c.name}>
                          {t("character.exchange.update", { name: c.name })}
                          {c.name === selectedName ? ` · ${t("character.row.current")}` : ""}
                        </option>
                      ))}
                    </Select>
                  </span>
                </label>
              </div>
              <div className="field-row field-row--stack">
                <span className="field-row__label">{t("character.exchange.preview")}</span>
                <p className="character-exchange__preview">
                  {rows[index]?.persona || t("character.exchange.noPersona")}
                </p>
              </div>
            </>
          ) : (
            <EmptyState title={t("character.exchange.empty")} />
          )}
          <div className="page__actions character-exchange__footer">
            <Button disabled={busy} onClick={() => setOpen(false)}>
              {t("common.cancel")}
            </Button>
            <AsyncButton variant="primary" loading={busy} disabled={busy || !rows.length} onClick={prepare}>
              {t("character.exchange.confirm")}
            </AsyncButton>
          </div>
        </div>
      ) : null}
      <PathPickerDialog
        acceptedExtensions={[".char", ".cha"]}
        onClose={() => setPicker(false)}
        onSelect={previewFile}
        open={picker}
        title={t("character.exchange.package")}
      />
    </section>
  );
}
