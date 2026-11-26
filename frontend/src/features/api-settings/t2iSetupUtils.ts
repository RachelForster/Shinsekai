import type { ApiConfig } from "../../entities/config/types";

export const DEFAULT_T2I_PROVIDER = "comfyui";
export const DEFAULT_T2I_API_URL = "http://127.0.0.1:8188";
export const DEFAULT_T2I_PROMPT_NODE_ID = "6";
export const DEFAULT_T2I_OUTPUT_NODE_ID = "9";

export type T2iSetupMode = "custom" | "local" | "skip";

export function inferT2iSetupMode(
  config: Pick<ApiConfig, "t2i_api_url" | "t2i_default_workflow_path" | "t2i_provider" | "t2i_work_path">,
): T2iSetupMode {
  const workflow = String(config.t2i_default_workflow_path || "").trim();
  const workPath = String(config.t2i_work_path || "").trim();
  const url = String(config.t2i_api_url || "")
    .trim()
    .toLowerCase();
  const provider = String(config.t2i_provider || DEFAULT_T2I_PROVIDER)
    .trim()
    .toLowerCase();
  const defaultUrl = !url || url === DEFAULT_T2I_API_URL;
  const defaultProvider = !provider || provider === DEFAULT_T2I_PROVIDER;
  if (!workflow && !workPath && defaultUrl && defaultProvider) {
    return "skip";
  }
  if (/^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(?::\d+)?(?:\/.*)?$/.test(url)) {
    return "local";
  }
  return "custom";
}

export function applyT2iSetupMode(config: ApiConfig, mode: T2iSetupMode): ApiConfig {
  const baseDefaults = {
    t2i_output_node_id: config.t2i_output_node_id || DEFAULT_T2I_OUTPUT_NODE_ID,
    t2i_prompt_node_id: config.t2i_prompt_node_id || DEFAULT_T2I_PROMPT_NODE_ID,
    t2i_provider: config.t2i_provider || DEFAULT_T2I_PROVIDER,
  };
  if (mode === "skip") {
    return {
      ...config,
      ...baseDefaults,
      t2i_api_url: DEFAULT_T2I_API_URL,
      t2i_default_workflow_path: "",
      t2i_output_node_id: DEFAULT_T2I_OUTPUT_NODE_ID,
      t2i_prompt_node_id: DEFAULT_T2I_PROMPT_NODE_ID,
      t2i_provider: DEFAULT_T2I_PROVIDER,
      t2i_work_path: "",
    };
  }
  if (mode === "local") {
    return {
      ...config,
      ...baseDefaults,
      t2i_api_url: inferT2iSetupMode(config) === "local" ? config.t2i_api_url : DEFAULT_T2I_API_URL,
      t2i_provider: DEFAULT_T2I_PROVIDER,
    };
  }
  return {
    ...config,
    ...baseDefaults,
    t2i_api_url: config.t2i_api_url || DEFAULT_T2I_API_URL,
  };
}

export function isT2iReadyForSprites(
  config: Pick<ApiConfig, "t2i_api_url" | "t2i_default_workflow_path" | "t2i_provider">,
) {
  const provider = String(config.t2i_provider || "")
    .trim()
    .toLowerCase();
  const apiUrl = String(config.t2i_api_url || "").trim();
  const workflow = String(config.t2i_default_workflow_path || "").trim();
  if (!provider || !apiUrl) {
    return false;
  }
  if (provider === DEFAULT_T2I_PROVIDER) {
    return Boolean(workflow);
  }
  return true;
}
