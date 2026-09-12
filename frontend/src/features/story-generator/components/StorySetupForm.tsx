import { useI18n } from "../../../shared/i18n";
import { CharacterPicker } from "../../template-editor/CharacterPicker";
import { Button, Select, TextArea } from "../../../shared/ui";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { backgroundsQueryKey, listBackgrounds } from "../../../entities/background/repository";
import { charactersQueryKey, ensureCharacterBriefs, listCharacters } from "../../../entities/character/repository";
import type { Character, CharacterPromptMode, StoryGenerationInput } from "../../../shared/platform/types";
import { TRANSPARENT_BACKGROUND_NAME } from "../../../shared/constants";
import { PrimaryCharacterDialog } from "../../template-editor/PrimaryCharacterDialog";
import { CharacterRoleStatus } from "../../template-editor/CharacterRoleStatus";
import { updateCharacterRoles } from "../../template-editor/characterRoles";

export function StorySetupForm({
  pending,
  onStart,
}: {
  pending: boolean;
  onStart: (input: StoryGenerationInput) => void;
}) {
  const { t } = useI18n();
  const client = useQueryClient();
  const [selected, setSelected] = useState<string[]>([]);
  const [primary, setPrimary] = useState<string[]>([]);
  const [mode, setMode] = useState<CharacterPromptMode | undefined>("full");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [background, setBackground] = useState(TRANSPARENT_BACKGROUND_NAME);
  const [synopsis, setSynopsis] = useState("");
  const characters = useQuery({ queryKey: charactersQueryKey, queryFn: listCharacters });
  const backgrounds = useQuery({ queryKey: backgroundsQueryKey, queryFn: listBackgrounds });
  const selectedCharacters = useMemo(
    () => selected.flatMap((name) => characters.data?.find((item) => item.name === name) ?? []),
    [characters.data, selected],
  );
  const briefs = useMutation({
    mutationFn: async (names: string[]) => {
      const result = await ensureCharacterBriefs(selected.filter((name) => !names.includes(name)));
      const updated = new Map(result.characters.map((character) => [character.name, character]));
      client.setQueryData<Character[]>(charactersQueryKey, (current = []) =>
        current.map((character) => updated.get(character.name) ?? character),
      );
      setPrimary(names);
      setMode(names.length === selected.length ? "full" : "compact");
      setDialogOpen(false);
    },
  });
  const busy = pending || briefs.isPending;
  const updateSelected = (next: string[]) => {
    const roles = updateCharacterRoles(selected, next, primary, mode);
    setSelected(next);
    setMode(roles.mode);
    setPrimary(roles.primary);
  };
  const useAll = () => {
    setPrimary(selected);
    setMode("full");
    setDialogOpen(false);
  };
  return (
    <section className="section" aria-labelledby="story-setup-title">
      <h2 className="section__title" id="story-setup-title">
        {t("story.setup.title")}
      </h2>
      {characters.isPending && <p role="status">{t("story.setup.loadingCharacters")}</p>}
      {characters.isSuccess && !characters.data.length && (
        <p className="section__description">{t("story.setup.noCharacters")}</p>
      )}
      <CharacterPicker
        characters={characters.data ?? []}
        selected={selected}
        onChange={updateSelected}
        disabled={busy}
      />
      <CharacterRoleStatus
        disabled={busy}
        mode={mode}
        onConfigure={() => {
          briefs.reset();
          setDialogOpen(true);
        }}
        onUseAll={useAll}
        selectedCount={selected.length}
        primaryCount={mode === "full" ? selected.length : primary.length}
      />
      <label className="story-setup-field">
        {t("story.setup.background")}
        <Select
          aria-label={t("story.setup.background")}
          value={background}
          disabled={busy || !backgrounds.isSuccess}
          onChange={(event) => setBackground(event.target.value)}
        >
          <option value={TRANSPARENT_BACKGROUND_NAME}>{t("template.transparentBackground")}</option>
          {backgrounds.data
            ?.filter((item) => item.name !== TRANSPARENT_BACKGROUND_NAME)
            .map((item) => (
              <option key={item.name} value={item.name}>
                {item.name}
              </option>
            ))}
        </Select>
      </label>
      <label className="story-setup-field">
        {t("story.setup.synopsisOptional")}
        <TextArea
          aria-label={t("story.setup.synopsis")}
          disabled={busy}
          maxLength={20000}
          rows={5}
          value={synopsis}
          onChange={(event) => setSynopsis(event.target.value)}
          placeholder={t("story.setup.synopsisPlaceholder")}
        />
      </label>
      {[characters, backgrounds].map(
        (query, index) =>
          query.isError && (
            <p key={index} className="story-generator-error" role="alert">
              {query.error.message}
              <Button onClick={() => void query.refetch()}>{t("common.retry")}</Button>
            </p>
          ),
      )}
      <div className="story-generator-actions">
        <Button
          variant="primary"
          disabled={busy || !selected.length || !characters.isSuccess || !backgrounds.isSuccess}
          onClick={() => {
            if (!mode) {
              setDialogOpen(true);
              return;
            }
            onStart({
              synopsis: synopsis.trim(),
              options: {
                targetLength: "short",
                controlMode: "prompt",
                characters: selected,
                backgroundName: background,
                characterPromptMode: mode,
                primaryCharacters: mode === "full" ? selected : primary,
              },
            });
          }}
        >
          {pending ? t("story.setup.generating") : t("story.setup.start")}
        </Button>
        <small>{t("story.setup.savedHint")}</small>
      </div>
      <PrimaryCharacterDialog
        characters={selectedCharacters}
        initialPrimaryCharacters={primary}
        open={dialogOpen}
        error={briefs.error?.message}
        pending={briefs.isPending}
        onUseAll={useAll}
        onConfirm={(names) => briefs.mutate(names)}
      />
    </section>
  );
}
