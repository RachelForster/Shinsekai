import os
import threading
import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
from pydantic import ValidationError
from config.schema import (
    AppConfig,
    Character,
    ApiConfig,
    SystemConfig,
    Background,
    Effect,
    clamp_compact_target_ratio,
)
from config.tts_provider_config import (
    default_tts_work_path,
    is_http_url,
    normalize_tts_provider,
    requires_tts_work_path,
    tts_server_url_or_default,
    uses_shared_tts_server_config,
)
from config.api_path_validation import validate_t2i_paths_for_save
from config.llm_defaults import LLM_BASE_URLS
from config.mirror_env import apply_mirror_environment
from config.network_proxy import apply_network_proxy_environment
from config.sprite_voice import normalize_sprite_voice_types
import traceback
from sdk.path_contract import (
    project_root,
    resolve_managed_project_path,
    resolve_project_path,
    resolve_runtime_asset_read_path,
    validate_exact_path_text,
)
from sdk.file_transactions import atomic_write_text, read_text_without_links
from sdk.path_references import (
    make_path_reference,
    normalize_project_relative_path,
)


_CONFIG_WRITE_LOCK = threading.RLock()
_PATH_CONTRACT_VERSION = 1


def _migrate_legacy_dot_relative_path(raw: str) -> str:
    """Canonicalize the one relative alias emitted by pre-contract releases.

    Older PyQt/early React defaults were persisted as ``./data/...`` (and the
    Windows spelling ``.\\data\\...``).  Runtime resolvers deliberately reject
    lexical aliases now, so accept exactly one historical leading ``./`` only
    while loading a known configuration path and immediately save the
    canonical portable value.  Nested aliases and traversal remain invalid.
    """

    portable = raw.replace("\\", "/")
    if not portable.startswith("./"):
        return raw
    normalized = normalize_project_relative_path(portable[2:])
    if normalized is None:
        raise ValueError("legacy project path contains lexical path aliases")
    return normalized


def _migrate_legacy_duplicated_storage_path(raw: str) -> str:
    """Collapse the exact duplicated storage prefix emitted by an old UI.

    A migration-era join bug persisted values such as
    ``data/sprite/mika/sprite/mika/idle.png``.  Runtime file serving used to
    guess several alternative targets on every request, which let a displayed
    path name one file while the bridge served another.  Recognize only that
    documented repeated ``<family>/<owner>`` shape here so the corrected value
    is saved once with the rest of the configuration migration.
    """

    parts = raw.split("/")
    managed_families = {"backgrounds", "bgm", "effects", "speech", "sprite"}
    if (
        len(parts) >= 6
        and parts[0] == "data"
        and parts[1] in managed_families
        and parts[2]
        and parts[3] == parts[1]
        and parts[4] == parts[2]
    ):
        return "/".join(parts[:3] + parts[5:])
    return raw


def _migrate_path_value(
    mapping: dict[str, Any],
    key: str,
    root: Path,
    *legacy_prefixes: tuple[str, ...],
    resource_prefixes: tuple[tuple[str, ...], ...] = (),
    recover_legacy_absolute: bool = True,
) -> bool:
    """Normalize one persisted path and report whether storage changed."""

    raw_value = mapping.get(key)
    if raw_value is None:
        return False
    raw = str(raw_value)
    if not raw:
        return False
    migrated_raw = _migrate_legacy_dot_relative_path(raw)
    reference = make_path_reference(
        migrated_raw,
        root,
        legacy_project_prefixes=legacy_prefixes,
        resource_prefixes=resource_prefixes,
        recover_legacy_absolute=recover_legacy_absolute,
    )
    if reference is None:
        return False
    normalized = _migrate_legacy_duplicated_storage_path(reference["path"])
    mapping[key] = normalized
    return normalized != raw


