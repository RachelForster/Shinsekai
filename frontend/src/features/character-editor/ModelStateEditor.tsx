import { useEffect, useRef, useState } from "react";
import type { Character } from "../../entities/config/types";
import { characterAvatarType, createEmptyCharacterAssets, getCharacterAssets } from "../../entities/character/assets";
import { importCharacterModel } from "../../entities/character/repository";
import { modelFileUrl } from "../../entities/files/repository";
import { registeredAvatarFormats, avatarFormat, CharacterVisual } from "../../modules/character-visual";
import { avatarStateUrl } from "../../entities/character/modelStateRepository";
import { tagContents } from "../../shared/assets/assetText";
import { useI18n } from "../../shared/i18n";
import { AsyncButton, Button, EmptyState, FilePicker, ImageAssetGallery, PathDisplay, Select } from "../../shared/ui";
import { ModelStateDialog } from "./ModelStateDialog";
import "./ModelStateEditor.css";

export function ModelStateEditor({
  character,
  onChange,
  onSaved,
}: {
  character: Character;
  onChange: (character: Character) => void;
  onSaved: (character: Character) => void;
}) {
  const { t } = useI18n();
  const kind = characterAvatarType(character);
  const bank = getCharacterAssets(character);
  const format = avatarFormat(kind);
  const [source, setSource] = useState("");
  const [index, setIndex] = useState(0);
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const request = useRef(0);
  const name = character.name;
  const modelPath = bank?.model_path ?? "";
  const sprite = bank?.sprites[index];
  const tags = tagContents(bank?.emotion_tags ?? "", bank?.sprites.length ?? 0);
  useEffect(() => {
    setIndex(0);
    setEditingIndex(null);
    setSource("");
    setError("");
    setPending(false);
    ++request.current;
    return () => {
      ++request.current;
    };
  }, [name, kind, modelPath]);
  const importModel = async () => {
    const sequence = ++request.current;
    setPending(true);
    setError("");
    try {
      const result = await importCharacterModel({ name, avatar_type: kind, source_path: source });
      if (request.current === sequence) onSaved(result);
    } catch (failure) {
      if (request.current === sequence) setError(String(failure));
    } finally {
      if (request.current === sequence) setPending(false);
    }
  };
  return (
    <section className="section page-section-anchor" id="character-model">
      <div className="section__header">
        <h2 className="section__title">{t("character.avatar.title")}</h2>
        {kind !== "static" && format && (
          <Button disabled={pending || !modelPath} onClick={() => setEditingIndex(-1)}>
            {t("character.avatar.newState")}
          </Button>
        )}
      </div>
      <div className="asset-editor">
        <label className="field-row field-row--stack">
          <span className="field-row__label">{t("character.avatar.format")}</span>
          <span className="field-row__control">
            <Select
              aria-label={t("character.avatar.format")}
              value={kind}
              disabled={pending}
              onChange={(event) => {
                const avatar_type = event.target.value;
                onChange({
                  ...character,
                  avatar_type,
                  avatars: {
                    ...character.avatars,
                    ...(avatar_type !== "static" && !character.avatars[avatar_type]
                      ? { [avatar_type]: createEmptyCharacterAssets() }
                      : {}),
                  },
                });
              }}
            >
              <option value="static">{t("character.avatar.static")}</option>
              {registeredAvatarFormats().map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
              {kind !== "static" && !format && (
                <option value={kind} disabled>
                  {t("character.avatar.unavailable", { format: kind })}
                </option>
              )}
            </Select>
          </span>
        </label>
        {kind !== "static" && format && (
          <>
            <p className="field-row__hint">{t("character.avatar.importHint")}</p>
            <label className="field-row field-row--stack">
              <span className="field-row__label">{t("character.avatar.modelEntry")}</span>
              <span className="field-row__control">
                <FilePicker
                  aria-label={t("character.avatar.modelEntry")}
                  value={source}
                  onChange={(event) => setSource(event.target.value)}
                  onPathChange={setSource}
                  acceptedExtensions={format.modelExtensions}
                  disabled={pending}
                  pickLabel={t("common.chooseFile")}
                  pickerTitle={t("character.avatar.modelEntry")}
                />
              </span>
            </label>
            <AsyncButton loading={pending} disabled={pending || !source || !name} onClick={() => void importModel()}>
              {t("character.avatar.importModel")}
            </AsyncButton>
            {modelPath && (
              <div className="asset-gallery-layout asset-gallery-layout--character">
                {bank?.sprites.length ? (
                  <ImageAssetGallery
                    selectedIndex={index}
                    onSelect={setIndex}
                    items={bank.sprites.map((item, i) => ({
                      id: item.path,
                      title: tags[i] || item.path.split(/[\\/]/).at(-1) || "",
                      meta: t("character.avatar.state"),
                      badge: format.label,
                    }))}
                  />
                ) : (
                  <EmptyState title={t("character.avatar.emptyStates")} />
                )}
                <aside className="asset-inspector">
                  {!pending && editingIndex === null && (
                    <CharacterVisual
                      className="model-state-editor__preview"
                      asset={{
                        id: modelPath,
                        label: t("character.avatar.preview"),
                        avatarType: kind,
                        modelUrl: modelFileUrl(modelPath),
                        url: sprite ? avatarStateUrl(modelPath, sprite.path) : "",
                      }}
                      mode="restore"
                      hitbox={false}
                      onImageError={() => {}}
                      onMouseDown={() => {}}
                    />
                  )}
                  <label className="field-row field-row--stack">
                    <span className="field-row__label">{t("character.sprite.tag")}</span>
                    <span className="field-row__control">{tags[index] || "—"}</span>
                  </label>
                  <label className="field-row field-row--stack">
                    <span className="field-row__label">{t("character.sprite.path")}</span>
                    <span className="field-row__control">
                      <PathDisplay className="path-display--input" path={sprite?.path || modelPath} />
                    </span>
                  </label>
                  <Button disabled={pending || !sprite} onClick={() => setEditingIndex(index)}>
                    {t("character.avatar.editState")}
                  </Button>
                </aside>
              </div>
            )}
          </>
        )}
        {error && (
          <p className="field-error" role="alert">
            {error}
          </p>
        )}
      </div>
      {editingIndex !== null && format && bank && (
        <ModelStateDialog
          key={`${name}:${kind}:${modelPath}`}
          character={character}
          index={editingIndex}
          onClose={() => setEditingIndex(null)}
          onSaved={(result) => {
            setIndex(editingIndex < 0 ? bank.sprites.length : editingIndex);
            setEditingIndex(null);
            onSaved(result);
          }}
        />
      )}
    </section>
  );
}
