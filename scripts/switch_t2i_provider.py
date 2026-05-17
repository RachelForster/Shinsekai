import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from t2i.provider_switcher import API_CONFIG, switch_t2i_provider


def main() -> int:
    parser = argparse.ArgumentParser(description="Switch Shinsekai drawing provider.")
    parser.add_argument(
        "provider",
        choices=("local", "comfyui", "api", "openai-image"),
        help="local/comfyui for local ComfyUI; api/openai-image for remote image API",
    )
    args = parser.parse_args()

    provider = args.provider.lower()
    canonical = switch_t2i_provider(provider)
    if canonical == "comfyui":
        label = "local ComfyUI"
    else:
        label = "remote API image provider"
    print(f"Drawing provider switched to: {label}")
    print(f"Config: {API_CONFIG}")
    print("Restart the chat window for the running conversation to pick it up.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