def _migrate_config_asset_paths(
    *,
    root: Path,
    api_data: Any,
    characters_data: Any,
    system_data: Any,
    background_data: Any,
    effect_data: Any,
    recover_legacy_absolute: bool = True,
) -> set[str]:
    """Rebase stale pre-migration managed paths before model validation."""

    changed: set[str] = set()
    if isinstance(characters_data, list):
        for character in characters_data:
            if not isinstance(character, dict):
                continue
            for field in ("gpt_model_path", "sovits_model_path", "refer_audio_path"):
                if _migrate_path_value(
                    character,
                    field,
                    root,
                    ("data", "models"),
                    ("data", "speech"),
                    resource_prefixes=(
                        (("assets", "system", "sound"),)
                        if field == "refer_audio_path"
                        else ()
                    ),
                    recover_legacy_absolute=recover_legacy_absolute,
                ):
                    changed.add("characters")
            for sprite in character.get("sprites") or []:
                if not isinstance(sprite, dict):
                    continue
                if _migrate_path_value(
                    sprite,
                    "path",
                    root,
                    ("data", "sprite"),
                    resource_prefixes=(
                        ("assets", "present_example.png"),
                        ("assets", "system", "picture"),
                    ),
                    recover_legacy_absolute=recover_legacy_absolute,
                ):
                    changed.add("characters")
                if _migrate_path_value(
                    sprite,
                    "voice_path",
                    root,
                    ("data", "speech"),
                    resource_prefixes=(("assets", "system", "sound"),),
                    recover_legacy_absolute=recover_legacy_absolute,
                ):
                    changed.add("characters")

    if isinstance(background_data, list):
        for background in background_data:
            if not isinstance(background, dict):
                continue
            for sprite in background.get("sprites") or []:
                if isinstance(sprite, dict) and _migrate_path_value(
                    sprite,
                    "path",
                    root,
                    ("data", "backgrounds"),
                    resource_prefixes=(("assets", "system", "picture"),),
                    recover_legacy_absolute=recover_legacy_absolute,
                ):
                    changed.add("background")
            bgm_list = background.get("bgm_list")
            if isinstance(bgm_list, list):
                for index, value in enumerate(bgm_list):
                    holder = {"path": value}
                    if _migrate_path_value(
                        holder,
                        "path",
                        root,
                        ("data", "bgm"),
                        resource_prefixes=(("assets", "system", "sound"),),
                        recover_legacy_absolute=recover_legacy_absolute,
                    ):
                        changed.add("background")
                    bgm_list[index] = holder["path"]

    if isinstance(effect_data, list):
        for effect in effect_data:
            if not isinstance(effect, dict):
                continue
            audio_list = effect.get("audio_list")
            if not isinstance(audio_list, list):
                continue
            for index, value in enumerate(audio_list):
                holder = {"path": value}
                if _migrate_path_value(
                    holder,
                    "path",
                    root,
                    ("data", "effects"),
                    resource_prefixes=(("assets", "system", "sound"),),
                    recover_legacy_absolute=recover_legacy_absolute,
                ):
                    changed.add("effect")
                audio_list[index] = holder["path"]

    if isinstance(system_data, dict):
        system_path_prefixes = {
            "background_path": (("data", "backgrounds"),),
            "bgm_path": (("data", "bgm"),),
            "chat_ui_theme_path": (
                ("data", "chat_ui_themes"),
                ("data", "chat_ui_theme.json"),
            ),
            "huggingface_cache_dir": (("data", "cache"),),
            "music_cover_work_dir": (("data", "music_cover"),),
            "music_cover_yt_dlp_exe": (),
            "music_cover_ffmpeg_exe": (),
            "music_cover_rvc_model_path": (("data", "models"), ("data", "music_cover")),
            "music_cover_rvc_index_path": (("data", "models"), ("data", "music_cover")),
            "asr_whisper_model_size": (("data", "models"), ("data", "cache")),
        }
        system_resource_prefixes = {
            "background_path": (("assets", "system", "picture"),),
            "bgm_path": (("assets", "system", "sound"),),
        }
        for field, prefixes in system_path_prefixes.items():
            if _migrate_path_value(
                system_data,
                field,
                root,
                *prefixes,
                resource_prefixes=system_resource_prefixes.get(field, ()),
                recover_legacy_absolute=recover_legacy_absolute,
            ):
                changed.add("system")

    if isinstance(api_data, dict):
        api_path_prefixes = {
            "gpt_sovits_api_path": (("data", "tts_bundles"),),
            # A ComfyUI installation is normally external.  With no legacy
            # prefix, an existing path under the current project is still
            # serialized relatively, but an unrelated stale /.../data/...
            # path is never guessed to belong to Shinsekai.
            "t2i_work_path": (),
            "t2i_default_workflow_path": (("data", "workflows"),),
        }
        for field, prefixes in api_path_prefixes.items():
            resource_prefixes = (
                (
                    ("assets", "system", "workflow"),
                    ("assets", "workflows"),
                )
                if field == "t2i_default_workflow_path"
                else ()
            )
            if _migrate_path_value(
                api_data,
                field,
                root,
                *prefixes,
                resource_prefixes=resource_prefixes,
                recover_legacy_absolute=recover_legacy_absolute,
            ):
                changed.add("api")
        asr_configs = api_data.get("asr_extra_configs")
        vosk_config = asr_configs.get("vosk") if isinstance(asr_configs, dict) else None
        if isinstance(vosk_config, dict) and _migrate_path_value(
            vosk_config,
            "model_path",
            root,
            ("data", "models"),
            ("data", "cache"),
            resource_prefixes=(("assets", "system", "models"),),
            recover_legacy_absolute=recover_legacy_absolute,
        ):
            changed.add("api")
        tts_configs = api_data.get("tts_extra_configs")
        kaggle_config = (
            tts_configs.get("kaggle-gpt-sovits")
            if isinstance(tts_configs, dict)
            else None
        )
        if isinstance(kaggle_config, dict):
            for field in (
                "remote_gpt_model_path",
                "remote_sovits_model_path",
                "remote_ref_audio_path",
            ):
                raw_value = str(kaggle_config.get(field) or "")
                if raw_value:
                    # Kaggle paths belong to the remote filesystem. Validate
                    # their exact text without assigning local path ownership.
                    validate_exact_path_text(
                        raw_value,
                        field=field,
                        allow_non_native_absolute=True,
                    )
    return changed


