# 立绘智能生成与 MiniMax H3 接入指南

第一次使用本地 H3，建议按 **ComfyUI 单独生成成功 → 新世界连接同一服务 → 先试一张立绘 → 批量生成** 的顺序操作。这样能先确认模型与节点可用，再检查应用连接。已经跑通同一套模型和工作流的用户可以直接从第二步开始，无需每次手动生成视频。

立绘生成通过当前配置的 T2I 服务工作，也支持其他 ComfyUI 图像工作流和 Stable Diffusion API。H3 是可选方案。尚未配置图像服务时，可以先用已配置的 LLM 生成提示词与标签；生成图片仍需要图像服务。新世界不会自动安装 ComfyUI 或下载 H3 权重。

## 工作流文件在哪里

文件位于新世界项目或运行目录下的 **`ai/t2i/workflows/`**。也可以通过下表链接下载 JSON，保存到自己方便查找的位置。

| 文件 | 应在哪里使用 |
| --- | --- |
| [minimax_h3_i2v.json](../ai/t2i/workflows/minimax_h3_i2v.json) | **导入 ComfyUI**，上传参考立绘，试跑图生视频。 |
| [minimax_h3_t2v.json](../ai/t2i/workflows/minimax_h3_t2v.json) | **导入 ComfyUI**，试跑不带参考图的文生视频。 |
| [minimax_h3_i2v_api.json](../ai/t2i/workflows/minimax_h3_i2v_api.json) | **新世界 API 设定 → 默认工作流**，选择此文件的绝对路径。 |
| [minimax_h3_t2v_api.json](../ai/t2i/workflows/minimax_h3_t2v_api.json) | **新世界 ComfyUI 扩展 → `text_only_workflow_path`**，填写此文件的绝对路径。 |

启动 ComfyUI 后，将 **不带 `_api` 的 JSON** 拖入网页画布，或通过工作流菜单打开该文件。图生视频需在 **Upload your reference sprite before running** 节点上传自己的图片，替换默认的 `reference.png`。可以再保存到 `ComfyUI/user/default/workflows/`，方便后续打开。网页下载时保存 JSON 原文件，不要保存 GitHub 展示文件的 HTML 网页。

## 1. 先在 ComfyUI 单独生成视频

### 准备节点与模型

