import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TaskProgress } from "../../../shared/ui";

describe("TaskProgress", () => {
  it("renders nothing without a task", () => {
    const { container } = render(<TaskProgress task={null} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("clamps progress, renders the message, and limits logs from the end", () => {
    render(
      <TaskProgress
        logLimit={2}
        task={{
          logs: ["prepare", "download", "done"],
          message: "Almost there",
          phase: "install",
          progress: 1.4,
          status: "running",
        }}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("安装");
    expect(screen.getByRole("status")).toHaveTextContent("100%");
    expect(screen.getByText("Almost there")).toBeInTheDocument();
    expect(screen.queryByText("prepare")).not.toBeInTheDocument();
    expect(screen.getByText((_, element) => element?.textContent === "download\ndone")).toBeInTheDocument();
  });

  it("uses status text when progress and message are absent", () => {
    render(<TaskProgress task={{ phase: "queued", status: "waiting" }} />);

    expect(screen.getByRole("status")).toHaveTextContent("waiting");
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it("accepts localized task presentation labels", () => {
    render(
      <TaskProgress
        labels={{ message: "正在初始化长期记忆…", phase: "初始化", status: "进行中" }}
        task={{ message: "Initializing long-term memory.", phase: "initialize", status: "running" }}
      />,
    );

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("初始化");
    expect(status).toHaveTextContent("进行中");
    expect(status).toHaveTextContent("正在初始化长期记忆…");
    expect(status).not.toHaveTextContent("initialize");
    expect(status).not.toHaveTextContent("running");
  });

  it("does not repeat a localized message that is identical to the phase", () => {
    const { container } = render(
      <TaskProgress
        labels={{ message: "正在下载 embedding 模型…", phase: "正在下载 embedding 模型…", status: "进行中" }}
        task={{ message: "Downloading model.", phase: "download", status: "running" }}
      />,
    );

    expect(screen.getAllByText("正在下载 embedding 模型…")).toHaveLength(1);
    expect(container.querySelector(".task-progress__message")).not.toBeInTheDocument();
  });

  it("renders fallback notices and failed package guidance", () => {
    const { rerender } = render(
      <TaskProgress
        task={{
          fallbackAllowed: true,
          logs: [],
          message: "正在下载源码",
          notice: "官方包体暂时无法访问，正在自动尝试 GitHub 源码安装。",
          noticeKind: "info",
          phase: "download",
          progress: 0.2,
          status: "running",
        }}
      />,
    );

    expect(screen.getByText("官方包体暂时无法访问，正在自动尝试 GitHub 源码安装。")).toBeInTheDocument();

    rerender(
      <TaskProgress
        task={{
          errorUserMessage: "包体校验未通过，已阻止安装。",
          fallbackAllowed: false,
          logs: [],
          message: "包体校验未通过，已阻止安装。",
          phase: "failed",
          status: "failed",
        }}
      />,
    );

    expect(screen.getByText("包体校验未通过，已阻止安装。")).toBeInTheDocument();
  });

  it("renders plugin install provenance and dependency details", () => {
    render(
      <TaskProgress
        task={{
          dependencyInstallStatus: "pip_ok",
          installSourceLabel: "官方包体 (R2)",
          message: "Installing demo plugin",
          packageSha256: "abcdef1234567890fedcba",
          packageSource: "r2",
          packageStatus: "installed",
          phase: "pip",
          progress: 0.8,
          status: "running",
        }}
      />,
    );

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("安装依赖");
    expect(status).toHaveTextContent("来源");
    expect(status).toHaveTextContent("官方包体 (R2)");
    expect(status).toHaveTextContent("包体");
    expect(status).toHaveTextContent("包体已校验 / R2");
    expect(status).toHaveTextContent("依赖");
    expect(status).toHaveTextContent("依赖完成");
    expect(status).toHaveTextContent("SHA256");
    expect(status).toHaveTextContent("abcdef123456...");
  });

  it("maps plugin install internal status keys to user-facing labels", () => {
    render(
      <TaskProgress
        task={{
          dependencyInstallStatus: "pip_ok",
          installSource: "package",
          message: "官方包体安装完成。",
          packageSource: "r2",
          packageStatus: "verified",
          phase: "completed",
          progress: 1,
          status: "succeeded",
        }}
      />,
    );

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("官方包体");
    expect(status).toHaveTextContent("包体已校验 / R2");
    expect(status).toHaveTextContent("依赖完成");
  });
});
