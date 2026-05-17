import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from t2i.provider_switcher import (
    API_CONFIG,
    list_t2i_api_profiles,
    switch_t2i_api_profile,
    switch_t2i_provider,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Switch Shinsekai drawing provider.")
    parser.add_argument(
        "provider",
        nargs="?",
        choices=("local", "comfyui", "api", "openai-image"),
        help="local/comfyui for local ComfyUI; api/openai-image for remote image API",
    )
    parser.add_argument(
        "--profile",
        default="",
        help="remote image API profile name to activate when provider is api/openai-image",
    )
    parser.add_argument(
        "--list-profiles",
        action="store_true",
        help="list saved remote image API profiles and exit",
    )
    args = parser.parse_args()

    if args.list_profiles:
        for name in list_t2i_api_profiles():
            print(name)
        return 0

    provider = (args.provider or "api").lower()
    if args.profile and provider in ("api", "openai-image"):
        switch_t2i_api_profile(args.profile)
        canonical = "openai-image"
    else:
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
