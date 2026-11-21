"""Backwards-compatible facade delegating package export/import to ``core/packaging``."""

from __future__ import annotations

import os
from pathlib import Path
import platform
import subprocess  # noqa: F401 - kept for legacy test monkeypatches
import tempfile
from typing import List

import yaml

from config.character_config import CharacterConfig
from config.schema import Background, Character, SELF_PERSONA_NAME, SELF_PERSONA_SPRITE_PREFIX
from core.packaging.background_package import (
    export_background_package,
    stage_background_package_import,
)
from core.packaging.character_package import (
    export_character_package,
    stage_character_package_import,
)
from core.packaging.zip_io import (
    resolve_name_conflict as _resolve_name_conflict,
    resolve_sprite_prefix_conflict as _resolve_sprite_prefix_conflict,
    rollback_staged_assets,
)

# Project base data path globals (tests monkeypatch these attributes directly).
BASE_DATA_PATH = Path("./data")
SPRITE_DIR = BASE_DATA_PATH / "sprite"
SPEECH_DIR = BASE_DATA_PATH / "speech"
MODEL_DIR = BASE_DATA_PATH / "models"
CONFIG_DIR = BASE_DATA_PATH / "config"
CHARACTERS_CONFIG_PATH = CONFIG_DIR / "characters.yaml"
BACKGROUND_CONFIG_PATH = CONFIG_DIR / "background.yaml"
BACKGROUND_UPLOAD_DIR = BASE_DATA_PATH / "backgrounds"
BGM_UPLOAD_DIR = BASE_DATA_PATH / "bgm"


def _open_export_folder(output_path: str | os.PathLike) -> bool:
    folder_path = Path(output_path).parent.resolve()
    try:
        system = platform.system()
        if system == "Windows":
            os.startfile(folder_path)  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.run(["open", str(folder_path)], check=True, timeout=10)
        elif system == "Linux":
            subprocess.run(["xdg-open", str(folder_path)], check=True, timeout=10)
        else:
            return False
        return True
    except Exception as exc:
        print(f"Failed to open export folder {folder_path}: {exc}")
        return False


def export_character(
    character_configs: list[CharacterConfig | Character],
    output_path: str,
    open_folder: bool = True,
) -> None:
    """Export character configs and media into a ``.cha`` / ``.char`` package."""
    export_character_package(
        character_configs,
        output_path,
        sprite_dir=Path(SPRITE_DIR),
        speech_dir=Path(SPEECH_DIR),
        model_dir=Path(MODEL_DIR),
    )
    if open_folder:
        _open_export_folder(output_path)
    print(f"人物成功导出到: {output_path}")


def import_character(input_path: str) -> list[CharacterConfig]:
    """Import a character package, resolve conflicts, and append to legacy YAML when used directly."""
    existing_names: set[str] = {SELF_PERSONA_NAME}
    existing_prefixes: set[str] = {SELF_PERSONA_SPRITE_PREFIX}
    existing_data: list[dict] = []
    if CHARACTERS_CONFIG_PATH.exists():
        with open(CHARACTERS_CONFIG_PATH, "r", encoding="utf-8") as handle:
            existing_data = yaml.safe_load(handle) or []
            for config in existing_data:
                if isinstance(config, dict):
                    if config.get("name"):
                        existing_names.add(str(config["name"]))
                    if config.get("sprite_prefix"):
                        existing_prefixes.add(str(config["sprite_prefix"]))

    staged = stage_character_package_import(
        input_path,
        existing_names=existing_names,
        existing_prefixes=existing_prefixes,
        sprite_dir=Path(SPRITE_DIR),
        speech_dir=Path(SPEECH_DIR),
        model_dir=Path(MODEL_DIR),
        cwd_base=Path.cwd(),
    )
    try:
        imported_configs = [CharacterConfig.parse_dic(dict(raw)) for raw in staged.raw_dicts]
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        latest_data: list[dict] = []
        if CHARACTERS_CONFIG_PATH.exists():
            with open(CHARACTERS_CONFIG_PATH, "r", encoding="utf-8") as handle:
                latest_data = yaml.safe_load(handle) or []
        latest_data.extend(dict(config.__dict__) for config in imported_configs)

        temp_config_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                delete=False,
                dir=CONFIG_DIR,
                encoding="utf-8",
                prefix="characters-",
                suffix=".yaml.tmp",
            ) as handle:
                temp_config_path = Path(handle.name)
                yaml.safe_dump(latest_data, handle, allow_unicode=True, sort_keys=False)
            os.replace(temp_config_path, CHARACTERS_CONFIG_PATH)
            temp_config_path = None
        finally:
            if temp_config_path is not None:
                temp_config_path.unlink(missing_ok=True)

        print(f"人物成功从 {input_path} 导入，并已将配置追加到 {CHARACTERS_CONFIG_PATH}。")
        return imported_configs
    except BaseException:
        rollback_staged_assets(staged.created_dirs)
        raise


def export_background(
    background_configs: List[Background],
    output_path: str = "./output/background.bg",
    open_folder: bool = True,
) -> None:
    """Export background configs and bundled media into a ``.bg`` package."""
    Path("./output").mkdir(exist_ok=True)
    export_background_package(
        background_configs,
        output_path,
        background_upload_dir=Path(BACKGROUND_UPLOAD_DIR),
        bgm_upload_dir=Path(BGM_UPLOAD_DIR),
    )
    if open_folder:
        _open_export_folder(output_path)
    print(f"背景包成功导出到: {output_path}")


def import_background(
    input_path: str,
    existing_configs: List[Background],
) -> List[Background]:
    """Import a ``.bg`` archive and return new ``Background`` models with conflict resolution."""
    staged = stage_background_package_import(
        input_path,
        existing_configs=existing_configs,
        background_upload_dir=Path(BACKGROUND_UPLOAD_DIR),
        bgm_upload_dir=Path(BGM_UPLOAD_DIR),
    )
    print(f"背景包成功从 {input_path} 导入。")
    return staged.backgrounds


__all__ = [
    "BACKGROUND_CONFIG_PATH",
    "BACKGROUND_UPLOAD_DIR",
    "BASE_DATA_PATH",
    "BGM_UPLOAD_DIR",
    "CHARACTERS_CONFIG_PATH",
    "CONFIG_DIR",
    "MODEL_DIR",
    "SPEECH_DIR",
    "SPRITE_DIR",
    "_open_export_folder",
    "_resolve_name_conflict",
    "_resolve_sprite_prefix_conflict",
    "export_background",
    "export_character",
    "import_background",
    "import_character",
]