按 [ComfyUI 官方 H3 原生工作流教程](https://docs.comfy.org/tutorials/video/minimax/minimax-h3-native) 安装支持 H3 原生节点的 ComfyUI，获取官方可视化模板。模型来源与版本要求以官方教程及 [Comfy-Org/MiniMax-H3 模型仓库](https://huggingface.co/Comfy-Org/MiniMax-H3) 为准。

本项目附带的 API 工作流使用以下文件；目录相对于 ComfyUI：

| 模型文件 | 放置目录 |
| --- | --- |
| `minimax_h3_fl2va_pruned_int8_convrot.safetensors` | `models/diffusion_models/` |
| `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | `models/text_encoders/` |
| `minimax_h3_video_vae_int8_convrot.safetensors` | `models/vae/` |
| `minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors` | `models/loras/` |

文件名必须与 API 工作流对应。若使用不同量化版本，请同步修改工作流的模型名称，并先独立验证该组合。官方可视化模板如果保留音频分支，还需按官方教程安装音频 VAE；项目附带的立绘 API 工作流输出无声视频，不使用音频分支。

### 完成一次独立测试

1. 启动 ComfyUI，打开它实际监听的地址。默认常见地址为 `http://127.0.0.1:8188`；本项目 H3 配置示例使用 `8189`，请按自己的服务填写。
2. 将上表中的 `minimax_h3_i2v.json` 拖入 ComfyUI 画布。上传一张完整、人物居中的参考立绘，检查已安装的模型。附带工作流已经配置 8 步 Turbo；也可以使用官方教程的可视化模板或模板库中的 **MiniMax H3 I2V**，按模板启用 Turbo。
3. 先用较低分辨率生成一段短视频。本项目测试参数为 **480×832、107 帧、24 fps、8 步**；调整时保持与所用 H3 模板兼容的尺寸和帧数。手动测试也要让画布比例接近参考图，避免默认画布将人物拉伸。可使用提示词：`make the character stand and smile with relaxed eyebrows, wave the open right hand beside the head and rest the left hand at the side, full body, full scene, plain light, sprite`。
4. 确认任务成功，并能在 ComfyUI 查看输出视频。需要无参考图生成时，再导入 `minimax_h3_t2v.json` 验证。先解决缺失节点、模型加载、显存不足等报错，然后再连接新世界。

**可视化工作流与 API 工作流不同。** 不带 `_api` 的文件用于导入 ComfyUI；带 `_api` 的文件用于新世界提交任务。配套文件使用相同的节点 ID、模型与生成参数。不要把 API 文件无法正常展示为画布当成模型故障。第二步在新世界选择对应的 API 文件。自行修改模型或画布参数后，需同步修改 API 文件，或从 ComfyUI 重新导出 API 工作流，并确认实际节点 ID。

## 2. 在新世界连接同一个服务

保持已经跑通的 ComfyUI 运行，使用项目附带的 API 工作流时按下表设置。官方模板跑通说明模型环境可用；第三步的首张立绘测试用于确认 API 工作流和新世界之间的配置也正确。

API 设定 → 图像生成服务，先选择“本机 ComfyUI”或“自定义”，再填写下表参数，适配器选 `comfyui`。不要把模型名填成适配器名。配置完成后不要再点“应用 ComfyUI 默认值”，以免将 H3 的端口和节点恢复为通用默认值。下面的节点 ID 仅适用于项目附带的两份 API 工作流：

| 设置 | 值 |
| --- | --- |
| API 地址 | H3 ComfyUI 地址，例如 `http://127.0.0.1:8189` |
| 工作目录 | portable 安装目录，包含 `python_embeded/` 和 `ComfyUI/`；已手动启动服务时可留空 |
| 默认工作流 | 项目内 `ai/t2i/workflows/minimax_h3_i2v_api.json` 的绝对路径 |
| 提示词节点 ID | `131` |
| 输出节点 ID | `92` |

在 ComfyUI 扩展配置中填写：

| 设置 | 值 |
| --- | --- |
| `reference_node_id` | `114` |
| `text_only_workflow_path` | `ai/t2i/workflows/minimax_h3_t2v_api.json` 的绝对路径 |
| `generation_timeout` | `2400`，首次加载或内存换页时可适当增加 |
| `startup_args` | `--windows-standalone-build --reserve-vram 1.5 --disable-all-custom-nodes --disable-partner-nodes` |

启动端口自动从 API 地址读取。直接修改 `data/config/api.yaml` 后需要重新启动应用，让配置重新加载。

工作流路径必须是当前电脑上真实存在的 JSON 文件路径，不能照抄他人的 `C:/AI/...`。连接已经运行的本地或远程 ComfyUI 时，工作目录可以留空；只有希望由新世界启动 Windows portable 版时才填写 portable 根目录。使用其他安装方式时先手动启动服务。上面的启动参数适用于本指南的 H3 原生节点配置，自定义工作流需要的节点不应被禁用。

这里的 API 地址必须与第一步访问的地址一致。本地 H3 不需要 MiniMax 云端 API Key。LLM 用于设计提示词和标签，需要单独在新世界中配置；已有立绘的智能标注还需要可用的 Vision 服务。

## 3. 生成并保存立绘

保存角色并填写人物性格与设定后，在角色编辑页点击“立绘智能生成”。先选择一张现有立绘作为参考，将数量设为 1，生成提示词和标签，再点击“生成待处理立绘”。确认人物比例、表情和双手姿势符合预期后，再增加数量批量生成。有参考图时运行 H3 图生视频工作流；配置了 `text_only_workflow_path` 时，无参考图会自动使用文生视频工作流。当前自动提示词只描述动作、表情与道具，建议提供参考图传递人物外貌；没有参考图时无法保证与现有角色外观一致。T2I Manager 保持返回静态图片，ComfyUI 适配器会下载视频并自动提取中间帧。

自动设计的提示词只包含动作、表情与必要道具，不描述人物外貌、服装或画风。每张立绘保持站立、双脚着地，主要变化表情、手部与上半身动作，避免坐、跪、蹲、躺、跳跃或行走等姿态。每条提示词都明确描述面部表情，包含眉眼／视线和嘴形的变化，例如眉眼放松地微笑、眯眼抿嘴或扬眉微张嘴；表情也要写入生图 prompt，并与中文标签一致。这里描述的是动态表情，不包含五官固有长相或颜色。每条提示词也都说明左右手的姿势与位置，非主要动作的手要交代，双手相同时可用 both hands。模型根据人物性格设计英文动作，程序统一使用 `make the character stand and <面部表情、动作、双手姿势与位置>, full body, full scene, plain light, sprite`，例如 `make the character stand and smile warmly with relaxed eyebrows, wave the open right hand beside the head and rest the relaxed left hand at the side, full body, full scene, plain light, sprite`。需要道具时可写 `make the character stand and smile gently with relaxed eyes, hold a small sketchbook in the left hand at chest height and point to it with the right index finger, full body, full scene, plain light, sprite`。手动编辑的提示词按原文生成。

生成后展开卡片里的“从生成视频重新选帧”，拖动视频进度条，点击“使用 … 秒的画面”。这一步只读取已经生成的视频，不会重新调用模型。每次截帧都有独立结果，失败会保留上一张预览。勾选需要的立绘后添加到现有立绘集，提示词配对的标签会一起保存。

立绘标签统一以 2–3 个简短中文词语描述情绪、表情和动作，例如“开心，微笑，挥手”或“害羞，低头”。已有立绘的“智能标注”使用当前 Vision Adapter，只补充空白标签；MP4 会取中间帧送入视觉服务。模型输出不合格式时重试一次，仍不合格则保留空白并报告失败。

Vision Adapter 默认跟随 LLM 的配置与标注修复单独提交在 [PR #397](https://github.com/RachelForster/Shinsekai/pull/397)。

## 工作流与依赖细节

随附两个 API 格式工作流使用 480 × 832 竖向画布、107 帧、24 fps、8 步 Turbo LoRA，输出无声 MP4。需要本地已有对应 H3 主模型、Qwen 文本编码器、视频 VAE 和 Turbo LoRA；若文件名不同，请调整工作流中的模型名称。

H3 原生节点会直接将首帧拉伸到画布尺寸。适配器默认让 H3 画布匹配参考图比例，宽高按 32 像素对齐，总像素数和长边都不超过原工作流预算；再对参考图等比缩放，仅在剩余空隙补白。透明区域也会合成到白底，避免黑色边缘。这样保持人物比例，并减少因大面积补边造成的重新取景。例如 3:4 参考图在原 480×832 预算内使用 512×672 画布。

如果必须固定输出尺寸，可在扩展配置关闭 `match_reference_aspect`，此时只做等比缩放和补边。工作流同时连接其他首帧／尾帧时也会保留原画布，避免影响其他参考图。自定义工作流若用其他图像处理节点间接连接参考图，需自行保证最终画布比例；同一张图直连多个 H3 节点时，这些画布必须使用一致的整数尺寸。

默认开启“自动抠图”：生成的静态图、H3 自动提取的中间帧、重新选取的视频帧都会通过现有 `rembg` / `isnet-anime` 模型移除背景，输出保持原尺寸的透明 PNG。此步骤在本机 CPU 上执行，复用模型会话，不额外占用 H3 的 GPU 显存。关闭选项只影响后续生成或选帧；未抠图的结果仍可单独点击“移除背景”。预览使用棋盘格显示透明区域。

原始图片和视频保留在生成缓存内，不修改视频本身。抠图失败时保留原图并显示错误，点击“重新抠图”即可单独重试，不会再次运行 H3。确认满意后，再多选添加到角色立绘集，保存的是当前预览的 PNG 和标签。

首次使用抠图时会下载 `isnet-anime` 模型到 rembg 缓存目录；离线环境需预先下载模型。运行依赖 `rembg[cpu]` 包含 CPU 推理引擎，已有环境可以执行 `python -m pip install -r requirements-runtime-core.txt` 更新。之前已经被拉伸的视频无法仅靠换帧恢复人物比例，需要重新生成。

视频解码使用新增运行依赖 `av`（PyAV，提供 FFmpeg 解码能力），按时间定位并逐帧解码，不将整段视频读入系统内存。执行 `python -m pip install -r requirements-runtime-core.txt` 可安装。普通 SaveImage 工作流保持原有用法；SaveVideo 的 `images`、`videos` 或 `gifs` 历史输出均可识别，下载的源视频保存在立绘生成缓存中。

## 遇到问题时先检查哪一层

| 现象 | 检查方式 |
| --- | --- |
| ComfyUI 自己也不能生成、提示缺节点或模型 | 先按官方模板检查 ComfyUI 版本、模型目录和文件名；新世界不会补装这些依赖。 |
| 服务连接失败 | 确认 ComfyUI 仍在运行，API 地址和端口与浏览器访问的一致；连接已有服务不必填写启动目录。 |
| `Unsupported T2I adapter` | 适配器选择 `comfyui`，H3 模型名称写在工作流里。 |
| 提示词节点或输出节点不存在 | 附带工作流使用提示词 `131`、输出 `92`、参考图 `114`；自定义工作流按实际 ID 配置。 |
| 模型选项无效、找不到工作流文件 | 检查当前电脑的 JSON 绝对路径，以及 JSON 内模型名称是否与 ComfyUI 列出的文件一致。 |
| 能生成视频，但人物变窄 | 开启 `match_reference_aspect`；确认参考图未被其他节点再次拉伸。旧视频需要重新生成才能修正。 |
| 生成超时或显存不足 | 查看 ComfyUI 控制台，先单张测试；按模板降低分辨率或时长。首次加载较慢时增加 `generation_timeout`，勿连续重复提交。 |
| 立绘已有预览，但自动抠图失败 | 保留原图，检查 rembg 依赖及首次模型下载；用“重新抠图”重试，无需再次生成视频。 |

已经正常连接的其他 T2I 服务可以直接使用立绘生成。只有返回视频的工作流才提供选帧功能；普通图像工作流直接返回静态立绘。
