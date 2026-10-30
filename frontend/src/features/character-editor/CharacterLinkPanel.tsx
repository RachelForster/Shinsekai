import { useEffect, useState } from "react";
import type { Character } from "../../entities/config/types";
import { useI18n } from "../../shared/i18n";
import { getPlatform } from "../../shared/platform/platform";
import type { ShinsekaiPlatform } from "../../shared/platform/types";
import { AsyncButton, Button, Select } from "../../shared/ui";
import "./CharacterExchangePanel.css";

type LinkResponse = Awaited<ReturnType<NonNullable<ShinsekaiPlatform["characters"]["linkDoki"]>>>;
const nameKey = (name: string) => name.normalize("NFKC").trim().toLocaleLowerCase();

export function CharacterLinkPanel({ character }: { character?: Character }) {
  const { t } = useI18n();
  const [link, setLink] = useState<LinkResponse["link"]>(null);
  const [rows, setRows] = useState<NonNullable<LinkResponse["characters"]>>([]);
  const [selected, setSelected] = useState("");
  const [open, setOpen] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const request = (action: "state" | "doki-list" | "bind" | "unlink", dokiId?: string, role?: string) => {
    const operation = getPlatform().characters.linkDoki;
    if (!operation || !character?.id) return Promise.reject(new Error(t("character.link.saveFirst")));
    return operation({ action, characterId: character.id, dokiId, role });
  };
  useEffect(() => {
    let current = true;
    setLink(null);
    setOpen(false);
    setRows([]);
    if (character?.id)
      request("state")
        .then((result) => {
          if (current) setLink(result.link);
        })
        .catch(() => {});
    return () => {
      current = false;
    };
  }, [character?.id]);
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
  const load = () =>
    run(async () => {
      const result = await request("doki-list");
      const sorted = [...(result.characters || [])].sort(
        (a, b) =>
          Number(nameKey(b.name) === nameKey(character?.name || "")) -
            Number(nameKey(a.name) === nameKey(character?.name || "")) || a.name.localeCompare(b.name),
      );
      setRows(sorted);
      const first = sorted.find((r) => !r.linked);
      setSelected(first ? `${first.role}:${first.id}` : "");
      setOpen(true);
    });
  const bind = () =>
    run(async () => {
      const target = rows.find((r) => `${r.role}:${r.id}` === selected);
      if (!target) return;
      const result = await request("bind", target.id, target.role);
      setLink(result.link);
      setOpen(false);
    });
  return (
    <section className="section character-exchange" aria-busy={busy}>
      <div className="section__header">
        <h2 className="section__title">{t("character.link.title")}</h2>
        <div className="page__actions">
          {link ? (
            <Button
              disabled={busy}
              onClick={() =>
                run(async () => {
                  await request("unlink");
                  setLink(null);
                  setRows([]);
                })
              }
            >
              {t("character.link.unlink")}
            </Button>
          ) : (
            <AsyncButton loading={busy} disabled={busy || !character?.id} onClick={load}>
              {t("character.link.fromDoki")}
            </AsyncButton>
          )}
        </div>
      </div>
      <p className="field-row__hint">{t("character.link.hint")}</p>
      {!character?.id && <p className="inline-status">{t("character.link.saveFirst")}</p>}
      {link && (
        <p className="inline-status">
          {t("character.link.linked", { name: link.doki_name })}
          {link.role === "player" ? ` · ${t("character.link.player")}` : ""}
        </p>
      )}
      {error && (
        <p className="inline-status character-exchange__error" role="alert">
          {error} {t("character.exchange.serviceHint")}
        </p>
      )}
      {open && !link && (
        <div className="character-exchange__content">
          <label className="field-row">
            <span className="field-row__label">{t("character.link.select")}</span>
            <span className="field-row__control">
              <Select disabled={busy || !rows.length} value={selected} onChange={(e) => setSelected(e.target.value)}>
                <option value="">{t("character.link.select")}</option>
                {rows.map((r) => (
                  <option key={`${r.role}:${r.id}`} value={`${r.role}:${r.id}`} disabled={r.linked}>
                    {r.name}
                    {r.role === "player" ? ` · ${t("character.link.player")}` : ""}
                    {nameKey(r.name) === nameKey(character?.name || "") ? ` · ${t("character.link.sameName")}` : ""}
                    {r.linked ? ` · ${t("character.link.alreadyLinked")}` : ""}
                  </option>
                ))}
              </Select>
            </span>
          </label>
          {!rows.length && <p className="inline-status">{t("character.exchange.empty")}</p>}
          <div className="page__actions character-exchange__footer">
            <Button disabled={busy} onClick={() => setOpen(false)}>
              {t("common.cancel")}
            </Button>
            <AsyncButton variant="primary" loading={busy} disabled={busy || !selected} onClick={bind}>
              {t("character.link.confirm")}
            </AsyncButton>
          </div>
        </div>
      )}
    </section>
  );
}
