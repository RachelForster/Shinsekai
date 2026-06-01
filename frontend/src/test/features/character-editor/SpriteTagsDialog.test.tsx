import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SpriteTagsDialog } from "../../../features/character-editor/SpriteTagsDialog";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

function renderDialog(open = true) {
  const props: Parameters<typeof SpriteTagsDialog>[0] = {
    draft: "1. smile\n2. angry",
    onChange: vi.fn(),
    onClose: vi.fn(),
    onConfirm: vi.fn(),
    open,
  };

  const result = render(
    <I18nProvider language="en">
      <SpriteTagsDialog {...props} />
    </I18nProvider>,
  );

  return { props, ...result };
}

describe("SpriteTagsDialog", () => {
  it("does not render dialog content while closed", () => {
    renderDialog(false);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("edits draft text and routes close/confirm actions", () => {
    const { props } = renderDialog();
    const dialog = screen.getByRole("dialog", { name: "Batch sprite tags" });

    fireEvent.change(within(dialog).getByLabelText("Emotion tags (per upload / order)"), {
      target: { value: "1. smile" },
    });
    expect(props.onChange).toHaveBeenCalledWith("1. smile");

    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(props.onClose).toHaveBeenCalledTimes(1);

    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    expect(props.onConfirm).toHaveBeenCalledTimes(1);

    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(props.onClose).toHaveBeenCalledTimes(2);
  });
});
