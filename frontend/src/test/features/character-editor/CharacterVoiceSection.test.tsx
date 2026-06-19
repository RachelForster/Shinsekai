import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CharacterVoiceSection } from "../../../features/character-editor/CharacterVoiceSection";
import { createCharacter } from "../../../features/character-editor/characterEditorUtils";
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
