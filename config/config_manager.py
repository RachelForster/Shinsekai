"""Thin configuration manager facade delegating persistence to ``ConfigBackendPort`` or YAML."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import threading
import traceback
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from pydantic import ValidationError
import yaml

from config.backend_port import ConfigBackendPort
from config.feature_flags import FeatureFlagConfigManager
from config.llm_defaults import resolve_llm_base_url
from config.mirror_env import apply_mirror_environment
from config.network_proxy import apply_network_proxy_environment
from config.schema import (
    ApiConfig,
    AppConfig,
    Background,
    Character,
    Effect,
    SystemConfig,
    build_default_self_persona,
    is_self_persona_name,
)
from config.sprite_voice import normalize_sprite_voice_types
from config.tts_provider_config import (
    default_tts_work_path,
    normalize_tts_provider,
    tts_server_url_or_default,
)
from sdk.file_io import durable_mkdir, durable_rename


def character_name_key(name: str) -> str:
    """Return the case-insensitive identity key used for character lookup."""
    return name.lower()


def _normalize_root_key(project_root: str | os.PathLike[str] | None = None) -> str:
    raw = (
        os.fspath(project_root).strip()
        if project_root is not None
        else (
            os.environ.get("SHINSEKAI_PROJECT_ROOT", "").strip()
            or os.environ.get("EASYAI_PROJECT_ROOT", "").strip()
        )
    )
    candidate = Path(raw).expanduser() if raw else Path.cwd()
    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        resolved = candidate
    return os.path.normcase(str(resolved))


class ConfigManager:
    """
    配置管理器（薄兼容门面）：
    优先委托给通过 ``bind_backend()`` 注入的 ``ConfigBackendPort``（SQLite + DocumentStore），
    未绑定或单测覆写实例文件路径时自动回退至原子 YAML 读写。
    """

    _instance: Optional["ConfigManager"] = None
    _config: Optional[AppConfig] = None
    _characters_revision: str = ""

    _backends_lock = threading.RLock()
    _backends_by_root: Dict[str, ConfigBackendPort] = {}

    _API_CONFIG_PATH = Path("data/config/api.yaml")
    _CHARACTERS_CONFIG_PATH = Path("data/config/characters.yaml")
    _SYSTEM_CONFIG_PATH = Path("data/config/system_config.yaml")
    _BACKGOUND_CONFIG_PATH = Path("data/config/background.yaml")
    _EFFECT_CONFIG_PATH = Path("data/config/effect.yaml")
    _VERSION_PATH = Path("VERSION")

    _YAML_OVERRIDE_ATTRS = (
        "_API_CONFIG_PATH",
        "_CHARACTERS_CONFIG_PATH",
        "_SYSTEM_CONFIG_PATH",
        "_BACKGOUND_CONFIG_PATH",
        "_EFFECT_CONFIG_PATH",
    )

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_all_configs()
        return cls._instance

    @classmethod
    def bind_backend(
        cls,
        project_root: str | os.PathLike[str],
        backend: ConfigBackendPort,
    ) -> None:
        """Bind a unified storage backend for ``project_root``."""
        root_key = _normalize_root_key(project_root)
        with cls._backends_lock:
            cls._backends_by_root[root_key] = backend
            if cls._instance is not None and _normalize_root_key() == root_key:
                cls._instance._config = None

    @classmethod
    def unbind_backend(cls, project_root: str | os.PathLike[str]) -> None:
        """Remove a previously bound backend for ``project_root``."""
        root_key = _normalize_root_key(project_root)
        with cls._backends_lock:
            cls._backends_by_root.pop(root_key, None)

    def _has_custom_yaml_paths(self) -> bool:
        return any(attr in self.__dict__ for attr in self._YAML_OVERRIDE_ATTRS)

    @property
    def active_backend(self) -> ConfigBackendPort | None:
        """Return bound storage backend unless instance paths were overridden for YAML tests."""
        if self._has_custom_yaml_paths():
            return None
        direct = self.__dict__.get("_backend")
        if direct is not None:
            return direct
        root_key = _normalize_root_key()
        with self._backends_lock:
            return self._backends_by_root.get(root_key)

    @property
    def version(self) -> str:
        """读取项目根目录 VERSION 文件，缺失时返回占位字符串。"""
        candidates = [self._VERSION_PATH]
        frozen_root = getattr(sys, "_MEIPASS", None)
        if frozen_root:
            candidates.append(Path(frozen_root) / "VERSION")
        candidates.append(Path(sys.executable).resolve(strict=False).parent / "VERSION")
        seen: set[Path] = set()
        for candidate in candidates:
            try:
                path = candidate.resolve(strict=False)
            except OSError:
                path = candidate
            if path in seen:
                continue
            seen.add(path)
            try:
                text = path.read_text(encoding="utf-8").strip()
            except Exception:
                continue
            if text:
                return text
        return "unknown"

    @property
    def config(self) -> AppConfig:
        if self._config is None:
            self._load_all_configs()
            if self._config is None:
                raise RuntimeError("配置加载失败，无法访问配置数据。")
        return self._config

    @property
    def characters_revision(self) -> str:
        """Opaque catalog version, changed only after a save or changed reload."""
        backend = self.active_backend
        if backend is not None:
            return backend.characters_revision
        return self._characters_revision

    def _mark_characters_changed(self) -> None:
        self._characters_revision = uuid4().hex

    @property
    def feature_flags(self) -> FeatureFlagConfigManager:
        """Return the centralized flag view for the current system config."""
        return FeatureFlagConfigManager(self.config.system_config)

    # --- 内部加载/合并逻辑 ---
    def _load_yaml(self, file_path: Path) -> Dict[str, Any]:
        if not file_path.exists():
            print(f"警告：配置文件未找到：{file_path}")
            return {}
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                return yaml.safe_load(handle)
        except Exception as exc:
            raise IOError(f"加载配置文件 {file_path} 失败: {exc}")

    def _load_all_configs(self) -> None:
        backend = self.active_backend
        if backend is not None:
            api_config = backend.load_api_config()
            system_config = backend.load_system_config()
            character_list = backend.list_characters()
            background = backend.list_backgrounds()
            effect_list = backend.list_effects()
            self._config = AppConfig(
                api_config=api_config,
                system_config=system_config,
                characters=character_list,
                background_list=background,
                effect_list=effect_list,
            )
            self._characters_revision = backend.characters_revision
            apply_network_proxy_environment(system_config)
            apply_mirror_environment(system_config)
            return

        try:
            api_data = self._load_yaml(self._API_CONFIG_PATH)
            characters_data = self._load_yaml(self._CHARACTERS_CONFIG_PATH)
            system_data = self._load_yaml(self._SYSTEM_CONFIG_PATH)
            background_data = self._load_yaml(self._BACKGOUND_CONFIG_PATH)
            effect_data = self._load_yaml(self._EFFECT_CONFIG_PATH)

            api_config = ApiConfig.model_validate(api_data)
            system_config = SystemConfig.model_validate(system_data)

            if not isinstance(characters_data, list):
                characters_data = []
            if not isinstance(background_data, list):
                background_data = []
            if not isinstance(effect_data, list):
                effect_data = []

            character_list = [
                Character.model_validate(normalize_sprite_voice_types(item))
                for item in characters_data
            ]
            background = [Background.model_validate(item) for item in background_data]
            effect_list = [Effect.model_validate(item) for item in effect_data]

            previous_config = self._config
            self._config = AppConfig(
                api_config=api_config,
                system_config=system_config,
                characters=character_list,
                background_list=background,
                effect_list=effect_list,
            )
            if previous_config is None or previous_config.characters != character_list:
                self._mark_characters_changed()
            apply_network_proxy_environment(system_config)
            apply_mirror_environment(system_config)
            print("配置加载成功！")
        except ValidationError as exc:
            self._config = None
            traceback.print_exc()
            raise ValidationError(f"配置验证失败，请检查配置文件格式: \n {exc.json()}")
        except Exception as exc:
            self._config = None
            raise Exception(f"初始化配置管理器时发生错误: {exc}")

    # --- 公共刷新与保存方法 ---
    def reload(self) -> None:
        self._load_all_configs()

    def _with_updated_config(self, **updates: Any) -> None:
        current = self._config
        if current is None:
            self._load_all_configs()
            return
        model_copy = getattr(current, "model_copy", None)
        if callable(model_copy):
            self._config = model_copy(update=updates)
        else:
            for key, value in updates.items():
                setattr(current, key, value)

    def refresh_characters(self) -> None:
        """Reload only the character catalog without touching settings or other YAML files."""
        backend = self.active_backend
        if backend is not None:
            characters = backend.list_characters()
            if self._config is None:
                self._load_all_configs()
            else:
                self._with_updated_config(characters=characters)
            self._characters_revision = backend.characters_revision
            return

        characters_data = self._load_yaml(self._CHARACTERS_CONFIG_PATH)
        if not isinstance(characters_data, list):
            characters_data = []
        characters = [
            Character.model_validate(normalize_sprite_voice_types(item))
            for item in characters_data
        ]
        changed = self.config.characters != characters
        self._with_updated_config(characters=characters)
        if changed:
            self._mark_characters_changed()

    def refresh_backgrounds(self) -> None:
        """Reload only the background catalog."""
        backend = self.active_backend
        if backend is not None:
            backgrounds = backend.list_backgrounds()
            if self._config is None:
                self._load_all_configs()
            else:
                self._with_updated_config(background_list=backgrounds)
            return

        background_data = self._load_yaml(self._BACKGOUND_CONFIG_PATH)
        if not isinstance(background_data, list):
            background_data = []
        backgrounds = [Background.model_validate(item) for item in background_data]
        self._with_updated_config(background_list=backgrounds)

    def refresh_effects(self) -> None:
        """Reload only the effect catalog."""
        backend = self.active_backend
        if backend is not None:
            effects = backend.list_effects()
            if self._config is None:
                self._load_all_configs()
            else:
                self._with_updated_config(effect_list=effects)
            return

        effect_data = self._load_yaml(self._EFFECT_CONFIG_PATH)
        if not isinstance(effect_data, list):
            effect_data = []
        effects = [Effect.model_validate(item) for item in effect_data]
        self._with_updated_config(effect_list=effects)

    def refresh_media_catalogs(self) -> None:
        """Reload editable character/background assets without resetting runtime config."""
        backend = self.active_backend
        if backend is not None:
            characters = backend.list_characters()
            backgrounds = backend.list_backgrounds()
            self._with_updated_config(characters=characters, background_list=backgrounds)
            self._characters_revision = backend.characters_revision
            return

        characters_data = self._load_yaml(self._CHARACTERS_CONFIG_PATH)
        background_data = self._load_yaml(self._BACKGOUND_CONFIG_PATH)
        if not isinstance(characters_data, list):
            characters_data = []
        if not isinstance(background_data, list):
            background_data = []
        characters = [
            Character.model_validate(normalize_sprite_voice_types(item))
            for item in characters_data
        ]
        backgrounds = [Background.model_validate(item) for item in background_data]
        changed = self.config.characters != characters
        self._with_updated_config(characters=characters, background_list=backgrounds)
        if changed:
            self._mark_characters_changed()

    def save_api_config(self) -> None:
        if self._config is None:
            print("警告：配置未加载或加载失败，无法保存 API 配置。")
            return
        backend = self.active_backend
        if backend is not None:
            backend.save_api_config(self.config.api_config)
            return

        self._save_single_config(
            self._API_CONFIG_PATH,
            self.config.api_config.model_dump(mode="json", by_alias=True),
        )

    def save_system_config(self) -> None:
        if self._config is None:
            print("警告：配置未加载或加载失败，无法保存系统配置。")
            return
        backend = self.active_backend
        if backend is not None:
            backend.save_system_config(self.config.system_config)
        else:
            self._save_single_config(
                self._SYSTEM_CONFIG_PATH,
                self.config.system_config.model_dump(mode="json", by_alias=True),
            )
        apply_network_proxy_environment(self.config.system_config)
        apply_mirror_environment(self.config.system_config)

    def set_ui_language(self, code: str) -> None:
        if self._config is None:
            return
        from sdk.lang import normalize_lang

        sc = self.config.system_config.model_copy(deep=True)
        sc.ui_language = normalize_lang(code)
        self.config.system_config = sc
        self.save_system_config()

    def update_llm_info(self, llm_provider: str) -> tuple[str, str, str]:
        if self._config is None:
            raise RuntimeError("配置未加载，无法获取 LLM 信息。")
        api_config = self.config.api_config
        base_url = resolve_llm_base_url(api_config, llm_provider)
        llm_model = api_config.llm_model.get(llm_provider, "")
        api_key = api_config.llm_api_key.get(llm_provider, "")
        return base_url, llm_model, api_key

    def save_characters_config(self) -> None:
        if self._config is None:
            raise RuntimeError("配置未加载或加载失败，无法保存角色配置。")
        backend = self.active_backend
        if backend is not None:
            rev = backend.save_characters(self.config.characters)
            self._config.characters = backend.list_characters()
            self._characters_revision = rev
            return

        characters_data = [
            Character.model_validate(
                normalize_sprite_voice_types(char.model_dump(mode="python"))
            ).model_dump(mode="json", by_alias=True)
            for char in self.config.characters
        ]
        self._save_single_config(self._CHARACTERS_CONFIG_PATH, characters_data)
        self._mark_characters_changed()

    def save_background_config(self) -> None:
        if self._config is None:
            print("警告：配置未加载或加载失败，无法保存背景配置。")
            return
        backend = self.active_backend
        if backend is not None:
            backend.save_backgrounds(self.config.background_list)
            self._config.background_list = backend.list_backgrounds()
            return

        background_data = [
            Background.model_validate(bg.model_dump(mode="python")).model_dump(
                mode="json", by_alias=True
            )
            for bg in self.config.background_list
        ]
        self._save_single_config(self._BACKGOUND_CONFIG_PATH, background_data)

    def save_effect_config(self) -> None:
        if self._config is None:
            print("警告：配置未加载或加载失败，无法保存特效配置。")
            return
        backend = self.active_backend
        if backend is not None:
            backend.save_effects(self.config.effect_list)
            self._config.effect_list = backend.list_effects()
            return

        effect_data = [ef.model_dump(mode="json", by_alias=True) for ef in self.config.effect_list]
        self._save_single_config(self._EFFECT_CONFIG_PATH, effect_data)

    def _save_single_config(self, file_path: Path, data: Union[Dict, List]) -> None:
        """Atomically save YAML; callers must observe failures to roll back changes."""
        durable_mkdir(file_path.parent)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=file_path.parent,
                prefix=f".{file_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                yaml.dump(data, handle, Dumper=yaml.SafeDumper, allow_unicode=True, default_flow_style=False, sort_keys=False)
                handle.flush()
                os.fsync(handle.fileno())
            durable_rename(temporary_path, file_path, replace=True)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def get_background_by_name(self, name: str) -> Optional[Background]:
        for bg in self.config.background_list:
            if bg.name.lower() == name.lower():
                return bg
        return None

    def get_effect_by_name(self, name: str) -> Optional[Effect]:
        for ef in self.config.effect_list:
            if ef.name.lower() == name.lower():
                return ef
        return None

    def list_effects(self) -> tuple[Effect, ...]:
        """Return a stable read-only snapshot for application use cases."""
        return tuple(self.config.effect_list)

    def list_characters_catalog(self) -> List[Character]:
        """返回面向界面的完整人物目录（始终将内置「自设」槽位置顶，不破坏原始未保存列表）。"""
        self_char: Optional[Character] = None
        others: List[Character] = []
        for char in self.config.characters:
            if is_self_persona_name(char.name) and self_char is None:
                self_char = char
            else:
                others.append(char)
        if self_char is None:
            self_char = build_default_self_persona()
        return [self_char, *others]

    def ensure_self_persona_persisted(self) -> Character:
        """确保「自设」存在于内存 ``config.characters`` 首位，供编辑或立绘变更持久化使用。"""
        for idx, char in enumerate(self.config.characters):
            if is_self_persona_name(char.name):
                if idx != 0:
                    self.config.characters.pop(idx)
                    self.config.characters.insert(0, char)
                return char
        created = build_default_self_persona()
        self.config.characters.insert(0, created)
        return created

    def get_character_by_name(self, name: str) -> Optional[Character]:
        """根据角色名称获取角色配置实体"""
        name_key = character_name_key(name)
        for char in self.config.characters:
            if character_name_key(char.name) == name_key:
                return char
        if is_self_persona_name(name):
            return build_default_self_persona()
        return None

    def get_llm_api_config(self):
        llm_provider = self.config.api_config.llm_provider
        api_key = self.config.api_config.llm_api_key.get(llm_provider, "")
        model = self.config.api_config.llm_model.get(llm_provider, "")
        base_url = resolve_llm_base_url(self.config.api_config, llm_provider)
        return llm_provider, model, base_url, api_key

    def get_gpt_sovits_config(self):
        provider = normalize_tts_provider(self.config.api_config.tts_provider)
        return (
            tts_server_url_or_default(provider, self.config.api_config.gpt_sovits_url),
            default_tts_work_path(provider, self.config.api_config.gpt_sovits_api_path),
            provider,
        )

    def get_adapter_extra_config(self, kind: str, provider_key: str) -> Dict[str, Any]:
        """读取某类适配器在指定 provider/slug 下的扩展配置（扁平 dict）。"""
        pk = (provider_key or "").strip()
        if self._config is None:
            return {}
        ac = self.config.api_config
        kind_map = {
            "llm": ac.llm_extra_configs,
            "tts": ac.tts_extra_configs,
            "asr": ac.asr_extra_configs,
            "t2i": ac.t2i_extra_configs,
            "vision": ac.vision_extra_configs,
        }
        src = kind_map.get(kind)
        if src is None:
            return {}
        return dict((src or {}).get(pk, {}) or {})

    def set_adapter_extra_config(self, kind: str, provider_key: str, data: Dict[str, Any]) -> None:
        """写入扩展配置到内存中的 ApiConfig（需配合 save_api_config 持久化）。"""
        if self._config is None:
            return
        pk = (provider_key or "").strip()
        ac = self.config.api_config.model_copy(deep=True)
        attr_map = {
            "llm": "llm_extra_configs",
            "tts": "tts_extra_configs",
            "asr": "asr_extra_configs",
            "t2i": "t2i_extra_configs",
            "vision": "vision_extra_configs",
        }
        attr = attr_map.get(kind)
        if attr is None:
            return
        current = dict(getattr(ac, attr, None) or {})
        current[pk] = dict(data)
        setattr(ac, attr, current)
        self.config.api_config = ac

    def merged_llm_factory_kwargs(self, llm_provider: str, base_kwargs: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(base_kwargs)
        out.update(self.get_adapter_extra_config("llm", llm_provider))
        return out

    def merged_tts_factory_kwargs(self, adapter_name: str, base_kwargs: Dict[str, Any]) -> Dict[str, Any]:
        slug = (adapter_name or "").strip().lower()
        out = dict(base_kwargs)
        out.update(self.get_adapter_extra_config("tts", slug))
        return out

    def merged_t2i_factory_kwargs(self, adapter_name: str, base_kwargs: Dict[str, Any]) -> Dict[str, Any]:
        name = (adapter_name or "").strip().lower()
        out = dict(base_kwargs)
        out.update(self.get_adapter_extra_config("t2i", name))
        return out

    def get_base_font_size(self) -> int:
        return self.config.system_config.base_font_size_px

    def save_music_cover_config(
        self,
        work_dir: str,
        yt_dlp_exe: str,
        ffmpeg_exe: str,
        uvr_cmd_template: str,
        rvc_cmd_template: str,
        rvc_model_path: str,
        rvc_index_path: str,
        rvc_device: str,
        rvc_model_version: str,
        rvc_f0_method: str,
        rvc_pitch: float,
        rvc_index_rate: float,
        rvc_filter_radius: int,
        rvc_resample_sr: int,
        rvc_rms_mix_rate: float,
        rvc_protect: float,
    ) -> str:
        """保存音乐翻唱流水线相关系统配置。"""
        if self._config is None:
            return "错误：配置未加载，无法保存。"
        sc = self.config.system_config.model_copy(deep=True)
        sc.music_cover_work_dir = work_dir or "./data/music_cover"
        sc.music_cover_yt_dlp_exe = yt_dlp_exe or ""
        sc.music_cover_ffmpeg_exe = ffmpeg_exe or ""
        sc.music_cover_uvr_cmd_template = uvr_cmd_template or ""
        sc.music_cover_rvc_cmd_template = rvc_cmd_template or ""
        sc.music_cover_rvc_model_path = rvc_model_path or ""
        sc.music_cover_rvc_index_path = rvc_index_path or ""
        sc.music_cover_rvc_device = rvc_device or "cuda:0"
        sc.music_cover_rvc_model_version = rvc_model_version or "v2"
        sc.music_cover_rvc_f0_method = rvc_f0_method or "rmvpe"
        sc.music_cover_rvc_pitch = float(rvc_pitch)
        sc.music_cover_rvc_index_rate = float(rvc_index_rate)
        sc.music_cover_rvc_filter_radius = int(rvc_filter_radius)
        sc.music_cover_rvc_resample_sr = int(rvc_resample_sr)
        sc.music_cover_rvc_rms_mix_rate = float(rvc_rms_mix_rate)
        sc.music_cover_rvc_protect = float(rvc_protect)
        self.config.system_config = sc
        self.save_system_config()
        return "音乐翻唱配置已保存。"
