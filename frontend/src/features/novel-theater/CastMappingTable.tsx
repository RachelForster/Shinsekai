import { Plus, Trash2 } from "lucide-react";
import { useI18n } from "../../shared/i18n";
import type { Character, NovelCastBindingInput, NovelCastCandidate, NovelCastRole } from "../../shared/platform/types";
import { Button, IconButton, Select, TextInput } from "../../shared/ui";
import "./CastMappingTable.css";

export interface CastMappingRow {
  sourceName: string;
  aliasesText: string;
  targetCharacter: string;
  role: NovelCastRole;
  description?: string;
}

const ALIAS_SPLIT_RE = /[,\uff0c\u3001]+/;

export function parseAliasesText(raw: string): string[] {
  return [
    ...new Set(
      raw
        .split(ALIAS_SPLIT_RE)
        .map((part) => part.trim())
        .filter(Boolean),
    ),
  ];
}

export function rowsToCastBindings(rows: CastMappingRow[]): NovelCastBindingInput[] {
  return rows.flatMap((row) => {
    const sourceName = row.sourceName.trim();
    if (!sourceName) return [];
    return [
      {
        sourceName,
        aliases: parseAliasesText(row.aliasesText),
        targetCharacter: row.targetCharacter.trim(),
        role: row.role,
        silhouetteUntilRevealed: false,
      },
    ];
  });
}

export function bindingsToCastRows(bindings: readonly NovelCastBindingInput[] | undefined): CastMappingRow[] {
  if (!bindings?.length) return [];
  return bindings.map((item) => ({
    sourceName: item.sourceName || "",
    aliasesText: (item.aliases ?? []).join(", "),
    targetCharacter: item.targetCharacter ?? "",
    role: item.role ?? "supporting",
  }));
}

export function candidatesToCastRows(candidates: readonly NovelCastCandidate[]): CastMappingRow[] {
  return candidates.map((item) => ({
    sourceName: item.name,
    aliasesText: item.aliases.join(", "),
    targetCharacter: item.suggestedCharacter || "",
    role: item.role || "supporting",
    description: item.description,
  }));
}

export function CastMappingTable({
  rows,
  characters,
  disabled = false,
  onChange,
}: {
  rows: CastMappingRow[];
  characters: Pick<Character, "name">[];
  disabled?: boolean;
  onChange: (next: CastMappingRow[]) => void;
}) {
  const { t } = useI18n();

  const updateRow = (index: number, patch: Partial<CastMappingRow>) => {
    onChange(rows.map((row, idx) => (idx === index ? { ...row, ...patch } : row)));
  };

  const addRow = () => {
    onChange([
      ...rows,
      {
        sourceName: "",
        aliasesText: "",
        targetCharacter: "",
        role: "supporting",
      },
    ]);
  };

  const removeRow = (index: number) => {
    onChange(rows.filter((_, idx) => idx !== index));
  };

  return (
    <div className="cast-mapping">
      {rows.length === 0 ? (
        <p className="cast-mapping__empty">{t("novel.cast.empty")}</p>
      ) : (
        <div className="cast-mapping__list">
          {rows.map((row, index) => (
            <div className="cast-mapping__row" key={`cast-row-${index}`}>
              <label className="cast-mapping__field">
                <span>{t("novel.cast.sourceName")}</span>
                <TextInput
                  aria-label={`${t("novel.cast.sourceName")} ${index + 1}`}
                  disabled={disabled}
                  maxLength={80}
                  onChange={(event) => updateRow(index, { sourceName: event.target.value })}
                  value={row.sourceName}
                />
              </label>
              <label className="cast-mapping__field">
                <span>{t("novel.cast.aliases")}</span>
                <TextInput
                  aria-label={`${t("novel.cast.aliases")} ${index + 1}`}
                  disabled={disabled}
                  onChange={(event) => updateRow(index, { aliasesText: event.target.value })}
                  value={row.aliasesText}
                />
              </label>
              <label className="cast-mapping__field">
                <span>{t("novel.cast.role")}</span>
                <Select
                  aria-label={`${t("novel.cast.role")} ${index + 1}`}
                  disabled={disabled}
                  onChange={(event) => updateRow(index, { role: event.target.value as NovelCastRole })}
                  value={row.role}
                >
                  <option value="protagonist">{t("novel.cast.role.protagonist")}</option>
                  <option value="supporting">{t("novel.cast.role.supporting")}</option>
                  <option value="antagonist">{t("novel.cast.role.antagonist")}</option>
                </Select>
              </label>
              <label className="cast-mapping__field">
                <span>{t("novel.cast.target")}</span>
                <Select
                  aria-label={`${t("novel.cast.target")} ${index + 1}`}
                  disabled={disabled}
                  onChange={(event) => updateRow(index, { targetCharacter: event.target.value })}
                  value={row.targetCharacter}
                >
                  <option value="">{t("novel.cast.unbound")}</option>
                  {characters.map((char) => (
                    <option key={char.name} value={char.name}>
                      {char.name}
                    </option>
                  ))}
                </Select>
              </label>
              <IconButton disabled={disabled} label={t("novel.cast.removeRow")} onClick={() => removeRow(index)}>
                <Trash2 aria-hidden className="icon-button__icon" />
              </IconButton>
              {row.description ? (
                <p className="cast-mapping__desc">
                  {t("novel.cast.description")}: {row.description}
                </p>
              ) : null}
            </div>
          ))}
        </div>
      )}
      <div className="cast-mapping__actions">
        <Button disabled={disabled} icon={<Plus aria-hidden className="button__icon" />} onClick={addRow} type="button">
          {t("novel.cast.addRow")}
        </Button>
      </div>
    </div>
  );
}
