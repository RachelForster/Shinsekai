import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { KnowledgeDeleteDialogs } from "../../../features/knowledge-manager/KnowledgeDialogs";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

it("names the captured target and prevents dismissing or confirming while pending", () => {
  const onCancel = vi.fn();
  const onConfirm = vi.fn();
  const view = (pending: boolean) => (
    <I18nProvider language="en">
      <KnowledgeDeleteDialogs
        target={{ knowledgeId: "alpha" }}
        pending={pending}
        onCancel={onCancel}
        onConfirm={onConfirm}
      />
    </I18nProvider>
  );
  const { rerender } = render(view(false));
  expect(screen.getByRole("dialog")).toHaveTextContent("alpha");
  expect(screen.getByRole("dialog")).toHaveTextContent("All entries and character bindings");
  expect(screen.getByRole("dialog")).toHaveTextContent("Characters will be kept");
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(onCancel).toHaveBeenCalledTimes(1);
  rerender(view(true));
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
  expect(onConfirm).not.toHaveBeenCalled();
  expect(onCancel).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("button", { name: "Close" })).not.toBeInTheDocument();
});
