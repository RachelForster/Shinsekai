#!/usr/bin/env python3
"""读取 assets/present_example.png，用 Moondream 本地推理回答 what's on the screen。

依赖：plugins/moondream_vision/requirements.txt（torch、transformers、PIL 等）。
首次运行会下载 vikhyatk/moondream2 权重，耗时较长。

用法（在仓库根目录）::
    python test/test_moondream_present_example.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Windows 控制台默认编码易导致中文乱码；调试时请配合 PYTHONUTF8=1 或使用本脚本写入的 UTF-8 结果文件。
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from plugins.moondream_vision.config_model import MoondreamVisionConfig
from plugins.moondream_vision.local_infer import infer_screen_png


def main() -> None:
    image_path = _ROOT / "assets" / "present_example.png"
    if not image_path.is_file():
        print(f"缺少测试图片: {image_path}", file=sys.stderr)
        sys.exit(1)

    png = image_path.read_bytes()
    cfg = MoondreamVisionConfig()
    cfg.clamp()
    question = "what's on the screen"

    print(f"图片: {image_path}")
    print(f"问题: {question!r}")
    print("推理中（首次可能下载模型，请稍候）…")

    answer = infer_screen_png(png, question, cfg)
    out_txt = Path(__file__).resolve().parent / "moondream_present_example_answer.txt"
    out_txt.write_text(answer, encoding="utf-8")
    print(f"完整回答已写入: {out_txt}（长度 {len(answer)} 字符）")
    print("--- 模型回答（前 500 字符预览）---")
    preview = answer[:500] + ("…" if len(answer) > 500 else "")
    print(preview)


if __name__ == "__main__":
    main()
