# 使用 MiniMax H3 生成静态立绘

在角色编辑页点击“立绘智能生成”，设计提示词和标签，再生成立绘。有参考图时运行 H3 图生视频工作流；无参考图时自动使用文生视频工作流。T2I Manager 保持返回静态图片，ComfyUI 适配器会下载视频并自动提取中间帧。

自动设计的提示词只包含动作、表情与必要道具，不描述人物外貌、服装或画风。每张立绘保持站立、双脚着地，主要变化表情、手部与上半身动作，避免坐、跪、蹲、躺、跳跃或行走等姿态。每条提示词都明确描述面部表情，包含眉眼／视线和嘴形的变化，例如眉眼放松地微笑、眯眼抿嘴或扬眉微张嘴；表情也要写入生图 prompt，并与中文标签一致。这里描述的是动态表情，不包含五官固有长相或颜色。每条提示词也都说明左右手的姿势与位置，非主要动作的手要交代，双手相同时可用 both hands。模型根据人物性格设计英文动作，程序统一使用 `make the character stand and <面部表情、动作、双手姿势与位置>, full body, full scene, plain light, sprite`，例如 `make the character stand and smile warmly with relaxed eyebrows, wave the open right hand beside the head and rest the relaxed left hand at the side, full body, full scene, plain light, sprite`。需要道具时可写 `make the character stand and smile gently with relaxed eyes, hold a small sketchbook in the left hand at chest height and point to it with the right index finger, full body, full scene, plain light, sprite`。手动编辑的提示词按原文生成。

生成后展开卡片里的“从生成视频重新选帧”，拖动视频进度条，点击“使用 … 秒的画面”。这一步只读取已经生成的视频，不会重新调用模型。每次截帧都有独立结果，失败会保留上一张预览。勾选需要的立绘后添加到现有立绘集，提示词配对的标签会一起保存。

立绘标签统一以 2–3 个简短中文词语描述情绪、表情和动作，例如“开心，微笑，挥手”或“害羞，低头”。已有立绘的“智能标注”使用当前 Vision Adapter，只补充空白标签；MP4 会取中间帧送入视觉服务。模型输出不合格式时重试一次，仍不合格则保留空白并报告失败。

Vision Adapter 默认跟随 LLM 的配置与标注修复单独提交在 [PR #397](https://github.com/RachelForster/Shinsekai/pull/397)。

## 本地配置

API 设置 → 图像生成服务选择 `comfyui`：

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

## 工作流与依赖

随附两个 API 格式工作流使用 480 × 832 竖向画布、107 帧、24 fps、8 步 Turbo LoRA，输出无声 MP4。需要本地已有对应 H3 主模型、Qwen 文本编码器、视频 VAE 和 Turbo LoRA；若文件名不同，请调整工作流中的模型名称。

H3 原生节点会直接将首帧拉伸到画布尺寸。适配器默认让 H3 画布匹配参考图比例，宽高按 32 像素对齐，总像素数和长边都不超过原工作流预算；再对参考图等比缩放，仅在剩余空隙补白。透明区域也会合成到白底，避免黑色边缘。这样保持人物比例，并减少因大面积补边造成的重新取景。例如 3:4 参考图在原 480×832 预算内使用 512×672 画布。

如果必须固定输出尺寸，可在扩展配置关闭 `match_reference_aspect`，此时只做等比缩放和补边。工作流同时连接其他首帧／尾帧时也会保留原画布，避免影响其他参考图。自定义工作流若用其他图像处理节点间接连接参考图，需自行保证最终画布比例；同一张图直连多个 H3 节点时，这些画布必须使用一致的整数尺寸。

默认开启“自动抠图”：生成的静态图、H3 自动提取的中间帧、重新选取的视频帧都会通过现有 `rembg` / `isnet-anime` 模型移除背景，输出保持原尺寸的透明 PNG。此步骤在本机 CPU 上执行，复用模型会话，不额外占用 H3 的 GPU 显存。关闭选项只影响后续生成或选帧；未抠图的结果仍可单独点击“移除背景”。预览使用棋盘格显示透明区域。

原始图片和视频保留在生成缓存内，不修改视频本身。抠图失败时保留原图并显示错误，点击“重新抠图”即可单独重试，不会再次运行 H3。确认满意后，再多选添加到角色立绘集，保存的是当前预览的 PNG 和标签。

首次使用抠图时会下载 `isnet-anime` 模型到 rembg 缓存目录；离线环境需预先下载模型。运行依赖 `rembg[cpu]` 包含 CPU 推理引擎，已有环境可以执行 `python -m pip install -r requirements-runtime-core.txt` 更新。之前已经被拉伸的视频无法仅靠换帧恢复人物比例，需要重新生成。

视频解码使用新增运行依赖 `av`（PyAV，提供 FFmpeg 解码能力），按时间定位并逐帧解码，不将整段视频读入系统内存。执行 `python -m pip install -r requirements-runtime-core.txt` 可安装。普通 SaveImage 工作流保持原有用法；SaveVideo 的 `images`、`videos` 或 `gifs` 历史输出均可识别，下载的源视频保存在立绘生成缓存中。
