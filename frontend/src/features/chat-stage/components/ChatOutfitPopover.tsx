import { Lock, Unlock, X } from "lucide-react";

import { useI18n } from "../../../shared/i18n";
import type { CharacterOutfitCatalogEntry, CharacterOutfitState, ChatCommand } from "../../../shared/platform/types";
import { IconButton, Switch } from "../../../shared/ui";

export function ChatOutfitPopover({
  autoOutfitSwitch,
  onClose,
  onCommand,
  open,
  outfitCatalog,
  outfits,
}: {
  autoOutfitSwitch: boolean;
  onClose: () => void;
  onCommand: (command: ChatCommand) => void;
  open: boolean;
  outfitCatalog: Record<string, CharacterOutfitCatalogEntry>;
  outfits: Record<string, CharacterOutfitState>;
}) {
  const { t } = useI18n();

  if (!open) {
    return null;
  }

  const switchableEntries = Object.entries(outfitCatalog).filter(([, entry]) => entry.groups.length > 1);

  return (
    <section
      aria-label={t("chat.outfit.title")}
      className="dialog-stage-controls__chat-settings dialog-stage-controls__outfit-popover"
      id="chat-outfit-popover"
      role="dialog"
    >
      <header className="dialog-stage-controls__chat-settings-header">
        <strong>{t("chat.outfit.title")}</strong>
        <IconButton className="dialog-stage-controls__chat-settings-close" label={t("common.close")} onClick={onClose}>
          <X aria-hidden />
        </IconButton>
      </header>
      <div className="dialog-stage-controls__chat-settings-options">
        <Switch
          checked={autoOutfitSwitch}
          className="dialog-stage-controls__chat-setting"
          id="chat-outfit-auto-switch"
          onChange={(event) =>
            onCommand({
              type: "set-auto-outfit-switch",
              payload: { enabled: event.currentTarget.checked },
            })
          }
        >
          {t("chat.outfit.autoSwitch")}
        </Switch>
        <p className="dialog-stage-controls__popover-hint">{t("chat.outfit.autoSwitchHint")}</p>
      </div>
      {switchableEntries.length === 0 ? (
        <p className="dialog-stage-controls__popover-hint">{t("chat.outfit.empty")}</p>
      ) : (
        <div className="dialog-stage-controls__outfit-list">
          {switchableEntries.map(([characterName, catalog]) => {
            const current = outfits[characterName];
            const activeGroup = current?.activeGroup || catalog.defaultGroup || catalog.groups[0] || "";
            const locked = Boolean(current?.locked);
            const lockLabel = locked ? t("chat.outfit.unlock") : t("chat.outfit.lock");

            return (
              <div className="dialog-stage-controls__outfit-card" key={characterName}>
                <div className="dialog-stage-controls__outfit-card-header">
                  <span className="dialog-stage-controls__outfit-name">
                    {characterName}
                    {locked ? (
                      <span className="dialog-stage-controls__outfit-badge">{t("chat.outfit.lockedBadge")}</span>
                    ) : null}
                  </span>
                  <IconButton
                    aria-pressed={locked}
                    className="dialog-stage-controls__chat-settings-close"
                    label={`${characterName} · ${lockLabel}`}
                    onClick={() =>
                      onCommand({
                        type: "set-character-outfit",
                        payload: { characterName, locked: !locked },
                      })
                    }
                  >
                    {locked ? <Lock aria-hidden /> : <Unlock aria-hidden />}
                  </IconButton>
                </div>
                <div className="dialog-stage-controls__pill-row" role="group" aria-label={characterName}>
                  {catalog.groups.map((group) => {
                    const active = group === activeGroup;
                    return (
                      <button
                        aria-pressed={active}
                        className="dialog-stage-controls__pill"
                        data-active={active ? "true" : "false"}
                        key={group}
                        onClick={() =>
                          onCommand({
                            type: "set-character-outfit",
                            payload: { characterName, group },
                          })
                        }
                        type="button"
                      >
                        {group}
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
