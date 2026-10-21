# MiniMax H3 立绘工作流

这些工作流由 [ComfyUI 官方 H3 原生模板](https://docs.comfy.org/tutorials/video/minimax/minimax-h3-native) 整理。可视化版与 API 版使用相同的节点 ID、模型文件名、480×832 画布、107 帧、24 fps 和 8 步 Turbo 配置，输出无声视频。

| 文件 | 用途 |
| --- | --- |
| [minimax_h3_i2v.json](minimax_h3_i2v.json) | **导入 ComfyUI**：上传参考立绘作为首帧，生成视频。 |
| [minimax_h3_t2v.json](minimax_h3_t2v.json) | **导入 ComfyUI**：无参考图的文生视频。 |
| [minimax_h3_i2v_api.json](minimax_h3_i2v_api.json) | **新世界 API 设定 → 默认工作流**：图生视频。 |
| [minimax_h3_t2v_api.json](minimax_h3_t2v_api.json) | **新世界 ComfyUI 扩展 → `text_only_workflow_path`**：文生视频。 |

## 导入与试跑

1. 启动支持 H3 原生节点的 ComfyUI，打开它的网页。
2. 将 `minimax_h3_i2v.json` 拖入画布，或通过工作流菜单打开该 JSON。使用文生视频时选择 `minimax_h3_t2v.json`。
3. 图生视频需先在 **Upload your reference sprite before running** 节点上传自己的图片，替换 `reference.png`。检查模型已安装，画布比例与参考图匹配，然后点击运行。
4. 成功生成视频后，在新世界选择对应的 **`_api.json`** 文件。提示词节点 `131`、输出节点 `92`、参考图节点 `114`。文件路径使用当前电脑的绝对路径。

工作流可以保存到 `ComfyUI/user/default/workflows/` 方便以后打开。JSON 只包含节点与参数，模型权重需要另行安装。

模型下载与目录说明见上方官方教程。完整的新世界接入指南位于源码仓库的 `docs/CHARACTER_SPRITE_GENERATION_zh-CN.md`，包含连接参数与常见问题。
