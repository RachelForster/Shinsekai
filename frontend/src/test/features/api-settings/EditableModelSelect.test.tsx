import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EditableModelSelect, ModelCapabilityBadge } from "../../../features/api-settings/EditableModelSelect";

describe("EditableModelSelect", () => {
  const options = [
    { id: "deepseek-chat", tags: ["text"] },
    { id: "vision-model", tags: ["vision", "image_out"] },
  ];

  it("lets users type a custom model id", () => {
    const onChange = vi.fn();
    render(
      <EditableModelSelect
        disabled={false}
        id="model"
        onChange={onChange}
        options={options}
        placeholder="Model ID"
        value=""
      />,
    );

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "custom-model" } });

    expect(onChange).toHaveBeenCalledWith("custom-model");
  });

  it("opens the option list, renders capability tags, and selects a model", () => {
    const onChange = vi.fn();
    render(
      <EditableModelSelect
        disabled={false}
        id="model"
        onChange={onChange}
        options={options}
        placeholder="Model ID"
        value=""
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Model ID" }));

    expect(screen.getByRole("listbox")).toBeInTheDocument();
    expect(screen.getByText("Vision")).toBeInTheDocument();
    expect(screen.getByText("Image")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("option", { name: /vision-model/ }));

    expect(onChange).toHaveBeenCalledWith("vision-model");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("closes with Escape and when focus moves outside", () => {
    render(
      <>
        <EditableModelSelect
          disabled={false}
          id="model"
          onChange={() => {}}
          options={options}
          placeholder="Model ID"
          value="deepseek-chat"
        />
        <button type="button">Outside</button>
      </>,
    );

    fireEvent.focus(screen.getByRole("combobox"));
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Escape" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Model ID" }));
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    fireEvent.focusIn(screen.getByRole("button", { name: "Outside" }));
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("disables the dropdown button when there are no options", () => {
    render(
      <EditableModelSelect
        disabled={false}
        id="model"
        onChange={() => {}}
        options={[]}
        placeholder="Model ID"
        value=""
      />,
    );

    expect(screen.getByRole("button", { name: "Model ID" })).toBeDisabled();
  });
});

describe("ModelCapabilityBadge", () => {
  it("maps known tags to user-facing labels and preserves unknown tags", () => {
    const { rerender } = render(<ModelCapabilityBadge ghost tag="image_out" />);
    expect(screen.getByText("Image")).toHaveClass("llm-model-badge--ghost");

    rerender(<ModelCapabilityBadge tag="custom" />);
    expect(screen.getByText("custom")).toHaveAttribute("data-tag", "custom");
  });
});
