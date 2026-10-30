# MiniMax H3 立绘工作流

这些工作流由 [ComfyUI 官方 H3 原生模板](https://docs.comfy.org/tutorials/video/minimax/minimax-h3-native) 整理。可视化版与 API 版使用相同的节点 ID、模型文件名、480×832 画布、107 帧、24 fps 和 8 步 Turbo 配置，输出无声视频。

| 文件 | 用途 |
| --- | --- |
| [minimax_h3_i2v.json](minimax_h3_i2v.json) | **导入 ComfyUI**：上传参考立绘作为首帧，生成视频。 |
| [minimax_h3_t2v.json](minimax_h3_t2v.json) | **导入 ComfyUI**：无参考图的文生视频。 |
| [minimax_h3_i2v_api.json](minimax_h3_i2v_api.json) | **新世界 API 设定 → 默认工作流**：图生视频。 |
| [minimax_h3_t2v_api.json](minimax_h3_t2v_api.json) | **新世界 ComfyUI 扩展 → `text_only_workflow_path`**：文生视频。 |

## 导入与试跑

秋叶／绘世整合包、Desktop 等沿用自己的启动器，等网页可用后，在新世界关闭自动启动并填入相同服务根地址和实际端口。标准 ComfyUI API 工作流可复用，但内核版本、节点和模型仍需满足工作流要求。详细步骤见 [ComfyUI 连接指南](../../../docs/COMFYUI_SETUP_zh-CN.md)。

新世界的“立绘智能生成”窗口提供“打开工作流文件夹”，无需手动查找安装目录；“H3 模型下载页”和“H3 安装教程”也可以直接点击。

1. 启动支持 H3 原生节点的 ComfyUI，打开它的网页。
2. 将 `minimax_h3_i2v.json` 拖入画布，或通过工作流菜单打开该 JSON。使用文生视频时选择 `minimax_h3_t2v.json`。
3. 图生视频需先在 **Upload your reference sprite before running** 节点上传自己的图片，替换 `reference.png`。检查模型已安装，画布比例与参考图匹配，然后点击运行。
4. 成功生成视频后，在新世界选择对应的 **`_api.json`** 文件。提示词节点 `131`、输出节点 `92`、参考图节点 `114`。文件路径使用当前电脑的绝对路径。

工作流可以保存到 `ComfyUI/user/default/workflows/` 方便以后打开。JSON 只包含节点与参数，模型权重需要另行安装。

图生视频默认提示词保留参考图构图、裁切、机位和人物占比，支持半身或局部立绘；文生视频默认要求全身像。两者均使用固定镜头。手动运行时也应让画布比例匹配参考图，保留原有取景。

模型下载与目录说明见上方官方教程。完整的新世界接入指南位于源码仓库的 `docs/CHARACTER_SPRITE_GENERATION_zh-CN.md`，包含连接参数与常见问题。

## 模型下载

配套无声工作流只需以下四个文件，点击名称进入下载页，放置目录相对于 ComfyUI：

| 模型文件 | 放置目录 |
| --- | --- |
| [minimax_h3_fl2va_pruned_int8_convrot.safetensors](https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors) | `models/diffusion_models/` |
| [qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors](https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors) | `models/text_encoders/` |
| [minimax_h3_video_vae_int8_convrot.safetensors](https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/vae/minimax_h3_video_vae_int8_convrot.safetensors) | `models/vae/` |
| [minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors](https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors) | `models/loras/` |
