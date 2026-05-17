from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = "_temp"
BACKGROUND = "弹丸论破"


def _find_gpt_sovits_root() -> Path | None:
    bundle_root = ROOT / "data" / "tts_bundles" / "installed" / "gpt_sovits_v2pro"
    candidates = [
        bundle_root / "GPT-SoVITS-v2pro-20250604",
        bundle_root,
    ]
    candidates.extend(p for p in bundle_root.glob("GPT-SoVITS*") if p.is_dir())
    for candidate in candidates:
        if (
            (candidate / "api_v2.py").exists()
            and (candidate / "runtime" / "python.exe").exists()
        ):
            return candidate
    return None


def _load_yaml(path: Path, default):
    if not path.exists():
        return default
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if data is not None else default


def _save_yaml(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def repair_known_config_pitfalls(tts_provider: str) -> None:
    api_path = ROOT / "data" / "config" / "api.yaml"
    api = _load_yaml(api_path, {})
    if api:
        base_url = str(api.get("llm_base_url") or "").rstrip("/")
        if base_url == "https://api.ikuncode.cc":
            api["llm_base_url"] = "https://api.ikuncode.cc/v1"
        if tts_provider == "genie-tts":
            genie_root = (
                ROOT
                / "data"
                / "tts_bundles"
                / "installed"
                / "genie_tts_server"
                / "Genie-TTS Server"
            )
            if (genie_root / "start.py").exists():
                api["gpt_sovits_api_path"] = str(genie_root)
                api["gpt_sovits_url"] = "http://127.0.0.1:9880"
        elif tts_provider == "gpt-sovits":
            gpt_root = _find_gpt_sovits_root()
            if gpt_root is not None:
                api["gpt_sovits_api_path"] = str(gpt_root)
                api["gpt_sovits_url"] = "http://127.0.0.1:9880"
        api["tts_provider"] = tts_provider
        _save_yaml(api_path, api)

    chars_path = ROOT / "data" / "config" / "characters.yaml"
    chars = _load_yaml(chars_path, [])
    if isinstance(chars, list) and chars:
        first = chars[0]
        source = chars[1] if len(chars) > 1 and isinstance(chars[1], dict) else {}
        if isinstance(first, dict):
            if float(first.get("speech_volume") or 0) <= 0:
                first["speech_volume"] = 1.0
            if not first.get("speech_speed"):
                first["speech_speed"] = 1.0
            for key in (
                "gpt_model_path",
                "sovits_model_path",
                "refer_audio_path",
                "prompt_text",
                "prompt_lang",
            ):
                if not first.get(key) and source.get(key):
                    first[key] = source[key]
            _save_yaml(chars_path, chars)


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch Shinsekai chat with stable defaults.")
    parser.add_argument("--check", action="store_true", help="repair config and print launch command only")
    parser.add_argument(
        "--tts",
        default=os.environ.get("SHINSEKAI_TTS_PROVIDER", "none"),
        help="TTS provider to force before launch; default: none",
    )
    parser.add_argument(
        "--t2i",
        default=os.environ.get("SHINSEKAI_T2I_PROVIDER", ""),
        help="T2I provider to enable before launch; default: disabled",
    )
    args = parser.parse_args()

    os.chdir(ROOT)
    tts_provider = (args.tts or "none").strip().lower()
    t2i_provider = (args.t2i or "").strip()
    repair_known_config_pitfalls(tts_provider)

    template_path = ROOT / "data" / "character_templates" / f"{TEMPLATE}.txt"
    if not template_path.exists():
        print(f"Missing template: {template_path}")
        print("Open Settings, generate and save a chat template first.")
        return 2

    cmd = [
        sys.executable,
        str(ROOT / "main.py"),
        "--template",
        TEMPLATE,
        "--tts",
        tts_provider,
        "--bg",
        BACKGROUND,
        "--t2i",
        t2i_provider,
    ]

    print("Launching Shinsekai chat:")
    print(" ".join(f'"{x}"' if " " in x else x for x in cmd))
    if args.check:
        return 0

    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "one_click_chat.log"
    with log_path.open("a", encoding="utf-8") as log:
        log.write("\n" + "=" * 80 + "\n")
        log.write(f"launch_time={datetime.now().isoformat(timespec='seconds')}\n")
        log.write("cmd=" + " ".join(cmd) + "\n")
        log.flush()
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
    print(f"Log: {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
