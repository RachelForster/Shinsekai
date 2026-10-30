import { useState } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ApiConfig } from "../../../entities/config/types";
import { T2iSetupSection } from "../../../features/api-settings/T2iSetupSection";
import { I18nProvider } from "../../../shared/i18n";
import { sampleConfig } from "../../../shared/platform/sampleData";
import type { ComfyUIConnectionTestResult } from "../../../shared/platform/types";

const mocks = vi.hoisted(() => ({ testComfyuiConnection: vi.fn() }));
vi.mock("../../../entities/config/repository", () => ({
  testComfyuiConnection: (...args: unknown[]) => mocks.testComfyuiConnection(...args),
}));

function Setup({ extras = {}, workPath = "" }: { extras?: Record<string, unknown>; workPath?: string }) {
  const [draft, setDraft] = useState<ApiConfig>({
    ...sampleConfig.api_config,
    t2i_provider: "comfyui",
    t2i_api_url: "http://127.0.0.1:8189",
    t2i_default_workflow_path: "D:/minimax_h3_i2v_api.json",
    t2i_prompt_node_id: "131",
    t2i_output_node_id: "92",
    t2i_work_path: workPath,
  });
  const [values, setValues] = useState(extras);
  return (
    <I18nProvider language="zh_CN">
      <T2iSetupSection
        disabled={false}
        draft={draft}
        errors={{}}
        extraSchema={{
          auto_start: { type: "bool", default: false, label: "backend auto start" },
          startup_args: { type: "str", default: "--windows-standalone-build", label: "启动参数" },
          reference_node_id: { type: "str", default: "", label: "参考图节点" },
        }}
        extraValues={values}
        onAdapterExtraChange={(key, value) => setValues((previous) => ({ ...previous, [key]: value }))}
        onChange={setDraft}
        providerOptions={[
          { label: "ComfyUI", value: "comfyui" },
          { label: "Stable Diffusion", value: "stable diffusion" },
        ]}
      />
    </I18nProvider>
  );
}

describe("ComfyUI setup", () => {
  beforeEach(() => {
    mocks.testComfyuiConnection.mockReset();
  });

  it("checks the unsaved URL and states that workflow execution is not verified", async () => {
    mocks.testComfyuiConnection.mockResolvedValue({ ok: true, code: "connected", serverVersion: "0.3.test" });
    render(<Setup />);
    fireEvent.change(screen.getByLabelText("ComfyUI API 地址"), { target: { value: "http://localhost:8190" } });
    fireEvent.click(screen.getByRole("button", { name: "检测连接" }));
    expect(mocks.testComfyuiConnection).toHaveBeenCalledWith({ baseUrl: "http://localhost:8190" });
    expect(await screen.findByRole("status")).toHaveTextContent("ComfyUI API 连接成功");
    expect(screen.getByRole("status")).toHaveTextContent("ComfyUI 0.3.test");
    expect(screen.getByRole("status")).toHaveTextContent("检查工作流与模型");
    fireEvent.change(screen.getByLabelText("ComfyUI API 地址"), { target: { value: "http://localhost:8191" } });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("ignores an old response after the address changes and allows a new check", async () => {
    let resolveOld!: (result: ComfyUIConnectionTestResult) => void;
    mocks.testComfyuiConnection.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveOld = resolve;
      }),
    );
    render(<Setup />);
    fireEvent.click(screen.getByRole("button", { name: "检测连接" }));
    expect(screen.getByRole("button", { name: "检测中…" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("ComfyUI API 地址"), { target: { value: "http://localhost:8191" } });
    mocks.testComfyuiConnection.mockResolvedValueOnce({ ok: false, code: "unreachable" });
    fireEvent.click(screen.getByRole("button", { name: "检测连接" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("无法连接"));
    await act(async () => {
      resolveOld({ ok: true, code: "connected" });
    });
    expect(screen.getByRole("status")).toHaveTextContent("无法连接");
    expect(screen.queryByText("ComfyUI API 连接成功")).not.toBeInTheDocument();
  });

  it("shows HTTP failure guidance and offers retry after bridge failure", async () => {
    mocks.testComfyuiConnection.mockResolvedValueOnce({ ok: false, code: "auth_required", httpStatus: 401 });
    render(<Setup />);
    fireEvent.click(screen.getByRole("button", { name: "检测连接" }));
    expect(await screen.findByRole("status")).toHaveTextContent("服务要求登录或拒绝访问");
    expect(screen.getByRole("status")).toHaveTextContent("HTTP 401");
    mocks.testComfyuiConnection.mockRejectedValueOnce(new Error("bridge offline"));
    fireEvent.click(screen.getByRole("button", { name: "检测连接" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("无法完成检测");
    expect(screen.getByRole("button", { name: "检测连接" })).toBeEnabled();
    fireEvent.change(screen.getByLabelText("ComfyUI API 地址"), { target: { value: "" } });
    expect(screen.getByRole("button", { name: "检测连接" })).toBeDisabled();
  });

  it("connects to a manually started bundle without requiring a portable directory", () => {
    render(<Setup />);
    expect(screen.getByText(/先用自己的启动器启动/)).toBeVisible();
    expect(screen.getByRole("checkbox", { name: /自动启动官方/ })).not.toBeChecked();
    expect(screen.queryByLabelText("官方便携版根目录")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("启动参数")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("首次连接指引（含秋叶整合包）"));
    expect(screen.getByText("准备 API 格式的工作流")).toBeVisible();
    expect(screen.getByText(/API 兼容不代表模型和节点已安装/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "补全缺失的默认值" }));
    expect(screen.getByLabelText("ComfyUI API 地址")).toHaveValue("http://127.0.0.1:8189");
    expect(screen.getByDisplayValue("131")).toBeInTheDocument();
    expect(screen.getByDisplayValue("92")).toBeInTheDocument();
  });

  it("lets a legacy portable user switch to their launcher without deleting saved paths", () => {
    render(<Setup workPath="D:/ComfyUI portable" />);
    const toggle = screen.getByRole("checkbox", { name: /自动启动官方/ });
    expect(toggle).toBeChecked();
    expect(screen.getByLabelText("官方便携版根目录")).toHaveValue("D:/ComfyUI portable");
    fireEvent.click(toggle);
    expect(screen.queryByLabelText("官方便携版根目录")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("启动参数")).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(screen.getByLabelText("官方便携版根目录")).toHaveValue("D:/ComfyUI portable");
    expect(screen.getByDisplayValue("--windows-standalone-build")).toBeInTheDocument();
  });

  it("respects an explicit manual mode even when a directory is still configured", () => {
    render(<Setup extras={{ auto_start: false }} workPath="D:/old portable" />);
    expect(screen.getByRole("checkbox", { name: /自动启动官方/ })).not.toBeChecked();
    expect(screen.queryByLabelText("官方便携版根目录")).not.toBeInTheDocument();
    expect(screen.queryByText("backend auto start")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("combobox", { name: "T2I 服务商" }));
    fireEvent.click(screen.getByRole("option", { name: "Stable Diffusion" }));
    expect(screen.queryByRole("checkbox", { name: /自动启动官方/ })).not.toBeInTheDocument();
    expect(screen.queryByText("首次连接指引（含秋叶整合包）")).not.toBeInTheDocument();
  });
});
