import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it } from "vitest";

import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { MentionTextArea } from "../../../shared/ui/MentionTextArea";
import { characterMentionOptions, MENTION_RECENT_STORAGE_KEY } from "../../../shared/ui/mentionTokens";

const options = characterMentionOptions(
  [
    { color: "#66ccff", name: "Nanami" },
    { color: "#ff99aa", name: "Mika" },
  ],
  "User",
);

const manyOptions = characterMentionOptions(
  Array.from({ length: 16 }, (_, index) => ({ color: "#66ccff", name: `Hero${index + 1}` })),
  "User",
);

function Harness({ mentionOptions = options }: { mentionOptions?: typeof options }) {
  const [value, setValue] = useState("");
  return (
    <I18nProvider language="en">
      <MentionTextArea aria-label="Scenario" onChange={setValue} options={mentionOptions} value={value} />
    </I18nProvider>
  );
}

function typeMention(textarea: HTMLTextAreaElement, value: string) {
  fireEvent.change(textarea, { target: { value } });
  textarea.setSelectionRange(value.length, value.length);
  fireEvent.keyUp(textarea, { key: value.slice(-1) });
}

function typeAtCaret(textarea: HTMLTextAreaElement, text: string) {
  const start = textarea.selectionStart ?? textarea.value.length;
  const end = textarea.selectionEnd ?? start;
  const next = `${textarea.value.slice(0, start)}${text}${textarea.value.slice(end)}`;
  fireEvent.change(textarea, { target: { value: next } });
  textarea.setSelectionRange(start + text.length, start + text.length);
  fireEvent.keyUp(textarea, { key: text.slice(-1) });
}

describe("MentionTextArea", () => {
  beforeEach(() => {
    window.localStorage.removeItem(MENTION_RECENT_STORAGE_KEY);
  });

  it("opens the character list on @ and inserts a label token", () => {
    render(<Harness />);
    const textarea = screen.getByRole("textbox", { name: "Scenario" });
    typeMention(textarea as HTMLTextAreaElement, "@");

    const listbox = screen.getByRole("listbox", { name: "Mention a character" });
    expect(listbox).toHaveClass("custom-select__menu");
    expect(screen.getByRole("option", { name: "User" })).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByRole("option", { name: "Nanami" }));

    expect(textarea).toHaveValue("@Nanami ");
    expect(textarea).toHaveProperty("selectionStart", "@Nanami ".length);
    expect(document.querySelector(".mention-editor__chip")).toHaveTextContent("@Nanami");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("can mention again after inserting a token and keeps the caret after it", () => {
    render(<Harness />);
    const textarea = screen.getByRole("textbox", { name: "Scenario" }) as HTMLTextAreaElement;
    typeMention(textarea, "@");
    fireEvent.mouseDown(screen.getByRole("option", { name: "Nanami" }));

    expect(textarea.selectionStart).toBe("@Nanami ".length);
    typeAtCaret(textarea, "meets ");
    typeAtCaret(textarea, "@");

    expect(screen.getByRole("listbox")).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByRole("option", { name: "Mika" }));
    expect(textarea).toHaveValue("@Nanami meets @Mika ");
    expect(textarea.selectionStart).toBe("@Nanami meets @Mika ".length);
  });

  it("filters options and confirms the highlighted match with Enter", () => {
    render(<Harness />);
    const textarea = screen.getByRole("textbox", { name: "Scenario" });
    typeMention(textarea as HTMLTextAreaElement, "@Na");

    fireEvent.keyDown(textarea, { key: "Enter" });
    expect(textarea).toHaveValue("@Nanami ");
    expect(textarea).toHaveProperty("selectionStart", "@Nanami ".length);
  });

  it("orders mention options by most recently used", () => {
    render(<Harness />);
    const textarea = screen.getByRole("textbox", { name: "Scenario" }) as HTMLTextAreaElement;
    typeMention(textarea, "@");
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual(["User", "Nanami", "Mika"]);
    fireEvent.mouseDown(screen.getByRole("option", { name: "Mika" }));

    typeAtCaret(textarea, "@");
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual(["Mika", "User", "Nanami"]);
  });

  it("scrolls the active mention option into view with arrow keys", () => {
    render(<Harness mentionOptions={manyOptions} />);
    const textarea = screen.getByRole("textbox", { name: "Scenario" });
    typeMention(textarea as HTMLTextAreaElement, "@");

    fireEvent.keyDown(textarea, { key: "ArrowDown" });
    fireEvent.keyDown(textarea, { key: "ArrowDown" });
    expect(screen.getByRole("option", { name: "Hero2" })).toHaveAttribute("data-active", "true");
  });
});
