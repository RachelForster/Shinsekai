"""Run with the GPU Python that should handle ToonOut: python -m tools.setup_toonout."""

import json
import argparse
import importlib
import sys

from core.media.toonout_assets import install_assets, model_directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--comfyui-url",
        default="",
        help="Optional local ComfyUI whose idle cache may be released before matting",
    )
    args = parser.parse_args()
    directory = model_directory()
    sys.path.insert(0, str(directory / "deps"))
    try:
        import torch

        for name in ("torchvision", "timm", "kornia", "transformers", "einops"):
            importlib.import_module(name)
    except ImportError as exc:
        raise SystemExit(
            f"Missing ToonOut dependency: {exc}. Install requirements-toonout.txt in this Python first."
        ) from exc
    install_assets(directory)
    runtime = directory / "runtime.json"
    temporary = runtime.with_suffix(".json.part")
    temporary.write_text(
        json.dumps(
            {"python": sys.executable, "comfyui_url": args.comfyui_url}, indent=2
        ),
        encoding="utf-8",
    )
    temporary.replace(runtime)
    print(
        f"ToonOut ready: {directory}\nPython: {sys.executable}\nCUDA: {torch.cuda.is_available()}"
    )


if __name__ == "__main__":
    main()
