import { useI18n } from "../../../shared/i18n";
import type { MemoryMode } from "../../../shared/platform/types";
import { FilePicker, Select, Switch, TextInput, type PageSectionProps } from "../../../shared/ui";
import { characterOutfitGroups, type TemplateEditorContext } from "../templateContext";

export function TemplateRuntimeSection({ ctx }: PageSectionProps<TemplateEditorContext>) {
  const { t } = useI18n();

  return (
    <div className="template-runtime-fields">
      <label className="template-side-field" data-standalone-gpu="true">
        <span className="template-side-field__label">{t("chat.memoryMode.label")}</span>
        <Select
          aria-label={t("chat.memoryMode.label")}
          onChange={(event) => ctx.setMemoryMode(event.target.value as MemoryMode)}
          value={ctx.memoryMode}
        >
          <option value="isolated">{t("chat.memoryMode.isolated")}</option>
          <option value="shared">{t("chat.memoryMode.shared")}</option>
          <option value="inherit_readonly">{t("chat.memoryMode.inheritReadonly")}</option>
        </Select>
        <span className="template-options-panel__hint">
          {t(
            ctx.memoryMode === "shared"
              ? "chat.memoryMode.sharedHint"
              : ctx.memoryMode === "inherit_readonly"
                ? "chat.memoryMode.inheritReadonlyHint"
                : "chat.memoryMode.isolatedHint",
          )}
        </span>
      </label>
      <div className="template-side-field">
        <div className="template-sprite-heading">
          <label className="template-side-field__label" htmlFor="template-auto-outfit-switch">
            {t("launch.autoOutfitSwitch")}
          </label>
          <Switch
            aria-label={t("launch.autoOutfitSwitch")}
            checked={ctx.autoOutfitSwitch}
            id="template-auto-outfit-switch"
            onChange={(event) => ctx.setAutoOutfitSwitch(event.currentTarget.checked)}
          />
        </div>
      </div>
      {ctx.selectedCharacterRecords
        .map((character) => ({ character, groups: characterOutfitGroups(character) }))
        .filter(({ groups }) => groups.length > 1)
        .map(({ character, groups }) => (
          <label className="template-side-field" key={character.name}>
            <span className="template-side-field__label">
              {t("launch.initialOutfits")} · {character.name}
            </span>
            <Select
              aria-label={`${t("launch.initialOutfits")} · ${character.name}`}
              onChange={(event) =>
                ctx.setInitialOutfits((current) => {
                  const next = { ...current };
                  if (event.target.value) {
                    next[character.name] = event.target.value;
                  } else {
                    delete next[character.name];
                  }
                  return next;
                })
              }
              value={ctx.initialOutfits[character.name] ?? ""}
            >
              <option value="">{t("launch.initialOutfitDefault")}</option>
              {groups.map((group) => (
                <option key={group} value={group}>
                  {group}
                </option>
              ))}
            </Select>
          </label>
        ))}
      <div className="template-side-field">
        <div className="template-sprite-heading">
          <label className="template-side-field__label" htmlFor="template-initial-sprite">
            {t("template.field.initSprite")}
          </label>
          <Switch
            aria-label={t("template.field.showInitialSprite")}
            checked={ctx.showInitialSprite}
            onChange={(event) => ctx.setShowInitialSprite(event.target.checked)}
            title={t("template.field.showInitialSprite")}
          />
        </div>
        <FilePicker
          acceptedExtensions={[".gif", ".jpeg", ".jpg", ".png", ".webp"]}
          disabled={!ctx.showInitialSprite}
          id="template-initial-sprite"
          onChange={(event) => ctx.setInitSpritePath(event.target.value)}
          onPathChange={ctx.setInitSpritePath}
          pickLabel={t("common.chooseFile")}
          pickerTitle={t("template.field.initSprite")}
          readOnly={false}
          value={ctx.initSpritePath}
        />
      </div>
      {!ctx.createOnly && !ctx.conversationId && (
        <label className="template-side-field">
          <span className="template-side-field__label">{t("template.field.historyFile")}</span>
          <TextInput onChange={(event) => ctx.setHistoryPath(event.target.value)} value={ctx.historyPath} />
        </label>
      )}
    </div>
  );
}
