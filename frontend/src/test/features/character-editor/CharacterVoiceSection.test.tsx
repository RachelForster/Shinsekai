import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CharacterVoiceSection } from "../../../features/character-editor/CharacterVoiceSection";
import {
  buildCommittedCharacterPayload,
  createCharacter,
  removeCharacterVoice,
} from "../../../features/character-editor/characterEditorUtils";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

function renderSection(voiceReferenceReadOnly = false) {
  const props: Parameters<typeof CharacterVoiceSection>[0] = {
    draft: {
      ...createCharacter(),
      gpt_model_path: "D:/models/gpt.ckpt",
      prompt_lang: "ja",
      prompt_text: "hello",
      refer_audio_path: "D:/audio/ref.wav",
      sovits_model_path: "D:/models/sovits.pth",
      speech_speed: 1,
      speech_volume: 1,
    },
    onChange: vi.fn(),
    voiceReferenceReadOnly,
  };

  const result = render(
    <I18nProvider language="en">
      <CharacterVoiceSection {...props} />
    </I18nProvider>,
  );

  return { props, ...result };
}

describe("CharacterVoiceSection", () => {
  it("routes voice reference paths and numeric settings through public callbacks", () => {
    const { props } = renderSection();

    expect(screen.queryByText(/Upload the \.char package in the Kaggle Notebook/)).not.toBeInTheDocument();

    fireEvent.change(screen.getByDisplayValue("D:/models/gpt.ckpt"), { target: { value: "D:/models/new.ckpt" } });
    expect(props.onChange).toHaveBeenCalledWith("gpt_model_path", "D:/models/new.ckpt");

    fireEvent.change(screen.getByDisplayValue("D:/models/sovits.pth"), { target: { value: "D:/models/new.pth" } });
    expect(props.onChange).toHaveBeenCalledWith("sovits_model_path", "D:/models/new.pth");

    fireEvent.change(screen.getByDisplayValue("D:/audio/ref.wav"), { target: { value: "D:/audio/new.wav" } });
    expect(props.onChange).toHaveBeenCalledWith("refer_audio_path", "D:/audio/new.wav");

    fireEvent.change(screen.getByDisplayValue("ja"), { target: { value: "en" } });
    expect(props.onChange).toHaveBeenCalledWith("prompt_lang", "en");

    fireEvent.change(screen.getByDisplayValue("hello"), { target: { value: "updated line" } });
    expect(props.onChange).toHaveBeenCalledWith("prompt_text", "updated line");

    fireEvent.change(screen.getByLabelText("TTS Speed"), { target: { value: "1.25" } });
    expect(props.onChange).toHaveBeenCalledWith("speech_speed", 1.25);

    fireEvent.change(screen.getByLabelText("TTS Volume"), { target: { value: "0.8" } });
    expect(props.onChange).toHaveBeenCalledWith("speech_volume", 0.8);
  });

  it("creates a named profile and edits its model without editing the default profile", () => {
    const onChange = vi.fn();
    const draft = { ...createCharacter(), gpt_model_path: "D:/models/default.ckpt" };
    const { rerender } = render(
      <I18nProvider language="en">
        <CharacterVoiceSection draft={draft} onChange={onChange} voiceProfilesEnabled />
      </I18nProvider>,
    );
    fireEvent.change(screen.getByLabelText("Voice name"), { target: { value: "Haru" } });
    expect(onChange).toHaveBeenLastCalledWith("default_voice_name", "Haru");
    fireEvent.click(screen.getByRole("button", { name: /Add voice/ }));
    const [field, profiles] = onChange.mock.lastCall!;
    expect(field).toBe("voice_profiles");
    const [profileId] = Object.keys(profiles);
    rerender(
      <I18nProvider language="en">
        <CharacterVoiceSection
          draft={{ ...draft, voice_profiles: profiles }}
          onChange={onChange}
          voiceProfilesEnabled
        />
      </I18nProvider>,
    );

    fireEvent.change(screen.getByLabelText("Voice name"), { target: { value: "Mujina" } });
    expect(onChange).toHaveBeenLastCalledWith("voice_profiles", {
      [profileId]: { ...profiles[profileId], name: "Mujina" },
    });
    fireEvent.change(screen.getByLabelText("GPT model path"), { target: { value: "D:/models/mujina.ckpt" } });
    expect(onChange).toHaveBeenLastCalledWith("voice_profiles", {
      [profileId]: { ...profiles[profileId], gpt_model_path: "D:/models/mujina.ckpt" },
    });
    expect(onChange).not.toHaveBeenCalledWith("gpt_model_path", expect.anything());
  });

  it("confirms replacement of the default voice and saves the new default with its bindings", () => {
    const draft = {
      ...createCharacter(),
      default_voice_name: "Haru",
      refer_audio_path: "D:/audio/haru.wav",
      voice_profiles: {
        mujina: { name: "Mujina", gpt_model_path: "D:/model/mujina.ckpt", speech_speed: 0.9, speech_volume: 0.8 },
        other: { name: "Other", speech_speed: 1, speech_volume: 1 },
      },
      sprites: [
        { path: "haru.png" },
        { path: "mujina.png", voice_profile_id: "mujina", voice_path: "D:/audio/sprite.wav" },
        { path: "other.png", voice_profile_id: "other" },
      ],
    };
    const onRemoveProfile = vi.fn();
    render(
      <I18nProvider language="en">
        <CharacterVoiceSection
          draft={draft}
          onChange={vi.fn()}
          onRemoveProfile={onRemoveProfile}
          voiceProfilesEnabled
        />
      </I18nProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Delete voice profile" }));
    expect(screen.getByText(/deleting “Haru”.*use “Mujina”/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onRemoveProfile).toHaveBeenCalledWith("");

    const next = removeCharacterVoice(draft, "");
    const payload = buildCommittedCharacterPayload(next, {}, draft);
    expect(payload.default_voice_name).toBe("Mujina");
    expect(payload.gpt_model_path).toBe("D:/model/mujina.ckpt");
    expect(payload.refer_audio_path).toBe("");
    expect(payload.voice_profiles).toEqual({ other: draft.voice_profiles.other });
    expect(payload.sprites.map((sprite) => sprite.voice_profile_id)).toEqual([undefined, null, "other"]);
    expect(payload.sprites[1].voice_path).toBe("D:/audio/sprite.wav");

    const withoutOther = removeCharacterVoice(next, "other");
    expect(withoutOther.default_voice_name).toBe("Mujina");
    expect(withoutOther.sprites[2].voice_profile_id).toBeNull();
    expect(removeCharacterVoice(withoutOther, "")).toBe(withoutOther);
  });

  it("keeps voice reference fields read-only when requested", () => {
    const { props } = renderSection(true);

    expect(screen.getByText(/Upload the \.char package in the Kaggle Notebook/)).toBeInTheDocument();
    expect(screen.queryByDisplayValue("D:/models/gpt.ckpt")).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue("D:/models/sovits.pth")).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue("D:/audio/ref.wav")).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("ja")).toHaveAttribute("readonly");
    expect(screen.getByDisplayValue("ja")).toBeDisabled();
    expect(screen.getByDisplayValue("hello")).toHaveAttribute("readonly");
    expect(screen.getByDisplayValue("hello")).toBeDisabled();
    expect(screen.getByLabelText("TTS Speed")).toBeDisabled();
    expect(screen.getByLabelText("TTS Volume")).not.toBeDisabled();
    expect(screen.getAllByRole("button", { name: "Choose file" })).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ disabled: true }),
        expect.objectContaining({ disabled: true }),
        expect.objectContaining({ disabled: true }),
      ]),
    );

    fireEvent.change(screen.getByDisplayValue("ja"), { target: { value: "en" } });
    fireEvent.change(screen.getByDisplayValue("hello"), { target: { value: "updated line" } });
    fireEvent.change(screen.getByLabelText("TTS Speed"), { target: { value: "1.25" } });
    fireEvent.change(screen.getByLabelText("TTS Volume"), { target: { value: "0.8" } });

    expect(props.onChange).not.toHaveBeenCalledWith("prompt_lang", expect.any(String));
    expect(props.onChange).not.toHaveBeenCalledWith("prompt_text", expect.any(String));
    expect(props.onChange).not.toHaveBeenCalledWith("speech_speed", expect.any(Number));
    expect(props.onChange).toHaveBeenCalledWith("speech_volume", 0.8);
  });
});
