import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AsyncButton, Button } from "../../../shared/ui";

describe("Button", () => {
  it("renders with a label", () => {
    render(<Button>保存</Button>);
    expect(screen.getByRole("button", { name: "保存" })).toBeInTheDocument();
  });

  it("disables when loading", () => {
    render(<Button loading>提交</Button>);
    expect(screen.getByRole("button")).toBeDisabled();
  });

  it("renders primary variant", () => {
    render(<Button variant="primary">确认</Button>);
    const btn = screen.getByRole("button", { name: "确认" });
    expect(btn.className).toContain("button--primary");
  });

  it("renders danger variant", () => {
    render(<Button variant="danger">删除</Button>);
    const btn = screen.getByRole("button", { name: "删除" });
    expect(btn.className).toContain("button--danger");
  });

  it("renders ghost variant", () => {
    render(<Button variant="ghost">取消</Button>);
    const btn = screen.getByRole("button", { name: "取消" });
    expect(btn.className).toContain("button--ghost");
  });

  it("renders an icon", () => {
    render(<Button icon={<span data-testid="icon" />}>带图标</Button>);
    expect(screen.getByTestId("icon")).toBeInTheDocument();
  });

  it("renders tooltip as title attribute", () => {
    render(<Button tooltip="提示文字">悬停</Button>);
    expect(screen.getByRole("button")).toHaveAttribute("title", "提示文字");
  });

  it("fires onClick", () => {
    let fired = false;
    render(<Button onClick={() => (fired = true)}>点击</Button>);
    screen.getByRole("button").click();
    expect(fired).toBe(true);
  });
});

describe("AsyncButton", () => {
  it("is an alias for Button with loading support", () => {
    render(<AsyncButton loading>加载中</AsyncButton>);
    expect(screen.getByRole("button")).toBeDisabled();
  });
});
