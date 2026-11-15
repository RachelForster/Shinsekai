import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DialogStageControls } from "../../../features/chat-stage/components/DialogStageControls";
import { applyStageEvent } from "../../../features/chat-stage/state/events";
import { emptyChatState } from "../../../features/chat-stage/state/initialState";
import { hydrateFromSnapshot } from "../../../features/chat-stage/state/snapshot";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

vi.mock("../../../shared/plugin/PluginSlot", () => ({
  PluginSlot: () => null,
}));

describe("Chat stage outfit & memory mode state and controls", () => {
  it("folds memory.mode and outfit.state stage events and hydrates snapshot outfit state", () => {
    const hydrated = hydrateFromSnapshot(emptyChatState, {
      autoOutfitSwitch: true,
      dialogText: "Hello",
      eventSeq: 2,
      inputDraft: "",
      memoryMode: "isolated",
      options: [],
      outfitCatalog: {
        Nanami: {
          defaultGroup: "校服",
          fallbackToDefaultGroup: true,
          groups: ["校服", "私服"],
        },
      },
      outfits: {
        Nanami: { activeGroup: "校服", characterName: "Nanami", locked: false },
      },
      sprites: [],
      status: "idle",
    });

    expect(hydrated.memoryMode).toBe("isolated");
    expect(hydrated.outfits?.Nanami.activeGroup).toBe("校服");

    const afterMemory = applyStageEvent(hydrated, {
      memoryMode: "shared",
      seq: 3,
      ts: 100,
      type: "memory.mode",
      v: 1,
    });
    expect(afterMemory.memoryMode).toBe("shared");

    const afterOutfit = applyStageEvent(afterMemory, {
      autoOutfitSwitch: false,
      outfitCatalog: {
        Nanami: {
          defaultGroup: "校服",
          fallbackToDefaultGroup: true,
          groups: ["校服", "私服"],
        },
      },
      outfits: {
        Nanami: { activeGroup: "私服", characterName: "Nanami", locked: true },
      },
      seq: 4,
      ts: 200,
      type: "outfit.state",
      v: 1,
    });
    expect(afterOutfit.autoOutfitSwitch).toBe(false);
    expect(afterOutfit.outfits?.Nanami).toEqual({
      activeGroup: "私服",
      characterName: "Nanami",
      locked: true,
    });
  });

  it("renders ChatOutfitPopover and dispatches outfit switch, lock, and memory mode commands", () => {
    const onCommand = vi.fn();

    render(
      <I18nProvider language="en">
        <DialogStageControls
          asrEnabled={false}
          auto={false}
          autoOutfitSwitch
          bgmVolume={0.5}
          closeLabel="Close"
          configOpen={false}
          effectVolume={0.5}
          hidden={false}
          hideCloseButton={false}
          locked={false}
          longPressTalk={false}
          memoryMode="isolated"
          onAutoChange={vi.fn()}
          onBgmVolumeChange={vi.fn()}
          onCancelBatch={vi.fn()}
          onCloseSurface={vi.fn()}
          onCommand={onCommand}
          onConfigOpenChange={vi.fn()}
          onEffectVolumeChange={vi.fn()}
          onFlushBatch={vi.fn()}
          onLockedChange={vi.fn()}
          onLongPressTalkChange={vi.fn()}
          onOpenHistory={vi.fn()}
          onOpenPluginPage={vi.fn()}
          onTurnOptionsChange={vi.fn()}
          outfitCatalog={{
            Nanami: {
              defaultGroup: "校服",
              fallbackToDefaultGroup: true,
              groups: ["校服", "私服"],
            },
          }}
          outfits={{
            Nanami: { activeGroup: "校服", characterName: "Nanami", locked: false },
          }}
          showAsrControl={false}
          turnOptions={emptyChatState.turnOptions}
          turnState={emptyChatState.turnState}
        />
      </I18nProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Switch character outfits" }));
    expect(screen.getByRole("dialog", { name: "Character Outfits" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox", { name: /Auto-switch outfits with story/ }));
    expect(onCommand).toHaveBeenCalledWith({
      payload: { enabled: false },
      type: "set-auto-outfit-switch",
    });

    fireEvent.click(screen.getByRole("button", { name: "私服" }));
    expect(onCommand).toHaveBeenCalledWith({
      payload: { characterName: "Nanami", group: "私服" },
      type: "set-character-outfit",
    });

    fireEvent.click(screen.getByRole("button", { name: "Nanami · Lock current outfit" }));
    expect(onCommand).toHaveBeenCalledWith({
      payload: { characterName: "Nanami", locked: true },
      type: "set-character-outfit",
    });

    // Opening chat turn settings closes outfit popover and exposes live memory mode pills
    fireEvent.click(screen.getByRole("button", { name: "Chat settings" }));
    expect(screen.queryByRole("dialog", { name: "Character Outfits" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Shared across saves" }));
    expect(onCommand).toHaveBeenCalledWith({
      payload: { memoryMode: "shared" },
      type: "set-memory-mode",
    });
  });
});
