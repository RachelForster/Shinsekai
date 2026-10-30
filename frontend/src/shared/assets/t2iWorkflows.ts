export const H3_MODEL_REPOSITORY_URL = "https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main";
export const H3_SETUP_GUIDE_URL = "https://docs.comfy.org/tutorials/video/minimax/minimax-h3-native";

export const H3_REQUIRED_MODELS = [
  { fileName: "minimax_h3_fl2va_pruned_int8_convrot.safetensors", folder: "models/diffusion_models/" },
  { fileName: "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", folder: "models/text_encoders/" },
  { fileName: "minimax_h3_video_vae_int8_convrot.safetensors", folder: "models/vae/" },
  { fileName: "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors", folder: "models/loras/" },
].map((model) => ({
  ...model,
  url: `https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/${model.folder.replace("models/", "")}${model.fileName}`,
}));
