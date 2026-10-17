import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { CharacterPicker } from "../../../features/template-editor/CharacterPicker";
import { I18nProvider } from "../../../shared/i18n";

it("allows removing an unavailable character even when the library is empty", () => {
  const onChange = vi.fn();
  render(
    <I18nProvider language="en">
      <CharacterPicker characters={[]} selected={["Alice"]} onChange={onChange} />
    </I18nProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Alice (unavailable; click to deselect)" }));
  expect(onChange).toHaveBeenCalledWith([]);
});

it("shows the current player beside the settings button and removes stale names", () => {
  const onConfigurePlayer = vi.fn();
  const picker = (playerCharacter: string, selected = ["Alice", "Bob"]) => (
    <I18nProvider language="en">
      <CharacterPicker
        characters={["Alice", "Bob"].map((name) => ({
          name,
          color: "#66ccff",
          sprite_prefix: "",
          sprites: [],
          avatar_type: "static",
          avatars: {},
          character_setting: "",
          sprite_scale: 1,
          emotion_tags: "",
          speech_speed: 1,
          speech_volume: 1,
          pronunciation_map: {},
        }))}
        selected={selected}
        onChange={vi.fn()}
        onConfigurePlayer={onConfigurePlayer}
        playerCharacter={playerCharacter}
      />
    </I18nProvider>
  );
  const { rerender } = render(picker("Alice"));
  const playerControls = screen.getByRole("button", { name: "Player character" }).parentElement!;
  expect(within(playerControls).getByText("Alice")).toHaveAttribute("title", "Alice");
  fireEvent.click(within(playerControls).getByRole("button", { name: "Player character" }));
  expect(onConfigurePlayer).toHaveBeenCalledOnce();

  rerender(picker("Bob"));
  expect(within(playerControls).getByText("Bob")).toBeInTheDocument();
  expect(within(playerControls).queryByText("Alice")).not.toBeInTheDocument();

  rerender(picker(""));
  expect(within(playerControls).queryByText("Bob")).not.toBeInTheDocument();

  rerender(picker("Alice", ["Bob"]));
  expect(within(playerControls).queryByText("Alice")).not.toBeInTheDocument();
});
