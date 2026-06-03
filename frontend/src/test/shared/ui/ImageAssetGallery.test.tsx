import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ImageAssetGallery } from "../../../shared/ui";

const items = [
  {
    badge: "Current",
    id: "first",
    imageSrc: "first.png",
    meta: "512x512",
    title: "First image",
  },
  {
    badgeTone: "muted" as const,
    id: "second",
    meta: "No image",
    title: "Second image",
  },
];

describe("ImageAssetGallery", () => {
  it("renders titles, metadata, badges, and selected state", () => {
    render(<ImageAssetGallery items={items} onSelect={() => {}} selectedIndex={0} />);

    expect(screen.getByRole("button", { name: /First image/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("button", { name: /Second image/ })).toHaveAttribute("aria-selected", "false");
    expect(screen.getByText("512x512")).toBeInTheDocument();
    expect(screen.getByText("Current")).toHaveClass("image-asset-card__badge--default");
  });

  it("calls onSelect with the clicked item index", () => {
    const onSelect = vi.fn();
    render(<ImageAssetGallery items={items} onSelect={onSelect} selectedIndex={0} />);

    fireEvent.click(screen.getByRole("button", { name: /Second image/ }));

    expect(onSelect).toHaveBeenCalledWith(1);
  });

  it("updates image thumb state after load and error events", () => {
    const { container } = render(
      <ImageAssetGallery
        imageDecoding="sync"
        imageLoading="eager"
        items={items}
        onSelect={() => {}}
        selectedIndex={0}
      />,
    );

    const img = container.querySelector("img") as HTMLImageElement;
    const media = img.closest(".image-asset-card__media");
    expect(media).toHaveAttribute("data-state", "loading");

    Object.defineProperty(img, "naturalWidth", { configurable: true, value: 64 });
    Object.defineProperty(img, "decode", { configurable: true, value: vi.fn(() => new Promise(() => {})) });
    fireEvent.load(img);
    expect(media).toHaveAttribute("data-state", "loaded");

    fireEvent.error(img);
    expect(media).toHaveAttribute("data-state", "error");
  });
});
