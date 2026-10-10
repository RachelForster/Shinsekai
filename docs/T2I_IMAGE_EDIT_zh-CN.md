# T2I 参考图与 Qwen-Image-2.1

T2I 适配器同时用于文生图和图片编辑。参考图是**有顺序的本地文件路径数组**，不是 URL 或 base64。

```python
adapter.generate_image(
    prompt="保持人物外观与服装，把姿势改为抱臂站立",
    file_path="output.png",
    reference_images=["character.png", "outfit.png"],
)

manager.t2i(prompt="一座山间小屋", reference_images=[])  # 文生图
manager.queue_generation(prompt="修改姿势", reference_images=["character.png"])
```

`reference_images=None` 或 `[]` 保留原来的文生图行为。队列会保存参考图数组的副本。不能编辑图片的后端应明确拒绝参考图，不能悄悄丢弃；现有 Stable Diffusion txt2img 适配器会报出不支持的原因。

## 配置本地 Qwen

在「AI 服务 → 图像生成」选择 `Qwen-Image-2.1（本地）`。它使用官方的统一生成/编辑模型 `Qwen/Qwen-Image-2.1`，最多接受 10 张参考图，PNG 输出保留模型原生 RGBA。参见[官方模型说明](https://huggingface.co/Qwen/Qwen-Image-2.1)。

推理在独立 Python 进程运行。应用主环境使用 Transformers 4，Qwen 使用 Transformers 5，因此 **Qwen 依赖应安装在独立环境中**。先在该环境安装适配显卡的 CUDA PyTorch，再安装：

```powershell
& '你的Qwen环境/python.exe' -m pip install -r ai/t2i/requirements-qwen-image21.txt
```

扩展配置复用现有 `t2i_extra_configs`：

```json
{
  "t2i_provider": "qwen-image-2.1",
  "t2i_extra_configs": {
    "qwen-image-2.1": {
      "python_executable": "C:/path/to/qwen-env/python.exe",
      "dependency_path": "",
      "model_path": "",
      "transformer_bits": 8,
      "resolution": 768,
      "steps": 40,
      "seed": 42,
      "timeout_seconds": 1800
    }
  }
}
```

- `python_executable`：推理环境的 Python 路径；空值使用现有运行时 Python，仍需具备 Qwen 依赖。
- `dependency_path`：可选的独立 site-packages 目录，只有子进程会加入此目录。可复用已经测试过的依赖覆盖目录。
- `model_path`：已有官方模型完整目录。空值使用共享 Hugging Face 缓存；页面下载按钮复用现有模型下载、凭据和任务进度模块，约 33 GB。运行时只读取本地权重，不会隐式下载。
- `transformer_bits`：4 或 8。视觉/文本编码器使用 NF4，扩散 Transformer 使用所选量化，VAE 使用 BF16。
- `resolution`：默认 768，控制输出像素面积和参考图编码尺寸。通用编辑调用默认沿用最后一张参考图的宽高比；立绘工具指定第一张主参考图为画幅依据，避免补充细节图改变构图。单次调用可用 `reference_canvas_index`（从 0 开始）指定参考图，显式的 `width`、`height` 优先。
- `seed=-1`：每次随机种子；其余值用于复现。单次调用可覆盖 `steps`、`seed`、`resolution`、`width`、`height`。

模型在请求时加载，编码器与扩散模型分阶段使用 GPU，解码前将扩散模型移至 CPU。请求结束后子进程退出并释放显存。跨进程文件锁避免聊天 CG 与立绘工具同时运行 Qwen；适配器关闭或超时会终止它拥有的子进程。进度回调 `on_progress(fraction, message)` 会报告加载、编码、采样步数和解码。

此路径已在 RTX 5080 16 GB 上用 768 分辨率、8 bit Transformer、40 步验证；参考图数量与输出尺寸会改变资源占用。

## 立绘工具与 HTTP

立绘工具可添加、移除参考图，并选择「已配置的 T2I」或 Gemini。Qwen 生成立绘时会追加透明背景指令，清理近零 alpha 的杂色像素。「生成立绘提示词」使用 AI 服务中当前配置的 LLM Adapter，复用其供应商、模型、地址、凭据及扩展配置；也可手动填写提示词。提示词的 LLM 与图片生成服务各按自己的配置使用。

POST `/api/tools/sprite-prompts` 接受 `characterName` 和 `count`（1–100），读取该已保存人物的设定，并通过独立的一次 LLM 请求编写指定数量的姿势与表情提示词。结果保持 `{ "prompts": ["..."] }`，沿用后台任务与进度。LLM 未配置、请求失败、输出为空、格式错误或数量不符时，任务失败并显示具体错误。

### 保持人物一致性

每次将原始立绘放在参考图数组的第一位，其余图片仅补充细节或提供本次明确要转移的素材。批量生成中的每张图都使用同一组原始参考图，不串联上一张生成结果。立绘服务会为手写、LLM 和 Agent 提示词统一补充保留人物身份、发型、服装、配饰、身体比例与画风的编辑要求；明确要求修改的属性例外。Qwen 多图调用使用 `<image1>` 等标签区分主图与补充素材，画幅也以第一张主图为准；单图使用自然语言引用。

自动提示词只编写具体的动作和表情，不按人物设定重新描述长相。这个 LLM 请求没有读取参考图，因此不能把它当成外观分析。提示词中已有的冒号和保留要求会完整传给生成服务；结构化 `prompts` 数组不剥离内容，兼容的多行字符串仅去掉 `Sprite 1:`、`立绘 1：`、`立ち絵 1：` 这样的编号标签。

这符合 [Qwen 官方提示词改写指导](https://huggingface.co/Qwen/Qwen-Image-2.1-PE-I2I/blob/main/system_prompt.txt)：描述要修改的属性，用参考图保留未修改的内容，避免文字重述外貌引起重新生成。提示词约束不能保证像素级一致，生成后仍需检查脸、发型、服装和手脚；不合格的图片保留为待筛选结果，不自动替换原始立绘。

### 预览、重生成与标签

桌面预览区独立占据一整行，默认每排 4 张卡片；窄屏调整为 2 列或 1 列。每张图片上方的「重新生成」仅提交该卡片的原始参考图、图像服务和提示词，并使用新种子。成功后只更新该卡片和标签，失败时保留原图；Qwen 与 Gemini 均使用唯一输出文件名，避免覆盖已有图片。

桌面默认启用 `autoLabel=true`，生成结束、释放图像服务资源后，复用现有视觉服务与人物立绘智能标注指令识别实际图片。HTTP 旧客户端省略该字段时不自动标注。结果中的 `labels` 字符串数组与 `files` 一一对应，`labelErrors` 包含失败图片的 `index` 和 `message`；视觉服务未就绪或单张标注失败时，图片仍成功交付，缺失标签为空并显示错误。标签可手动修改，导入时通过已有 POST `/api/characters/sprites/upload` 的可选 `spriteTags` 数组与图片一起保存，仅追加本次新立绘的标签。已经导入的卡片不会重复导入，重新生成后的新版本可再次追加。

生成 HTTP API 的可选 `seed` 是 -1 或无符号 32 位整数，-1 在宿主生成随机种子，配置 T2I 后端可接收该值；未传时沿用后端配置。Gemini 沿用自己的采样行为。

```http
POST /api/tools/sprites/generate
Content-Type: application/json

{
  "characterName": "Rafal",
  "provider": "configured",
  "referenceImages": ["C:/sprites/character.png", "C:/sprites/outfit.png"],
  "prompts": ["保持人物外观与服装，把姿势改为抱臂站立"],
  "outputDir": "C:/sprites/generated"
}
```

该接口沿用后台任务与任务进度轮询。`provider="configured"` 使用保存的 T2I 配置；`provider="gemini"` 使用原有 Gemini 生成器。省略 `provider` 的旧客户端继续使用 Gemini。旧的单张 `referenceImage` 字段仍兼容；新客户端应传 `referenceImages`（1–10 张）。所有参考图仍经过 Bridge 本地文件访问检查。T2I 生成结果使用新的文件名，Qwen 也会拒绝覆盖参考图。

ComfyUI 使用同一个参考图接口：先上传每张参考图，再按顺序写入工作流的图像输入节点。可在扩展配置 `reference_image_node_ids` 填写逗号分隔的节点 ID；为空时使用工作流中的 `LoadImage` 节点顺序。工作流必须有足够的图像输入节点，并实际把它们连入编辑模型。