def _normalize_config_payload_paths(kind: str, payload: Any, root: Path) -> Any:
    """Serialize project-owned paths portably on every config write."""

    values: dict[str, Any] = {
        "api_data": {},
        "characters_data": [],
        "system_data": {},
        "background_data": [],
        "effect_data": [],
    }
    field = {
        "api": "api_data",
        "characters": "characters_data",
        "system": "system_data",
        "background": "background_data",
        "effect": "effect_data",
    }.get(kind)
    if field is None:
        raise ValueError(f"unknown config payload kind: {kind}")
    values[field] = payload
    _migrate_config_asset_paths(
        root=root,
        recover_legacy_absolute=False,
        **values,
    )
    return payload


def character_name_key(name: str) -> str:
    """Return the case-insensitive identity key used for character lookup."""
    return name.lower()


def _llm_default_base_url(llm_provider: str) -> str:
    """Return the built-in base URL for a provider, accepting minor case drift."""
    provider = (llm_provider or "").strip()
    if provider in LLM_BASE_URLS:
        return LLM_BASE_URLS[provider]
    provider_lower = provider.lower()
    for name, base_url in LLM_BASE_URLS.items():
        if name.lower() == provider_lower:
            return base_url
    return ""


class ConfigManager:
    """
    配置管理器：负责加载、保存和管理应用的全局配置。
    使用单例模式确保全局只有一个配置实例。
    """
    _instance: Optional['ConfigManager'] = None
    _config: Optional[AppConfig] = None
    
    # 配置文件路径定义
    _API_CONFIG_PATH = Path("data/config/api.yaml")
    _CHARACTERS_CONFIG_PATH = Path("data/config/characters.yaml")
    _SYSTEM_CONFIG_PATH = Path("data/config/system_config.yaml")
    _BACKGOUND_CONFIG_PATH = Path("data/config/background.yaml")
    _EFFECT_CONFIG_PATH = Path("data/config/effect.yaml")

    def __new__(cls, *args, **kwargs):
        """实现单例模式"""
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance._bind_project_paths()
            # 在首次创建时尝试加载配置
            cls._instance._load_all_configs()
        return cls._instance

    def _bind_project_paths(self) -> None:
        """Freeze all writable config paths to the authoritative project root."""

        root = project_root()
        self._project_root = root
        for attribute in (
            "_API_CONFIG_PATH",
            "_CHARACTERS_CONFIG_PATH",
            "_SYSTEM_CONFIG_PATH",
            "_BACKGOUND_CONFIG_PATH",
            "_EFFECT_CONFIG_PATH",
        ):
            configured = getattr(type(self), attribute)
            resolved = resolve_managed_project_path(configured, root=root)
            setattr(
                self,
                attribute,
                resolved,
            )

    @property
    def version(self) -> str:
        """Read immutable application version metadata, never project data."""

        candidates: list[Path] = []
        try:
            from sdk.path_contract import resolve_runtime_asset_read_path

            candidates.append(
                resolve_runtime_asset_read_path(
                    "VERSION",
                    root=self._project_root,
                    resource_prefixes=(("VERSION",),),
                )
            )
        except Exception:
            pass
        seen: set[Path] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            try:
                text = read_text_without_links(candidate).strip()
            except Exception:
                continue
            if text:
                return text
        return "unknown"

    @property
    def config(self) -> AppConfig:
        """提供对 Pydantic AppConfig 实例的访问"""
        if self._config is None:
            # 如果配置尚未加载，尝试重新加载或抛出错误
            self._load_all_configs()
            if self._config is None:
                 raise RuntimeError("配置加载失败，无法访问配置数据。")
        return self._config

    # --- 内部加载/合并逻辑 ---
    def _load_yaml(self, file_path: Path) -> Dict[str, Any]:
        """加载单个 YAML 文件"""
        root = getattr(self, "_project_root", None) or project_root()
        file_path = resolve_managed_project_path(file_path, root=root)
        if not file_path.exists():
            print(f"警告：配置文件未找到：{file_path}")
            return {}
        try:
            return yaml.safe_load(read_text_without_links(file_path))
        except Exception as e:
            raise IOError(f"加载配置文件 {file_path} 失败: {e}")

    def _load_all_configs(self) -> None:
        """加载所有配置并合并到一个结构中"""
        try:
            # 加载单个配置文件
            api_data = self._load_yaml(self._API_CONFIG_PATH)
            characters_data = self._load_yaml(self._CHARACTERS_CONFIG_PATH)
            system_data = self._load_yaml(self._SYSTEM_CONFIG_PATH)
            background_data = self._load_yaml(self._BACKGOUND_CONFIG_PATH)
            effect_data = self._load_yaml(self._EFFECT_CONFIG_PATH)

            path_contract_version = (
                system_data.get("path_contract_version")
                if isinstance(system_data, dict)
                else None
            )
            recover_legacy_absolute = not (
                isinstance(path_contract_version, int)
                and not isinstance(path_contract_version, bool)
                and path_contract_version >= _PATH_CONTRACT_VERSION
            )
            migrated = _migrate_config_asset_paths(
                root=getattr(self, "_project_root", None) or project_root(),
                api_data=api_data,
                characters_data=characters_data,
                system_data=system_data,
                background_data=background_data,
                effect_data=effect_data,
                recover_legacy_absolute=recover_legacy_absolute,
            )
            if recover_legacy_absolute:
                if not isinstance(system_data, dict):
                    system_data = {}
                system_data["path_contract_version"] = _PATH_CONTRACT_VERSION
                migrated.add("system")
            migrated_payloads = {
                "api": (self._API_CONFIG_PATH, api_data),
                "characters": (self._CHARACTERS_CONFIG_PATH, characters_data),
                "system": (self._SYSTEM_CONFIG_PATH, system_data),
                "background": (self._BACKGOUND_CONFIG_PATH, background_data),
                "effect": (self._EFFECT_CONFIG_PATH, effect_data),
            }

            # 通过 Pydantic 进行验证和结构化
            api_config = ApiConfig.model_validate(api_data)
            system_config = SystemConfig.model_validate(system_data)

            # 对于 characters.yaml，它是一个列表，直接传递给 List[Character]
            if not isinstance(characters_data, list):
                characters_data = [] # 处理文件为空或格式错误的情况
                
            character_list = [Character.model_validate(normalize_sprite_voice_types(item)) for item in characters_data]
            if not isinstance(background_data, list):
                background_data = []
            background = [Background.model_validate(item) for item in background_data]
            if not isinstance(effect_data, list):
                effect_data = []
            effect_list = [Effect.model_validate(item) for item in effect_data]

            # 构建顶层 AppConfig 实体
            self._config = AppConfig(
                api_config=api_config,
                system_config=system_config,
                characters=character_list,
                background_list=background,
                effect_list=effect_list,
            )
            # Persist the one-time migration marker only after every config
            # payload has validated. Otherwise a malformed unrelated file
            # could permanently suppress the legacy recovery on the next
            # successful launch.
            # The system file owns ``path_contract_version`` and therefore acts
            # as the commit record for this multi-file migration. Publish every
            # other repaired payload first and the marker last. If any earlier
            # write fails, the next launch must retry legacy-path recovery.
            migration_write_order = (
                "api",
                "characters",
                "background",
                "effect",
                "system",
            )
            for name in migration_write_order:
                if name not in migrated:
                    continue
                path, payload = migrated_payloads[name]
                self._save_single_config(path, payload)
            apply_network_proxy_environment(system_config)
            apply_mirror_environment(
                system_config,
                root=getattr(self, "_project_root", None) or project_root(),
            )
            print("配置加载成功！")
        except ValidationError as e:
            self._config = None
            traceback.print_exc()
            raise ValidationError(f"配置验证失败，请检查配置文件格式: \n {e.json()}")
        except Exception as e:
            self._config = None
            raise Exception(f"初始化配置管理器时发生错误: {e}")
            
    # --- 公共方法 ---

    def reload(self) -> None:
        """重新加载所有配置文件"""
        self._load_all_configs()
        
    def save_api_config(self) -> None:
        """独立保存 API 配置到 api.yaml"""
        if self._config is None:
            print("警告：配置未加载或加载失败，无法保存 API 配置。")
            return
        
        print("正在保存 api.yaml...")
        # 将 Pydantic 实体转换为字典进行保存
        payload = self.config.api_config.model_dump(by_alias=True)
        _normalize_config_payload_paths(
            "api",
            payload,
            getattr(self, "_project_root", None) or project_root(),
        )
        self._save_single_config(
            self._API_CONFIG_PATH, 
            payload,
        )
        print("api.yaml 保存完成。")

    def save_system_config(self) -> None:
        """独立保存系统配置到 system_config.yaml"""
        if self._config is None:
            print("警告：配置未加载或加载失败，无法保存系统配置。")
            return
            
        print("正在保存 system_config.yaml...")
        payload = self.config.system_config.model_dump(by_alias=True)
        _normalize_config_payload_paths(
            "system",
            payload,
            getattr(self, "_project_root", None) or project_root(),
        )
        self._save_single_config(
            self._SYSTEM_CONFIG_PATH, 
            payload,
        )
        apply_network_proxy_environment(self.config.system_config)
        apply_mirror_environment(
            self.config.system_config,
            root=getattr(self, "_project_root", None) or project_root(),
        )
        print("system_config.yaml 保存完成。")

    def set_ui_language(self, code: str) -> None:
        """更新界面语言并写入 system_config.yaml。"""
        if self._config is None:
            return
        from sdk.lang import normalize_lang

        sc = self.config.system_config.model_copy(deep=True)
        sc.ui_language = normalize_lang(code)
        previous = self.config.system_config
        self.config.system_config = sc
        try:
            self.save_system_config()
        except BaseException:
            self.config.system_config = previous
            raise
    
    def save_api_config_new(
        self,
        llm_provider: str,
        llm_model: str,
        api_key: str,
        base_url: str,
        is_streaming: str,
        tts_provider: str,
        sovits_url: str,
        gpt_sovits_api_path: str,
        t2i_provider: str,
        t2i_url: str,
        t2i_work_path: str,
        t2i_default_workflow_path: str,
        prompt_node_id: str,
        output_node_id: str,
        temperature: float,
        repetition_penalty: float,
        presence_penalty: float,
        frequency_penalty: float,
        max_context_tokens: int,
        tts_split_enabled: bool = False,
        tts_max_sentence_length: int = 15,
        compact_threshold: float = 0.4,
        compact_target_ratio: float = 0.3,
        history_recent_messages: int = 20,
        max_tool_result_chars: int = 6000,
        max_active_tool_groups: int = 3,
    ) -> str:
        """
        更新内存中的 ApiConfig，并将其保存到 api.yaml。
        """
        if self._config is None:
            return "错误：配置未加载或加载失败，无法保存 API 配置。"

        print("正在更新并保存 api.yaml...")
        current_api_config = self.config.api_config.model_copy(deep=True)
        current_api_config.llm_api_key[llm_provider] = api_key
        current_api_config.llm_model[llm_provider] = llm_model

        current_api_config.llm_provider = llm_provider
        current_api_config.llm_base_url = base_url
        current_api_config.is_streaming = (is_streaming == "是")
        current_api_config.tts_provider = normalize_tts_provider(tts_provider)

        def _norm_t2i_provider(v: str) -> str:
            s = (v or "").strip()
            if not s:
                return "comfyui"
            lowered = s.lower()
            if lowered in {"comfyui", "stable diffusion"}:
                return lowered
            return s

        current_api_config.t2i_provider = _norm_t2i_provider(t2i_provider)
        current_api_config.gpt_sovits_url = tts_server_url_or_default(
            current_api_config.tts_provider,
            sovits_url,
        )
        current_api_config.gpt_sovits_api_path = default_tts_work_path(
            current_api_config.tts_provider,
            gpt_sovits_api_path,
            getattr(self, "_project_root", None) or project_root(),
        )
        if uses_shared_tts_server_config(current_api_config.tts_provider):
            tts_url = str(current_api_config.gpt_sovits_url or "").strip()
            tts_path = str(current_api_config.gpt_sovits_api_path or "")
            if not tts_url:
                return "错误：当前 TTS 引擎需要填写 URL。"
            if not is_http_url(tts_url):
                return "错误：TTS URL 必须是有效的 http(s) URL。"
            if requires_tts_work_path(current_api_config.tts_provider) and not tts_path:
                return "错误：本地 TTS 引擎需要填写服务启动路径。"
            if tts_path and current_api_config.tts_provider != "kaggle-gpt-sovits":
                try:
                    tts_directory = resolve_runtime_asset_read_path(
                        tts_path,
                        root=getattr(self, "_project_root", None) or project_root(),
                        resource_prefixes=(),
                    )
                except (OSError, RuntimeError, ValueError):
                    return "错误：TTS 服务启动路径必须是已存在且不经过链接的目录。"
                if not tts_directory.is_dir():
                    return "错误：TTS 服务启动路径必须是已存在的目录。"
        current_api_config.t2i_api_url=t2i_url
        current_api_config.t2i_work_path=t2i_work_path
        current_api_config.t2i_default_workflow_path=t2i_default_workflow_path
        current_api_config.t2i_prompt_node_id=prompt_node_id
        current_api_config.t2i_output_node_id=output_node_id
        try:
            validate_t2i_paths_for_save(
                current_api_config,
                project_root=getattr(self, "_project_root", None) or project_root(),
            )
        except (OSError, RuntimeError, ValueError) as exc:
            return f"错误：{exc}"
        current_api_config.temperature = float(temperature)
        current_api_config.repetition_penalty = float(repetition_penalty)
        current_api_config.presence_penalty = float(presence_penalty)
        current_api_config.frequency_penalty = float(frequency_penalty)
        current_api_config.max_context_tokens = int(max_context_tokens)
        current_api_config.tts_split_enabled = bool(tts_split_enabled)
        current_api_config.tts_max_sentence_length = int(tts_max_sentence_length)
        current_api_config.compact_threshold = float(compact_threshold)
        current_api_config.compact_target_ratio = clamp_compact_target_ratio(
            current_api_config.compact_threshold,
            compact_target_ratio,
        )
        current_api_config.history_recent_messages = int(history_recent_messages)
        current_api_config.max_tool_result_chars = int(max_tool_result_chars)
        current_api_config.max_active_tool_groups = int(max_active_tool_groups)
        previous_api_config = self.config.api_config
        self.config.api_config = current_api_config

        # 6. 持久化到文件
        try:
            self.save_api_config()
        except BaseException:
            self.config.api_config = previous_api_config
            raise
        return "API配置已保存！"

    def update_llm_info(self, llm_provider: str) -> tuple[str, str, str]:
        """
        根据给定的 LLM 提供商名称，从配置中获取对应的 Base URL, 模型名称和 API Key。
        
        返回: (base_url, llm_model, api_key)
        """
        if self._config is None:
            raise RuntimeError("配置未加载，无法获取 LLM 信息。")

        api_config = self.config.api_config
        
        base_url = _llm_default_base_url(llm_provider)
        
        # 从字典中获取对应提供商的模型和 API Key
        llm_model = api_config.llm_model.get(llm_provider, "")
        api_key = api_config.llm_api_key.get(llm_provider, "")

        # 返回 Base URL, 模型名称, API Key
        return base_url, llm_model, api_key

    def save_characters_config(self) -> None:
        """独立保存角色列表配置到 characters.yaml"""
        if self._config is None:
            print("警告：配置未加载或加载失败，无法保存角色配置。")
            return
            
        print("正在保存 characters.yaml...")
        # 角色列表需要将每个 Character 实体转换为字典
        characters_data = [char.model_dump(by_alias=True) for char in self.config.characters]
        _normalize_config_payload_paths(
            "characters",
            characters_data,
            getattr(self, "_project_root", None) or project_root(),
        )
        self._save_single_config(self._CHARACTERS_CONFIG_PATH, characters_data)
        print("characters.yaml 保存完成。")
    
    def save_background_config(self) -> None:
        if self._config is None:
            print("警告：配置未加载或加载失败，无法保存角色配置。")
            return

        print("正在保存 background.yaml...")
        background_data = [char.model_dump(by_alias=True) for char in self.config.background_list]
        _normalize_config_payload_paths(
            "background",
            background_data,
            getattr(self, "_project_root", None) or project_root(),
        )
        self._save_single_config(self._BACKGOUND_CONFIG_PATH, background_data)
        print("background.yaml 保存完成。")

    def save_effect_config(self) -> None:
        if self._config is None:
            print("警告：配置未加载或加载失败，无法保存特效配置。")
            return

        print("正在保存 effect.yaml...")
        effect_data = [ef.model_dump(by_alias=True) for ef in self.config.effect_list]
        _normalize_config_payload_paths(
            "effect",
            effect_data,
            getattr(self, "_project_root", None) or project_root(),
        )
        self._save_single_config(self._EFFECT_CONFIG_PATH, effect_data)
        print("effect.yaml 保存完成。")

    def _save_single_config(self, file_path: Path, data: Union[Dict, List]) -> None:
        """Atomically publish one YAML config or leave the prior file untouched."""

        raw_file_path = validate_exact_path_text(file_path, field="config file path")
        root = getattr(self, "_project_root", None) or project_root()
        file_path = resolve_managed_project_path(raw_file_path, root=root)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        serialized = yaml.dump(
            data,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
        with _CONFIG_WRITE_LOCK:
            atomic_write_text(file_path, serialized)

    def get_background_by_name(self, name: str) -> Optional[Background]:
        for char in self.config.background_list:
            if char.name.lower() == name.lower():
                return char
        return None

    def get_effect_by_name(self, name: str) -> Optional[Effect]:
        for ef in self.config.effect_list:
            if ef.name.lower() == name.lower():
                return ef
        return None

    def get_character_by_name(self, name: str) -> Optional[Character]:
        """根据角色名称获取角色配置实体"""
        name_key = character_name_key(name)
        for char in self.config.characters:
            if character_name_key(char.name) == name_key:
                return char
        return None

    def get_llm_api_config(self):
        llm_provider = self.config.api_config.llm_provider
        api_key = self.config.api_config.llm_api_key.get(llm_provider,"")
        model = self.config.api_config.llm_model.get(llm_provider,"")
        base_url = str(self.config.api_config.llm_base_url or "").strip()
        if not base_url:
            base_url = _llm_default_base_url(llm_provider)
        return llm_provider, model, base_url, api_key

    def get_gpt_sovits_config(self):
        provider = normalize_tts_provider(self.config.api_config.tts_provider)
        return (
            tts_server_url_or_default(provider, self.config.api_config.gpt_sovits_url),
            default_tts_work_path(
                provider,
                self.config.api_config.gpt_sovits_api_path,
                getattr(self, "_project_root", None) or project_root(),
            ),
            provider,
        )

    def get_adapter_extra_config(self, kind: str, provider_key: str) -> Dict[str, Any]:
        """读取某类适配器在指定 provider/slug 下的扩展配置（扁平 dict）。"""
        pk = (provider_key or "").strip()
        if self._config is None:
            return {}
        ac = self.config.api_config
        if kind == "llm":
            src = ac.llm_extra_configs or {}
        elif kind == "tts":
            src = ac.tts_extra_configs or {}
        elif kind == "asr":
            src = ac.asr_extra_configs or {}
        elif kind == "t2i":
            src = ac.t2i_extra_configs or {}
        else:
            return {}
        return dict(src.get(pk, {}) or {})

    def set_adapter_extra_config(self, kind: str, provider_key: str, data: Dict[str, Any]) -> None:
        """写入扩展配置到内存中的 ApiConfig（需配合 save_api_config 或 save_api_config_new 持久化）。"""
        if self._config is None:
            return
        pk = (provider_key or "").strip()
        ac = self.config.api_config.model_copy(deep=True)
        if kind == "llm":
            m = dict(ac.llm_extra_configs or {})
            m[pk] = dict(data)
            ac.llm_extra_configs = m
        elif kind == "tts":
            m = dict(ac.tts_extra_configs or {})
            m[pk] = dict(data)
            ac.tts_extra_configs = m
        elif kind == "asr":
            m = dict(ac.asr_extra_configs or {})
            m[pk] = dict(data)
            ac.asr_extra_configs = m
        elif kind == "t2i":
            m = dict(ac.t2i_extra_configs or {})
            m[pk] = dict(data)
            ac.t2i_extra_configs = m
        else:
            return
        self.config.api_config = ac

    def merged_llm_factory_kwargs(self, llm_provider: str, base_kwargs: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(base_kwargs)
        extra = self.get_adapter_extra_config("llm", llm_provider)
        out.update(extra)
        return out

    def merged_tts_factory_kwargs(self, adapter_name: str, base_kwargs: Dict[str, Any]) -> Dict[str, Any]:
        slug = (adapter_name or "").strip().lower()
        out = dict(base_kwargs)
        extra = self.get_adapter_extra_config("tts", slug)
        out.update(extra)
        return out

    def merged_t2i_factory_kwargs(self, adapter_name: str, base_kwargs: Dict[str, Any]) -> Dict[str, Any]:
        name = (adapter_name or "").strip().lower()
        out = dict(base_kwargs)
        extra = self.get_adapter_extra_config("t2i", name)
        out.update(extra)
        return out

    def get_base_font_size(self) -> int:
        """获取基础字体大小"""
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
        sc.music_cover_work_dir = work_dir or "data/music_cover"
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
        previous_system_config = self.config.system_config
        self.config.system_config = sc
        try:
            self.save_system_config()
        except BaseException:
            self.config.system_config = previous_system_config
            raise
        return "音乐翻唱配置已保存。"
